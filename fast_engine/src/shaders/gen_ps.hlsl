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
//
// One vector a block is wrong wherever a block holds two motions, at the edge of a thing
// that moves against its background, now and then for a whole block of fine texture that
// matched elsewhere, and over most of the picture once the motion outruns the estimator,
// from about 50 texels a frame at 1440p. So where the block's own vector fails a texel, the
// texel tries the eight neighbouring blocks' vectors, no motion at all, and the nine vectors
// of each of up to three coarser estimates, at half, a quarter and an eighth of the size
// (framegen.h: each one's blocks twice as large and its reach twice as far as the one
// before), and takes the one the two pictures agree on best, if it beats the
// block's own by a clear margin. Whether a vector fails is read off the pictures
// themselves: the disagreement between the first picture moved on by it and the second
// moved back, over a window round the texel, 3x3 for the block's own vector and a 5x5
// extent for the trial of the others, taken at nine texels two apart. Where the block's own
// vector holds, which is nearly everywhere, nothing changes against the plain warp.
//
// Measured offline on synthetic sequences with known motion, the research in
// _harnesses\wip-060\research\framegen-quality, whose README holds the figures: against
// the plain warp this takes a third off a 32 texel pan's error and 40 to 60 percent off a
// 64 and a 128 texel pan's, and 40 percent off a textured thing's crossing of its
// background, for a fraction of a millisecond a 1440p frame, more where the motion outruns
// the estimator and most on heavy grain, which opens the gate at every texel (its threshold
// is six levels on a 3x3 mean; grain of sigma 5 and up is over it everywhere). A search
// without the gate and the margin made the sprite's edges a third better and everything
// else a fifth worse, the ties in weak texture going to chance. A hint to the estimator
// from the frame before changed nothing at all.
#include "gen_common.hlsli"

// The noise pass's histogram of the block's own vector's 3x3 disagreement over the picture,
// sixteen bins of a level each, the count at the end, see gen_noise_cs.hlsl
ByteAddressBuffer noise_acc : register(t6);

// Grain or shimmer leaves the two pictures apart everywhere, by the same amount wherever the
// vector is right, and opened the gate at every texel from sigma 5 up (measured, the
// research): the threshold is the larger of the six levels and 1.8 times the 25th percentile
// of the frame's own disagreement, so a wrong vector, tens of levels, still opens it and
// grain does not. A low percentile, not the mean: where the estimator fails over much of the
// picture the failures would raise a mean, and did, and the gate with it. At 1.8 a tenth of
// the texels still opened on sigma 6 grain; 2.0 closes most of them, and a clean picture's
// percentile, a level or two, keeps the floor either way
static const float kNoiseFactor = 2.0;
float gate_threshold() {
  if (adaptive == 0) return kFailsAt;
  const uint count = noise_acc.Load(64);
  if (count == 0) return kFailsAt;
  const uint quarter = (count + 3) / 4;
  uint seen = 0;
  float noise = 16.0 / 255.0;
  [unroll] for (uint b = 0; b < 16; ++b) {
    seen += noise_acc.Load(4 * b);
    if (seen >= quarter) {
      noise = ((float)b + 0.5) / 255.0;
      break;
    }
  }
  return max(kFailsAt, kNoiseFactor * noise);
}

float4 main(float4 pos : SV_Position) : SV_Target {
  const float2 p = pos.xy;  // the pixel's middle
  const float2 size = float2(w, h);
  const int2 at = int2(p / (scale * block));
  float2 v = move_at(at);
  const float own = disagreement(p, v, size, 1, 1.0);
  if (own > gate_threshold()) {
    // the block's own vector fails here: the neighbours' and no motion, over a wider window,
    // against the own one over the same window
    float best = disagreement(p, v, size, 1, 2.0) * kMargin;
    [unroll] for (int ny = -1; ny <= 1; ++ny) {
      [unroll] for (int nx = -1; nx <= 1; ++nx) {
        if (nx == 0 && ny == 0) continue;
        const float2 u = move_at(at + int2(nx, ny));
        const float c = disagreement(p, u, size, 1, 2.0);
        if (c < best) {
          best = c;
          v = u;
        }
      }
    }
    {
      const float c = disagreement(p, float2(0.0, 0.0), size, 1, 2.0);
      if (c < best) {
        best = c;
        v = float2(0.0, 0.0);
      }
    }
    // the coarser estimates' vectors, this block's and its neighbours' at each level, which
    // reach twice as far at each and see past finer texture
    [unroll] for (int lv = 0; lv < 3; ++lv) {
      if ((uint)lv >= levels) break;
      const int2 atl = int2(p / (lscale[lv] * block));
      [unroll] for (int cy = -1; cy <= 1; ++cy) {
        [unroll] for (int cx = -1; cx <= 1; ++cx) {
          const float2 u = level_move_at(lv, atl + int2(cx, cy));
          const float c = disagreement(p, u, size, 1, 2.0);
          if (c < best) {
            best = c;
            v = u;
          }
        }
      }
    }
  }
  if (mode == 0) {
    const float2 pa = p - v * part;
    const float2 pb = p + v * (1.0 - part);
    const float4 a = first.SampleLevel(linear_clamp, pa / size, 0);
    const float4 b = second.SampleLevel(linear_clamp, pb / size, 0);
    // at the picture's edge one of the two may have no content for the texel, it came in or
    // went out between the frames and the sample lies outside: then the other alone, not a
    // blend with the clamped edge
    const bool a_in = all(pa >= 0.0) && all(pa <= size);
    const bool b_in = all(pb >= 0.0) && all(pb <= size);
    if (a_in != b_in) return a_in ? a : b;
    return lerp(a, b, part);
  }
  // ahead: where the carried-on sample lies outside the second picture nothing is known of
  // the content coming in, and the clamped edge is the least wrong: the picture's own texel
  // there, tried, put the same content twice with a seam, 1 to 2 percent worse measured
  return second.SampleLevel(linear_clamp, (p - v * part) / size, 0);
}
