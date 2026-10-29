// flowluma_cs.hlsl, the optical flow unit's input. It writes the luma of a new frame at the
// motion estimator's size into the buffer the unit copies into its session (flow.h), one
// byte a texel, a row after another, padded to the session's size.
//
// The unit is given the luma the research's optical flow probe gave it, byte for byte, so
// that its flow, and the edges found in it, are the research's own. For an 8-bit frame the
// frame is first brought to the estimator's size by the exact area filter of
// ingest_cs.hlsl, with the same footprint in whole numbers, the level back from the UNORM
// value, precise float taps with the weights from the CPU (pipeline.cpp area_weights),
// across each row and then down, and each channel is rounded to the nearest level with a
// half going up. The luma of those levels is the BT.709 sum rounded to the nearest whole
// number. The probe took that sum in double, as floor(0.2126 R + 0.7152 G + 0.0722 B + 0.5).
// Here it is (2126 R + 7152 G + 722 B + 5000) / 10000 in whole numbers, which gives the same
// for every colour but those whose exact luma lies on a half. For 769 of those 3368 colours
// the double sum lands just below the half and the probe's luma is one less. They are the
// keys of g_ties, made when the unit starts by the probe's own line and found here by a
// binary search, which runs for those colours alone.
//
// A 16-bit frame, linear scRGB with 1.0 at 80 nits, gets the same filter on its linear
// values and then the probe's luma for such frames in float. Each channel is scaled by the
// SDR white and kneed as nv12_cs.hlsl does (0.8 c up to the white, 1 - 0.2 / c above it),
// and 255 times their BT.709 sum is rounded to the nearest whole number.
//
// The session's picture is pad8(w) by pad8(h). Past the picture the last column and the
// last row repeat, as the probe padded. One thread writes four texels of a row, one 32-bit
// word, so a padded row, a multiple of 8 texels, is whole words.

cbuffer Constants : register(b0) {
  uint g_src_w;      // the frame, W x H
  uint g_src_h;
  uint g_me_w;       // the estimator's picture, w x h
  uint g_me_h;
  uint g_pad_w;      // the session's picture, pad8(w) x pad8(h)
  uint g_pad_h;
  uint g_taps_x;     // weights kept for each texel across, the widest footprint
  uint g_taps_y;     // and down
  uint g_fp16;       // 1 when the frame is in 16-bit floats, linear scRGB
  float g_white;     // for a 16-bit frame, the SDR white level in units of 80 nits
  uint g_tie_count;  // the keys in g_ties
};

Texture2D<float4> g_frame : register(t0);      // B8G8R8A8_UNORM, or R16G16B16A16_FLOAT with g_fp16
// w * g_taps_x weights across, then h * g_taps_y weights down. The weight of the n-th
// texel of texel i's footprint is at i * taps + n.
Buffer<float> g_weights : register(t1);
StructuredBuffer<uint> g_ties : register(t2);  // (R << 16) | (G << 8) | B, ascending
RWByteAddressBuffer g_luma : register(u0);     // g_pad_w * g_pad_h bytes

// The area filter of ingest_cs.hlsl for texel (x, y) of the w x h picture, in its order.
float3 area(uint x, uint y) {
  // the footprint, in units of 1/w of a frame texel across and 1/h down
  const uint ax = x * g_src_w, bx = ax + g_src_w;
  const uint ay = y * g_src_h, by = ay + g_src_h;
  const uint x0 = ax / g_me_w, x1 = (bx + g_me_w - 1) / g_me_w;  // first texel, one past the last
  const uint y0 = ay / g_me_h, y1 = (by + g_me_h - 1) / g_me_h;
  // where this texel's weights start, less the first texel, so texel x is at + x
  const uint across = x * g_taps_x - x0;
  const uint down = g_me_w * g_taps_x + y * g_taps_y - y0;

  precise float3 sum = 0.0;
  [loop] for (uint fy = y0; fy < y1; ++fy) {
    precise float3 row = 0.0;
    [loop] for (uint fx = x0; fx < x1; ++fx) {
      const float4 c = g_frame.Load(int3(fx, fy, 0));
      float3 level;
      if (g_fp16 != 0) {
        level = c.rgb;
      } else {
        // back to the whole number the texel holds, so the sums run on what the probe summed
        level = floor(c.rgb * 255.0 + 0.5);
      }
      precise float3 tap = g_weights[across + fx] * level;
      row = row + tap;
    }
    precise float3 part = g_weights[down + fy] * row;
    sum = sum + part;
  }
  return sum;
}

// Whether a colour is one of those whose probe luma is one less than the rounded sum.
bool is_tie(uint key) {
  uint lo = 0, hi = g_tie_count;
  [loop] while (lo < hi) {
    const uint mid = (lo + hi) >> 1;
    if (g_ties[mid] < key) {
      lo = mid + 1;
    } else {
      hi = mid;
    }
  }
  return lo < g_tie_count && g_ties[lo] == key;
}

uint luma_of_levels(float3 sum) {
  // to the nearest level, a half going up, as ingest_cs.hlsl rounds the work picture
  float3 level = floor(sum);
  level += step(0.5, sum - level);
  const uint3 l = (uint3)clamp(level, 0.0, 255.0);
  const uint s = 2126u * l.r + 7152u * l.g + 722u * l.b;
  uint y = (s + 5000u) / 10000u;
  if (s % 10000u == 5000u && is_tie((l.r << 16) | (l.g << 8) | l.b)) y -= 1u;
  return y;
}

uint luma_of_linear(float3 sum) {
  const float s = 1.0 / max(g_white, 1.0);
  const float3 c = max(sum * s, 0.0);
  const float3 k = min(0.8 * c, 1.0 - 0.2 / max(c, 1.0));
  const float y = 0.2126 * k.r + 0.7152 * k.g + 0.0722 * k.b;
  return (uint)clamp(floor(255.0 * y + 0.5), 0.0, 255.0);
}

[numthreads(8, 8, 1)]
void main(uint3 id : SV_DispatchThreadID) {
  if (id.x >= g_pad_w / 4 || id.y >= g_pad_h) return;
  const uint y = min(id.y, g_me_h - 1);
  uint word = 0;
  [unroll] for (uint k = 0; k < 4; ++k) {
    const uint x = min(id.x * 4 + k, g_me_w - 1);
    const float3 sum = area(x, y);
    const uint v = g_fp16 != 0 ? luma_of_linear(sum) : luma_of_levels(sum);
    word |= v << (8 * k);
  }
  g_luma.Store(id.y * g_pad_w + id.x * 4, word);
}
