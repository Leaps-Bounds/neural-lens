// edges.cpp, the edge detector, see edges.h.
#include "edges.h"

#include "edge_cut_cs.h"
#include "edge_grow_cs.h"
#include "edge_mark_cs.h"

#include <cstring>

using Microsoft::WRL::ComPtr;

namespace {

// Each context has a table for each pass, an SRV and two UAVs: the mark's (the flow, the marks,
// the counts), the largest across's (the marks, the across maxima, the counts) and the largest
// down's (the across maxima, the zone, the counts).
constexpr UINT kSlotsPerTable = 3;
constexpr UINT kTables = 3;
constexpr UINT kSlotsPerContext = kSlotsPerTable * kTables;
constexpr UINT kSlots = kSlotsPerContext * (UINT)Edges::kContexts;
// Then a table for the cut for each draw context, after the detect's: the zone's SRV, the
// field's UAV and a null UAV in the root signature's second UAV, which the cut does not read.
constexpr UINT kCutSlot0 = kSlots;
constexpr UINT kCutSlots = kSlotsPerTable * (UINT)Edges::kCutContexts;
// Two timestamps a draw context round the cut.
constexpr UINT kCutTimes = 2;
// Each context's two counts, 256 bytes apart as copies like them.
constexpr UINT kCountStride = 256;
constexpr UINT kCountBytes = 8;
// Four timestamps a context: the start, after the mark, after the largest across, the end.
constexpr UINT kTimesPerContext = 4;
// The groups of edge_grow_cs.hlsl, which takes 64 texels of a line a group.
constexpr UINT kGrowGroup = 64;

// As the shaders declare them.
struct MarkConstants {
  UINT w, h, me_w, me_h, cells_w, crop_w, crop_h, step, border, count, unused0, unused1;
};
struct GrowConstants {
  UINT w, h, down, border, limit, count, unused0, unused1;
};
struct CutConstants {
  UINT w, h, unused0, unused1;
};
static_assert(sizeof(GrowConstants) <= sizeof(MarkConstants));
static_assert(sizeof(CutConstants) <= sizeof(MarkConstants));

bool make_root(ID3D12Device* device, const D3D12_ROOT_PARAMETER* params, UINT count, ComPtr<ID3D12RootSignature>& out,
               std::string& err) {
  D3D12_ROOT_SIGNATURE_DESC d = {};
  d.NumParameters = count;
  d.pParameters = params;
  ComPtr<ID3DBlob> blob, problem;
  HRESULT hr = D3D12SerializeRootSignature(&d, D3D_ROOT_SIGNATURE_VERSION_1, &blob, &problem);
  if (FAILED(hr) || !blob) {
    err = "the edge detector's root signature did not serialise " + hr_text(hr);
    return false;
  }
  hr = device->CreateRootSignature(0, blob->GetBufferPointer(), blob->GetBufferSize(), IID_PPV_ARGS(&out));
  if (FAILED(hr)) {
    err = "the edge detector's root signature failed " + hr_text(hr);
    return false;
  }
  return true;
}

}  // namespace

void Edges::interior_of(UINT w, UINT h, UINT& interior, UINT& limit) {
  interior = limit = 0;
  if (w <= 2 * kBorder || h <= 2 * kBorder) return;
  const unsigned long long n = (unsigned long long)(w - 2 * kBorder) * (unsigned long long)(h - 2 * kBorder);
  interior = (UINT)n;
  limit = (UINT)(n * kGuardPercent / 100ull);
}

