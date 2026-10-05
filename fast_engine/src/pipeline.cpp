// pipeline.cpp: the GPU work for one captured frame. See pipeline.h for the contract.
//
// Five shaders do it all (src\shaders):
//   convert_cs     a frame in 16-bit floats to 8 bits, scaled by the SDR white level, before
//                  anything else, see pipeline.h. Never for an 8-bit frame
//   ingest_cs      the area downscale into the network's input and the exact comparison
//                  with the frame before, in one pass over the frame
//   fullscreen_vs  one triangle over the whole target
//   composite_ps   native + upsample(network output - network input), or native alone,
//                  into an 8-bit target
//   composite_hdr_ps
//                  the same change taken back to linear light on the 16-bit frame, into a
//                  16-bit target, see pipeline.h. Never for an 8-bit target
//
// Lists. An ingest waits for the GPU, so one allocator and one list serve every ingest. A
// draw (render, repaint or a joined draw, which holds its own ingest) does not wait, so
// draws take turns on three contexts, each with its own allocator, list, descriptors and
// timestamps, and a context is taken again only once the GPU has finished what was last
// recorded from it. That is what makes it safe to reset its allocator and to write its
// descriptors. Each context has tables of its own for the ingest and the conversion as
// well, since a joined list names two frames until it is done, and a region of its own in
// the flag's readback buffer, read once the list is done, see take_flag().
//
// Resource states between calls, which every function here restores:
//   the network's input    NON_PIXEL_SHADER_RESOURCE, as Nr::evaluate wants it
//   the network's outputs  UNORDERED_ACCESS, the same
//   the flag buffer        UNORDERED_ACCESS
//   frames and targets     COMMON (PRESENT), they are someone else's
//   the converted frames   COMMON, as the frames they stand in for
//
// The work size. Everything that depends on it is one WorkSet: the network's input and
// output textures and the downscale's weights. A new work size gets a second set, made
// while the first is in use, and the two change places between two pictures, when the GPU
// has finished every list that named the old one (commit_work).
#include "pipeline.h"

#include "nr.h"

#include "composite_hdr_ps.h"
#include "composite_ps.h"
#include "convert_cs.h"
#include "fullscreen_vs.h"
#include "ingest_cs.h"

#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstring>
#include <deque>
#include <system_error>
#include <thread>

using Microsoft::WRL::ComPtr;

namespace {

constexpr DXGI_FORMAT kFrameFormat = DXGI_FORMAT_B8G8R8A8_UNORM;  // frames and targets
// A captured frame in 16-bit floats, and the 8-bit frame the conversion makes of it. The
// latter is R8G8B8A8 and not B8G8R8A8 because a typed store into R8G8B8A8_UNORM is one
// every D3D12 device supports, and the network's input is written the same way.
constexpr DXGI_FORMAT kRawFormat = DXGI_FORMAT_R16G16B16A16_FLOAT;
constexpr DXGI_FORMAT kConvertedFormat = DXGI_FORMAT_R8G8B8A8_UNORM;

constexpr int kDrawContexts = 3;
// The times queue holds four draws for each context at most, see Pipeline::keep_times().
static_assert(Pipeline::kTimesKept == 4 * kDrawContexts);
// Who records an ingest: the ingest context, whose list is waited for, and each draw
// context for a joined list, which is not. Table 0 is the ingest context's and table 1 + i
// the draw context i's, for the ingest's descriptors, the conversion's and the flag's region.
constexpr int kIngestTables = 1 + kDrawContexts;

// Every wait on the GPU in the frame loop gives up after this long: the window is topmost
// over the whole screen, and a process that waits for ever looks like a frozen computer.
constexpr DWORD kWaitMs = 2000;

// The shader visible descriptors: an ingest table of seven for each of the kIngestTables,
// then the conversion's table of two for each, then a table of four for each draw context.
// The seven of an ingest table, as offsets from its start:
constexpr UINT kSlotCur = 0;       // SRV, the new frame
constexpr UINT kSlotPrev = 1;      // SRV, the frame before
constexpr UINT kSlotWeights = 2;   // SRV, the downscale's weights
constexpr UINT kSlotWorkUav = 3;   // UAV, the network's input
constexpr UINT kSlotFlagUav = 4;   // UAV, the flags
constexpr UINT kSlotCur16 = 5;     // SRV, the new frame in 16-bit floats, when the comparison
constexpr UINT kSlotPrev16 = 6;    // SRV, and the frame before: runs on those, see record_ingest()
constexpr UINT kSlotsPerIngest = 7;
constexpr UINT kSlotIngest0 = 0;

// The flags: one uint for the whole frame and one for each tile, as the ingest shader
// numbers them. They are read back into a region of their own for each ingest table, 256
// bytes apart as copies like to be, so a joined list's answer waits there until the list
// is done and the next ingest's copy does not write over it.
constexpr UINT kFlagCount = 1 + (UINT)Pipeline::kTiles;
constexpr UINT kFlagBytes = kFlagCount * 4;
constexpr UINT kFlagStride = (kFlagBytes + 255) / 256 * 256;
// The conversion's table of two: SRV the 16-bit frame, UAV the 8-bit frame it makes.
constexpr UINT kSlotsPerConv = 2;
constexpr UINT kSlotConv0 = kSlotIngest0 + kSlotsPerIngest * kIngestTables;
// Per draw context: SRV native, SRV input, SRV output, and for a 16-bit target the SRV of
// the 16-bit frame behind the native one. The 8-bit composite's table is the first three.
constexpr UINT kSlotsPerDraw = 4;
constexpr UINT kSlotDraw0 = kSlotConv0 + kSlotsPerConv * kIngestTables;
constexpr UINT kSlotCount = kSlotDraw0 + kSlotsPerDraw * kDrawContexts;

// The timestamps: three for the ingest (start, after the conversion of a 16-bit frame,
// end), five for each draw context (the same three for the ingest a joined list holds,
// the last of which is the draw's start, then after the network, then after the composite
// and the copies). A render or a repaint marks the first three together.
constexpr UINT kTimeIngest = 0;
constexpr UINT kTimesIngest = 3;
constexpr UINT kTimeDraw0 = kTimeIngest + kTimesIngest;
constexpr UINT kTimesPerDraw = 5;
constexpr UINT kTimeCount = kTimeDraw0 + kTimesPerDraw * kDrawContexts;

// As the shaders declare them.
struct IngestConstants {
  UINT src_w, src_h, dst_w, dst_h, token, compare, downscale, taps_x, taps_y, raw_compare, unused[2];
};
struct ConvertConstants {
  UINT w, h;
  float scale;  // 1 / the SDR white level in units of 80 nits
  UINT unused;
};
struct DrawConstants {
  UINT w, h, work_w, work_h, residual;
  float inv_x, inv_y;  // the floats nearest to 1 / (2 w) and 1 / (2 h), see composite_ps.hlsl
  UINT unused;
};
struct HdrDrawConstants {
  UINT w, h, work_w, work_h, residual;
  float inv_x, inv_y;
  float white;         // the SDR white level in units of 80 nits
  UINT above;          // HdrAbove
  UINT have_raw;       // 1: the 16-bit frame behind the native one is in the table
  UINT unused[2];
};

struct Context {
  ComPtr<ID3D12CommandAllocator> allocator;
  ComPtr<ID3D12GraphicsCommandList> list;
  UINT64 fence = 0;          // what the queue's fence reaches when its last list is done
  bool used = false;
  bool ran_network = false;  // what that list held, for times()
  double ingest_ms = 0.0;    // the ingest that led to it, 0 for a repaint and for a joined
                             // draw, whose own ingest is timed by its timestamps
  bool joined = false;       // a render_joined(): the list held the ingest too
  bool converted = false;    // and that ingest converted a 16-bit frame
  bool compared = false;     // and it compared the frame with the one before
  UINT token = 0;            // the token it wrote where something differed
  bool flag_unread = false;  // a joined draw whose answer take_flag() has not given out
  bool times_unread = false; // a draw whose times take_times() has not given out
  UINT64 sequence = 0;       // the draw's number, see Pipeline::last_draw_sequence()
};

// What one work size needs. Without a network there are no textures and no weights, and
// the size only says how the comparison is cut into threads and tiles.
struct WorkSet {
  UINT w = 0, h = 0;
  ComPtr<ID3D12Resource> in;       // the network's input, the downscaled frame
  ComPtr<ID3D12Resource> out[2];   // pass n writes [n % 2] and reads what pass n - 1 wrote
  ComPtr<ID3D12Resource> weights;  // the downscale's weights, see area_weights()
  UINT taps_x = 1, taps_y = 1;
  UINT weight_count = 1;
  bool made = false;
};

bool make_root(ID3D12Device* device, const D3D12_ROOT_PARAMETER* params, UINT count, const char* what,
               ComPtr<ID3D12RootSignature>& out, std::string& err) {
  D3D12_ROOT_SIGNATURE_DESC d = {};
  d.NumParameters = count;
  d.pParameters = params;
  ComPtr<ID3DBlob> blob, problem;
  HRESULT hr = D3D12SerializeRootSignature(&d, D3D_ROOT_SIGNATURE_VERSION_1, &blob, &problem);
  if (FAILED(hr) || !blob) {
    err = strf("the %s root signature did not serialise %s", what, hr_text(hr).c_str());
    return false;
  }
  hr = device->CreateRootSignature(0, blob->GetBufferPointer(), blob->GetBufferSize(), IID_PPV_ARGS(&out));
  if (FAILED(hr)) {
    err = strf("the %s root signature failed %s", what, hr_text(hr).c_str());
    return false;
  }
  return true;
}

// The weights of the area downscale along one axis, appended to out: for each of the dst
// work texels, `taps` weights, one for each source texel of its footprint in order, 0 for
// what a narrower footprint leaves unused. taps is the widest footprint.
//
// The footprint is the shader's, in whole numbers: floor(i*src/dst) up to ceil((i+1)*src/dst).
// The weight of a texel is what the probe's AreaTaps gives it, computed the same way, in
// double and then rounded to float: the part of the texel under the work texel, over the
// scale. The same floats, so the same sums. Checked: with this table the network's input
// is the probe's work-input.png byte for byte.
void area_weights(UINT src, UINT dst, UINT& taps, std::vector<float>& out) {
  taps = 1;
  for (UINT i = 0; i < dst; ++i) {
    const UINT first = (UINT)(((UINT64)i * src) / dst);
    const UINT end = (UINT)((((UINT64)i + 1) * src + dst - 1) / dst);
    if (end - first > taps) taps = end - first;
  }
  const size_t base = out.size();
  out.resize(base + (size_t)dst * taps, 0.0f);
  const double scale = (double)src / (double)dst;
  for (UINT i = 0; i < dst; ++i) {
    const UINT first = (UINT)(((UINT64)i * src) / dst);
    const UINT end = (UINT)((((UINT64)i + 1) * src + dst - 1) / dst);
    const double a = (double)i * scale, b = (double)(i + 1) * scale;
    for (UINT x = first; x < end; ++x) {
      const double lo = a > (double)x ? a : (double)x;
      const double hi = b < (double)x + 1.0 ? b : (double)x + 1.0;
      const double part = hi - lo;
      if (part > 0.0) out[base + (size_t)i * taps + (x - first)] = (float)(part / scale);
    }
  }
}

// B8G8R8A8 rows with a pitch to tight RGB8, every step-th texel each way. With rgba the
// rows are R8G8B8A8, as a converted frame is.
void bgra_to_rgb(const uint8_t* base, UINT pitch, UINT width, UINT height, UINT step, std::vector<uint8_t>& rgb,
                 bool rgba = false) {
  const UINT w = (width + step - 1) / step, h = (height + step - 1) / step;
  rgb.resize((size_t)w * h * 3);
  uint8_t* out = rgb.data();
  const int r = rgba ? 0 : 2, b = rgba ? 2 : 0;
  for (UINT y = 0; y < height; y += step) {
    const uint8_t* in = base + (size_t)y * pitch;
    for (UINT x = 0; x < width; x += step) {
      const uint8_t* t = in + (size_t)x * 4;
      out[0] = t[r];
      out[1] = t[1];
      out[2] = t[b];
      out += 3;
    }
  }
}

// A 16-bit float as a float: the sign, five bits of exponent, ten of fraction, with the
// subnormals, infinities and NaNs of the format.
float half_to_float(uint16_t h) {
  const uint32_t sign = (uint32_t)(h & 0x8000) << 16;
  const uint32_t exponent = (h >> 10) & 0x1F;
  const uint32_t fraction = h & 0x3FF;
  uint32_t bits;
  if (exponent == 0) {
    if (fraction == 0) {
      bits = sign;  // a zero
    } else {
      // a subnormal: normalise it
      int e = -1;
      uint32_t f = fraction;
      do {
        ++e;
        f <<= 1;
      } while (!(f & 0x400));
      bits = sign | ((uint32_t)(127 - 15 - e) << 23) | ((f & 0x3FF) << 13);
    }
  } else if (exponent == 31) {
    bits = sign | 0x7F800000u | (fraction << 13);  // an infinity or a NaN
  } else {
    bits = sign | ((exponent + 127 - 15) << 23) | (fraction << 13);
  }
  float out;
  memcpy(&out, &bits, 4);
  return out;
}

// The conversion shader's formula on the CPU: a linear value in scRGB to the level Windows
// shows standard range content at, scaled by the SDR white level, clipped, sRGB-encoded,
// rounded with a half going up.
uint8_t level_of(float lin, float scale) {
  float c = lin * scale;
  if (!(c > 0.0f)) c = 0.0f;  // NaN too
  if (c > 1.0f) c = 1.0f;
  const float enc = c <= 0.0031308f ? c * 12.92f : 1.055f * std::pow(c, 1.0f / 2.4f) - 0.055f;
  const float level = std::floor(enc * 255.0f + 0.5f);
  return (uint8_t)(level < 0.0f ? 0.0f : level > 255.0f ? 255.0f : level);
}

// R16G16B16A16_FLOAT rows with a pitch to tight RGB8 as Windows shows standard range
// content on that monitor, every step-th texel each way. table is level_of() for every
// half at the scale, see Impl::levels(): the formula itself, with a pow() for each channel
// of each texel, took 0.36 s for a picture of 6144x2526 on the main thread, the table 12 ms.
void half_rows_to_rgb(const uint8_t* base, UINT pitch, UINT width, UINT height, UINT step, const uint8_t* table,
                      std::vector<uint8_t>& rgb) {
  const UINT w = (width + step - 1) / step, h = (height + step - 1) / step;
  rgb.resize((size_t)w * h * 3);
  uint8_t* out = rgb.data();
  for (UINT y = 0; y < height; y += step) {
    const uint16_t* in = (const uint16_t*)(base + (size_t)y * pitch);
    for (UINT x = 0; x < width; x += step) {
      const uint16_t* t = in + (size_t)x * 4;
      out[0] = table[t[0]];
      out[1] = table[t[1]];
      out[2] = table[t[2]];
      out += 3;
    }
  }
}

}  // namespace

