// scale_cs.hlsl: the network's change scaled by the strength, see NrPasses in common.h.
//
// The network itself does no more above an intensity of 1: measured on game pictures, 1.8
// and 2.0 gave the picture of 1.0 byte for byte. So a stronger picture is the lens's own
// strength, which this pass applies once the last pass has run, in place, on that pass's
// output, against the network's input, which the first pass read:
//
//   out = in + (out - in) * scale
//
// on the 0 to 255 scale, rounded to the nearest level with a half going up and held inside
// 0 to 255, as the composite rounds. The composite then adds the change the passes made
// together, scaled, to the native frame: in standard range and in HDR alike, since both
// composites read the same two textures. scale is above 1 and at most 2 (common.h,
// kStrengthMost). At 1 this shader is not run, so the switch off, the key missing or a
// strength of 1 changes no byte.
//
// (out - in) is a whole number and the product and the sum are each rounded once, with
// precise, so a CPU can do the same arithmetic to the byte. For a scale of 2 and of 1.5
// every value is exact in a float, which the self test uses to check the output.
//
// The output is read and written through one typed unordered access view, each thread its
// own texel, which needs a device that can load R8G8B8A8_UNORM through such a view
// (pipeline.cpp looks, and every RTX card can).

cbuffer Constants : register(b0) {
  uint g_w;        // the work size
  uint g_h;
  float g_scale;   // above 1, at most 2
  uint g_unused;
};

Texture2D<float4> g_in : register(t0);            // R8G8B8A8_UNORM, the network's input
RWTexture2D<unorm float4> g_out : register(u0);   // R8G8B8A8_UNORM, the last pass's output, read and written

// The whole number a texel holds, 0 to 255.
float3 level(float4 texel) { return floor(texel.rgb * 255.0 + 0.5); }

[numthreads(8, 8, 1)]
void main(uint3 id : SV_DispatchThreadID) {
  if (id.x >= g_w || id.y >= g_h) return;
  const float3 a = level(g_in.Load(int3(id.xy, 0)));
  const float4 o = g_out[id.xy];
  const float3 b = level(o);
  precise float3 v = a + (b - a) * g_scale;
  // to the nearest level, a half going up, then held inside 0 to 255
  float3 q = floor(v);
  q += step(0.5, v - q);
  g_out[id.xy] = float4(clamp(q, 0.0, 255.0) / 255.0, o.a);
}
