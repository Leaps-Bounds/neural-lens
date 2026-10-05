// convert_cs.hlsl: a captured frame in 16-bit floats to the 8-bit frame the pipeline takes.
//
// With Windows HDR on for a monitor the desktop is composed in scRGB, linear with 1.0 at
// 80 nits, and standard programs are shown at the SDR white level, 1.0 to 6.0 (80 to 480
// nits, a slider in Windows). An 8-bit capture of that monitor is the desktop clipped at
// 1.0 and sRGB-encoded, so everything from 80 nits up is one white and the rest comes out
// about three times too bright once the lens presents it in standard range, since Windows
// then shows the lens at SDR white too. This pass undoes that, texel by texel:
//
//   level = round(255 * srgb(clamp(scRGB / white, 0, 1)))
//
// where white is the SDR white level in units of 80 nits. A standard program's white comes
// out as 255, its greys where they were, and what lies above SDR white, true HDR content, is
// clipped to white as any standard program shows it. The pipeline then compares, downscales,
// runs the network and composes on this frame as it does on an 8-bit capture, and Windows
// shows the result at SDR white, which matches the desktop's standard content.
//
// The sRGB transfer function is the one in the standard: 12.92 c below 0.0031308, else
// 1.055 c^(1/2.4) - 0.055. The rounding is explicit, a half going up, as the other shaders
// do it, so the level does not depend on how a unorm store rounds.

cbuffer Constants : register(b0) {
  uint g_w;         // the frame, W x H
  uint g_h;
  float g_scale;    // 1 / white
  uint g_unused;
};

Texture2D<float4> g_src : register(t0);           // R16G16B16A16_FLOAT, scRGB
RWTexture2D<unorm float4> g_dst : register(u0);   // R8G8B8A8_UNORM

float3 srgb_encode(float3 c) {
  const float3 low = c * 12.92;
  const float3 high = 1.055 * pow(max(c, 0.0), 1.0 / 2.4) - 0.055;
  return (c <= 0.0031308) ? low : high;
}

[numthreads(8, 8, 1)]
void main(uint3 id : SV_DispatchThreadID) {
  if (id.x >= g_w || id.y >= g_h) return;
  const float3 lin = saturate(g_src.Load(int3(id.xy, 0)).rgb * g_scale);
  const float3 enc = srgb_encode(lin);
  const float3 level = floor(enc * 255.0 + 0.5);
  g_dst[id.xy] = float4(clamp(level, 0.0, 255.0) / 255.0, 1.0);
}
