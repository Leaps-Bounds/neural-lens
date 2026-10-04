// fullscreen_vs.hlsl: one triangle that covers the whole target, made from the vertex
// number alone, so the draw needs no vertex buffer and no input layout. Three vertices at
// (-1, 1), (3, 1) and (-1, -3): the target is the part of the triangle inside the clip
// square, every pixel of it covered once and with no diagonal seam, which two triangles
// would have.

float4 main(uint id : SV_VertexID) : SV_Position {
  const float2 corner = float2((float)((id << 1) & 2), (float)(id & 2));  // (0,0) (2,0) (0,2)
  return float4(corner.x * 2.0 - 1.0, 1.0 - corner.y * 2.0, 0.0, 1.0);
}
