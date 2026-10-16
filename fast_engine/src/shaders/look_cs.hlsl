// look_cs.hlsl: the Look stage's compose, see look.h. At the work size, on the network's input
// and the last pass's output as the composite will read them: the network's edit is measured
// per channel in linear light as stops, e = log2(n / p), reshaped, and the output rewritten as
// n' = n * 2^(t (e' - e)), so an edit left as it is returns the output byte for byte, and the
// composite then adds the reshaped change to the frame as before. Everything here is the
// engine's own; the ideas are the add-on's, see _harnesses\wip-060\research\look-stage-spec.md.
//
// The reshaping, in order:
//   bands     with the band split (look_band_cs.hlsl) the luma edit a splits into the broad
//             band aB = A I + B, the fine band aD = a - aB and the mid band aM between the
//             narrow and the wide coefficients; without it aB = a and the rest is 0
//   filter    the temporal filter: the history, read where this texel's content was in the
//             frame before (its place, or its place moved by the motion estimate), held inside
//             the 3x3 range of the current frame, kept only where the input's log luminance
//             is near the history's, blended in by beta = max(alpha, 1 - confidence); the
//             broad band and the colour always, the fine and mid bands with g_detail_filter
//   halo      where a texel is 1 to 3 stops darker than the brightest input near it, its fine
//             darkening is taken back by g_halo times that weight; the twin does the same on
//             the brighter side of dark objects, with the mid band lifted too
//   bands     a' = tone aB + detail aD + detail mid_lift
//   knees     soft limits, M tanh(x / M), on brightening, darkening and the colour's size
cbuffer Constants : register(b0) {
  uint g_w;              // the work size
  uint g_h;
  uint g_hw;             // the half size of the band textures
  uint g_hh;
  uint g_bands;          // 1: the band textures hold this frame's split
  uint g_filter;         // 0 none, 1 in place, 2 along the motion estimate
  uint g_detail_filter;  // 1: the fine and mid bands are filtered too
  uint g_range_test;     // 1: the input change is measured against the 3x3 range, 0 at the point
  uint g_history;        // 1: the history holds the frame before, 0: start afresh
  float g_alpha;         // the filter's weight for a frame
  float g_tone;          // the broad band's gain
  float g_detail;        // the fine band's
  float g_halo;          // 0 to 1
  float g_halo_bright;   // 0 to 1
  float g_max_brighten;  // stops, 0 for none
  float g_max_darken;
  float g_max_colour;
  uint g_vec_w;          // the motion estimate's grid
  uint g_vec_h;
  float g_vec_cell;      // work texels per cell of that grid
  float g_vec_scale;     // work texels per unit of a vector
  uint g_pad0;
  uint g_pad1;
  uint g_pad2;
};

Texture2D<float4> g_in : register(t0);          // R8G8B8A8_UNORM, the network's input
Texture2D<float4> g_coef : register(t1);        // RGBA32F, half size: (A_n, B_n, A_w, B_w)
Texture2D<float2> g_ext : register(t2);         // RG32F, half size: (max I, max -I) dilated
Texture2D<float4> g_hist_a : register(t3);      // RGBA16F, the frame before: (aB, aD, c.r, c.b)
Texture2D<float2> g_hist_b : register(t4);      // RG16F: (I, aM)
Texture2D<int2> g_vectors : register(t5);       // R16G16_SINT, the motion estimate
Texture2D<float4> g_src : register(t6);         // the last pass's output as the network left it, a copy,
                                                // read for every texel and its neighbours while g_out is written
RWTexture2D<unorm float4> g_out : register(u0); // R8G8B8A8_UNORM, the last pass's output, written
RWTexture2D<float4> g_next_a : register(u1);    // the history written for the next frame
RWTexture2D<float2> g_next_b : register(u2);
SamplerState g_linear : register(s0);

static const float3 kW = float3(0.212639, 0.715169, 0.072192);
static const float kFloor = 1.0 / 1024.0;

float3 srgb_decode(float3 c) {
  c = saturate(c);
  const float3 low = c / 12.92;
  const float3 high = pow((c + 0.055) / 1.055, 2.4);
  return c <= 0.04045 ? low : high;
}

float3 srgb_encode(float3 c) {
  c = saturate(c);
  const float3 low = c * 12.92;
  const float3 high = 1.055 * pow(c, 1.0 / 2.4) - 0.055;
  return c <= 0.0031308 ? low : high;
}

struct Edit {
  float3 e;    // the edit in stops per channel
  float a;     // the luma edit
  float3 c;    // the colour edit, dot(kW, c) = 0
  float I;     // the input's log luminance
  float t;     // floor trust
  float3 n;    // the output in linear light
  float aB, aD, aM, peak, trough;
};

