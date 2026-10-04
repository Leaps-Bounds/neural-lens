// composite_ps.hlsl: the picture that is presented.
//
//   out = native + upsample(network output - network input)
//
// Only what the network changed is scaled up, bilinearly, from the work size, and added to
// the frame as it was captured at full size. So the original keeps its own detail, and the
// network's change comes on top: measured in the probe, the composite's edge figure is 270
// where the original has 273.
//
// With g_residual 0 it is the native frame and nothing else: the network is off.
//
// It follows the probe's ResidualComposite step by step, on the same 0 to 255 scale and in
// the same order, so the result is the reference's. Along one axis, for target pixel x with
// `work` texels under `full` pixels:
//     s = (x + 0.5) * work / full - 0.5, held inside [0, work - 1]
//     i0 = floor(s), i1 = min(i0 + 1, work - 1), f = s - i0
// which is what a bilinear sampler with clamped edges does, but a sampler keeps only 8 bits
// of f. Here s is computed in whole numbers, s = n / d with n = (2x + 1) * work - full and
// d = 2 * full, so i0 is exact. Each axis has its own work and full, so the two scales need
// not be the same.
//
// f is the remainder n - i0 * d, as a float, times the float nearest to 1 / d, which the
// CPU hands over. It is not a division here. A GPU may round a division one unit in the
// last place off, and this one did. Measured on an RTX 5090, its quotient was the product
// with the reciprocal in every case, which is a unit off the rounded quotient for 1279 of
// the 3840 columns of a 3840x2160 picture at 2560 work texels across. Where a sum lands on
// a half, that last place decides which way a level rounds, which was 28 of 24.9 million
// bytes at 2560x1152. With the product written out, every GPU computes the same f and the
// composite can be done again on the CPU to the byte, which tools\verify_math.py does.

cbuffer Constants : register(b0) {
  uint g_w;         // the picture: the target and the native frame
  uint g_h;
  uint g_work_w;    // the network's textures
  uint g_work_h;
  uint g_residual;  // 0: the native frame unchanged
  float g_inv_x;    // the float nearest to 1 / (2 * g_w)
  float g_inv_y;    // the float nearest to 1 / (2 * g_h)
};

Texture2D<float4> g_native : register(t0);  // B8G8R8A8_UNORM, full size
Texture2D<float4> g_in : register(t1);      // R8G8B8A8_UNORM, work size: what the network was given
Texture2D<float4> g_out : register(t2);     // R8G8B8A8_UNORM, work size: what it made of it

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

float4 main(float4 pos : SV_Position) : SV_Target {
  const uint2 p = (uint2)pos.xy;  // pos is the pixel's middle, x + 0.5
  const float4 native = g_native.Load(int3(p, 0));
  if (g_residual == 0) return float4(native.rgb, 1.0);

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
  precise float3 v = level(native) + d;

  // to the nearest level, a half going up, then held inside 0 to 255: lround and clamp
  float3 q = floor(v);
  q += step(0.5, v - q);
  return float4(clamp(q, 0.0, 255.0) / 255.0, 1.0);
}
