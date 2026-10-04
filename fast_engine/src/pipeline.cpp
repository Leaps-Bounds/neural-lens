// pipeline.cpp: the GPU work for one captured frame. See pipeline.h for the contract.
//
// Three shaders do it all (src\shaders):
//   ingest_cs      the area downscale into the network's input and the exact comparison
//                  with the frame before, in one pass over the frame
//   fullscreen_vs  one triangle over the whole target
//   composite_ps   native + upsample(network output - network input), or native alone
//
// Lists. An ingest waits for the GPU, so one allocator and one list serve every ingest. A
// draw (render or repaint) does not wait, so draws take turns on three contexts, each with
// its own allocator, list, descriptors and timestamps, and a context is taken again only
// once the GPU has finished what was last recorded from it. That is what makes it safe to
// reset its allocator and to write its descriptors.
//
// Resource states between calls, which every function here restores:
//   the network's input    NON_PIXEL_SHADER_RESOURCE, as Nr::evaluate wants it
//   the network's outputs  UNORDERED_ACCESS, the same
//   the flag buffer        UNORDERED_ACCESS
//   frames and targets     COMMON (PRESENT), they are someone else's
//
// The work size. Everything that depends on it is one WorkSet: the network's input and
// output textures and the downscale's weights. A new work size gets a second set, made
// while the first is in use, and the two change places between two pictures, when the GPU
// has finished every list that named the old one (commit_work).
#include "pipeline.h"

#include "nr.h"

#include "composite_ps.h"
#include "fullscreen_vs.h"
#include "ingest_cs.h"

#include <atomic>
#include <cstring>
#include <system_error>
#include <thread>

using Microsoft::WRL::ComPtr;

