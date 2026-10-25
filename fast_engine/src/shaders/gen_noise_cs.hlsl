// gen_noise_cs.hlsl: the frame's own noise, for the warp's gate (gen_ps.hlsl). One thread for
// every 16x16 block of the target takes the block's own vector's 3x3 disagreement at the
// block's middle and counts it into a histogram of sixteen bins, a level of 255 each, the
// last holding everything from fifteen up, with the count at the end; the buffer is zeroed
// before each pass. The warp reads a low percentile of it: on a clean picture with right
// vectors that is the resampling's residue, a level or two, and the gate stays at its six;
// on grain it is just under the grain's level, and the gate rises above it; where the
// estimator fails over much of the picture the failures fill the top bin and the percentile
// stays low, which a mean did not (measured, the research). About 14,000 threads at 1440p.
#include "gen_common.hlsli"

RWByteAddressBuffer noise_acc : register(u0);

[numthreads(8, 8, 1)]
void main(uint3 id : SV_DispatchThreadID) {
  const float2 size = float2(w, h);
  const float2 p = (float2(id.xy) + 0.5) * 16.0;
  if (p.x >= size.x || p.y >= size.y) return;
  const int2 at = int2(p / (scale * block));
  const float2 v = move_at(at);
  const float d = disagreement(p, v, size, 1, 1.0);
  const uint bin = min((uint)(d * 255.0), 15u);
  noise_acc.InterlockedAdd(4 * bin, 1u);
  noise_acc.InterlockedAdd(64, 1u);
}
