// look_band_cs.hlsl: the Look stage's band split, see look.h. Five passes over a grid of half
// the work size, chosen by g_pass, which split the network's luma edit a into a broad band
// and a fine one by a guided filter of a on the input's log luminance I, and find for each
// half-size texel the brightest and the darkest input near it, with a round penalty, which the
// halo witnesses read. Everything here is the engine's own; the ideas are the add-on's, see
// _harnesses\wip-060\research\look-stage-spec.md.
//
//   pass 0  down:    per half-size texel the mean over its 2x2 work texels of (I, a, I*I, I*a),
//                    and the 2x2 max of I and of -I
//   pass 1  across:  box means of the moments over x - R..x + R; the max of I dilated over
//                    2R with a 2-stop penalty at R, and of -I over 2 R_min with it at R_min
//   pass 2  down:    the same down, then the guided filter's coefficients A = cov / (var +
//                    eps), B = mean(a) - A mean(I); the dilations finished
//   pass 3  across:  box means of (A, B) over R, the narrow pair, and over R_mid, the wide
//   pass 4  down:    the same down: (A_narrow, B_narrow, A_wide, B_wide)
//
// Box windows are clamped at the border and divided by the count inside it, so a constant
// field stays constant. A texel of the moments holds (I, a, I*I, I*a); of the extrema (max I,
// max -I); of the coefficients (A_n, B_n, A_w, B_w) once pass 4 has run, (A, B, 0, 0) before.
// A pass reads one texture and writes another, never the one it reads.
cbuffer Constants : register(b0) {
  uint g_w;        // the work size
  uint g_h;
  uint g_hw;       // the half size, (w + 1) / 2 by (h + 1) / 2
  uint g_hh;
  uint g_pass;     // 0 to 4
  uint g_r;        // R, in half-size texels
  uint g_r_min;    // R_min, the trough's witness
  uint g_r_mid;    // R_mid, the wide transport
  float g_eps;     // the guided filter's regularisation, stops squared
  uint g_pad0;
  uint g_pad1;
  uint g_pad2;
};

Texture2D<float4> g_in : register(t0);     // R8G8B8A8_UNORM, the network's input, sRGB levels
Texture2D<float4> g_out : register(t1);    // the last pass's output, the same
RWTexture2D<float4> g_mom_a : register(u0);   // moments, half size, RGBA32F
RWTexture2D<float4> g_mom_b : register(u1);
RWTexture2D<float2> g_ext_a : register(u2);   // extrema, half size, RG32F
RWTexture2D<float2> g_ext_b : register(u3);
RWTexture2D<float4> g_coef_a : register(u4);  // coefficients, half size, RGBA32F
RWTexture2D<float4> g_coef_b : register(u5);

static const float3 kW = float3(0.212639, 0.715169, 0.072192);
static const float kFloor = 1.0 / 1024.0;

float3 srgb_decode(float3 c) {
  c = saturate(c);
  const float3 low = c / 12.92;
  const float3 high = pow((c + 0.055) / 1.055, 2.4);
  return c <= 0.04045 ? low : high;
}

// The input's log luminance I and the luma edit a at a work texel.
void edit_at(int2 x, out float I, out float a) {
  const float3 p = srgb_decode(g_in.Load(int3(x, 0)).rgb);
  const float3 n = srgb_decode(g_out.Load(int3(x, 0)).rgb);
  const float3 e = log2(max(n, kFloor)) - log2(max(p, kFloor));
  a = dot(kW, e);
  I = log2(max(dot(kW, p), kFloor));
}

// A box mean along one axis, clamped at the border: the sum over the texels inside the
// picture, divided by their count.
float4 box_x(RWTexture2D<float4> t, int2 at, int r) {
  const int x0 = max(at.x - r, 0), x1 = min(at.x + r, (int)g_hw - 1);
  float4 sum = 0.0;
  for (int x = x0; x <= x1; ++x) sum += t[int2(x, at.y)];
  return sum / (float)(x1 - x0 + 1);
}

float4 box_y(RWTexture2D<float4> t, int2 at, int r) {
  const int y0 = max(at.y - r, 0), y1 = min(at.y + r, (int)g_hh - 1);
  float4 sum = 0.0;
  for (int y = y0; y <= y1; ++y) sum += t[int2(at.x, y)];
  return sum / (float)(y1 - y0 + 1);
}