struct Pipeline::Impl {
  Gpu* gpu = nullptr;
  PipelineDesc desc;
  Nr nr;
  bool network = false;     // the runtime is loaded and its textures exist
  bool nr_on = true;
  bool reset_next = true;   // the next render drops the network's history
  bool run_at_zero = false; // the self test's switch, see set_run_at_zero()
  NrPasses settings;        // each pass's own, see common.h

  ComPtr<ID3D12RootSignature> ingest_root, draw_root, draw_hdr_root, convert_root;
  ComPtr<ID3D12PipelineState> ingest_pso, draw_pso, draw_hdr_pso, convert_pso;
  ComPtr<ID3D12DescriptorHeap> heap;
  UINT heap_step = 0;
  HdrAbove hdr_above = HdrAbove::Fade;  // see set_hdr_above()

  // Frames in 16-bit floats, see pipeline.h. conv holds the 8-bit frames made of them, in
  // turns: conv[conv_index] is the conversion of conv_slot, the 16-bit frame last given to
  // ingest(), and the other one is free. Nothing until the first such frame.
  ComPtr<ID3D12Resource> conv[2];
  int conv_index = -1;
  ID3D12Resource* conv_slot = nullptr;
  double sdr_white = 1.0;          // in units of 80 nits, see set_sdr_white()
  double last_convert_ms = 0.0;
  // level_of() for every half at a scale, for the rendition of a 16-bit target to 8 bits,
  // made once for each scale asked (3 ms) and kept, see levels().
  std::vector<uint8_t> level_table;
  float level_table_scale = -1.0f;
  // The raw copy a test asks for, see keep_raw(): the 16-bit frame behind the last draw.
  bool raw_wanted = false;
  ComPtr<ID3D12Resource> raw_copy;
  D3D12_PLACED_SUBRESOURCE_FOOTPRINT raw_fp = {};
  UINT64 raw_bytes = 0;
  bool have_raw = false;
  bool native_copy_rgba = false;   // the kept native copy is R8G8B8A8, a converted frame

  WorkSet work;  // the work size in use
  WorkSet next;  // the one being made or made, until commit_work() puts it in use
  // The thread that makes the next size's features (begin_work). While it runs the main
  // thread makes no call into the runtime (hold), and it alone touches nr.
  std::thread maker;
  std::atomic<int> making{0};    // 0 nothing, 1 being made, 2 made, 3 could not be made
  std::string make_err;          // why not, written by the thread before `making` turns 3
  HANDLE made_event = nullptr;   // set by the thread when it is done. Auto-reset
  bool hold = false;             // no call goes into the runtime. ingest only compares, and
                                 // render draws with the network's change as it stood
  // The flags the ingest writes its token into: one for "something differs", then one for
  // each tile of the picture that holds a difference.
  ComPtr<ID3D12Resource> flag;
  ComPtr<ID3D12Resource> flag_back;    // where they are read back, one region for each
                                       // ingest table, mapped for life
  const uint8_t* flag_bytes = nullptr;
  const UINT* flag_value = nullptr;    // region 0, the ingest context's
  UINT token = 0;                      // the last token given out, to either kind of ingest
  bool ingest_compared = false;        // whether the most recent ingest() compared anything
  UINT ingest_token = 0;               // and the token it wrote, for add_changed_tiles()

  Context ingest;
  Context draw[kDrawContexts];
  int next_draw = 0;
  UINT64 draw_sequence = 0;            // the last draw's number, see last_draw_sequence()
  GpuTimer timer;
  double last_ingest_ms = 0.0;
  bool split_wait = false;             // LENS_FAST_SPLIT_WAIT=1, see ingest()
  double last_copy_wait_ms = 0.0;      // the CPU's wait for the capture's copy under it

  // What the finished draw contexts held for the caller, oldest first, moved here by
  // harvest_finished() so that a context can be taken again, see take_flag(), take_times().
  struct Flag {
    bool changed = false;
    uint8_t tiles[Pipeline::kTiles] = {};
  };
  std::deque<Flag> flags;
  std::deque<StageTimes> times_queue;
  bool times_kept = false;             // keep_times(): whether times_queue is filled at all

  // What a repaint draws from: which texture holds the native picture, and how the last
  // render drew. The network's input and output are the retained rest of it.
  ID3D12Resource* native = nullptr;
  bool drawn_residual = false;
  // The network's input and output textures hold an input and what the network made of
  // that same input, so their difference is the network's change. Not so before the first
  // run of the network at this work size, nor after a render with the network off.
  bool pair = false;

  // The copies a shot or a probe asks for. A copy into a buffer names the texture's format in
  // its footprint, and a converted frame has another format than a slot of the same bytes,
  // so there are two footprints of the same layout. The target's copy has a layout of its
  // own, since a 16-bit target takes twice the bytes: target_format says which it was made
  // for, and the buffer is made again after drop_target_copies() for the other.
  ComPtr<ID3D12Resource> native_copy, target_copy;
  D3D12_PLACED_SUBRESOURCE_FOOTPRINT copy_fp = {};
  D3D12_PLACED_SUBRESOURCE_FOOTPRINT conv_fp = {};
  D3D12_PLACED_SUBRESOURCE_FOOTPRINT target_fp = {};
  UINT64 copy_bytes = 0;
  UINT64 target_bytes = 0;
  DXGI_FORMAT target_format = DXGI_FORMAT_UNKNOWN;
  UINT64 copy_fence = 0;
  bool have_copy = false;

  D3D12_CPU_DESCRIPTOR_HANDLE cpu_slot(UINT slot) const {
    D3D12_CPU_DESCRIPTOR_HANDLE h = heap->GetCPUDescriptorHandleForHeapStart();
    h.ptr += (SIZE_T)slot * heap_step;
    return h;
  }
  D3D12_GPU_DESCRIPTOR_HANDLE gpu_slot(UINT slot) const {
    D3D12_GPU_DESCRIPTOR_HANDLE h = heap->GetGPUDescriptorHandleForHeapStart();
    h.ptr += (UINT64)slot * heap_step;
    return h;
  }
  ID3D12Resource* last_out() const { return work.out[(desc.passes - 1) % 2].Get(); }

  // The next token for an ingest: never 0, which is what the flags hold before any.
  UINT next_token() {
    if (++token == 0) token = 1;
    return token;
  }

  // Whether the network's change is part of the picture. A strength of 0 on every pass
  // counts as off, see network_runs().
  bool runs() const {
    if (!network || !nr_on) return false;
    if (run_at_zero) return true;
    for (int p = 0; p < desc.passes && p < kNrMaxPasses; ++p) {
      if (settings.pass[p].intensity > 0.0f) return true;
    }
    return false;
  }

  // The flag's region of an ingest table, as the CPU reads it.
  const UINT* flag_region(UINT table) const { return (const UINT*)(flag_bytes + (size_t)table * kFlagStride); }

  // What a joined draw's ingest found, read from its region once its list is done: changed
  // as ingest() decides it, and the tiles as add_changed_tiles() sets them.
  void read_flag(const Context& c, int index, Flag& f) const {
    const UINT* v = flag_region((UINT)(1 + index));
    f.changed = !c.compared || v[0] == c.token;
    for (int i = 0; i < Pipeline::kTiles; ++i) f.tiles[i] = (!c.compared || v[1 + i] == c.token) ? 1 : 0;
  }

  // The GPU times of a draw context whose list is done, see StageTimes.
  StageTimes read_times(const Context& c, int index) const {
    const UINT t0 = kTimeDraw0 + kTimesPerDraw * (UINT)index;
    StageTimes t;
    t.joined = c.joined;
    t.ran_network = c.ran_network;
    t.ingest_ms = c.joined ? timer.ms(*gpu, t0 + 1, t0 + 2) : c.ingest_ms;
    t.convert_ms = c.joined && c.converted ? timer.ms(*gpu, t0, t0 + 1) : 0.0;
    t.nr_ms = c.ran_network ? timer.ms(*gpu, t0 + 2, t0 + 3) : 0.0;
    t.composite_ms = timer.ms(*gpu, t0 + 3, t0 + 4);
    t.sequence = c.sequence;
    for (UINT i = 0; i < kTimesPerDraw; ++i) t.ticks[i] = timer.ticks ? timer.ticks[t0 + i] : 0;
    return t;
  }

