// nv12_cs.hlsl: frame generation's conversion of a captured frame into the two planes of an
// NV12 picture at the motion estimator's size, see framegen.h: the luma, one texel a texel,
// and the chroma, one texel for each two by two of them, both BT.709 at full range. The
// frame is read through a linear sampler at the middle of each texel of the smaller
// picture, which for a picture half the frame's size is the mean of a two by two block of
// the frame, and for one of the frame's own size the texel itself. A 16-bit frame in scRGB
// (1.0 is 80 nits) is scaled by the SDR white level first, so standard range content fills
// 0 to 0.8 of the planes, and what is brighter is compressed above that, never flat: the
// estimator wants a steady picture with its detail everywhere, not the highlights'
// brightness. Held inside 0 to 1 unscaled, as at first, everything brighter than 80 nits
// was flat white to it, a third of a 240 nit SDR white, and it found no motion there. A
// threefold highlight has a seventh of the range here and its blocks go wrong twice as
// often as in standard range; a knee at 0.6, which gives the highlights more, made that
// worse, not better, since the standard range lost more (measured, the 16-bit sequence mode).
cbuffer Constants : register(b0) {
  uint me_w;   // the planes' size, the luma's
  uint me_h;
  uint fp16;   // 1: the frame is in 16-bit floats, linear scRGB
  uint taps;   // taps a side: 1, one bilinear tap, the mean of a two by two of the frame, for
               // a frame up to twice the planes' size; 2 or more for a frame four or more
               // times their size, that many taps a side two frame texels apart, together
               // the mean of a (2 taps) square, so the planes do not alias on the texture
  float white; // for a 16-bit frame, the SDR white level in units of 80 nits (3.0 at 240 nits)
};

Texture2D<float4> frame : register(t0);
RWTexture2D<float> luma : register(u0);     // R8_UNORM, me_w x me_h
RWTexture2D<float2> chroma : register(u1);  // R8G8_UNORM, me_w / 2 x me_h / 2
SamplerState linear_clamp : register(s0);

float3 rgb_at(float2 uv) {
  float3 c;
  if (taps <= 1) {
    c = frame.SampleLevel(linear_clamp, uv, 0).rgb;
  } else {
    float fw, fh;
    frame.GetDimensions(fw, fh);
    const float2 step = 2.0 / float2(fw, fh);
    const float2 start = uv - step * (0.5 * (float)(taps - 1));
    c = 0.0;
    for (uint y = 0; y < taps; ++y) {
      for (uint x = 0; x < taps; ++x) c += frame.SampleLevel(linear_clamp, start + step * float2(x, y), 0).rgb;
    }
    c /= (float)(taps * taps);
  }
  if (fp16 != 0) {
    c = max(c / max(white, 1.0), 0.0);
    // 0.8 c up to the SDR white, 1 - 0.2 / c above it: continuous at 1, rising towards 1
    c = min(0.8 * c, 1.0 - 0.2 / max(c, 1.0));
  }
  return c;
}

[numthreads(8, 8, 1)]
void main(uint3 id : SV_DispatchThreadID) {
  if (id.x >= me_w || id.y >= me_h) return;
  const float2 size = float2(me_w, me_h);
  const float3 c = rgb_at((float2(id.xy) + 0.5) / size);
  luma[id.xy] = 0.2126 * c.r + 0.7152 * c.g + 0.0722 * c.b;
  if ((id.x & 1) == 0 && (id.y & 1) == 0) {
    // the middle of the two by two block, so the sampler averages its texels
    const float3 m = rgb_at((float2(id.xy) + 1.0) / size);
    chroma[id.xy / 2] = float2(0.5 - 0.1146 * m.r - 0.3854 * m.g + 0.5 * m.b,
                               0.5 + 0.5 * m.r - 0.4542 * m.g - 0.0458 * m.b);
  }
}
