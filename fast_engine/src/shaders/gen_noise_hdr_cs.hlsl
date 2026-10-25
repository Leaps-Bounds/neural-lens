// gen_noise_hdr_cs.hlsl: gen_noise_cs.hlsl built for 16-bit scRGB pictures, whose samples go on
// the encoded scale first, as the warp's do in gen_hdr_ps.hlsl, so the histogram and the gate
// read the same levels. A second blob, as the warp has, so the 8-bit form carries no branch.
#define HDR 1
#include "gen_noise_cs.hlsl"