  // Moves what every draw context the GPU has finished still holds unread into the queues,
  // oldest first. Called before a context is taken again, so nothing is written over
  // unread, and by take_flag() and take_times().
  void harvest_finished() {
    if (!gpu->fence) return;
    const UINT64 done = gpu->fence->GetCompletedValue();
    for (;;) {
      int best = -1;
      for (int i = 0; i < kDrawContexts; ++i) {
        const Context& c = draw[i];
        if (c.used && (c.flag_unread || c.times_unread) && c.fence <= done &&
            (best < 0 || c.fence < draw[best].fence)) {
          best = i;
        }
      }
      if (best < 0) return;
      Context& c = draw[best];
      if (c.flag_unread) {
        Flag f;
        read_flag(c, best, f);
        flags.push_back(f);
        c.flag_unread = false;
      }
      if (c.times_unread) {
        // The flag goes whether the times are kept or not: the selection above keys on it.
        // Kept, the queue holds the newest kTimesKept at most, so a caller that takes none
        // for a while costs nothing more than that. The loop takes them every turn.
        if (times_kept) {
          times_queue.push_back(read_times(c, best));
          while (times_queue.size() > (size_t)Pipeline::kTimesKept) times_queue.pop_front();
        }
        c.times_unread = false;
      }
    }
  }

  // Whether a texture is one of the two converted frames, and so R8G8B8A8.
  bool is_converted(const ID3D12Resource* t) const {
    return t && (t == conv[0].Get() || t == conv[1].Get());
  }
  // The format a frame's view takes: a converted frame's own, else the capture's 8-bit one.
  DXGI_FORMAT frame_format(const ID3D12Resource* t) const {
    return is_converted(t) ? kConvertedFormat : kFrameFormat;
  }
  // The frame a draw composes from, for the frame a caller named: a 16-bit frame stands for
  // its conversion, which is the one of the last ingest(), and an 8-bit frame for itself.
  ID3D12Resource* composed_from(ID3D12Resource* cur) const {
    return cur == conv_slot && conv_index >= 0 ? conv[conv_index].Get() : cur;
  }
  // The 16-bit frame behind a frame that is drawn, for the raw copy, null for an 8-bit one.
  ID3D12Resource* raw_behind(const ID3D12Resource* frame) const {
    return is_converted(frame) && conv_index >= 0 && frame == conv[conv_index].Get() ? conv_slot : nullptr;
  }

  // The two converted frames, made at the first 16-bit frame. 4 bytes a texel each, so
  // together they take what two more 8-bit slots would.
  bool make_conv(std::string& err) {
    if (conv[0] && conv[1]) return true;
    for (int i = 0; i < 2; ++i) {
      if (!gpu->make_texture(kConvertedFormat, desc.width, desc.height, D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS,
                             D3D12_RESOURCE_STATE_COMMON, i == 0 ? L"converted frame 0" : L"converted frame 1",
                             conv[i], err)) {
        conv[0].Reset();
        conv[1].Reset();
        return false;
      }
    }
    note("pipeline: two textures of %ux%u for the 8-bit frames made of 16-bit ones, %.0f MiB", desc.width,
         desc.height, 2.0 * desc.width * desc.height * 4.0 / 1048576.0);
    return true;
  }

  bool make_raw_copy(std::string& err) {
    if (raw_copy) return true;
    D3D12_RESOURCE_DESC d = {};
    d.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
    d.Width = desc.width;
    d.Height = desc.height;
    d.DepthOrArraySize = 1;
    d.MipLevels = 1;
    d.Format = kRawFormat;
    d.SampleDesc.Count = 1;
    gpu->device->GetCopyableFootprints(&d, 0, 1, 0, &raw_fp, nullptr, nullptr, &raw_bytes);
    return gpu->make_buffer(raw_bytes, D3D12_HEAP_TYPE_READBACK, D3D12_RESOURCE_STATE_COPY_DEST,
                            D3D12_RESOURCE_FLAG_NONE, L"raw copy", raw_copy, err);
  }

  // The maker thread has ended, or there was none. It is joined, so nr is the main thread's
  // again.
  void join_maker() {
    if (maker.joinable()) maker.join();
  }

  // A view of a 2D texture, or a null view when there is no texture: a table may not hold
  // a descriptor that was never written.
  void srv(ID3D12Resource* texture, DXGI_FORMAT format, UINT slot) {
    D3D12_SHADER_RESOURCE_VIEW_DESC d = {};
    d.Format = format;
    d.ViewDimension = D3D12_SRV_DIMENSION_TEXTURE2D;
    d.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
    d.Texture2D.MipLevels = 1;
    gpu->device->CreateShaderResourceView(texture, &d, cpu_slot(slot));
  }