namespace {

constexpr DXGI_FORMAT kFrameFormat = DXGI_FORMAT_B8G8R8A8_UNORM;  // frames and targets

constexpr int kDrawContexts = 3;

// Every wait on the GPU in the frame loop gives up after this long: the window is topmost
// over the whole screen, and a process that waits for ever looks like a frozen computer.
constexpr DWORD kWaitMs = 2000;

// The shader visible descriptors: ingest's table of five, then a table of three for each
// draw context.
constexpr UINT kSlotCur = 0;       // SRV, the new frame
constexpr UINT kSlotPrev = 1;      // SRV, the frame before
constexpr UINT kSlotWeights = 2;   // SRV, the downscale's weights
constexpr UINT kSlotWorkUav = 3;   // UAV, the network's input
constexpr UINT kSlotFlagUav = 4;   // UAV, the flags

// The flags: one uint for the whole frame and one for each tile, as the ingest shader
// numbers them.
constexpr UINT kFlagCount = 1 + (UINT)Pipeline::kTiles;
constexpr UINT kFlagBytes = kFlagCount * 4;
constexpr UINT kSlotDraw0 = 5;     // per draw context: SRV native, SRV input, SRV output
constexpr UINT kSlotsPerDraw = 3;
constexpr UINT kSlotCount = kSlotDraw0 + kSlotsPerDraw * kDrawContexts;

// The timestamps: two for the ingest, three for each draw context (start, after the
// network, after the composite and the copies).
constexpr UINT kTimeIngest = 0;
constexpr UINT kTimeDraw0 = 2;
constexpr UINT kTimesPerDraw = 3;
constexpr UINT kTimeCount = kTimeDraw0 + kTimesPerDraw * kDrawContexts;

// As the shaders declare them.
struct IngestConstants {
  UINT src_w, src_h, dst_w, dst_h, token, compare, downscale, taps_x, taps_y, unused[3];
};
struct DrawConstants {
  UINT w, h, work_w, work_h, residual;
  float inv_x, inv_y;  // the floats nearest to 1 / (2 w) and 1 / (2 h), see composite_ps.hlsl
  UINT unused;
};

struct Context {
  ComPtr<ID3D12CommandAllocator> allocator;
  ComPtr<ID3D12GraphicsCommandList> list;
  UINT64 fence = 0;          // what the queue's fence reaches when its last list is done
  bool used = false;
  bool ran_network = false;  // what that list held, for times()
  double ingest_ms = 0.0;    // the ingest that led to it, 0 for a repaint
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

// B8G8R8A8 rows with a pitch to tight RGB8, every step-th texel each way.
void bgra_to_rgb(const uint8_t* base, UINT pitch, UINT width, UINT height, UINT step, std::vector<uint8_t>& rgb) {
  const UINT w = (width + step - 1) / step, h = (height + step - 1) / step;
  rgb.resize((size_t)w * h * 3);
  uint8_t* out = rgb.data();
  for (UINT y = 0; y < height; y += step) {
    const uint8_t* in = base + (size_t)y * pitch;
    for (UINT x = 0; x < width; x += step) {
      const uint8_t* t = in + (size_t)x * 4;
      out[0] = t[2];
      out[1] = t[1];
      out[2] = t[0];
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
  NrSettings settings;

  ComPtr<ID3D12RootSignature> ingest_root, draw_root;
  ComPtr<ID3D12PipelineState> ingest_pso, draw_pso;
  ComPtr<ID3D12DescriptorHeap> heap;
  UINT heap_step = 0;

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
  ComPtr<ID3D12Resource> flag_back;    // where they are read back, mapped for life
  const UINT* flag_value = nullptr;
  UINT token = 0;
  bool compared = false;               // whether the most recent ingest compared anything

  Context ingest;
  Context draw[kDrawContexts];
  int next_draw = 0;
  GpuTimer timer;
  double last_ingest_ms = 0.0;
  bool split_wait = false;             // LENS_FAST_SPLIT_WAIT=1, see ingest()
  double last_copy_wait_ms = 0.0;      // the CPU's wait for the capture's copy under it

  // What a repaint draws from: which texture holds the native picture, and how the last
  // render drew. The network's input and output are the retained rest of it.
  ID3D12Resource* native = nullptr;
  bool drawn_residual = false;
  // The network's input and output textures hold an input and what the network made of
  // that same input, so their difference is the network's change. Not so before the first
  // run of the network at this work size, nor after a render with the network off.
  bool pair = false;

  // The copies a shot or a probe asks for.
  ComPtr<ID3D12Resource> native_copy, target_copy;
  D3D12_PLACED_SUBRESOURCE_FOOTPRINT copy_fp = {};
  UINT64 copy_bytes = 0;
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

  // Whether the network's change is part of the picture. A strength of 0 counts as off, see
  // network_runs().
  bool runs() const { return network && nr_on && (settings.intensity > 0.0f || run_at_zero); }

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

  // The descriptors that name the work set in use: the ingest's two and two in each draw
  // context's table. Null views where there is no network, so the tables are whole either
  // way. The GPU must have finished every list that used them.
  void write_work_descriptors() {
    D3D12_UNORDERED_ACCESS_VIEW_DESC uav = {};
    uav.Format = kNrFormat;
    uav.ViewDimension = D3D12_UAV_DIMENSION_TEXTURE2D;
    gpu->device->CreateUnorderedAccessView(work.in.Get(), nullptr, &uav, cpu_slot(kSlotWorkUav));
    D3D12_SHADER_RESOURCE_VIEW_DESC table = {};
    table.Format = DXGI_FORMAT_R32_FLOAT;
    table.ViewDimension = D3D12_SRV_DIMENSION_BUFFER;
    table.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
    table.Buffer.NumElements = work.weight_count;
    gpu->device->CreateShaderResourceView(work.weights.Get(), &table, cpu_slot(kSlotWeights));
    for (UINT i = 0; i < (UINT)kDrawContexts; ++i) {
      const UINT slot = kSlotDraw0 + kSlotsPerDraw * i;
      srv(work.in.Get(), kNrFormat, slot + 1);
      srv(network ? last_out() : nullptr, kNrFormat, slot + 2);
    }
  }

  // Makes the context ready to record: waits until the GPU has finished what was last
  // recorded from it, then resets its allocator and list.
  bool begin(Context& c, std::string& err) {
    if (c.fence && !gpu->wait(c.fence, kWaitMs, err)) return false;
    HRESULT hr = c.allocator->Reset();
    if (SUCCEEDED(hr)) hr = c.list->Reset(c.allocator.Get(), nullptr);
    if (FAILED(hr)) {
      if (gpu->alive(err)) err = "resetting a command list failed " + hr_text(hr);
      return false;
    }
    return true;
  }

  bool make_copies(std::string& err) {
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
    return gpu->make_buffer(copy_bytes, D3D12_HEAP_TYPE_READBACK, D3D12_RESOURCE_STATE_COPY_DEST,
                            D3D12_RESOURCE_FLAG_NONE, L"native copy", native_copy, err) &&
           gpu->make_buffer(copy_bytes, D3D12_HEAP_TYPE_READBACK, D3D12_RESOURCE_STATE_COPY_DEST,
                            D3D12_RESOURCE_FLAG_NONE, L"target copy", target_copy, err);
  }

  void copy_out(ID3D12GraphicsCommandList* l, ID3D12Resource* texture, ID3D12Resource* buffer) {
    D3D12_TEXTURE_COPY_LOCATION dst = {};
    dst.pResource = buffer;
    dst.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
    dst.PlacedFootprint = copy_fp;
    D3D12_TEXTURE_COPY_LOCATION src = {};
    src.pResource = texture;
    src.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
    l->CopyTextureRegion(&dst, 0, 0, 0, &src, nullptr);
  }

  // Records the composite on the context's open list, after whatever the caller recorded,
  // and submits the list. The caller has marked timestamps 0 and 1 of the context.
  bool compose(int index, ID3D12Resource* frame, const Target& target, bool residual, bool keep_copy,
               std::string& err) {
    Context& c = draw[index];
    ID3D12GraphicsCommandList* l = c.list.Get();
    if (keep_copy && !make_copies(err)) {
      l->Close();
      return false;
    }
    const UINT table = kSlotDraw0 + kSlotsPerDraw * (UINT)index;
    srv(frame, kFrameFormat, table);  // the other two of the table name the work set, and were
                                      // written when it was put in use

    const D3D12_RESOURCE_STATES kCommon = D3D12_RESOURCE_STATE_COMMON;
    const D3D12_RESOURCE_STATES kPixel = D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE;
    const D3D12_RESOURCE_STATES kRead = D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
    const D3D12_RESOURCE_STATES kWrite = D3D12_RESOURCE_STATE_UNORDERED_ACCESS;
    const D3D12_RESOURCE_STATES kTarget = D3D12_RESOURCE_STATE_RENDER_TARGET;
    const D3D12_RESOURCE_STATES kSource = D3D12_RESOURCE_STATE_COPY_SOURCE;

    transition(l, frame, kCommon, kPixel);
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
    l->SetGraphicsRootSignature(draw_root.Get());
    l->SetPipelineState(draw_pso.Get());
    DrawConstants k = {};
    k.w = desc.width;
    k.h = desc.height;
    k.work_w = work.w;
    k.work_h = work.h;
    k.residual = residual ? 1u : 0u;
    // 1 / d in float, with d = 2 w and 2 h whole numbers that a float holds exactly. The
    // division is the CPU's, rounded as IEEE asks, and the shader only multiplies.
    k.inv_x = 1.0f / (float)(2u * desc.width);
    k.inv_y = 1.0f / (float)(2u * desc.height);
    l->SetGraphicsRoot32BitConstants(0, sizeof(k) / 4, &k, 0);
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
      copy_out(l, frame, native_copy.Get());
      transition(l, frame, kSource, kCommon);
      transition(l, target.texture, kTarget, kSource);
      copy_out(l, target.texture, target_copy.Get());
      transition(l, target.texture, kSource, D3D12_RESOURCE_STATE_PRESENT);
    } else {
      transition(l, frame, kPixel, kCommon);
      transition(l, target.texture, kTarget, D3D12_RESOURCE_STATE_PRESENT);
    }

    const UINT t0 = kTimeDraw0 + kTimesPerDraw * (UINT)index;
    timer.mark(l, t0 + 2);
    timer.resolve(l, t0, kTimesPerDraw);
    if (!gpu->execute(l, c.fence, err)) return false;
    c.used = true;
    have_copy = keep_copy;
    if (keep_copy) copy_fence = c.fence;
    return true;
  }

  // One of the kept copies as tight RGB8, every step-th texel each way.
  bool read_copy(ID3D12Resource* buffer, UINT step, std::vector<uint8_t>& rgb, std::string& err) {
    rgb.clear();
    if (!have_copy || !buffer) {
      err = "no copy was kept";
      return false;
    }
    if (!gpu->wait(copy_fence, kWaitMs, err)) return false;
    void* p = nullptr;
    const D3D12_RANGE whole = {0, (SIZE_T)copy_bytes};
    const HRESULT hr = buffer->Map(0, &whole, &p);
    if (FAILED(hr) || !p) {
      err = "mapping the copy failed " + hr_text(hr);
      return false;
    }
    bgra_to_rgb((const uint8_t*)p + copy_fp.Offset, copy_fp.Footprint.RowPitch, desc.width, desc.height, step,
                rgb);
    const D3D12_RANGE none = {0, 0};  // nothing was written
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

  // ---- the ingest: constants, and a table of two frames, the weights, the network's input
  // and the flag
  {
    D3D12_DESCRIPTOR_RANGE ranges[2] = {};
    ranges[0].RangeType = D3D12_DESCRIPTOR_RANGE_TYPE_SRV;
    ranges[0].NumDescriptors = 3;
    ranges[0].OffsetInDescriptorsFromTableStart = kSlotCur;
    ranges[1].RangeType = D3D12_DESCRIPTOR_RANGE_TYPE_UAV;
    ranges[1].NumDescriptors = 2;
    ranges[1].OffsetInDescriptorsFromTableStart = kSlotWorkUav;
    D3D12_ROOT_PARAMETER params[2] = {};
    params[0].ParameterType = D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS;
    params[0].Constants.Num32BitValues = sizeof(IngestConstants) / 4;
    params[1].ParameterType = D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
    params[1].DescriptorTable.NumDescriptorRanges = 2;
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
      !gpu.make_buffer(kFlagBytes, D3D12_HEAP_TYPE_READBACK, D3D12_RESOURCE_STATE_COPY_DEST,
                       D3D12_RESOURCE_FLAG_NONE, L"ingest flag readback", m.flag_back, err)) {
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
  // written at every use. The ones that name the work set are written again when it changes.
  {
    D3D12_UNORDERED_ACCESS_VIEW_DESC flag = {};
    flag.Format = DXGI_FORMAT_R32_UINT;
    flag.ViewDimension = D3D12_UAV_DIMENSION_BUFFER;
    flag.Buffer.NumElements = kFlagCount;
    device->CreateUnorderedAccessView(m.flag.Get(), nullptr, &flag, m.cpu_slot(kSlotFlagUav));
    m.srv(nullptr, kFrameFormat, kSlotCur);
    m.srv(nullptr, kFrameFormat, kSlotPrev);
    for (UINT i = 0; i < (UINT)kDrawContexts; ++i) m.srv(nullptr, kFrameFormat, kSlotDraw0 + kSlotsPerDraw * i);
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
  const bool compare = prev != nullptr && prev != cur;

  Context& c = m.ingest;
  if (!m.begin(c, err)) return false;
  ID3D12GraphicsCommandList* l = c.list.Get();

  // The ingest before this one has finished, it waited, so its descriptors are free.
  m.srv(cur, kFrameFormat, kSlotCur);
  m.srv(compare ? prev : cur, kFrameFormat, kSlotPrev);
  if (++m.token == 0) m.token = 1;

  const D3D12_RESOURCE_STATES kCommon = D3D12_RESOURCE_STATE_COMMON;
  const D3D12_RESOURCE_STATES kRead = D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
  const D3D12_RESOURCE_STATES kWrite = D3D12_RESOURCE_STATE_UNORDERED_ACCESS;

  // While another work size is being made the network's input stays as the last render
  // used it, so that its change can still be drawn. The frame is only compared.
  const bool downscale = m.network && !m.hold;
  m.timer.mark(l, kTimeIngest);
  if (compare || downscale) {
    transition(l, cur, kCommon, kRead);
    if (compare) transition(l, prev, kCommon, kRead);
    if (downscale) transition(l, m.work.in.Get(), kRead, kWrite);

    ID3D12DescriptorHeap* heaps[] = {m.heap.Get()};
    l->SetDescriptorHeaps(1, heaps);
    l->SetComputeRootSignature(m.ingest_root.Get());
    l->SetPipelineState(m.ingest_pso.Get());
    IngestConstants k = {};
    k.src_w = m.desc.width;
    k.src_h = m.desc.height;
    k.dst_w = m.work.w;
    k.dst_h = m.work.h;
    k.token = m.token;
    k.compare = compare ? 1u : 0u;
    k.downscale = downscale ? 1u : 0u;
    k.taps_x = m.work.taps_x;
    k.taps_y = m.work.taps_y;
    l->SetComputeRoot32BitConstants(0, sizeof(k) / 4, &k, 0);
    l->SetComputeRootDescriptorTable(1, m.gpu_slot(kSlotCur));
    l->Dispatch((m.work.w + 7) / 8, (m.work.h + 7) / 8, 1);

    if (downscale) transition(l, m.work.in.Get(), kWrite, kRead);
    transition(l, cur, kRead, kCommon);
    if (compare) {
      transition(l, prev, kRead, kCommon);
      transition(l, m.flag.Get(), kWrite, D3D12_RESOURCE_STATE_COPY_SOURCE);
      l->CopyBufferRegion(m.flag_back.Get(), 0, m.flag.Get(), 0, kFlagBytes);
      transition(l, m.flag.Get(), D3D12_RESOURCE_STATE_COPY_SOURCE, kWrite);
    }
  }
  m.timer.mark(l, kTimeIngest + 1);
  m.timer.resolve(l, kTimeIngest, 2);

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

  m.last_ingest_ms = m.timer.ms(gpu, kTimeIngest, kTimeIngest + 1);
  changed = !compare || *m.flag_value == m.token;
  m.compared = compare;
  // The same picture in a newer texture: repaints draw from the newer one from now on, so
  // the capture can have the older one back.
  if (!changed && m.native) m.native = cur;
  return true;
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
  m.timer.mark(l, t0);
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
  m.timer.mark(l, t0 + 1);

  c.ran_network = evaluate;
  c.ingest_ms = m.last_ingest_ms;
  if (!m.compose(index, cur, target, residual, keep_copy, err)) return false;
  m.native = cur;
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
  m.timer.mark(c.list.Get(), t0);
  m.timer.mark(c.list.Get(), t0 + 1);
  c.ran_network = false;
  c.ingest_ms = 0.0;
  // as the last render drew it, whatever "nr" says by now: the picture is the same one
  if (!m.compose(index, m.native, target, m.drawn_residual, keep_copy, err)) return false;
  m.next_draw = (index + 1) % kDrawContexts;
  return true;
}

bool Pipeline::prepare_copies(std::string& err) {
  if (!impl_) {
    err = "the pipeline is not set up";
    return false;
  }
  return impl_->make_copies(err);
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

void Pipeline::set_settings(const NrSettings& settings) {
  if (!impl_ || same_settings(settings, impl_->settings)) return;
  impl_->settings = settings;
  impl_->reset_next = true;
  if (impl_->network) impl_->nr.set_settings(settings);
}

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
  const UINT t0 = kTimeDraw0 + kTimesPerDraw * (UINT)best;
  t.ingest_ms = m.draw[best].ingest_ms;
  t.nr_ms = m.draw[best].ran_network ? m.timer.ms(*m.gpu, t0, t0 + 1) : 0.0;
  t.composite_ms = m.timer.ms(*m.gpu, t0 + 1, t0 + 2);
  return t;
}

double Pipeline::last_ingest_ms() const { return impl_ ? impl_->last_ingest_ms : 0.0; }
double Pipeline::last_copy_wait_ms() const { return impl_ ? impl_->last_copy_wait_ms : 0.0; }

void Pipeline::add_changed_tiles(uint8_t tiles[kTiles]) const {
  if (!impl_ || !impl_->flag_value) return;
  const Impl& m = *impl_;
  // A tile's flag holds the token of the last frame that differed there, so only this
  // frame's token counts and the flags never need clearing.
  for (int i = 0; i < kTiles; ++i) {
    if (!m.compared || m.flag_value[1 + i] == m.token) tiles[i] = 1;
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