// A round dilation along one axis: the max over 2r each way of the value less 2 (d / r)^2,
// so the penalty is 2 stops at r and 8 at 2r; the two axes together subtract the penalty
// of the distance.
float dilate_x(RWTexture2D<float2> t, int2 at, int r, int part) {
  const int x0 = max(at.x - 2 * r, 0), x1 = min(at.x + 2 * r, (int)g_hw - 1);
  float best = -1e30;
  for (int x = x0; x <= x1; ++x) {
    const float d = (float)(x - at.x) / (float)r;
    const float v = part == 0 ? t[int2(x, at.y)].x : t[int2(x, at.y)].y;
    best = max(best, v - 2.0 * d * d);
  }
  return best;
}

float dilate_y(RWTexture2D<float2> t, int2 at, int r, int part) {
  const int y0 = max(at.y - 2 * r, 0), y1 = min(at.y + 2 * r, (int)g_hh - 1);
  float best = -1e30;
  for (int y = y0; y <= y1; ++y) {
    const float d = (float)(y - at.y) / (float)r;
    const float v = part == 0 ? t[int2(at.x, y)].x : t[int2(at.x, y)].y;
    best = max(best, v - 2.0 * d * d);
  }
  return best;
}

[numthreads(8, 8, 1)]
void main(uint3 id : SV_DispatchThreadID) {
  if (id.x >= g_hw || id.y >= g_hh) return;
  const int2 hp = int2(id.xy);
  if (g_pass == 0) {
    // the mean over the 2x2 work texels, fewer at a right or bottom edge of odd size
    float4 m = 0.0;
    float2 ext = float2(-1e30, -1e30);
    float count = 0.0;
    for (int dy = 0; dy < 2; ++dy) {
      for (int dx = 0; dx < 2; ++dx) {
        const int2 x = hp * 2 + int2(dx, dy);
        if (x.x >= (int)g_w || x.y >= (int)g_h) continue;
        float I, a;
        edit_at(x, I, a);
        m += float4(I, a, I * I, I * a);
        ext = max(ext, float2(I, -I));
        count += 1.0;
      }
    }
    g_mom_a[hp] = m / max(count, 1.0);
    g_ext_a[hp] = ext;
  } else if (g_pass == 1) {
    g_mom_b[hp] = box_x(g_mom_a, hp, (int)g_r);
    g_ext_b[hp] = float2(dilate_x(g_ext_a, hp, (int)g_r, 0), dilate_x(g_ext_a, hp, (int)g_r_min, 1));
  } else if (g_pass == 2) {
    const float4 m = box_y(g_mom_b, hp, (int)g_r);
    const float variance = m.z - m.x * m.x;
    const float covariance = m.w - m.x * m.y;
    const float slope = covariance / (variance + g_eps);
    g_coef_a[hp] = float4(slope, m.y - slope * m.x, 0.0, 0.0);
    g_ext_a[hp] = float2(dilate_y(g_ext_b, hp, (int)g_r, 0), dilate_y(g_ext_b, hp, (int)g_r_min, 1));
  } else if (g_pass == 3) {
    const float4 narrow = box_x(g_coef_a, hp, (int)g_r);
    const float4 wide = box_x(g_coef_a, hp, (int)g_r_mid);
    g_coef_b[hp] = float4(narrow.xy, wide.xy);
  } else {
    // the narrow pair down over R and the wide pair over R_mid, each from its own half
    const int2 at = hp;
    const int yn0 = max(at.y - (int)g_r, 0), yn1 = min(at.y + (int)g_r, (int)g_hh - 1);
    const int yw0 = max(at.y - (int)g_r_mid, 0), yw1 = min(at.y + (int)g_r_mid, (int)g_hh - 1);
    float2 narrow = 0.0, wide = 0.0;
    for (int y = yn0; y <= yn1; ++y) narrow += g_coef_b[int2(at.x, y)].xy;
    for (int y2 = yw0; y2 <= yw1; ++y2) wide += g_coef_b[int2(at.x, y2)].zw;
    g_coef_a[hp] = float4(narrow / (float)(yn1 - yn0 + 1), wide / (float)(yw1 - yw0 + 1));
  }
}
