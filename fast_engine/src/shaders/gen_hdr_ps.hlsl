// gen_hdr_ps.hlsl: gen_ps.hlsl built for 16-bit scRGB pictures, where the gate's threshold
// needs the samples on an encoded scale first, see encode() there. A second blob so that the
// 8-bit form carries no branch for it: the warp's loops unroll only with everything static,
// and a runtime switch in them cost it nearly three times its time, measured.
#define HDR 1
#include "gen_ps.hlsl"
