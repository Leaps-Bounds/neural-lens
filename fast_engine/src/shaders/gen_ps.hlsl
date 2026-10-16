// gen_ps.hlsl: frame generation's made picture, drawn into the target as the composite is,
// one full-screen triangle, from the two pictures last presented and the motion the
// estimator found between their frames, see framegen.h.
//
// The vectors come one a block of the estimator's picture, in quarter texels of it, each
// pointing from a block of the second frame back to where its content was in the first. So
// the content's move from the first frame to the second is the vector turned round, scaled
// to the target's texels.
//
//   mode 0, between: the picture part of the way from the first to the second. Each texel is
//                    taken from the first picture moved back by part of the move and from the
//                    second moved on by the rest, and the two are blended.
//   mode 1, ahead:   the second picture carried on by part of the move, from it alone.
cbuffer Constants : register(b0) {
  uint w;        // the target
  uint h;
  uint vec_w;    // the vectors
  uint vec_h;
  float scale;   // the target's texels per texel of the estimator's picture
  float block;   // the block's side, in the estimator's texels
  float part;    // how far between the frames, 0.5 for the midpoint
  uint mode;
};

Texture2D<float4> first : register(t0);
Texture2D<float4> second : register(t1);
Texture2D<int2> vectors : register(t2);
SamplerState linear_clamp : register(s0);

float4 main(float4 pos : SV_Position) : SV_Target {
  const float2 p = pos.xy;  // the pixel's middle
  const int2 at = clamp(int2(p / (scale * block)), int2(0, 0), int2((int)vec_w - 1, (int)vec_h - 1));
  const float2 v = -float2(vectors.Load(int3(at, 0))) * (scale * 0.25);
  const float2 size = float2(w, h);
  if (mode == 0) {
    const float4 a = first.SampleLevel(linear_clamp, (p - v * part) / size, 0);
    const float4 b = second.SampleLevel(linear_clamp, (p + v * (1.0 - part)) / size, 0);
    return lerp(a, b, part);
  }
  return second.SampleLevel(linear_clamp, (p - v * part) / size, 0);
}