// The edit at a work texel, with the bands where they are on.
Edit edit_at(int2 x) {
  Edit r;
  const float3 p = srgb_decode(g_in.Load(int3(x, 0)).rgb);
  r.n = srgb_decode(g_src.Load(int3(x, 0)).rgb);
  r.e = log2(max(r.n, kFloor)) - log2(max(p, kFloor));
  r.a = dot(kW, r.e);
  r.c = r.e - r.a;
  r.I = log2(max(dot(kW, p), kFloor));
  r.t = smoothstep(kFloor, 1.0 / 64.0, max(p.r, max(p.g, p.b)));
  if (g_bands != 0) {
    const float2 uv = (float2(x) + 0.5) * 0.5 / float2(g_hw, g_hh);
    const float4 cf = g_coef.SampleLevel(g_linear, uv, 0);
    const float2 ex = g_ext.SampleLevel(g_linear, uv, 0);
    r.aB = cf.x * r.I + cf.y;
    r.aD = r.a - r.aB;
    r.aM = r.aB - (cf.z * r.I + cf.w);
    r.peak = ex.x;
    r.trough = -ex.y;
  } else {
    r.aB = r.a;
    r.aD = 0.0;
    r.aM = 0.0;
    r.peak = r.I;
    r.trough = r.I;
  }
  return r;
}

[numthreads(8, 8, 1)]
void main(uint3 id : SV_DispatchThreadID) {
  if (id.x >= g_w || id.y >= g_h) return;
  const int2 x = int2(id.xy);
  Edit cur = edit_at(x);
  float aB = cur.aB, aD = cur.aD, aM = cur.aM;
  float2 cc = float2(cur.c.r, cur.c.b);

  // ---- the temporal filter
  if (g_filter != 0) {
    // where this texel's content was in the frame before
    float2 previous = float2(x) + 0.5;
    if (g_filter == 2 && g_vec_w > 0) {
      const int2 cell = clamp(int2(floor((float2(x) + 0.5) / g_vec_cell)), int2(0, 0), int2(g_vec_w - 1, g_vec_h - 1));
      previous += float2(g_vectors.Load(int3(cell, 0))) * g_vec_scale;
    }
    const bool onscreen = all(previous >= 0.0) && all(previous <= float2(g_w, g_h));
    const float2 uv = previous / float2(g_w, g_h);
    const float4 ha = g_hist_a.SampleLevel(g_linear, uv, 0);
    const float2 hb = g_hist_b.SampleLevel(g_linear, uv, 0);
    // the current frame's range over the 3x3, which holds the history, and the input's range
    float4 lo = float4(aB, aD, cc), hi = lo;
    float lo_m = aM, hi_m = aM, lo_I = cur.I, hi_I = cur.I;
    for (int dy = -1; dy <= 1; ++dy) {
      for (int dx = -1; dx <= 1; ++dx) {
        if (dx == 0 && dy == 0) continue;
        const int2 nx = clamp(x + int2(dx, dy), int2(0, 0), int2(g_w - 1, g_h - 1));
        const Edit nb = edit_at(nx);
        const float4 v = float4(nb.aB, nb.aD, nb.c.r, nb.c.b);
        lo = min(lo, v);
        hi = max(hi, v);
        lo_m = min(lo_m, nb.aM);
        hi_m = max(hi_m, nb.aM);
        lo_I = min(lo_I, nb.I);
        hi_I = max(hi_I, nb.I);
      }
    }
    float change;
    if (g_range_test != 0) change = max(max(lo_I - hb.x, hb.x - hi_I), 0.0);
    else change = abs(cur.I - hb.x);
    const float confidence = (onscreen && g_history != 0) ? 1.0 - smoothstep(0.1, 0.3, change) : 0.0;
    const float beta = max(g_alpha, 1.0 - confidence);
    const float4 held = clamp(ha, lo, hi);
    const float4 filtered = held + beta * (float4(aB, aD, cc) - held);
    const float held_m = clamp(hb.y, lo_m, hi_m);
    const float filtered_m = held_m + beta * (aM - held_m);
    aB = filtered.x;
    cc = filtered.zw;
    if (g_detail_filter != 0) {
      aD = filtered.y;
      aM = filtered_m;
    }
    g_next_a[x] = float4(aB, aD, cc);
    g_next_b[x] = float2(cur.I, aM);
  }
  float3 c;
  c.r = cc.x;
  c.b = cc.y;
  c.g = -(kW.r * c.r + kW.b * c.b) / kW.g;

  // ---- the halos
  const float wmax = smoothstep(1.0, 3.0, cur.peak - cur.I);
  aD -= g_halo * wmax * min(aD, 0.0);
  float mid_lift = 0.0;
  if (g_halo_bright > 0.0) {
    const float wmin = smoothstep(1.0, 3.0, cur.I - cur.trough);
    const float wD = max(wmax, wmin);
    aD -= min(g_halo_bright * wD, 1.0) * min(aD, 0.0);
    mid_lift = -min(g_halo_bright * wmin, 1.0) * min(aM, 0.0);
  }

  // ---- the bands and the knees
  float a = g_tone * aB + g_detail * aD + g_detail * mid_lift;
  if (a > 0.0 && g_max_brighten > 0.0) a = g_max_brighten * tanh(min(a / g_max_brighten, 10.0));
  if (a < 0.0 && g_max_darken > 0.0) a = g_max_darken * tanh(max(a / g_max_darken, -10.0));
  const float norm = sqrt(dot(kW, c * c));
  if (g_max_colour > 0.0 && norm > 1e-6) c *= g_max_colour * tanh(min(norm / g_max_colour, 10.0)) / norm;
  const float3 e2 = a + c;

  const float3 n2 = cur.n * exp2(cur.t * (e2 - cur.e));
  const float4 o = g_src.Load(int3(x, 0));
  g_out[x] = float4(srgb_encode(n2), o.a);
}