bool Edges::init(Gpu& gpu, std::string& err) {
  shutdown();
  gpu_ = &gpu;
  ID3D12Device* device = gpu.device.Get();
  // one root signature for both shaders, the constants and a table of one SRV and two UAVs
  {
    D3D12_DESCRIPTOR_RANGE ranges[2] = {};
    ranges[0].RangeType = D3D12_DESCRIPTOR_RANGE_TYPE_SRV;
    ranges[0].NumDescriptors = 1;
    ranges[0].OffsetInDescriptorsFromTableStart = 0;
    ranges[1].RangeType = D3D12_DESCRIPTOR_RANGE_TYPE_UAV;
    ranges[1].NumDescriptors = 2;
    ranges[1].OffsetInDescriptorsFromTableStart = 1;
    D3D12_ROOT_PARAMETER params[2] = {};
    params[0].ParameterType = D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS;
    params[0].Constants.Num32BitValues = sizeof(MarkConstants) / 4;
    params[1].ParameterType = D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
    params[1].DescriptorTable.NumDescriptorRanges = 2;
    params[1].DescriptorTable.pDescriptorRanges = ranges;
    if (!make_root(device, params, 2, root_, err)) return false;
  }
  {
    D3D12_COMPUTE_PIPELINE_STATE_DESC d = {};
    d.pRootSignature = root_.Get();
    d.CS = {g_edge_mark_cs, sizeof(g_edge_mark_cs)};
    HRESULT hr = device->CreateComputePipelineState(&d, IID_PPV_ARGS(&mark_pso_));
    if (FAILED(hr)) {
      err = "the edge mark pipeline state failed " + hr_text(hr);
      return false;
    }
    d.CS = {g_edge_grow_cs, sizeof(g_edge_grow_cs)};
    hr = device->CreateComputePipelineState(&d, IID_PPV_ARGS(&grow_pso_));
    if (FAILED(hr)) {
      err = "the edge grow pipeline state failed " + hr_text(hr);
      return false;
    }
    d.CS = {g_edge_cut_cs, sizeof(g_edge_cut_cs)};
    hr = device->CreateComputePipelineState(&d, IID_PPV_ARGS(&cut_pso_));
    if (FAILED(hr)) {
      err = "the edge cut pipeline state failed " + hr_text(hr);
      return false;
    }
  }
  D3D12_DESCRIPTOR_HEAP_DESC hd = {};
  hd.Type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;
  hd.NumDescriptors = kSlots + kCutSlots;
  hd.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
  HRESULT hr = device->CreateDescriptorHeap(&hd, IID_PPV_ARGS(&heap_));
  if (FAILED(hr)) {
    err = "the edge detector's descriptor heap failed " + hr_text(hr);
    return false;
  }
  heap_step_ = device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
  const UINT64 bytes = (UINT64)kCountStride * kContexts;
  if (!gpu.make_buffer(bytes, D3D12_HEAP_TYPE_DEFAULT, D3D12_RESOURCE_STATE_COMMON,
                       D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS, L"edge counts", counts_, err) ||
      !gpu.make_buffer(kCountStride, D3D12_HEAP_TYPE_UPLOAD, D3D12_RESOURCE_STATE_GENERIC_READ,
                       D3D12_RESOURCE_FLAG_NONE, L"edge counts zeros", zeros_, err) ||
      !gpu.make_buffer(bytes, D3D12_HEAP_TYPE_READBACK, D3D12_RESOURCE_STATE_COPY_DEST, D3D12_RESOURCE_FLAG_NONE,
                       L"edge counts readback", back_, err)) {
    return false;
  }
  void* p = nullptr;
  const D3D12_RANGE none = {0, 0};
  if (FAILED(zeros_->Map(0, &none, &p)) || !p) {
    err = "mapping the edge counts' zeros failed";
    return false;
  }
  memset(p, 0, kCountStride);
  zeros_->Unmap(0, nullptr);
  p = nullptr;
  if (FAILED(back_->Map(0, nullptr, &p)) || !p) {
    err = "mapping the edge counts' readback failed";
    return false;
  }
  memset(p, 0, (size_t)bytes);
  back_bytes_ = (const uint8_t*)p;
  if (!timer_.init(gpu, kTimesPerContext * kContexts, err)) return false;
  if (!cut_timer_.init(gpu, kCutTimes * kCutContexts, err)) return false;
  return true;
}

D3D12_CPU_DESCRIPTOR_HANDLE Edges::cpu_slot(UINT slot) const {
  D3D12_CPU_DESCRIPTOR_HANDLE at = heap_->GetCPUDescriptorHandleForHeapStart();
  at.ptr += (SIZE_T)slot * heap_step_;
  return at;
}

D3D12_GPU_DESCRIPTOR_HANDLE Edges::gpu_slot(UINT slot) const {
  D3D12_GPU_DESCRIPTOR_HANDLE at = heap_->GetGPUDescriptorHandleForHeapStart();
  at.ptr += (UINT64)slot * heap_step_;
  return at;
}

void Edges::srv_texture(ID3D12Resource* r, UINT slot) {
  D3D12_SHADER_RESOURCE_VIEW_DESC d = {};
  d.Format = DXGI_FORMAT_R8_UINT;
  d.ViewDimension = D3D12_SRV_DIMENSION_TEXTURE2D;
  d.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
  d.Texture2D.MipLevels = 1;
  gpu_->device->CreateShaderResourceView(r, &d, cpu_slot(slot));
}

void Edges::uav_texture(ID3D12Resource* r, UINT slot) {
  D3D12_UNORDERED_ACCESS_VIEW_DESC d = {};
  d.Format = DXGI_FORMAT_R8_UINT;
  d.ViewDimension = D3D12_UAV_DIMENSION_TEXTURE2D;
  gpu_->device->CreateUnorderedAccessView(r, nullptr, &d, cpu_slot(slot));
}

