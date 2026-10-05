// composite_hdr_ps.hlsl: the picture that is presented when the swapchain is in 16-bit
// floats, which it is for a monitor with Windows HDR on.
//
// The desktop of such a monitor is composed in scRGB, linear with 1.0 at 80 nits, and the
// capture then comes in 16-bit floats (capture.h, fp16). The network saw the 8-bit frame
// made of it, scaled to the SDR white level and clipped (convert_cs.hlsl), and its change
// is a difference of levels on that frame, as composite_ps.hlsl draws it in standard range:
//
//   SDR:  out8 = clamp(level + change, 0, 255)         then shown at SDR white
//
// Here the same change is taken back to linear light at the pixel's own level and the
// original scRGB value stays beneath it:
//
//   v   = clamp(level + change, 0, 255)
//   out = native + white * (decode(v / 255) - decode(level / 255))
//
// where native is the 16-bit capture, white the SDR white level in units of 80 nits, and
// decode the sRGB transfer function. For a pixel at or below SDR white that is the standard
// range picture in linear light, since native is white * decode(level / 255) there up to
// the 8-bit rounding, and what that rounding lost is kept, because the original's own value
// is what the change is added to. The change is not rounded to a level first, so it is
// finer than the standard range picture by up to half a level.
//
// Above SDR white the network saw a clipped input, a level of 255, so what its change
// means there is decided by g_above:
//   0  pass   the change applies as at white. v is clamped at 255, so it can only darken,
//             as the standard range composite can only darken a white
//   1  fade   the change is scaled by a weight of 1 at or below white that falls to 0 at
//             twice white, per channel, by the original's own value: at twice white the
//             network saw half of the pixel's light, and from there on nothing it made of
//             the clipped input is shown. The engine's choice
//   2  clip   no change where the original's channel is above white
// Measured on a test computer with an RTX 5090, on a monitor with an SDR white of 240 nits,
// over a picture at SDR white with highlights above it. The network darkens what it took
// for a flat white: with pass a 480 nit disc came out 11.5 nits darker over its whole area
// and small highlights of 300 to 430 nits 43 nits darker on average, a tone shift of the
// highlights with nothing in the original behind it. With clip every highlight stayed as
// it was, but along the contour where a soft glow crosses white the change stepped from
// 11 nits to none within a few pixels, a ring the original does not have. With fade the
// change ran on through the crossing (11.3, 10.1 and 4.0 nits in the three steps of the
// original's value from 0.95 to 1.2 of white, against 11.0, 10.0 and 4.4 with pass), the
// disc stayed as it was, and the small highlights came out 34 nits darker on average.
//
// The change itself (axis and change) is composite_ps.hlsl's, kept the same so that the two
// shaders draw the same change at every pixel: a bilinear upsample of the level difference
// with the sample positions computed in whole numbers and the fraction as a product, see
// there. g_have_raw 0 means there is no 16-bit frame behind the 8-bit one (an 8-bit capture
// drawn into a 16-bit swapchain): native is then white * decode(level / 255), the 8-bit
// frame shown at SDR white, as Windows shows a standard program.

cbuffer Constants : register(b0) {
  uint g_w;         // the picture: the target and the frames
  uint g_h;
  uint g_work_w;    // the network's textures
  uint g_work_h;
  uint g_residual;  // 0: the native frame unchanged
  float g_inv_x;    // the float nearest to 1 / (2 * g_w)
  float g_inv_y;    // the float nearest to 1 / (2 * g_h)
  float g_white;    // the SDR white level in units of 80 nits, 1 or more
  uint g_above;     // what the change does above SDR white, see above
  uint g_have_raw;  // 1: g_raw holds the 16-bit frame behind g_native
  uint g_unused0;
  uint g_unused1;
};

Texture2D<float4> g_native : register(t0);  // the 8-bit frame the network saw, full size
Texture2D<float4> g_in : register(t1);      // R8G8B8A8_UNORM, work size: what the network was given
Texture2D<float4> g_out : register(t2);     // R8G8B8A8_UNORM, work size: what it made of it
Texture2D<float4> g_raw : register(t3);     // R16G16B16A16_FLOAT, scRGB, full size

void axis(uint x, uint work, uint full, float inv_d, out uint i0, out uint i1, out float f) {
  const int top = (int)((work - 1) * 2 * full);
  const uint n = (uint)clamp((int)((2 * x + 1) * work) - (int)full, 0, top);
  const uint d = 2 * full;
  i0 = n / d;
  precise float part = (float)(n - i0 * d) * inv_d;
  f = part;
  i1 = min(i0 + 1, work - 1);
}

// The whole number a texel holds, 0 to 255.
float3 level(float4 texel) { return floor(texel.rgb * 255.0 + 0.5); }

float3 change(uint x, uint y) {
  const int3 at = int3(x, y, 0);
  return level(g_out.Load(at)) - level(g_in.Load(at));
}

// The sRGB transfer function, encoded 0 to 1 to linear 0 to 1.
float3 srgb_decode(float3 c) {
  const float3 low = c / 12.92;
  const float3 high = pow(max((c + 0.055) / 1.055, 0.0), 2.4);
  return (c <= 0.04045) ? low : high;
}

float4 main(float4 pos : SV_Position) : SV_Target {
  const uint2 p = (uint2)pos.xy;  // pos is the pixel's middle, x + 0.5
  const int3 at = int3(p, 0);
  const float3 lvl = level(g_native.Load(at));
  float3 native;
  if (g_have_raw != 0) {
    native = g_raw.Load(at).rgb;
  } else {
    native = g_white * srgb_decode(lvl / 255.0);
  }
  if (g_residual == 0) return float4(native, 1.0);

  uint x0, x1, y0, y1;
  float fx, fy;
  axis(p.x, g_work_w, g_w, g_inv_x, x0, x1, fx);
  axis(p.y, g_work_h, g_h, g_inv_y, y0, y1, fy);

  const float3 d00 = change(x0, y0), d10 = change(x1, y0);
  const float3 d01 = change(x0, y1), d11 = change(x1, y1);
  // precise: each product and each sum rounded on its own, as the probe's were on the CPU
  precise float3 top = d00 + (d10 - d00) * fx;
  precise float3 bottom = d01 + (d11 - d01) * fx;
  precise float3 d = top + (bottom - top) * fy;
  precise float3 v = lvl + d;

  const float3 after = clamp(v, 0.0, 255.0) / 255.0;
  float3 delta = g_white * (srgb_decode(after) - srgb_decode(lvl / 255.0));
  // above SDR white, per channel by the original's own value
  const float3 over = native / g_white;  // 1.0 at SDR white
  if (g_above == 1) {
    delta *= saturate(2.0 - over);       // 1 at or below white, 0 at twice white
  } else if (g_above == 2) {
    delta *= (over > 1.0) ? 0.0 : 1.0;
  }
  return float4(native + delta, 1.0);
}
