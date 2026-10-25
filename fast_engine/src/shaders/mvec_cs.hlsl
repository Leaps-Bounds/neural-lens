// mvec_cs.hlsl: the card's motion estimate as the network's motion vectors, see model_motion.h
// and Pipeline::set_model_motion. One texel of the field for each work texel, R16G16_FLOAT,
// each the vector of the estimator's block the work texel's centre falls in, in work texels.
//
// The estimator (framegen.h) gives one vector for each 8x8 block of its picture, in quarter
// texels of that picture, pointing from the block in the new frame to where its content was in
// the frame before: previous minus current, x to the right and y down, which is the network's
// own convention, so nothing is turned round. Its picture and the work picture each cover the
// whole captured frame, so the one maps onto the other by a scale on each axis and no offset.
// A unit of a vector is therefore g_ux = 0.25 work_w / me_w work texels across and g_uy =
// 0.25 work_h / me_h down, each axis by itself, since a work size need not keep the frame's
// shape (2560x896 for 6144x2560).
//
// The block of a work texel x is floor((x + 0.5) me_w / (8 work_w)), done here in whole
// numbers as ((2x + 1) me_w) / (16 work_w), so no rounding moves a texel into the block beside
// it, and held inside the grid, whose last block may be partial. The nearest block, no
// blending: a vector spread into the blocks beside it would move still content next to moving
// content, and the network reads a wrong vector on still content as damage.
//
// A raw zero comes out as exactly 0.0, so a still picture hands the network zeros. g_constant
// is for the sequence mode's research switches alone: one vector everywhere, in work texels.
cbuffer Constants : register(b0) {
  uint g_w;         // the work size
  uint g_h;
  uint g_me_w;      // the estimator's picture
  uint g_me_h;
  uint g_vec_w;     // its grid of blocks
  uint g_vec_h;
  float g_ux;       // work texels per unit of a vector, across and down, a research switch's
  float g_uy;       // factor included
  uint g_constant;  // 1: (g_cx, g_cy) everywhere, the grid unread
  float g_cx;
  float g_cy;
  uint g_unused;
};

Texture2D<int2> g_vectors : register(t0);    // R16G16_SINT, g_vec_w x g_vec_h, quarter texels
RWTexture2D<float2> g_field : register(u0);  // R16G16_FLOAT, the work size

[numthreads(8, 8, 1)]
void main(uint3 id : SV_DispatchThreadID) {
  if (id.x >= g_w || id.y >= g_h) return;
  if (g_constant != 0) {
    g_field[id.xy] = float2(g_cx, g_cy);
    return;
  }
  const uint bx = min(((2 * id.x + 1) * g_me_w) / (16 * g_w), g_vec_w - 1);
  const uint by = min(((2 * id.y + 1) * g_me_h) / (16 * g_h), g_vec_h - 1);
  const int2 v = g_vectors.Load(int3(bx, by, 0));
  g_field[id.xy] = float2(v) * float2(g_ux, g_uy);
}
