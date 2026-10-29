// edge_mark_cs.hlsl, the first pass of the edge detector, see edges.h. One thread for each work
// texel. It takes the optical flow unit's cell under the texel's centre, marks the texel where
// that cell's vector steps by more than g_step against any of its four neighbours, and counts
// the marked texels inside the interior I.
//
// The flow holds one vector for each block of 4 by 4 texels of the motion estimator's picture,
// g_me_w x g_me_h, in 32nds of its texels, as the unit wrote them, R16G16_SINT, rows of g_cells_w
// pairs. Only the g_crop_w x g_crop_h cells over the picture itself are read, never those of
// the padding. A step of 2 texels is |a - b| > 64 on the raw pairs, which is the same test as
// |a / 32 - b / 32| > 2 on the vectors in floats, since both quotients and their difference are
// exact in a float. Marking a cell where any neighbour steps marks both cells of every pair
// that steps.
//
// The cell under the work texel x is floor((x + 0.5) g_me_w / (4 g_w)), done in whole numbers as
// ((2x + 1) g_me_w) / (8 g_w) and held inside the crop, the rule mvec_cs.hlsl takes its blocks
// by, so no rounding moves a texel into the cell beside it.
//
// I is the work picture less its outer g_border texels at each side. The count is summed in
// the group and added once a group into g_counts at byte g_count, which the detect list clears
// before this pass.
cbuffer Constants : register(b0) {
  uint g_w;        // the work size
  uint g_h;
  uint g_me_w;     // the motion estimator's picture, which the flow was taken of
  uint g_me_h;
  uint g_cells_w;  // the pairs in a row of the flow buffer
  uint g_crop_w;   // the cells over the picture itself
  uint g_crop_h;
  uint g_step;     // a step above this many 32nds of a texel marks the cell
  uint g_border;   // I leaves this many texels out at each side
  uint g_count;    // the byte of this detect's count in g_counts
  uint g_unused0;
  uint g_unused1;
};

Buffer<int2> g_flow : register(t0);           // R16G16_SINT, the unit's flow
RWTexture2D<uint> g_mark : register(u0);      // R8_UINT, the work size, 1 where marked
RWByteAddressBuffer g_counts : register(u1);  // the marked texels inside I, at g_count

groupshared uint s_count;

bool steps(int2 a, int2 b) {
  const int2 d = abs(a - b);
  return d.x > (int)g_step || d.y > (int)g_step;
}

[numthreads(8, 8, 1)]
void main(uint3 id : SV_DispatchThreadID, uint gi : SV_GroupIndex) {
  if (gi == 0) s_count = 0;
  GroupMemoryBarrierWithGroupSync();
  if (id.x < g_w && id.y < g_h) {
    const uint cx = min(((2 * id.x + 1) * g_me_w) / (8 * g_w), g_crop_w - 1);
    const uint cy = min(((2 * id.y + 1) * g_me_h) / (8 * g_h), g_crop_h - 1);
    const uint at = cy * g_cells_w + cx;
    const int2 c = g_flow[at];
    bool marked = false;
    if (cx > 0 && steps(c, g_flow[at - 1])) marked = true;
    if (cx + 1 < g_crop_w && steps(c, g_flow[at + 1])) marked = true;
    if (cy > 0 && steps(c, g_flow[at - g_cells_w])) marked = true;
    if (cy + 1 < g_crop_h && steps(c, g_flow[at + g_cells_w])) marked = true;
    g_mark[id.xy] = marked ? 1u : 0u;
    const bool inside = id.x >= g_border && id.x + g_border < g_w && id.y >= g_border && id.y + g_border < g_h;
    if (marked && inside) InterlockedAdd(s_count, 1u);
  }
  GroupMemoryBarrierWithGroupSync();
  if (gi == 0 && s_count > 0) g_counts.InterlockedAdd(g_count, s_count);
}
