// edge_grow_cs.hlsl, the second and third passes of the edge detector, see edges.h. Each texel
// takes the largest value of g_src within kRadius texels of it along one line, across
// (g_down 0, the marked texels into the across maxima) or down (g_down 1, the across maxima
// into the zone). The two together give every texel within kRadius texels of a marked texel
// in both directions, a square of 33 by 33, since the largest value over a square is the
// largest over its columns of the largest over its rows. Texels outside the picture are left
// out, which reading them as 0 does, as the values are 0 and 1 and the texel itself always
// counts.
//
// The pass down also keeps the zone inside the interior I, the work picture less its outer
// g_border texels at each side, and empties it on a frame the guard stops, one where the
// marked texels inside I, which edge_mark_cs.hlsl counted at byte g_count of g_counts, are
// more than g_limit. It counts the zone's texels into byte g_count + 4.
//
// A group of kGroup threads takes kGroup texels of one line, the row (across) or the column
// (down) group.y, from group.x * kGroup on, and first loads them with kRadius more at each end
// into groupshared memory.
cbuffer Constants : register(b0) {
  uint g_w;       // the work size
  uint g_h;
  uint g_down;    // 0 across, 1 down
  uint g_border;  // I leaves this many texels out at each side
  uint g_limit;   // the guard's limit on the marked texels inside I
  uint g_count;   // the byte of this detect's counts in g_counts
  uint g_unused0;
  uint g_unused1;
};

static const uint kRadius = 16;  // the zone's reach in work texels, Edges::kWidth
static const uint kGroup = 64;
static const uint kSpan = kGroup + 2 * kRadius;

Texture2D<uint> g_src : register(t0);         // R8_UINT, the marked texels or the across maxima
RWTexture2D<uint> g_dst : register(u0);       // R8_UINT, the across maxima or the zone
RWByteAddressBuffer g_counts : register(u1);  // the marked texels inside I, and the zone's texels

groupshared uint s_line[kSpan];
groupshared uint s_zoned;

[numthreads(64, 1, 1)]
void main(uint3 group : SV_GroupID, uint3 thread : SV_GroupThreadID) {
  const uint along = g_down != 0 ? g_h : g_w;
  const uint first = group.x * kGroup;
  const uint strip = group.y;
  if (thread.x == 0) s_zoned = 0;
  for (uint i = thread.x; i < kSpan; i += kGroup) {
    const int p = (int)(first + i) - (int)kRadius;
    uint v = 0;
    if (p >= 0 && p < (int)along) v = g_down != 0 ? g_src[uint2(strip, (uint)p)] : g_src[uint2((uint)p, strip)];
    s_line[i] = v;
  }
  GroupMemoryBarrierWithGroupSync();
  const uint pos = first + thread.x;
  uint zoned = 0;
  if (pos < along) {
    uint m = 0;
    for (uint j = 0; j <= 2 * kRadius; ++j) m = max(m, s_line[thread.x + j]);
    if (g_down == 0) {
      g_dst[uint2(pos, strip)] = m;
    } else {
      const uint x = strip;
      const uint y = pos;
      const bool inside = x >= g_border && x + g_border < g_w && y >= g_border && y + g_border < g_h;
      const bool guarded = g_counts.Load(g_count) > g_limit;
      zoned = (m != 0 && inside && !guarded) ? 1u : 0u;
      g_dst[uint2(x, y)] = zoned;
    }
  }
  if (zoned != 0) InterlockedAdd(s_zoned, 1u);
  GroupMemoryBarrierWithGroupSync();
  if (thread.x == 0 && s_zoned > 0) g_counts.InterlockedAdd(g_count + 4, s_zoned);
}