  // The textures and the weights of one work size. It uses the ingest's list for the upload
  // of the weights, which is free whenever no ingest is running, and waits for it.
  bool make_work(UINT w, UINT h, WorkSet& set, std::string& err) {
    set = WorkSet();
    set.w = w;
    set.h = h;
    if (!desc.load_network) {
      set.made = true;
      return true;
    }
    if (!gpu->make_texture(kNrFormat, w, h, D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS,
                           D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE, L"network input", set.in, err) ||
        !gpu->make_texture(kNrFormat, w, h, D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS,
                           D3D12_RESOURCE_STATE_UNORDERED_ACCESS, L"network output 0", set.out[0], err) ||
        (desc.passes > 1 &&
         !gpu->make_texture(kNrFormat, w, h, D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS,
                            D3D12_RESOURCE_STATE_UNORDERED_ACCESS, L"network output 1", set.out[1], err))) {
      return false;
    }
    // the downscale's weights: across, then down, uploaded once
    std::vector<float> table;
    area_weights(desc.width, w, set.taps_x, table);
    area_weights(desc.height, h, set.taps_y, table);
    set.weight_count = (UINT)table.size();
    const UINT64 bytes = (UINT64)table.size() * sizeof(float);
    ComPtr<ID3D12Resource> staging;
    if (!gpu->make_buffer(bytes, D3D12_HEAP_TYPE_DEFAULT, D3D12_RESOURCE_STATE_COPY_DEST, D3D12_RESOURCE_FLAG_NONE,
                          L"downscale weights", set.weights, err) ||
        !gpu->make_buffer(bytes, D3D12_HEAP_TYPE_UPLOAD, D3D12_RESOURCE_STATE_GENERIC_READ,
                          D3D12_RESOURCE_FLAG_NONE, L"downscale weights upload", staging, err)) {
      return false;
    }
    void* p = nullptr;
    const D3D12_RANGE none = {0, 0};
    if (FAILED(staging->Map(0, &none, &p)) || !p) {
      err = "mapping the weights failed";
      return false;
    }
    memcpy(p, table.data(), (size_t)bytes);
    staging->Unmap(0, nullptr);
    if (!begin(ingest, err)) return false;
    ingest.list->CopyBufferRegion(set.weights.Get(), 0, staging.Get(), 0, bytes);
    transition(ingest.list.Get(), set.weights.Get(), D3D12_RESOURCE_STATE_COPY_DEST,
               D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
    // waited for here, so the upload buffer can go when this function ends
    if (!gpu->execute(ingest.list.Get(), ingest.fence, err) || !gpu->wait(ingest.fence, kWaitMs, err)) return false;
    set.made = true;
    return true;
  }

  // What begin_work() and prepare_work() share: the sizes checked, whatever an earlier call
  // made and nobody put in use dropped, and the textures and weights of the new size made.
  bool start_work(UINT work_w, UINT work_h, std::string& err) {
    if (making.load() == 1) {
      err = "another work size is still being made";
      return false;
    }
    if (work_w < 1 || work_h < 1 || work_w > desc.width || work_h > desc.height) {
      err = strf("bad work size %ux%u for a picture of %ux%u", work_w, work_h, desc.width, desc.height);
      return false;
    }
    join_maker();
    hold = false;
    making.store(0);
    if (network) nr.drop_prepared();
    next = WorkSet();
    if (!make_work(work_w, work_h, next, err)) {
      next = WorkSet();
      return false;
    }
    return true;
  }

  // The descriptors that name the work set in use: two in each ingest table and two in
  // each draw context's table. Null views where there is no network, so the tables are
  // whole either way. The GPU must have finished every list that used them.
  void write_work_descriptors() {
    D3D12_UNORDERED_ACCESS_VIEW_DESC uav = {};
    uav.Format = kNrFormat;
    uav.ViewDimension = D3D12_UAV_DIMENSION_TEXTURE2D;
    D3D12_SHADER_RESOURCE_VIEW_DESC table = {};
    table.Format = DXGI_FORMAT_R32_FLOAT;
    table.ViewDimension = D3D12_SRV_DIMENSION_BUFFER;
    table.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
    table.Buffer.NumElements = work.weight_count;
    for (UINT t = 0; t < (UINT)kIngestTables; ++t) {
      const UINT base = kSlotIngest0 + kSlotsPerIngest * t;
      gpu->device->CreateUnorderedAccessView(work.in.Get(), nullptr, &uav, cpu_slot(base + kSlotWorkUav));
      gpu->device->CreateShaderResourceView(work.weights.Get(), &table, cpu_slot(base + kSlotWeights));
    }
    for (UINT i = 0; i < (UINT)kDrawContexts; ++i) {
      const UINT slot = kSlotDraw0 + kSlotsPerDraw * i;
      srv(work.in.Get(), kNrFormat, slot + 1);
      srv(network ? last_out() : nullptr, kNrFormat, slot + 2);
    }
  }

  // Makes the context ready to record: waits until the GPU has finished what was last
  // recorded from it, keeps what any finished context still holds unread, then resets its
  // allocator and list.
  bool begin(Context& c, std::string& err) {
    if (c.fence && !gpu->wait(c.fence, kWaitMs, err)) return false;
    harvest_finished();
    HRESULT hr = c.allocator->Reset();
    if (SUCCEEDED(hr)) hr = c.list->Reset(c.allocator.Get(), nullptr);
    if (FAILED(hr)) {
      if (gpu->alive(err)) err = "resetting a command list failed " + hr_text(hr);
      return false;
    }
    return true;
  }

  // Records an ingest on the list, between the timestamps time0 (start), time0 + 1 (after
  // the conversion) and time0 + 2 (end): the conversion of a 16-bit frame cur into cur8
  // when raw, then the comparison of cur8 with prev8 when compare and the downscale of cur8
  // into the network's input unless another work size is being made, and the copy of the
  // flags into region `table` of the readback buffer. The descriptors are those of ingest
  // table `table`. The same commands for both callers, ingest() and render_joined(), and
  // they leave the frames in COMMON, the network's input readable and the flag writable.
  // With prev16, the 16-bit frame before cur, the comparison runs on cur and prev16 as the
  // capture gave them instead of on the two conversions: those are clipped at the SDR white
  // level, so a change that lies only above it, in a highlight, would not be seen there and
  // the picture would wait for the heartbeat. Null on the 8-bit path, which stays as it was.
  void record_ingest(ID3D12GraphicsCommandList* l, UINT table, UINT time0, ID3D12Resource* cur, bool raw,
                     ID3D12Resource* cur8, ID3D12Resource* prev8, ID3D12Resource* prev16, bool compare,
                     UINT token) {
    const UINT base = kSlotIngest0 + kSlotsPerIngest * table;
    const UINT conv_base = kSlotConv0 + kSlotsPerConv * table;
    srv(cur8, frame_format(cur8), base + kSlotCur);
    srv(compare ? prev8 : cur8, frame_format(compare ? prev8 : cur8), base + kSlotPrev);
    const bool raw_compare = raw && compare && prev16 != nullptr;
    if (raw_compare) {
      srv(cur, kRawFormat, base + kSlotCur16);
      srv(prev16, kRawFormat, base + kSlotPrev16);
    }

    const D3D12_RESOURCE_STATES kCommon = D3D12_RESOURCE_STATE_COMMON;
    const D3D12_RESOURCE_STATES kRead = D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
    const D3D12_RESOURCE_STATES kWrite = D3D12_RESOURCE_STATE_UNORDERED_ACCESS;

    timer.mark(l, time0);
    if (raw) {
      srv(cur, kRawFormat, conv_base);
      D3D12_UNORDERED_ACCESS_VIEW_DESC uav = {};
      uav.Format = kConvertedFormat;
      uav.ViewDimension = D3D12_UAV_DIMENSION_TEXTURE2D;
      gpu->device->CreateUnorderedAccessView(cur8, nullptr, &uav, cpu_slot(conv_base + 1));
      transition(l, cur, kCommon, kRead);
      transition(l, cur8, kCommon, kWrite);
      ID3D12DescriptorHeap* heaps[] = {heap.Get()};
      l->SetDescriptorHeaps(1, heaps);
      l->SetComputeRootSignature(convert_root.Get());
      l->SetPipelineState(convert_pso.Get());
      ConvertConstants k = {};
      k.w = desc.width;
      k.h = desc.height;
      k.scale = (float)(1.0 / sdr_white);
      l->SetComputeRoot32BitConstants(0, sizeof(k) / 4, &k, 0);
      l->SetComputeRootDescriptorTable(1, gpu_slot(conv_base));
      l->Dispatch((desc.width + 7) / 8, (desc.height + 7) / 8, 1);
      // back to COMMON, as the frames the rest of the ingest takes are: the transition out of
      // UNORDERED_ACCESS is also what makes the stores visible to the reads that follow
      transition(l, cur8, kWrite, kCommon);
      transition(l, cur, kRead, kCommon);
    }
    timer.mark(l, time0 + 1);

    // While another work size is being made the network's input stays as the last render
    // used it, so that its change can still be drawn. The frame is only compared.
    const bool downscale = network && !hold;
    if (compare || downscale) {
      transition(l, cur8, kCommon, kRead);
      if (compare) transition(l, prev8, kCommon, kRead);
      if (raw_compare) {
        transition(l, cur, kCommon, kRead);
        transition(l, prev16, kCommon, kRead);
      }
      if (downscale) transition(l, work.in.Get(), kRead, kWrite);

      ID3D12DescriptorHeap* heaps[] = {heap.Get()};
      l->SetDescriptorHeaps(1, heaps);
      l->SetComputeRootSignature(ingest_root.Get());
      l->SetPipelineState(ingest_pso.Get());
      IngestConstants k = {};
      k.src_w = desc.width;
      k.src_h = desc.height;
      k.dst_w = work.w;
      k.dst_h = work.h;
      k.token = token;
      k.compare = compare ? 1u : 0u;
      k.downscale = downscale ? 1u : 0u;
      k.taps_x = work.taps_x;
      k.taps_y = work.taps_y;
      k.raw_compare = raw_compare ? 1u : 0u;
      l->SetComputeRoot32BitConstants(0, sizeof(k) / 4, &k, 0);
      l->SetComputeRootDescriptorTable(1, gpu_slot(base));
      l->Dispatch((work.w + 7) / 8, (work.h + 7) / 8, 1);

      if (downscale) transition(l, work.in.Get(), kWrite, kRead);
      transition(l, cur8, kRead, kCommon);
      if (raw_compare) {
        transition(l, cur, kRead, kCommon);
        transition(l, prev16, kRead, kCommon);
      }
      if (compare) {
        transition(l, prev8, kRead, kCommon);
        transition(l, flag.Get(), kWrite, D3D12_RESOURCE_STATE_COPY_SOURCE);
        l->CopyBufferRegion(flag_back.Get(), (UINT64)table * kFlagStride, flag.Get(), 0, kFlagBytes);
        transition(l, flag.Get(), D3D12_RESOURCE_STATE_COPY_SOURCE, kWrite);
      }
    }
    timer.mark(l, time0 + 2);
  }

  // The frame before, as the ingest compares it: the frame itself when it is an 8-bit one,
  // the conversion of the last ingest when it is the 16-bit frame that one converted, and
  // none otherwise. compare is false on return when there is nothing to compare with.
  ID3D12Resource* frame_before(ID3D12Resource* cur, ID3D12Resource* prev, bool raw, bool& compare) const {
    if (!raw) return compare ? prev : nullptr;
    ID3D12Resource* prev8 = compare && conv_index >= 0 && prev == conv_slot ? conv[conv_index].Get() : nullptr;
    compare = prev8 != nullptr;
    return prev8;
  }

  // The readback buffers for the native frame and for a target of this format. The
  // target's buffer is made for one format. After drop_target_copies() it is made again for
  // the format then drawn into.
  bool make_copies(DXGI_FORMAT for_target, std::string& err) {
    if (for_target != kFrameFormat && for_target != kRawFormat) {
      err = strf("a target of format %d cannot be read back", (int)for_target);
      return false;
    }
    if (target_copy && for_target != target_format) {
      err = "the target's format changed without drop_target_copies";
      return false;
    }
    if (native_copy && target_copy) return true;
    D3D12_RESOURCE_DESC d = {};
    d.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
    d.Width = desc.width;
    d.Height = desc.height;
    d.DepthOrArraySize = 1;
    d.MipLevels = 1;
    d.Format = kFrameFormat;
    d.SampleDesc.Count = 1;
    gpu->device->GetCopyableFootprints(&d, 0, 1, 0, &copy_fp, nullptr, nullptr, &copy_bytes);
    // the same layout for a converted frame: 4 bytes a texel either way
    d.Format = kConvertedFormat;
    UINT64 conv_bytes = 0;
    gpu->device->GetCopyableFootprints(&d, 0, 1, 0, &conv_fp, nullptr, nullptr, &conv_bytes);
    if (conv_bytes != copy_bytes || conv_fp.Footprint.RowPitch != copy_fp.Footprint.RowPitch) {
      err = "the two frame formats lay out differently";
      return false;
    }
    d.Format = for_target;
    gpu->device->GetCopyableFootprints(&d, 0, 1, 0, &target_fp, nullptr, nullptr, &target_bytes);
    if (!native_copy && !gpu->make_buffer(copy_bytes, D3D12_HEAP_TYPE_READBACK, D3D12_RESOURCE_STATE_COPY_DEST,
                                          D3D12_RESOURCE_FLAG_NONE, L"native copy", native_copy, err)) {
      return false;
    }
    if (!gpu->make_buffer(target_bytes, D3D12_HEAP_TYPE_READBACK, D3D12_RESOURCE_STATE_COPY_DEST,
                          D3D12_RESOURCE_FLAG_NONE, L"target copy", target_copy, err)) {
      return false;
    }
    target_format = for_target;
    return true;
  }

  void copy_out(ID3D12GraphicsCommandList* l, ID3D12Resource* texture, ID3D12Resource* buffer,
                const D3D12_PLACED_SUBRESOURCE_FOOTPRINT& fp) {
    D3D12_TEXTURE_COPY_LOCATION dst = {};
    dst.pResource = buffer;
    dst.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
    dst.PlacedFootprint = fp;
    D3D12_TEXTURE_COPY_LOCATION src = {};
    src.pResource = texture;
    src.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
    l->CopyTextureRegion(&dst, 0, 0, 0, &src, nullptr);
  }

  // Records the composite on the context's open list, after whatever the caller recorded,
  // and submits the list. The caller has marked timestamps 0 to 3 of the context. frame
  // is the 8-bit frame drawn, a slot or a converted one. With keep_copy and keep_raw the
  // 16-bit frame behind a converted one is copied too. A 16-bit target is drawn by the HDR
  // composite from the frame and the 16-bit frame behind it, see pipeline.h. With
  // wait_fence the queue first waits for it to reach wait_value, right before the list:
  // the capture's copy of a frame the list reads, see render_joined().
  bool compose(int index, ID3D12Resource* frame, const Target& target, bool residual, bool keep_copy,
               std::string& err, ID3D12Fence* wait_fence = nullptr, UINT64 wait_value = 0) {
    Context& c = draw[index];
    ID3D12GraphicsCommandList* l = c.list.Get();
    const bool hdr = target.format == kRawFormat;
    if (!hdr && target.format != kFrameFormat) {
      l->Close();
      err = strf("a target of format %d cannot be drawn into", (int)target.format);
      return false;
    }
    if (keep_copy && !make_copies(target.format, err)) {
      l->Close();
      return false;
    }
    // the 16-bit frame behind a converted one: read by the HDR composite, and copied for a
    // test that asked for it
    ID3D12Resource* behind = raw_behind(frame);
    ID3D12Resource* raw = keep_copy && raw_wanted ? behind : nullptr;
    if (raw && !make_raw_copy(err)) {
      l->Close();
      return false;
    }
    const UINT table = kSlotDraw0 + kSlotsPerDraw * (UINT)index;
    srv(frame, frame_format(frame), table);  // the next two of the table name the work set, and
                                             // were written when it was put in use
    srv(hdr ? behind : nullptr, kRawFormat, table + 3);

    const D3D12_RESOURCE_STATES kCommon = D3D12_RESOURCE_STATE_COMMON;
    const D3D12_RESOURCE_STATES kPixel = D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE;
    const D3D12_RESOURCE_STATES kRead = D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
    const D3D12_RESOURCE_STATES kWrite = D3D12_RESOURCE_STATE_UNORDERED_ACCESS;
    const D3D12_RESOURCE_STATES kTarget = D3D12_RESOURCE_STATE_RENDER_TARGET;
    const D3D12_RESOURCE_STATES kSource = D3D12_RESOURCE_STATE_COPY_SOURCE;

    transition(l, frame, kCommon, kPixel);
    if (hdr && behind) transition(l, behind, kCommon, kPixel);
    if (network) {
      // also when the picture is the plain copy: the table names them either way
      transition(l, work.in.Get(), kRead, kPixel);
      transition(l, last_out(), kWrite, kPixel);
    }
    transition(l, target.texture, D3D12_RESOURCE_STATE_PRESENT, kTarget);

    // Everything the draw needs is set here and nothing is assumed: the network leaves the
    // list's heaps, root signatures and pipeline state as it pleases.
    ID3D12DescriptorHeap* heaps[] = {heap.Get()};
    l->SetDescriptorHeaps(1, heaps);
    // 1 / d in float, with d = 2 w and 2 h whole numbers that a float holds exactly. The
    // division is the CPU's, rounded as IEEE asks, and the shader only multiplies.
    const float inv_x = 1.0f / (float)(2u * desc.width);
    const float inv_y = 1.0f / (float)(2u * desc.height);
    if (hdr) {
      l->SetGraphicsRootSignature(draw_hdr_root.Get());
      l->SetPipelineState(draw_hdr_pso.Get());
      HdrDrawConstants k = {};
      k.w = desc.width;
      k.h = desc.height;
      k.work_w = work.w;
      k.work_h = work.h;
      k.residual = residual ? 1u : 0u;
      k.inv_x = inv_x;
      k.inv_y = inv_y;
      k.white = (float)sdr_white;
      k.above = (UINT)hdr_above;
      k.have_raw = behind ? 1u : 0u;
      l->SetGraphicsRoot32BitConstants(0, sizeof(k) / 4, &k, 0);
    } else {
      l->SetGraphicsRootSignature(draw_root.Get());
      l->SetPipelineState(draw_pso.Get());
      DrawConstants k = {};
      k.w = desc.width;
      k.h = desc.height;
      k.work_w = work.w;
      k.work_h = work.h;
      k.residual = residual ? 1u : 0u;
      k.inv_x = inv_x;
      k.inv_y = inv_y;
      l->SetGraphicsRoot32BitConstants(0, sizeof(k) / 4, &k, 0);
    }
    l->SetGraphicsRootDescriptorTable(1, gpu_slot(table));
    D3D12_VIEWPORT view = {0.0f, 0.0f, (float)desc.width, (float)desc.height, 0.0f, 1.0f};
    D3D12_RECT all = {0, 0, (LONG)desc.width, (LONG)desc.height};
    l->RSSetViewports(1, &view);
    l->RSSetScissorRects(1, &all);
    l->OMSetRenderTargets(1, &target.rtv, FALSE, nullptr);
    l->IASetPrimitiveTopology(D3D_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
    l->DrawInstanced(3, 1, 0, 0);

    if (network) {
      transition(l, work.in.Get(), kPixel, kRead);
      transition(l, last_out(), kPixel, kWrite);
    }
    if (keep_copy) {
      transition(l, frame, kPixel, kSource);
      copy_out(l, frame, native_copy.Get(), is_converted(frame) ? conv_fp : copy_fp);
      transition(l, frame, kSource, kCommon);
      transition(l, target.texture, kTarget, kSource);
      copy_out(l, target.texture, target_copy.Get(), target_fp);
      transition(l, target.texture, kSource, D3D12_RESOURCE_STATE_PRESENT);
      if (raw) {
        transition(l, raw, hdr ? kPixel : kCommon, kSource);
        copy_out(l, raw, raw_copy.Get(), raw_fp);
        transition(l, raw, kSource, kCommon);
      } else if (hdr && behind) {
        transition(l, behind, kPixel, kCommon);
      }
    } else {
      transition(l, frame, kPixel, kCommon);
      if (hdr && behind) transition(l, behind, kPixel, kCommon);
      transition(l, target.texture, kTarget, D3D12_RESOURCE_STATE_PRESENT);
    }

    const UINT t0 = kTimeDraw0 + kTimesPerDraw * (UINT)index;
    timer.mark(l, t0 + 4);
    timer.resolve(l, t0, kTimesPerDraw);
    if (wait_fence) {
      // The capture's copy into the slot runs on its own device: the queue stands still until
      // that copy is done, and only then reads the frame.
      const HRESULT hr = gpu->queue->Wait(wait_fence, wait_value);
      if (FAILED(hr)) {
        l->Close();
        if (gpu->alive(err)) err = "waiting for the capture's fence failed " + hr_text(hr);
        return false;
      }
    }
    if (!gpu->execute(l, c.fence, err)) return false;
    c.used = true;
    c.times_unread = true;
    c.sequence = ++draw_sequence;
    have_copy = keep_copy;
    have_raw = raw != nullptr;
    native_copy_rgba = is_converted(frame);
    if (keep_copy) copy_fence = c.fence;
    return true;
  }

  // The level of every half at this scale, every one of the 65536 as level_of() maps it,
  // the NaNs and the infinities included. Made again only when the scale changes.
  const uint8_t* levels(float scale) {
    if (level_table.size() != 65536 || level_table_scale != scale) {
      level_table.resize(65536);
      for (uint32_t h = 0; h < 65536; ++h) level_table[h] = level_of(half_to_float((uint16_t)h), scale);
      level_table_scale = scale;
    }
    return level_table.data();
  }

  // One of the kept copies as tight RGB8, every step-th texel each way. The target's copy
  // of a 16-bit target is rendered to 8 bits as Windows shows standard range content.
  bool read_copy(ID3D12Resource* buffer, UINT step, std::vector<uint8_t>& rgb, std::string& err) {
    rgb.clear();
    if (!have_copy || !buffer) {
      err = "no copy was kept";
      return false;
    }
    if (!gpu->wait(copy_fence, kWaitMs, err)) return false;
    const bool is_target = buffer == target_copy.Get();
    const D3D12_PLACED_SUBRESOURCE_FOOTPRINT& fp = is_target ? target_fp : copy_fp;
    void* p = nullptr;
    const D3D12_RANGE whole = {0, (SIZE_T)(is_target ? target_bytes : copy_bytes)};
    const HRESULT hr = buffer->Map(0, &whole, &p);
    if (FAILED(hr) || !p) {
      err = "mapping the copy failed " + hr_text(hr);
      return false;
    }
    if (is_target && target_format == kRawFormat) {
      half_rows_to_rgb((const uint8_t*)p + fp.Offset, fp.Footprint.RowPitch, desc.width, desc.height, step,
                       levels((float)(1.0 / sdr_white)), rgb);
    } else {
      bgra_to_rgb((const uint8_t*)p + fp.Offset, fp.Footprint.RowPitch, desc.width, desc.height, step, rgb,
                  !is_target && native_copy_rgba);
    }
    const D3D12_RANGE none = {0, 0};  // nothing was written
    buffer->Unmap(0, &none);
    return true;
  }

  // A kept copy in 16-bit floats as tight R16G16B16A16_FLOAT: the raw frame's buffer or the
  // target's.
  bool read_halves(ID3D12Resource* buffer, const D3D12_PLACED_SUBRESOURCE_FOOTPRINT& fp, UINT64 bytes,
                   std::vector<uint16_t>& rgba, std::string& err) {
    if (!gpu->wait(copy_fence, kWaitMs, err)) return false;
    void* p = nullptr;
    const D3D12_RANGE whole = {0, (SIZE_T)bytes};
    const HRESULT hr = buffer->Map(0, &whole, &p);
    if (FAILED(hr) || !p) {
      err = "mapping the copy failed " + hr_text(hr);
      return false;
    }
    const UINT w = desc.width, h = desc.height;
    rgba.resize((size_t)w * h * 4);
    for (UINT y = 0; y < h; ++y) {
      memcpy(rgba.data() + (size_t)y * w * 4, (const uint8_t*)p + fp.Offset + (size_t)y * fp.Footprint.RowPitch,
             (size_t)w * 8);
    }
    const D3D12_RANGE none = {0, 0};
    buffer->Unmap(0, &none);
    return true;
  }
};

Pipeline::Pipeline() {}

Pipeline::~Pipeline() { shutdown(); }

bool Pipeline::init(Gpu& gpu, const PipelineDesc& desc, std::string& err) {
  shutdown();
  err.clear();
  if (!gpu.device || !gpu.queue) {
    err = "no device";
    return false;
  }
  if (desc.width < 1 || desc.height < 1 || desc.work_w < 1 || desc.work_h < 1 || desc.work_w > desc.width ||
      desc.work_h > desc.height || desc.width > 16384 || desc.height > 16384 || desc.passes < 1 ||
      desc.passes > kNrMaxPasses) {
    err = strf("bad sizes for the pipeline: picture %ux%u, work %ux%u, %d passes", desc.width, desc.height,
               desc.work_w, desc.work_h, desc.passes);
    return false;
  }

  impl_ = new Impl();
  Impl& m = *impl_;
  m.split_wait = env_text(L"LENS_FAST_SPLIT_WAIT") == L"1";
  if (m.split_wait) note("pipeline: LENS_FAST_SPLIT_WAIT, each ingest first waits on the CPU for the capture's copy");
  m.gpu = &gpu;
  m.desc = desc;
  m.settings = desc.settings;
  m.nr_on = desc.nr_on;
  ID3D12Device* device = gpu.device.Get();
  HRESULT hr = S_OK;
  m.made_event = CreateEventW(nullptr, FALSE, FALSE, nullptr);
  if (!m.made_event) {
    err = strf("the event for a new work size could not be made, error %lu", GetLastError());
    shutdown();
    return false;
  }

  // ---- descriptors
  {
    D3D12_DESCRIPTOR_HEAP_DESC d = {};
    d.Type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;
    d.NumDescriptors = kSlotCount;
    d.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
    hr = device->CreateDescriptorHeap(&d, IID_PPV_ARGS(&m.heap));
    if (FAILED(hr)) {
      err = "the descriptor heap failed " + hr_text(hr);
      shutdown();
      return false;
    }
    m.heap_step = device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
  }

  // ---- the ingest: constants, and a table of two frames, the weights, the network's input,
  // the flag, and the two frames in 16-bit floats for the comparison of those
  {
    D3D12_DESCRIPTOR_RANGE ranges[3] = {};
    ranges[0].RangeType = D3D12_DESCRIPTOR_RANGE_TYPE_SRV;
    ranges[0].NumDescriptors = 3;
    ranges[0].OffsetInDescriptorsFromTableStart = kSlotCur;
    ranges[1].RangeType = D3D12_DESCRIPTOR_RANGE_TYPE_UAV;
    ranges[1].NumDescriptors = 2;
    ranges[1].OffsetInDescriptorsFromTableStart = kSlotWorkUav;
    ranges[2].RangeType = D3D12_DESCRIPTOR_RANGE_TYPE_SRV;
    ranges[2].NumDescriptors = 2;
    ranges[2].BaseShaderRegister = 3;
    ranges[2].OffsetInDescriptorsFromTableStart = kSlotCur16;
    D3D12_ROOT_PARAMETER params[2] = {};
    params[0].ParameterType = D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS;
    params[0].Constants.Num32BitValues = sizeof(IngestConstants) / 4;
    params[1].ParameterType = D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
    params[1].DescriptorTable.NumDescriptorRanges = 3;
    params[1].DescriptorTable.pDescriptorRanges = ranges;
    if (!make_root(device, params, 2, "ingest", m.ingest_root, err)) {
      shutdown();
      return false;
    }
    D3D12_COMPUTE_PIPELINE_STATE_DESC d = {};
    d.pRootSignature = m.ingest_root.Get();
    d.CS = {g_ingest_cs, sizeof(g_ingest_cs)};
    hr = device->CreateComputePipelineState(&d, IID_PPV_ARGS(&m.ingest_pso));
    if (FAILED(hr)) {
      err = "the ingest pipeline state failed " + hr_text(hr);
      shutdown();
      return false;
    }
  }

  // ---- the conversion: constants, and a table of the 16-bit frame and the 8-bit one
  {
    D3D12_DESCRIPTOR_RANGE ranges[2] = {};
    ranges[0].RangeType = D3D12_DESCRIPTOR_RANGE_TYPE_SRV;
    ranges[0].NumDescriptors = 1;
    ranges[0].OffsetInDescriptorsFromTableStart = 0;
    ranges[1].RangeType = D3D12_DESCRIPTOR_RANGE_TYPE_UAV;
    ranges[1].NumDescriptors = 1;
    ranges[1].OffsetInDescriptorsFromTableStart = 1;
    D3D12_ROOT_PARAMETER params[2] = {};
    params[0].ParameterType = D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS;
    params[0].Constants.Num32BitValues = sizeof(ConvertConstants) / 4;
    params[1].ParameterType = D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
    params[1].DescriptorTable.NumDescriptorRanges = 2;
    params[1].DescriptorTable.pDescriptorRanges = ranges;
    if (!make_root(device, params, 2, "conversion", m.convert_root, err)) {
      shutdown();
      return false;
    }
    D3D12_COMPUTE_PIPELINE_STATE_DESC d = {};
    d.pRootSignature = m.convert_root.Get();
    d.CS = {g_convert_cs, sizeof(g_convert_cs)};
    hr = device->CreateComputePipelineState(&d, IID_PPV_ARGS(&m.convert_pso));
    if (FAILED(hr)) {
      err = "the conversion pipeline state failed " + hr_text(hr);
      shutdown();
      return false;
    }
  }

  // ---- the composite: constants and a table of three textures, for the pixel shader
  {
    D3D12_DESCRIPTOR_RANGE range = {};
    range.RangeType = D3D12_DESCRIPTOR_RANGE_TYPE_SRV;
    range.NumDescriptors = 3;
    D3D12_ROOT_PARAMETER params[2] = {};
    params[0].ParameterType = D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS;
    params[0].Constants.Num32BitValues = sizeof(DrawConstants) / 4;
    params[0].ShaderVisibility = D3D12_SHADER_VISIBILITY_PIXEL;
    params[1].ParameterType = D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
    params[1].DescriptorTable.NumDescriptorRanges = 1;
    params[1].DescriptorTable.pDescriptorRanges = &range;
    params[1].ShaderVisibility = D3D12_SHADER_VISIBILITY_PIXEL;
    if (!make_root(device, params, 2, "composite", m.draw_root, err)) {
      shutdown();
      return false;
    }
    D3D12_GRAPHICS_PIPELINE_STATE_DESC d = {};
    d.pRootSignature = m.draw_root.Get();
    d.VS = {g_fullscreen_vs, sizeof(g_fullscreen_vs)};
    d.PS = {g_composite_ps, sizeof(g_composite_ps)};
    // no blending, no depth, no culling: every field still gets a value the runtime accepts
    D3D12_RENDER_TARGET_BLEND_DESC& blend = d.BlendState.RenderTarget[0];
    blend.SrcBlend = D3D12_BLEND_ONE;
    blend.DestBlend = D3D12_BLEND_ZERO;
    blend.BlendOp = D3D12_BLEND_OP_ADD;
    blend.SrcBlendAlpha = D3D12_BLEND_ONE;
    blend.DestBlendAlpha = D3D12_BLEND_ZERO;
    blend.BlendOpAlpha = D3D12_BLEND_OP_ADD;
    blend.LogicOp = D3D12_LOGIC_OP_NOOP;
    blend.RenderTargetWriteMask = D3D12_COLOR_WRITE_ENABLE_ALL;
    d.SampleMask = UINT_MAX;
    d.RasterizerState.FillMode = D3D12_FILL_MODE_SOLID;
    d.RasterizerState.CullMode = D3D12_CULL_MODE_NONE;
    d.RasterizerState.DepthClipEnable = TRUE;
    d.DepthStencilState.DepthFunc = D3D12_COMPARISON_FUNC_ALWAYS;
    const D3D12_DEPTH_STENCILOP_DESC keep = {D3D12_STENCIL_OP_KEEP, D3D12_STENCIL_OP_KEEP, D3D12_STENCIL_OP_KEEP,
                                             D3D12_COMPARISON_FUNC_ALWAYS};
    d.DepthStencilState.FrontFace = keep;
    d.DepthStencilState.BackFace = keep;
    d.PrimitiveTopologyType = D3D12_PRIMITIVE_TOPOLOGY_TYPE_TRIANGLE;
    d.NumRenderTargets = 1;
    d.RTVFormats[0] = kFrameFormat;
    d.SampleDesc.Count = 1;
    hr = device->CreateGraphicsPipelineState(&d, IID_PPV_ARGS(&m.draw_pso));
    if (FAILED(hr)) {
      err = "the composite pipeline state failed " + hr_text(hr);
      shutdown();
      return false;
    }

    // ---- the HDR composite: its own constants, a table of four, a 16-bit target. The
    // rest of the state is the composite's.
    D3D12_DESCRIPTOR_RANGE hdr_range = {};
    hdr_range.RangeType = D3D12_DESCRIPTOR_RANGE_TYPE_SRV;
    hdr_range.NumDescriptors = 4;
    D3D12_ROOT_PARAMETER hdr_params[2] = {};
    hdr_params[0].ParameterType = D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS;
    hdr_params[0].Constants.Num32BitValues = sizeof(HdrDrawConstants) / 4;
    hdr_params[0].ShaderVisibility = D3D12_SHADER_VISIBILITY_PIXEL;
    hdr_params[1].ParameterType = D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
    hdr_params[1].DescriptorTable.NumDescriptorRanges = 1;
    hdr_params[1].DescriptorTable.pDescriptorRanges = &hdr_range;
    hdr_params[1].ShaderVisibility = D3D12_SHADER_VISIBILITY_PIXEL;
    if (!make_root(device, hdr_params, 2, "HDR composite", m.draw_hdr_root, err)) {
      shutdown();
      return false;
    }
    d.pRootSignature = m.draw_hdr_root.Get();
    d.PS = {g_composite_hdr_ps, sizeof(g_composite_hdr_ps)};
    d.RTVFormats[0] = kRawFormat;
    hr = device->CreateGraphicsPipelineState(&d, IID_PPV_ARGS(&m.draw_hdr_pso));
    if (FAILED(hr)) {
      err = "the HDR composite pipeline state failed " + hr_text(hr);
      shutdown();
      return false;
    }
  }

  // ---- lists, timestamps, the flag
  if (!gpu.make_list(m.ingest.allocator, m.ingest.list, L"ingest", err)) {
    shutdown();
    return false;
  }
  for (int i = 0; i < kDrawContexts; ++i) {
    if (!gpu.make_list(m.draw[i].allocator, m.draw[i].list, L"draw", err)) {
      shutdown();
      return false;
    }
  }
  if (!m.timer.init(gpu, kTimeCount, err) ||
      !gpu.make_buffer(kFlagBytes, D3D12_HEAP_TYPE_DEFAULT, D3D12_RESOURCE_STATE_UNORDERED_ACCESS,
                       D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS, L"ingest flag", m.flag, err) ||
      !gpu.make_buffer((UINT64)kFlagStride * kIngestTables, D3D12_HEAP_TYPE_READBACK,
                       D3D12_RESOURCE_STATE_COPY_DEST, D3D12_RESOURCE_FLAG_NONE, L"ingest flag readback",
                       m.flag_back, err)) {
    shutdown();
    return false;
  }
  {
    void* p = nullptr;
    hr = m.flag_back->Map(0, nullptr, &p);
    if (FAILED(hr) || !p) {
      err = "mapping the flag failed " + hr_text(hr);
      shutdown();
      return false;
    }
    m.flag_bytes = (const uint8_t*)p;
    m.flag_value = (const UINT*)p;
  }

  // ---- the work size's textures and weights, and the network
  if (!m.make_work(desc.work_w, desc.work_h, m.work, err)) {
    shutdown();
    return false;
  }
  if (desc.load_network) {
    if (!m.nr.init(gpu, desc.stack_dir, desc.data_dir, desc.work_w, desc.work_h, desc.passes, desc.settings,
                   err)) {
      shutdown();
      return false;
    }
    m.network = true;
  }

  // ---- the descriptors. The flag's never changes. The frames' start as null views and are
  // written at every use, as are the conversion's two. The ones that name the work set are
  // written again when it changes.
  {
    D3D12_UNORDERED_ACCESS_VIEW_DESC flag = {};
    flag.Format = DXGI_FORMAT_R32_UINT;
    flag.ViewDimension = D3D12_UAV_DIMENSION_BUFFER;
    flag.Buffer.NumElements = kFlagCount;
    D3D12_UNORDERED_ACCESS_VIEW_DESC conv = {};
    conv.Format = kConvertedFormat;
    conv.ViewDimension = D3D12_UAV_DIMENSION_TEXTURE2D;
    for (UINT t = 0; t < (UINT)kIngestTables; ++t) {
      const UINT base = kSlotIngest0 + kSlotsPerIngest * t;
      device->CreateUnorderedAccessView(m.flag.Get(), nullptr, &flag, m.cpu_slot(base + kSlotFlagUav));
      m.srv(nullptr, kFrameFormat, base + kSlotCur);
      m.srv(nullptr, kFrameFormat, base + kSlotPrev);
      m.srv(nullptr, kRawFormat, base + kSlotCur16);
      m.srv(nullptr, kRawFormat, base + kSlotPrev16);
      const UINT conv_base = kSlotConv0 + kSlotsPerConv * t;
      m.srv(nullptr, kRawFormat, conv_base);
      device->CreateUnorderedAccessView(nullptr, nullptr, &conv, m.cpu_slot(conv_base + 1));
    }
    for (UINT i = 0; i < (UINT)kDrawContexts; ++i) {
      m.srv(nullptr, kFrameFormat, kSlotDraw0 + kSlotsPerDraw * i);
      m.srv(nullptr, kRawFormat, kSlotDraw0 + kSlotsPerDraw * i + 3);
    }
    m.write_work_descriptors();
  }
  return true;
}

bool Pipeline::ingest(ID3D12Resource* cur, ID3D12Resource* prev, ID3D12Fence* shared_fence, UINT64 value,
                      bool& changed, std::string& err) {
  if (!impl_ || !cur) {
    err = "the pipeline is not set up";
    return false;
  }
  Impl& m = *impl_;
  Gpu& gpu = *m.gpu;
  // a frame cannot be the one before itself: drawn whatever it holds
  bool compare = prev != nullptr && prev != cur;

  // A 16-bit frame is converted first, into the free one of the two converted frames, and
  // the rest of the ingest works on that. The frame before is then the converted frame of
  // the last ingest, when prev is the frame that one converted, see pipeline.h.
  const bool raw = cur->GetDesc().Format == kRawFormat;
  ID3D12Resource* cur8 = cur;
  int next_conv = -1;
  if (raw) {
    if (!m.make_conv(err)) return false;
    next_conv = m.conv_index >= 0 ? 1 - m.conv_index : 0;
    cur8 = m.conv[next_conv].Get();
  }
  ID3D12Resource* prev8 = m.frame_before(cur, prev, raw, compare);
  // a 16-bit frame is compared with the 16-bit frame before it, see record_ingest()
  ID3D12Resource* prev16 = raw && compare ? prev : nullptr;

  Context& c = m.ingest;
  if (!m.begin(c, err)) return false;
  ID3D12GraphicsCommandList* l = c.list.Get();

  // The ingest before this one has finished, it waited, so its descriptors are free.
  const UINT token = m.next_token();
  m.record_ingest(l, 0, kTimeIngest, cur, raw, cur8, prev8, prev16, compare, token);
  m.timer.resolve(l, kTimeIngest, kTimesIngest);

  // LENS_FAST_SPLIT_WAIT=1, a test: the CPU first waits for the capture's copy itself, so the
  // profile can tell that wait from the queue's own turn that follows. It gives up the overlap
  // of the two, which a test of where the time goes can spare.
  m.last_copy_wait_ms = 0.0;
  if (shared_fence && m.split_wait && shared_fence->GetCompletedValue() < value) {
    const double t0 = now_s();
    HANDLE ev = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    if (ev && SUCCEEDED(shared_fence->SetEventOnCompletion(value, ev))) WaitForSingleObject(ev, kWaitMs);
    if (ev) CloseHandle(ev);
    m.last_copy_wait_ms = (now_s() - t0) * 1000.0;
  }

  // The capture's copy into the slot runs on its own device: the queue stands still until
  // that copy is done, and only then reads the frame. Later lists come after it in the
  // queue, so render() needs no wait of its own.
  if (shared_fence) {
    const HRESULT hr = gpu.queue->Wait(shared_fence, value);
    if (FAILED(hr)) {
      l->Close();
      if (gpu.alive(err)) err = "waiting for the capture's fence failed " + hr_text(hr);
      return false;
    }
  }
  if (!gpu.execute(l, c.fence, err)) return false;
  if (!gpu.wait(c.fence, kWaitMs, err)) return false;

  m.last_ingest_ms = m.timer.ms(gpu, kTimeIngest + 1, kTimeIngest + 2);
  m.last_convert_ms = raw ? m.timer.ms(gpu, kTimeIngest, kTimeIngest + 1) : 0.0;
  if (raw) {
    m.conv_index = next_conv;
    m.conv_slot = cur;
  }
  changed = !compare || *m.flag_value == token;
  m.ingest_compared = compare;
  m.ingest_token = token;
  // The same picture in a newer texture: repaints draw from the newer one from now on, so
  // the capture can have the older one back.
  if (!changed && m.native) m.native = cur8;
  return true;
}

bool Pipeline::render_joined(ID3D12Resource* cur, ID3D12Resource* prev, ID3D12Fence* shared_fence, UINT64 value,
                             const Target& target, bool reset, bool keep_copy, std::string& err) {
  if (!impl_ || !cur || !target.texture) {
    err = "the pipeline is not set up";
    return false;
  }
  Impl& m = *impl_;
  if (target.width != m.desc.width || target.height != m.desc.height) {
    err = strf("the target is %ux%u and the picture %ux%u", target.width, target.height, m.desc.width,
               m.desc.height);
    return false;
  }
  // the frames as ingest() takes them
  bool compare = prev != nullptr && prev != cur;
  const bool raw = cur->GetDesc().Format == kRawFormat;
  ID3D12Resource* cur8 = cur;
  int next_conv = -1;
  if (raw) {
    if (!m.make_conv(err)) return false;
    next_conv = m.conv_index >= 0 ? 1 - m.conv_index : 0;
    cur8 = m.conv[next_conv].Get();
  }
  ID3D12Resource* prev8 = m.frame_before(cur, prev, raw, compare);
  ID3D12Resource* prev16 = raw && compare ? prev : nullptr;

  const int index = m.next_draw;
  Context& c = m.draw[index];
  if (!m.begin(c, err)) return false;
  ID3D12GraphicsCommandList* l = c.list.Get();
  const UINT t0 = kTimeDraw0 + kTimesPerDraw * (UINT)index;

  // ---- the ingest, on this context's own tables and into its own region of the flags
  const UINT token = m.next_token();
  m.record_ingest(l, (UINT)(1 + index), t0, cur, raw, cur8, prev8, prev16, compare, token);

  // ---- the render, as render() records it. The ingest's last mark is the draw's start.
  const bool evaluate = m.runs() && !m.hold;
  const bool residual = m.hold ? (m.runs() && m.pair) : evaluate;
  if (evaluate) {
    const bool drop = reset || m.reset_next;
    const D3D12_RESOURCE_STATES kRead = D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
    const D3D12_RESOURCE_STATES kWrite = D3D12_RESOURCE_STATE_UNORDERED_ACCESS;
    ID3D12Resource* in = m.work.in.Get();
    for (int pass = 0; pass < m.desc.passes; ++pass) {
      ID3D12Resource* out = m.work.out[pass % 2].Get();
      if (pass > 0) transition(l, in, kWrite, kRead);
      if (!m.nr.evaluate(l, pass, in, out, drop, err)) {
        l->Close();
        return false;
      }
      if (pass > 0) transition(l, in, kRead, kWrite);
      in = out;
    }
  }
  m.timer.mark(l, t0 + 3);

  // LENS_FAST_SPLIT_WAIT=1, a test, as in ingest(): the CPU waits for the capture's copy
  // itself before it submits
  m.last_copy_wait_ms = 0.0;
  if (shared_fence && m.split_wait && shared_fence->GetCompletedValue() < value) {
    const double t_wait = now_s();
    HANDLE ev = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    if (ev && SUCCEEDED(shared_fence->SetEventOnCompletion(value, ev))) WaitForSingleObject(ev, kWaitMs);
    if (ev) CloseHandle(ev);
    m.last_copy_wait_ms = (now_s() - t_wait) * 1000.0;
  }

  // A 16-bit frame is drawn from the conversion this list makes, which compose() finds
  // through conv_index, so the two are set before it and put back should it fail.
  const int was_conv_index = m.conv_index;
  ID3D12Resource* const was_conv_slot = m.conv_slot;
  if (raw) {
    m.conv_index = next_conv;
    m.conv_slot = cur;
  }
  c.ran_network = evaluate;
  c.ingest_ms = 0.0;
  c.joined = true;
  c.converted = raw;
  c.compared = compare;
  c.token = token;
  if (!m.compose(index, cur8, target, residual, keep_copy, err, shared_fence, value)) {
    m.conv_index = was_conv_index;
    m.conv_slot = was_conv_slot;
    return false;
  }
  c.flag_unread = true;
  if (evaluate) m.reset_next = false;
  m.native = cur8;
  m.drawn_residual = residual;
  if (!m.hold) m.pair = evaluate;
  m.next_draw = (index + 1) % kDrawContexts;
  return true;
}

bool Pipeline::take_flag(bool& changed, uint8_t tiles[kTiles]) {
  if (!impl_) return false;
  Impl& m = *impl_;
  m.harvest_finished();
  if (m.flags.empty()) return false;
  const Impl::Flag& f = m.flags.front();
  changed = f.changed;
  for (int i = 0; i < kTiles; ++i) {
    if (f.tiles[i]) tiles[i] = 1;
  }
  m.flags.pop_front();
  return true;
}

bool Pipeline::take_times(StageTimes& t) {
  if (!impl_) return false;
  Impl& m = *impl_;
  m.harvest_finished();
  if (m.times_queue.empty()) return false;
  t = m.times_queue.front();
  m.times_queue.pop_front();
  return true;
}

void Pipeline::keep_times(bool on) {
  if (!impl_) return;
  impl_->times_kept = on;
  if (!on) impl_->times_queue.clear();
}

bool Pipeline::render(ID3D12Resource* cur, const Target& target, bool reset, bool keep_copy, std::string& err) {
  if (!impl_ || !cur || !target.texture) {
    err = "the pipeline is not set up";
    return false;
  }
  Impl& m = *impl_;
  if (target.width != m.desc.width || target.height != m.desc.height) {
    err = strf("the target is %ux%u and the picture %ux%u", target.width, target.height, m.desc.width,
               m.desc.height);
    return false;
  }
  // a 16-bit frame is drawn from its conversion, which the ingest before this made
  ID3D12Resource* frame = m.composed_from(cur);
  if (frame == cur && cur->GetDesc().Format == kRawFormat) {
    err = "a 16-bit frame was given to render without its ingest";
    return false;
  }
  const int index = m.next_draw;
  Context& c = m.draw[index];
  if (!m.begin(c, err)) return false;
  ID3D12GraphicsCommandList* l = c.list.Get();
  const UINT t0 = kTimeDraw0 + kTimesPerDraw * (UINT)index;

  // While another work size is being made no call goes to the runtime. The picture is then
  // the new native frame with the network's change as the last render before that left it,
  // if that render had one.
  const bool evaluate = m.runs() && !m.hold;
  const bool residual = m.hold ? (m.runs() && m.pair) : evaluate;
  // the three marks of an ingest a joined list would hold, together: no ingest here
  m.timer.mark(l, t0);
  m.timer.mark(l, t0 + 1);
  m.timer.mark(l, t0 + 2);
  if (evaluate) {
    const bool drop = reset || m.reset_next;
    const D3D12_RESOURCE_STATES kRead = D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
    const D3D12_RESOURCE_STATES kWrite = D3D12_RESOURCE_STATE_UNORDERED_ACCESS;
    ID3D12Resource* in = m.work.in.Get();
    for (int pass = 0; pass < m.desc.passes; ++pass) {
      // chained: a pass reads what the pass before it wrote
      ID3D12Resource* out = m.work.out[pass % 2].Get();
      if (pass > 0) transition(l, in, kWrite, kRead);
      if (!m.nr.evaluate(l, pass, in, out, drop, err)) {
        l->Close();  // it may hold part of the runtime's commands, and is never run
        return false;
      }
      if (pass > 0) transition(l, in, kRead, kWrite);
      in = out;
    }
    m.reset_next = false;
  }
  m.timer.mark(l, t0 + 3);

  c.ran_network = evaluate;
  c.ingest_ms = m.last_ingest_ms;
  c.joined = false;
  c.converted = false;
  c.compared = false;
  c.token = 0;
  if (!m.compose(index, frame, target, residual, keep_copy, err)) return false;
  m.native = frame;
  m.drawn_residual = residual;
  // Off hold, the ingest before this render wrote a new input, and the textures hold a pair
  // only if the network then ran on it. On hold they stay as they were.
  if (!m.hold) m.pair = evaluate;
  m.next_draw = (index + 1) % kDrawContexts;
  return true;
}

bool Pipeline::repaint(const Target& target, bool keep_copy, std::string& err) {
  if (!impl_ || !target.texture) {
    err = "the pipeline is not set up";
    return false;
  }
  Impl& m = *impl_;
  if (!m.native) {
    err = "nothing rendered yet";
    return false;
  }
  if (target.width != m.desc.width || target.height != m.desc.height) {
    err = strf("the target is %ux%u and the picture %ux%u", target.width, target.height, m.desc.width,
               m.desc.height);
    return false;
  }
  const int index = m.next_draw;
  Context& c = m.draw[index];
  if (!m.begin(c, err)) return false;
  const UINT t0 = kTimeDraw0 + kTimesPerDraw * (UINT)index;
  for (UINT k = 0; k < 4; ++k) m.timer.mark(c.list.Get(), t0 + k);  // no ingest, no network
  c.ran_network = false;
  c.ingest_ms = 0.0;
  c.joined = false;
  c.converted = false;
  c.compared = false;
  c.token = 0;
  // as the last render drew it, whatever "nr" says by now: the picture is the same one
  if (!m.compose(index, m.native, target, m.drawn_residual, keep_copy, err)) return false;
  m.next_draw = (index + 1) % kDrawContexts;
  return true;
}

bool Pipeline::wait_drawn(std::string& err) {
  if (!impl_) {
    err = "the pipeline is not set up";
    return false;
  }
  Impl& m = *impl_;
  // The queue runs in order, so the newest draw's value covers every draw before it.
  UINT64 newest = 0;
  for (const Context& c : m.draw) {
    if (c.used) newest = std::max(newest, c.fence);
  }
  if (newest == 0) return true;  // nothing drawn yet
  return m.gpu->wait(newest, kWaitMs, err);
}

bool Pipeline::prepare_copies(DXGI_FORMAT target_format, std::string& err) {
  if (!impl_) {
    err = "the pipeline is not set up";
    return false;
  }
  return impl_->make_copies(target_format, err);
}

bool Pipeline::read_native(std::vector<uint8_t>& rgb, std::string& err) {
  if (!impl_) {
    rgb.clear();
    err = "the pipeline is not set up";
    return false;
  }
  return impl_->read_copy(impl_->native_copy.Get(), 1, rgb, err);
}

bool Pipeline::read_target(std::vector<uint8_t>& rgb, std::string& err) {
  if (!impl_) {
    rgb.clear();
    err = "the pipeline is not set up";
    return false;
  }
  return impl_->read_copy(impl_->target_copy.Get(), 1, rgb, err);
}

void Pipeline::keep_raw(bool on) {
  if (impl_) impl_->raw_wanted = on;
}

bool Pipeline::read_raw(std::vector<uint16_t>& rgba, std::string& err) {
  rgba.clear();
  if (!impl_) {
    err = "the pipeline is not set up";
    return false;
  }
  Impl& m = *impl_;
  if (!m.have_raw || !m.raw_copy) {
    err = "no raw frame was kept";
    return false;
  }
  return m.read_halves(m.raw_copy.Get(), m.raw_fp, m.raw_bytes, rgba, err);
}

bool Pipeline::read_target_raw(std::vector<uint16_t>& rgba, std::string& err) {
  rgba.clear();
  if (!impl_) {
    err = "the pipeline is not set up";
    return false;
  }
  Impl& m = *impl_;
  if (!m.have_copy || !m.target_copy) {
    err = "no copy was kept";
    return false;
  }
  if (m.target_format != kRawFormat) {
    err = "the target is not a 16-bit one";
    return false;
  }
  return m.read_halves(m.target_copy.Get(), m.target_fp, m.target_bytes, rgba, err);
}

void Pipeline::set_sdr_white(double units) {
  if (impl_) impl_->sdr_white = units >= 1.0 ? units : 1.0;
}

void Pipeline::set_hdr_above(HdrAbove above) {
  if (impl_) impl_->hdr_above = above;
}

void Pipeline::drop_frames() {
  if (!impl_) return;
  Impl& m = *impl_;
  m.native = nullptr;
  m.drawn_residual = false;
  m.conv_index = -1;
  m.conv_slot = nullptr;
  m.conv[0].Reset();
  m.conv[1].Reset();
  m.have_copy = false;
  m.have_raw = false;
  m.reset_next = true;
}

void Pipeline::drop_target_copies() {
  if (!impl_) return;
  Impl& m = *impl_;
  m.have_copy = false;
  m.have_raw = false;
  m.target_copy.Reset();
  m.target_format = DXGI_FORMAT_UNKNOWN;
}

bool Pipeline::read_target_sparse(std::vector<uint8_t>& rgb, UINT& w, UINT& h, std::string& err) {
  w = 0;
  h = 0;
  if (!impl_) {
    rgb.clear();
    err = "the pipeline is not set up";
    return false;
  }
  if (!impl_->read_copy(impl_->target_copy.Get(), 4, rgb, err)) return false;
  w = (impl_->desc.width + 3) / 4;
  h = (impl_->desc.height + 3) / 4;
  return true;
}

bool Pipeline::read_work(bool output, std::vector<uint8_t>& rgb, UINT& w, UINT& h, std::string& err) {
  rgb.clear();
  w = 0;
  h = 0;
  if (!impl_ || !impl_->network) {
    err = "there is no network";
    return false;
  }
  Impl& m = *impl_;
  Gpu& gpu = *m.gpu;
  ID3D12Resource* texture = output ? m.last_out() : m.work.in.Get();
  const D3D12_RESOURCE_STATES rest =
      output ? D3D12_RESOURCE_STATE_UNORDERED_ACCESS : D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;

  const D3D12_RESOURCE_DESC d = texture->GetDesc();
  D3D12_PLACED_SUBRESOURCE_FOOTPRINT fp = {};
  UINT64 bytes = 0;
  gpu.device->GetCopyableFootprints(&d, 0, 1, 0, &fp, nullptr, nullptr, &bytes);
  ComPtr<ID3D12Resource> buffer;
  if (!gpu.make_buffer(bytes, D3D12_HEAP_TYPE_READBACK, D3D12_RESOURCE_STATE_COPY_DEST, D3D12_RESOURCE_FLAG_NONE,
                       L"work readback", buffer, err))
    return false;

  // on the ingest's list, which is free whenever no ingest is running
  Context& c = m.ingest;
  if (!m.begin(c, err)) return false;
  ID3D12GraphicsCommandList* l = c.list.Get();
  transition(l, texture, rest, D3D12_RESOURCE_STATE_COPY_SOURCE);
  D3D12_TEXTURE_COPY_LOCATION dst = {};
  dst.pResource = buffer.Get();
  dst.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
  dst.PlacedFootprint = fp;
  D3D12_TEXTURE_COPY_LOCATION src = {};
  src.pResource = texture;
  src.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
  l->CopyTextureRegion(&dst, 0, 0, 0, &src, nullptr);
  transition(l, texture, D3D12_RESOURCE_STATE_COPY_SOURCE, rest);
  if (!gpu.execute(l, c.fence, err) || !gpu.wait(c.fence, kWaitMs, err)) return false;

  void* p = nullptr;
  const D3D12_RANGE whole = {0, (SIZE_T)bytes};
  const HRESULT hr = buffer->Map(0, &whole, &p);
  if (FAILED(hr) || !p) {
    err = "mapping the work readback failed " + hr_text(hr);
    return false;
  }
  // R8G8B8A8 rows with a pitch to tight RGB8
  w = m.work.w;
  h = m.work.h;
  rgb.resize((size_t)w * h * 3);
  uint8_t* out = rgb.data();
  for (UINT y = 0; y < h; ++y) {
    const uint8_t* in = (const uint8_t*)p + fp.Offset + (size_t)y * fp.Footprint.RowPitch;
    for (UINT x = 0; x < w; ++x, in += 4, out += 3) {
      out[0] = in[0];
      out[1] = in[1];
      out[2] = in[2];
    }
  }
  const D3D12_RANGE none = {0, 0};
  buffer->Unmap(0, &none);
  return true;
}

void Pipeline::set_nr(bool on) {
  if (!impl_) return;
  if (on && !impl_->nr_on) impl_->reset_next = true;
  impl_->nr_on = on;
}

bool Pipeline::nr_on() const { return impl_ && impl_->network && impl_->nr_on; }

void Pipeline::set_settings(const NrPasses& settings) {
  if (!impl_ || same_passes(settings, impl_->settings, impl_->desc.passes)) return;
  impl_->settings = settings;
  impl_->reset_next = true;
  if (impl_->network) impl_->nr.set_settings(settings);
}

void Pipeline::set_settings(const NrSettings& settings) { set_settings(NrPasses(settings)); }

bool Pipeline::network_runs() const { return impl_ && impl_->runs() && !impl_->hold; }

void Pipeline::set_run_at_zero(bool run) {
  if (!impl_ || run == impl_->run_at_zero) return;
  impl_->run_at_zero = run;
  impl_->reset_next = true;
}

bool Pipeline::begin_work(UINT work_w, UINT work_h, std::string& err) {
  if (!impl_) {
    err = "the pipeline is not set up";
    return false;
  }
  Impl& m = *impl_;
  if (!m.start_work(work_w, work_h, err)) return false;
  if (!m.network) {
    m.making.store(2);  // no features to make
    SetEvent(m.made_event);
    return true;
  }
  // From here until the thread has ended, no call goes to the runtime from this thread.
  m.hold = true;
  m.making.store(1);
  Impl* impl = impl_;
  try {
    m.maker = std::thread([impl, work_w, work_h] {
      std::string why;
      const bool made = impl->nr.prepare(work_w, work_h, why);
      if (!made) impl->make_err = why;
      impl->making.store(made ? 2 : 3);
      SetEvent(impl->made_event);
    });
  } catch (const std::system_error&) {
    // No thread is to be had. It is made here and now, which holds the caller as
    // prepare_work() does.
    m.hold = false;
    if (!m.nr.prepare(work_w, work_h, err)) {
      m.making.store(0);
      m.next = WorkSet();
      return false;
    }
    m.making.store(2);
    SetEvent(m.made_event);
  }
  return true;
}

int Pipeline::work_state(std::string& err) {
  if (!impl_) return 0;
  Impl& m = *impl_;
  const int state = m.making.load();
  if (state != 3) return state;
  // It could not be made. The thread has ended, and the pipeline is as before begin_work().
  m.join_maker();
  err = m.make_err;
  m.make_err.clear();
  m.next = WorkSet();
  m.hold = false;
  m.making.store(0);
  return 3;
}

HANDLE Pipeline::work_event() const { return impl_ ? impl_->made_event : nullptr; }

bool Pipeline::prepare_work(UINT work_w, UINT work_h, std::string& err) {
  if (!impl_) {
    err = "the pipeline is not set up";
    return false;
  }
  Impl& m = *impl_;
  if (!m.start_work(work_w, work_h, err)) return false;
  if (m.network && !m.nr.prepare(work_w, work_h, err)) {
    m.next = WorkSet();
    return false;
  }
  m.making.store(2);
  return true;
}

bool Pipeline::commit_work(std::string& err) {
  if (!impl_ || !impl_->next.made || impl_->making.load() != 2) {
    err = "no work size was made";
    return false;
  }
  Impl& m = *impl_;
  // the thread that made the features has ended, and the runtime is this thread's again
  m.join_maker();
  // Everything submitted so far is finished before anything changes hands: the lists that
  // read the old textures and ran the old features, and with them every draw context, so
  // the descriptors are free to be written.
  if (!m.gpu->flush(kWaitMs, err)) return false;
  m.hold = false;
  m.making.store(0);
  // the features first, then the textures they were shown, which go when `old` does
  if (m.network) m.nr.use_prepared();
  const WorkSet old = m.work;
  m.work = m.next;
  m.next = WorkSet();
  m.desc.work_w = m.work.w;
  m.desc.work_h = m.work.h;
  m.write_work_descriptors();
  // The new features have no history, and the new textures hold nothing yet. Until the next
  // render a repaint is the native frame alone.
  m.reset_next = true;
  m.drawn_residual = false;
  m.pair = false;
  return true;
}

UINT Pipeline::work_width() const { return impl_ ? impl_->work.w : 0; }

UINT Pipeline::work_height() const { return impl_ ? impl_->work.h : 0; }

double Pipeline::prepare_ms() const { return impl_ && impl_->network ? impl_->nr.prepare_ms() : 0.0; }

StageTimes Pipeline::times() const {
  StageTimes t;
  if (!impl_ || !impl_->gpu->fence) return t;
  const Impl& m = *impl_;
  // the newest draw the GPU has finished
  const UINT64 done = m.gpu->fence->GetCompletedValue();
  int best = -1;
  for (int i = 0; i < kDrawContexts; ++i) {
    const Context& c = m.draw[i];
    if (c.used && c.fence <= done && (best < 0 || c.fence > m.draw[best].fence)) best = i;
  }
  if (best < 0) return t;
  return m.read_times(m.draw[best], best);
}

double Pipeline::last_ingest_ms() const { return impl_ ? impl_->last_ingest_ms : 0.0; }

UINT64 Pipeline::last_draw_sequence() const { return impl_ ? impl_->draw_sequence : 0; }

void Pipeline::last_ingest_ticks(UINT64 out[3]) const {
  for (UINT i = 0; i < kTimesIngest; ++i) {
    out[i] = impl_ && impl_->timer.ticks ? impl_->timer.ticks[kTimeIngest + i] : 0;
  }
}
double Pipeline::last_convert_ms() const { return impl_ ? impl_->last_convert_ms : 0.0; }
double Pipeline::last_copy_wait_ms() const { return impl_ ? impl_->last_copy_wait_ms : 0.0; }

void Pipeline::add_changed_tiles(uint8_t tiles[kTiles]) const {
  if (!impl_ || !impl_->flag_value) return;
  const Impl& m = *impl_;
  // A tile's flag holds the token of the last frame that differed there, so only this
  // frame's token counts and the flags never need clearing.
  for (int i = 0; i < kTiles; ++i) {
    if (!m.ingest_compared || m.flag_value[1 + i] == m.ingest_token) tiles[i] = 1;
  }
}

double Pipeline::network_create_ms() const { return impl_ && impl_->network ? impl_->nr.create_ms() : 0.0; }

void Pipeline::shutdown() {
  if (!impl_) return;
  Impl& m = *impl_;
  // a thread still making features ends first, which takes at most the time of one creation
  m.join_maker();
  if (m.made_event) CloseHandle(m.made_event);
  m.made_event = nullptr;
  // the network first: its features go before the textures they were shown
  m.nr.shutdown();
  if (m.flag_back && m.flag_value) m.flag_back->Unmap(0, nullptr);
  m.flag_value = nullptr;
  m.timer.shutdown();
  delete impl_;
  impl_ = nullptr;
}
