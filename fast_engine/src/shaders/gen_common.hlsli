// gen_common.hlsli: what the warp (gen_ps.hlsl, and gen_hdr_ps.hlsl with HDR defined) and the
// noise pass before it (gen_noise_cs.hlsl) share: the constants, the pictures, the vectors,
// and the disagreement between the two pictures under a vector, see gen_ps.hlsl.
cbuffer Constants : register(b0) {
  uint w;        // the target
  uint h;
  uint vec_w;    // the vectors
  uint vec_h;
  float scale;   // the target's texels per texel of the estimator's picture
  float block;   // the block's side, in the estimator's texels
  float part;    // how far between the frames, 0.5 for the midpoint
  uint mode;
  uint levels;   // the coarser estimates drawn from, 0 to 3, see framegen.h: each at half the
  uint adaptive; // 1: the gate's threshold follows the frame's noise, see gate_threshold()
  float white;   // a 16-bit picture's SDR white level in units of 80 nits, see encode(); 1 else
  uint pad2;
  uint4 lvec_w;  // each level's vectors, x y z for the levels (w unused)
  uint4 lvec_h;
  float4 lscale; // the target's texels per texel of each level's picture
};

Texture2D<float4> first : register(t0);
Texture2D<float4> second : register(t1);
Texture2D<int2> vectors : register(t2);
Texture2D<int2> level_vectors[3] : register(t3);
SamplerState linear_clamp : register(s0);

static const float3 kLuma = float3(0.299, 0.587, 0.114);
// A vector fails its texel when the pictures disagree by more than this a tap, six levels of
// 255 a tap: resampling alone leaves a few levels on texture, a wrong vector leaves tens
static const float kFailsAt = 6.0 / 255.0;   // the pictures are sampled on the 0 to 1 scale
// Another vector takes over only when its disagreement is under this share of the own one's
static const float kMargin = 0.6;
// The coarser levels' candidates compete on the same margin: a stricter one for them, 0.85,
// was tried against the few ahead-mode cases the levels made 2 to 5 percent worse (the flat
// sprites' boxes, the HUD) and left them where they were, costing the 128 px pan 3 to 4
// percent (measured, the research)

// The content's move from the first picture to the second at a block, in the target's texels
float2 move_at(int2 at) {
  at = clamp(at, int2(0, 0), int2((int)vec_w - 1, (int)vec_h - 1));
  return -float2(vectors.Load(int3(at, 0))) * (scale * 0.25);
}

// The same from a coarser level, whose blocks are larger on the target by its scale
float2 level_move_at(int lv, int2 at) {
  at = clamp(at, int2(0, 0), int2((int)lvec_w[lv] - 1, (int)lvec_h[lv] - 1));
  return -float2(level_vectors[lv].Load(int3(at, 0))) * (lscale[lv] * 0.25);
}

// The gate's threshold and the noise pass's bins are in levels of an 8-bit encoded picture,
// whose white is at 1. A 16-bit picture is linear scRGB, 1.0 being 80 nits, so its samples
// go on a like scale first: scaled by the SDR white level, so standard range content fills
// 0 to 1 as in 8-bit, what is brighter compressed above that (2 - 1/c, continuous at 1,
// rising towards 2, so a threefold highlight has a quarter of the range above white), then
// the gamma. Built in with HDR defined: gen_hdr_ps.hlsl and gen_noise_hdr_cs.hlsl, the blobs
// of the 16-bit pipeline states. With 80 nits at 1 instead, as at first, a 240 nit white sat
// at 1.2 and a threefold highlight in a tenth of the range above it (measured, the research)
float3 encode(float3 c) {
  c = max(c / max(white, 1.0), 0.0);
  c = c <= 1.0 ? c : 2.0 - 1.0 / c;
  return pow(c, 1.0 / 2.2);
}

// The two pictures' disagreement at p + d when the content there moved by v: for between,
// the first moved on by part against the second moved back by the rest, both at the made
// picture's moment; for ahead, the second against the first moved on by v, round the place
// the content at p sat in the second.
float disagree_at(float2 p, float2 d, float2 v, float2 size) {
  float3 a, b;
  if (mode == 0) {
    a = first.SampleLevel(linear_clamp, (p + d - v * part) / size, 0).rgb;
    b = second.SampleLevel(linear_clamp, (p + d + v * (1.0 - part)) / size, 0).rgb;
  } else {
    const float2 q = p - v * part;
    b = second.SampleLevel(linear_clamp, (q + d) / size, 0).rgb;
    a = first.SampleLevel(linear_clamp, (q + d - v) / size, 0).rgb;
  }
#ifdef HDR
  a = encode(a);
  b = encode(b);
#endif
  return dot(abs(a - b), kLuma);
}

// The mean disagreement over the (2r+1)x(2r+1) taps round p, step texels apart
float disagreement(float2 p, float2 v, float2 size, int r, float step) {
  float c = 0.0;
  for (int dy = -r; dy <= r; ++dy) {
    for (int dx = -r; dx <= r; ++dx) c += disagree_at(p, float2(dx, dy) * step, v, size);
  }
  const float n = (float)(2 * r + 1) * (float)(2 * r + 1);
  return c / n;
}