void Edges::uav_counts(UINT slot) {
  D3D12_UNORDERED_ACCESS_VIEW_DESC d = {};
  d.Format = DXGI_FORMAT_R32_TYPELESS;
  d.ViewDimension = D3D12_UAV_DIMENSION_BUFFER;
  d.Buffer.NumElements = kCountStride * kContexts / 4;
  d.Buffer.Flags = D3D12_BUFFER_UAV_FLAG_RAW;
  gpu_->device->CreateUnorderedAccessView(counts_.Get(), nullptr, &d, cpu_slot(slot));
}

void Edges::record(ID3D12GraphicsCommandList* l, int index, const EdgeFlow& flow, ID3D12Resource* mark,
                   ID3D12Resource* across, ID3D12Resource* zone, UINT w, UINT h) {
  const D3D12_RESOURCE_STATES kCommon = D3D12_RESOURCE_STATE_COMMON;
  const D3D12_RESOURCE_STATES kRead = D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
  const D3D12_RESOURCE_STATES kWrite = D3D12_RESOURCE_STATE_UNORDERED_ACCESS;
  const UINT base = kSlotsPerContext * (UINT)index;
  const UINT count_at = kCountStride * (UINT)index;
  const UINT time0 = kTimesPerContext * (UINT)index;
  EdgeCounts& c = last_[index];
  c = EdgeCounts();
  c.w = w;
  c.h = h;
  interior_of(w, h, c.interior, c.limit);

  // the three tables of this context
  {
    D3D12_SHADER_RESOURCE_VIEW_DESC d = {};
    d.Format = DXGI_FORMAT_R16G16_SINT;
    d.ViewDimension = D3D12_SRV_DIMENSION_BUFFER;
    d.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
    d.Buffer.NumElements = flow.cells_w * flow.cells_h;
    gpu_->device->CreateShaderResourceView(flow.flow, &d, cpu_slot(base));
  }
  uav_texture(mark, base + 1);
  uav_counts(base + 2);
  srv_texture(mark, base + kSlotsPerTable);
  uav_texture(across, base + kSlotsPerTable + 1);
  uav_counts(base + kSlotsPerTable + 2);
  srv_texture(across, base + 2 * kSlotsPerTable);
  uav_texture(zone, base + 2 * kSlotsPerTable + 1);
  uav_counts(base + 2 * kSlotsPerTable + 2);

  timer_.mark(l, time0);
  // the counts cleared
  transition(l, counts_.Get(), kCommon, D3D12_RESOURCE_STATE_COPY_DEST);
  l->CopyBufferRegion(counts_.Get(), count_at, zeros_.Get(), 0, kCountBytes);
  transition(l, counts_.Get(), D3D12_RESOURCE_STATE_COPY_DEST, kWrite);

  ID3D12DescriptorHeap* heaps[] = {heap_.Get()};
  l->SetDescriptorHeaps(1, heaps);
  l->SetComputeRootSignature(root_.Get());

  // the mark
  transition(l, flow.flow, kCommon, kRead);
  transition(l, mark, kRead, kWrite);
  {
    MarkConstants k = {};
    k.w = w;
    k.h = h;
    k.me_w = flow.me_w;
    k.me_h = flow.me_h;
    k.cells_w = flow.cells_w;
    k.crop_w = flow.crop_w;
    k.crop_h = flow.crop_h;
    k.step = kStep;
    k.border = kBorder;
    k.count = count_at;
    l->SetPipelineState(mark_pso_.Get());
    l->SetComputeRoot32BitConstants(0, sizeof(k) / 4, &k, 0);
    l->SetComputeRootDescriptorTable(1, gpu_slot(base));
    l->Dispatch((w + 7) / 8, (h + 7) / 8, 1);
  }
  timer_.mark(l, time0 + 1);
  transition(l, mark, kWrite, kRead);
  transition(l, flow.flow, kRead, kCommon);
  {
    // the mark's additions to the count done before the pass down reads it
    D3D12_RESOURCE_BARRIER b = {};
    b.Type = D3D12_RESOURCE_BARRIER_TYPE_UAV;
    b.UAV.pResource = counts_.Get();
    l->ResourceBarrier(1, &b);
  }

  // the largest across, then down with I and the guard
  l->SetPipelineState(grow_pso_.Get());
  GrowConstants k = {};
  k.w = w;
  k.h = h;
  k.border = kBorder;
  k.limit = c.limit;
  k.count = count_at;
  transition(l, across, kRead, kWrite);
  k.down = 0;
  l->SetComputeRoot32BitConstants(0, sizeof(k) / 4, &k, 0);
  l->SetComputeRootDescriptorTable(1, gpu_slot(base + kSlotsPerTable));
  l->Dispatch((w + kGrowGroup - 1) / kGrowGroup, h, 1);
  timer_.mark(l, time0 + 2);
  transition(l, across, kWrite, kRead);
  transition(l, zone, kRead, kWrite);
  k.down = 1;
  l->SetComputeRoot32BitConstants(0, sizeof(k) / 4, &k, 0);
  l->SetComputeRootDescriptorTable(1, gpu_slot(base + 2 * kSlotsPerTable));
  l->Dispatch((h + kGrowGroup - 1) / kGrowGroup, w, 1);
  timer_.mark(l, time0 + 3);
  transition(l, zone, kWrite, kRead);

  // the counts out for the CPU
  transition(l, counts_.Get(), kWrite, D3D12_RESOURCE_STATE_COPY_SOURCE);
  l->CopyBufferRegion(back_.Get(), count_at, counts_.Get(), count_at, kCountBytes);
  transition(l, counts_.Get(), D3D12_RESOURCE_STATE_COPY_SOURCE, kCommon);
  timer_.resolve(l, time0, kTimesPerContext);
}

