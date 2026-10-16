// nv12_cs.hlsl: frame generation's conversion of a captured frame into the two planes of an
// NV12 picture at the motion estimator's size, see framegen.h: the luma, one texel a texel,
// and the chroma, one texel for each two by two of them, both BT.709 at full range. The
// frame is read through a linear sampler at the middle of each texel of the smaller
// picture, which for a picture half the frame's size is the mean of a two by two block of
// the frame, and for one of the frame's own size the texel itself. A 16-bit frame in scRGB
// is held inside 0 to 1 first: the estimator wants a steady picture, not the highlights.
cbuffer Constants : register(b0) {
  uint me_w;   // the planes' size, the luma's
  uint me_h;
  uint fp16;   // 1: the frame is in 16-bit floats, linear scRGB
  uint pad;
};

Texture2D<float4> frame : register(t0);
RWTexture2D<float> luma : register(u0);     // R8_UNORM, me_w x me_h
RWTexture2D<float2> chroma : register(u1);  // R8G8_UNORM, me_w / 2 x me_h / 2
SamplerState linear_clamp : register(s0);

float3 rgb_at(float2 uv) {
  float3 c = frame.SampleLevel(linear_clamp, uv, 0).rgb;
  if (fp16 != 0) c = saturate(c);
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
