// edge_cut_cs.hlsl, the cut of the edge detector, see edges.h. One thread for each work texel.
// It runs in the render list right after mvec_cs.hlsl has resolved the card's motion estimate
// into the network's field. Every texel of the field inside the zone is written as the vector
// (0, 0), which tells the network that nothing moved there, and the texels outside the zone are
// not touched, so they keep the resolve's bits.
//
// The zero is a constant, so both halves of the texel are +0.0, 0x0000. It is not the vector
// times 0, which would give -0.0 where a component is negative.
cbuffer Constants : register(b0) {
  uint g_w;  // the work size
  uint g_h;
  uint g_unused0;
  uint g_unused1;
};

Texture2D<uint> g_zone : register(t0);       // R8_UINT, the work size, 1 inside the zone
RWTexture2D<float2> g_field : register(u0);  // R16G16_FLOAT, the work size, the network's field

[numthreads(8, 8, 1)]
void main(uint3 id : SV_DispatchThreadID) {
  if (id.x >= g_w || id.y >= g_h) return;
  if (g_zone[id.xy] != 0) g_field[id.xy] = float2(0.0f, 0.0f);
}
