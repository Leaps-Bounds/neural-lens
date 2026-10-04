// ingest_cs.hlsl: one pass over a new frame that does two things.
//
//   1. Area downscale of the frame to the network's work size: an exact box filter, where a
//      source texel that lies partly under a work texel counts by the share of it that does.
//   2. Exact comparison of the frame with the one before it, every texel, every channel.
//
// One thread works on one work texel. Its footprint in the source, for work texel i along
// one axis with W source texels and w work texels, is the source range [i*W/w, (i+1)*W/w):
// the texels from floor(i*W/w) up to, but not including, ceil((i+1)*W/w). Both are computed
// in whole numbers, so the footprint is exact for any pair of sizes.
//
// Why the comparison is complete: each source texel x is OWNED by exactly one work texel,
// the one with ceil(i*W/w) <= x < ceil((i+1)*W/w). Those ranges follow each other without a
// gap from 0 to W, and each lies inside its work texel's footprint, which starts at
// floor(i*W/w), at most one texel earlier. A thread compares the texels it owns and only
// those, so every source texel is compared exactly once. The same holds for the rows.
// The self test checks it with single texels changed by one level, corners included.
//
// The average follows the probe's AreaDownscale step by step, on the same 0 to 255 scale
// and in the same order: across each source row first, then down the rows. The weights
// come from the CPU (pipeline.cpp computes them as the probe's AreaTaps does) and not from
// a division here: a GPU may round a division one unit in the last place off, and where the
// exact average lies on a half, which symmetric weights make common, that last place
// decides which way the texel rounds. Measured before the table: 1500 of 8 million values
// one level off the probe's input, and through the network's history that grew into a
// composite 0.09 away from the reference on average. With the table the network is fed the
// reference's input, byte for byte.
//
// The flag: a thread that finds a difference writes the frame's token into g_flag[0].
// Every writer writes the same value, so the race between them is harmless, and since each
// frame has a token of its own the buffer never needs clearing.
//
// It writes the token a second time, into the flag of the tile its work texel lies in: the
// picture is cut into 16 by 16 tiles, and g_flag[1 + row * 16 + column] says that tile holds
// a difference. So the loop can tell how much of the picture a frame changed, a caret in one
// tile or a page across all of them.

cbuffer Constants : register(b0) {
  uint g_src_w;      // the frame, W x H
  uint g_src_h;
  uint g_dst_w;      // the work size, w x h
  uint g_dst_h;
  uint g_token;      // written into the flag when a texel differs, never 0
  uint g_compare;    // 0: there is no frame before this one, nothing is compared
  uint g_downscale;  // 0: there is no network, nothing is written
  uint g_taps_x;     // weights kept for each work texel across, the widest footprint
  uint g_taps_y;     // and down
};

Texture2D<float4> g_cur : register(t0);            // B8G8R8A8_UNORM
Texture2D<float4> g_prev : register(t1);           // B8G8R8A8_UNORM
// w * g_taps_x weights across, then h * g_taps_y weights down. The weight of the n-th
// texel of work texel i's footprint is at i * taps + n.
Buffer<float> g_weights : register(t2);
RWTexture2D<unorm float4> g_work : register(u0);   // R8G8B8A8_UNORM, the network's input
RWBuffer<uint> g_flag : register(u1);

[numthreads(8, 8, 1)]
void main(uint3 id : SV_DispatchThreadID) {
  if (id.x >= g_dst_w || id.y >= g_dst_h) return;

  // the footprint, in units of 1/w of a source texel across and 1/h down
  const uint ax = id.x * g_src_w, bx = ax + g_src_w;
  const uint ay = id.y * g_src_h, by = ay + g_src_h;
  const uint x0 = ax / g_dst_w, x1 = (bx + g_dst_w - 1) / g_dst_w;  // first texel, one past the last
  const uint y0 = ay / g_dst_h, y1 = (by + g_dst_h - 1) / g_dst_h;
  // the first texel this thread owns: ceil(ax / w), which is x0 or the one after
  const uint own_x = x0 + (x0 * g_dst_w != ax ? 1u : 0u);
  const uint own_y = y0 + (y0 * g_dst_h != ay ? 1u : 0u);
  // where this work texel's weights start, less the first texel, so texel x is at + x
  const uint across = id.x * g_taps_x - x0;
  const uint down = g_dst_w * g_taps_x + id.y * g_taps_y - y0;

  precise float3 sum = 0.0;
  bool differs = false;

  [loop] for (uint y = y0; y < y1; ++y) {
    precise float3 row = 0.0;
    [loop] for (uint x = x0; x < x1; ++x) {
      const float4 c = g_cur.Load(int3(x, y, 0));
      // back to the whole number the texel holds, so the sums run on what the probe summed
      const float3 level = floor(c.rgb * 255.0 + 0.5);
      precise float3 tap = g_weights[across + x] * level;
      row = row + tap;
      if (g_compare != 0 && x >= own_x && y >= own_y) {
        const float4 p = g_prev.Load(int3(x, y, 0));
        if (any(c != p)) differs = true;
      }
    }
    precise float3 part = g_weights[down + y] * row;
    sum = sum + part;
  }

  if (g_downscale != 0) {
    // to the nearest level, a half going up, as std::round does for what is never negative
    float3 level = floor(sum);
    level += step(0.5, sum - level);
    g_work[id.xy] = float4(clamp(level, 0.0, 255.0) / 255.0, 1.0);
  }
  if (differs) {
    g_flag[0] = g_token;
    g_flag[1u + (id.y * 16u / g_dst_h) * 16u + id.x * 16u / g_dst_w] = g_token;
  }
}