EdgeCounts Edges::counts(int index) const {
  if (index < 0 || index >= kContexts || !back_bytes_) return EdgeCounts();
  EdgeCounts c = last_[index];
  UINT v[2] = {};
  memcpy(v, back_bytes_ + (size_t)kCountStride * (size_t)index, sizeof v);
  c.marked = v[0];
  c.zoned = v[1];
  c.guarded = c.marked > c.limit;
  const UINT time0 = kTimesPerContext * (UINT)index;
  if (gpu_) c.ms = timer_.ms(*gpu_, time0, time0 + 3);
  return c;
}

void Edges::record_cut(ID3D12GraphicsCommandList* l, int index, ID3D12Resource* zone, ID3D12Resource* field, UINT w,
                       UINT h) {
  const D3D12_RESOURCE_STATES kRead = D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
  const D3D12_RESOURCE_STATES kWrite = D3D12_RESOURCE_STATE_UNORDERED_ACCESS;
  const UINT base = kCutSlot0 + kSlotsPerTable * (UINT)index;
  const UINT time0 = kCutTimes * (UINT)index;
  // this draw context's table, written now that its last list has finished
  srv_texture(zone, base);
  {
    D3D12_UNORDERED_ACCESS_VIEW_DESC d = {};
    d.Format = DXGI_FORMAT_R16G16_FLOAT;
    d.ViewDimension = D3D12_UAV_DIMENSION_TEXTURE2D;
    gpu_->device->CreateUnorderedAccessView(field, nullptr, &d, cpu_slot(base + 1));
    D3D12_UNORDERED_ACCESS_VIEW_DESC none = {};
    none.Format = DXGI_FORMAT_R8_UINT;
    none.ViewDimension = D3D12_UAV_DIMENSION_TEXTURE2D;
    gpu_->device->CreateUnorderedAccessView(nullptr, nullptr, &none, cpu_slot(base + 2));
  }
  cut_timer_.mark(l, time0);
  transition(l, field, kRead, kWrite);
  ID3D12DescriptorHeap* heaps[] = {heap_.Get()};
  l->SetDescriptorHeaps(1, heaps);
  l->SetComputeRootSignature(root_.Get());
  l->SetPipelineState(cut_pso_.Get());
  CutConstants k = {};
  k.w = w;
  k.h = h;
  l->SetComputeRoot32BitConstants(0, sizeof(k) / 4, &k, 0);
  l->SetComputeRootDescriptorTable(1, gpu_slot(base));
  l->Dispatch((w + 7) / 8, (h + 7) / 8, 1);
  transition(l, field, kWrite, kRead);
  cut_timer_.mark(l, time0 + 1);
  cut_timer_.resolve(l, time0, kCutTimes);
}

double Edges::cut_ms(int index) const {
  if (!gpu_ || index < 0 || index >= kCutContexts) return 0.0;
  const UINT time0 = kCutTimes * (UINT)index;
  return cut_timer_.ms(*gpu_, time0, time0 + 1);
}

void Edges::shutdown() {
  if (back_ && back_bytes_) back_->Unmap(0, nullptr);
  back_bytes_ = nullptr;
  timer_.shutdown();
  cut_timer_.shutdown();
  back_.Reset();
  zeros_.Reset();
  counts_.Reset();
  heap_.Reset();
  cut_pso_.Reset();
  grow_pso_.Reset();
  mark_pso_.Reset();
  root_.Reset();
  gpu_ = nullptr;
}
