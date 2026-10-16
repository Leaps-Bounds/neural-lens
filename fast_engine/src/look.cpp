// look.cpp: the Look stage, see look.h.
#include "look.h"

#include <algorithm>
#include <cmath>

#include "look_band_cs.h"
#include "look_cs.h"

using Microsoft::WRL::ComPtr;

namespace {

constexpr UINT kSlotBand0 = 0;       // the band shader's table: SRV in, SRV the output copy, UAV six
constexpr UINT kSlotsBand = 8;
constexpr UINT kSlotCompose0 = 8;    // the compose's table: SRV seven, UAV three
constexpr UINT kSlotsCompose = 10;
constexpr UINT kSlots = kSlotsBand + kSlotsCompose;
constexpr float kEps = 0.01f;        // the guided filter's regularisation, stops squared
constexpr double kGap = 0.25;        // the stabiliser's history is dropped after this long without a run
constexpr float kDetailAlpha = 0.15f;

struct BandConstants {
  UINT w, h, hw, hh, pass, r, r_min, r_mid;
  float eps;
  UINT pad0, pad1, pad2;
};

struct ComposeConstants {
  UINT w, h, hw, hh, bands, filter, detail_filter, range_test, history;
  float alpha, tone, detail, halo, halo_bright, max_brighten, max_darken, max_colour;
  UINT vec_w, vec_h;
  float vec_cell, vec_scale;
  UINT pad0, pad1, pad2;
};

bool make_root(ID3D12Device* device, const D3D12_ROOT_PARAMETER* params, UINT count, bool sampler_too,
               const char* what, ComPtr<ID3D12RootSignature>& out, std::string& err) {
  D3D12_STATIC_SAMPLER_DESC sampler = {};
  sampler.Filter = D3D12_FILTER_MIN_MAG_MIP_LINEAR;
  sampler.AddressU = sampler.AddressV = sampler.AddressW = D3D12_TEXTURE_ADDRESS_MODE_CLAMP;
  sampler.MaxLOD = D3D12_FLOAT32_MAX;
  sampler.ShaderVisibility = D3D12_SHADER_VISIBILITY_ALL;
  D3D12_ROOT_SIGNATURE_DESC d = {};
  d.NumParameters = count;
  d.pParameters = params;
  d.NumStaticSamplers = sampler_too ? 1 : 0;
  d.pStaticSamplers = sampler_too ? &sampler : nullptr;
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

void uav_barrier(ID3D12GraphicsCommandList* l, ID3D12Resource* r) {
  D3D12_RESOURCE_BARRIER b = {};
  b.Type = D3D12_RESOURCE_BARRIER_TYPE_UAV;
  b.UAV.pResource = r;
  l->ResourceBarrier(1, &b);
}

}  // namespace

bool Look::init(Gpu& gpu, std::string& err) {
  shutdown();
  gpu_ = &gpu;
  ID3D12Device* device = gpu.device.Get();
  {
    D3D12_DESCRIPTOR_RANGE ranges[2] = {};
    ranges[0].RangeType = D3D12_DESCRIPTOR_RANGE_TYPE_SRV;
    ranges[0].NumDescriptors = 2;
    ranges[0].OffsetInDescriptorsFromTableStart = 0;
    ranges[1].RangeType = D3D12_DESCRIPTOR_RANGE_TYPE_UAV;
    ranges[1].NumDescriptors = 6;
    ranges[1].OffsetInDescriptorsFromTableStart = 2;
    D3D12_ROOT_PARAMETER params[2] = {};
    params[0].ParameterType = D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS;
    params[0].Constants.Num32BitValues = sizeof(BandConstants) / 4;
    params[1].ParameterType = D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
    params[1].DescriptorTable.NumDescriptorRanges = 2;
    params[1].DescriptorTable.pDescriptorRanges = ranges;
    if (!make_root(device, params, 2, false, "look band", band_root_, err)) return false;
    D3D12_COMPUTE_PIPELINE_STATE_DESC d = {};
    d.pRootSignature = band_root_.Get();
    d.CS = {g_look_band_cs, sizeof(g_look_band_cs)};
    const HRESULT hr = device->CreateComputePipelineState(&d, IID_PPV_ARGS(&band_pso_));
    if (FAILED(hr)) {
      err = "the look band pipeline state failed " + hr_text(hr);
      return false;
    }
  }
  {
    D3D12_DESCRIPTOR_RANGE ranges[2] = {};
    ranges[0].RangeType = D3D12_DESCRIPTOR_RANGE_TYPE_SRV;
    ranges[0].NumDescriptors = 7;
    ranges[0].OffsetInDescriptorsFromTableStart = 0;
    ranges[1].RangeType = D3D12_DESCRIPTOR_RANGE_TYPE_UAV;
    ranges[1].NumDescriptors = 3;
    ranges[1].OffsetInDescriptorsFromTableStart = 7;
    D3D12_ROOT_PARAMETER params[2] = {};
    params[0].ParameterType = D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS;
    params[0].Constants.Num32BitValues = sizeof(ComposeConstants) / 4;
    params[1].ParameterType = D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
    params[1].DescriptorTable.NumDescriptorRanges = 2;
    params[1].DescriptorTable.pDescriptorRanges = ranges;
    if (!make_root(device, params, 2, true, "look compose", compose_root_, err)) return false;
    D3D12_COMPUTE_PIPELINE_STATE_DESC d = {};
    d.pRootSignature = compose_root_.Get();
    d.CS = {g_look_cs, sizeof(g_look_cs)};
    const HRESULT hr = device->CreateComputePipelineState(&d, IID_PPV_ARGS(&compose_pso_));
    if (FAILED(hr)) {
      err = "the look compose pipeline state failed " + hr_text(hr);
      return false;
    }
  }
  D3D12_DESCRIPTOR_HEAP_DESC hd = {};
  hd.Type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;
  hd.NumDescriptors = kSlots;
  hd.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
  const HRESULT hr = device->CreateDescriptorHeap(&hd, IID_PPV_ARGS(&heap_));
  if (FAILED(hr)) {
    err = "the look descriptor heap failed " + hr_text(hr);
    return false;
  }
  heap_step_ = device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
  return true;
}

void Look::srv(ID3D12Resource* r, DXGI_FORMAT format, UINT slot) {
  D3D12_SHADER_RESOURCE_VIEW_DESC d = {};
  d.Format = format;
  d.ViewDimension = D3D12_SRV_DIMENSION_TEXTURE2D;
  d.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
  d.Texture2D.MipLevels = 1;
  D3D12_CPU_DESCRIPTOR_HANDLE at = heap_->GetCPUDescriptorHandleForHeapStart();
  at.ptr += slot * heap_step_;
  gpu_->device->CreateShaderResourceView(r, &d, at);  // r null: a null view, which reads as zero
}

void Look::uav(ID3D12Resource* r, DXGI_FORMAT format, UINT slot) {
  D3D12_UNORDERED_ACCESS_VIEW_DESC d = {};
  d.Format = format;
  d.ViewDimension = D3D12_UAV_DIMENSION_TEXTURE2D;
  D3D12_CPU_DESCRIPTOR_HANDLE at = heap_->GetCPUDescriptorHandleForHeapStart();
  at.ptr += slot * heap_step_;
  gpu_->device->CreateUnorderedAccessView(r, nullptr, &d, at);
}

D3D12_GPU_DESCRIPTOR_HANDLE Look::gpu_slot(UINT slot) const {
  D3D12_GPU_DESCRIPTOR_HANDLE at = heap_->GetGPUDescriptorHandleForHeapStart();
  at.ptr += slot * heap_step_;
  return at;
}

bool Look::make_textures(std::string& err) {
  const D3D12_RESOURCE_FLAGS kUav = D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
  const D3D12_RESOURCE_STATES kWrite = D3D12_RESOURCE_STATE_UNORDERED_ACCESS;
  for (int i = 0; i < 2; ++i) {
    if (!gpu_->make_texture(DXGI_FORMAT_R32G32B32A32_FLOAT, hw_, hh_, kUav, kWrite, L"look moments", mom_[i], err) ||
        !gpu_->make_texture(DXGI_FORMAT_R32G32_FLOAT, hw_, hh_, kUav, kWrite, L"look extrema", ext_[i], err) ||
        !gpu_->make_texture(DXGI_FORMAT_R32G32B32A32_FLOAT, hw_, hh_, kUav, kWrite, L"look coefficients", coef_[i],
                            err) ||
        !gpu_->make_texture(DXGI_FORMAT_R16G16B16A16_FLOAT, w_, h_, kUav, kWrite, L"look history a", hist_a_[i], err) ||
        !gpu_->make_texture(DXGI_FORMAT_R16G16_FLOAT, w_, h_, kUav, kWrite, L"look history b", hist_b_[i], err)) {
      return false;
    }
    hist_state_[i] = kWrite;
  }
  if (!gpu_->make_texture(DXGI_FORMAT_R8G8B8A8_UNORM, w_, h_, D3D12_RESOURCE_FLAG_NONE, D3D12_RESOURCE_STATE_COPY_DEST,
                          L"look output copy", src_, err)) {
    return false;
  }
  // the band shader's fixed views: the six half-size textures
  uav(mom_[0].Get(), DXGI_FORMAT_R32G32B32A32_FLOAT, kSlotBand0 + 2);
  uav(mom_[1].Get(), DXGI_FORMAT_R32G32B32A32_FLOAT, kSlotBand0 + 3);
  uav(ext_[0].Get(), DXGI_FORMAT_R32G32_FLOAT, kSlotBand0 + 4);
  uav(ext_[1].Get(), DXGI_FORMAT_R32G32_FLOAT, kSlotBand0 + 5);
  uav(coef_[0].Get(), DXGI_FORMAT_R32G32B32A32_FLOAT, kSlotBand0 + 6);
  uav(coef_[1].Get(), DXGI_FORMAT_R32G32B32A32_FLOAT, kSlotBand0 + 7);
  // the compose's fixed views: the finished coefficients and extrema, and the output copy
  srv(coef_[0].Get(), DXGI_FORMAT_R32G32B32A32_FLOAT, kSlotCompose0 + 1);
  srv(ext_[0].Get(), DXGI_FORMAT_R32G32_FLOAT, kSlotCompose0 + 2);
  srv(src_.Get(), DXGI_FORMAT_R8G8B8A8_UNORM, kSlotCompose0 + 6);
  srv(src_.Get(), DXGI_FORMAT_R8G8B8A8_UNORM, kSlotBand0 + 1);
  return true;
}

bool Look::resize(UINT w, UINT h, std::string& err) {
  if (!gpu_) {
    err = "the look is not set up";
    return false;
  }
  for (int i = 0; i < 2; ++i) {
    mom_[i].Reset();
    ext_[i].Reset();
    coef_[i].Reset();
    hist_a_[i].Reset();
    hist_b_[i].Reset();
  }
  src_.Reset();
  w_ = w;
  h_ = h;
  hw_ = (w + 1) / 2;
  hh_ = (h + 1) / 2;
  forget();
  return make_textures(err);
}

void Look::forget() {
  history_ = false;
  history_kind_ = 0;
}

void Look::set_motion(ID3D12Resource* vectors, UINT vec_w, UINT vec_h, float cell_work_texels, float unit_work_texels) {
  vectors_ = vectors;
  vec_w_ = vec_w;
  vec_h_ = vec_h;
  vec_cell_ = cell_work_texels;
  vec_unit_ = unit_work_texels;
}

bool Look::record(ID3D12GraphicsCommandList* l, ID3D12Resource* in, ID3D12Resource* out, UINT w, UINT h,
                  const NrLook& look, bool reset, double now, std::string& err) {
  ran_ = ran_bands_ = false;
  if (!gpu_) {
    err = "the look is not set up";
    return false;
  }
  if (!look.active()) {
    forget();
    return true;
  }
  if (w != w_ || h != h_ || !src_) {
    if (!resize(w, h, err)) return false;
  }
  const D3D12_RESOURCE_STATES kRead = D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
  const D3D12_RESOURCE_STATES kWrite = D3D12_RESOURCE_STATE_UNORDERED_ACCESS;
  const D3D12_RESOURCE_STATES kCommon = D3D12_RESOURCE_STATE_COMMON;

  // ---- the output as the network left it, copied, so the compose reads neighbours as they were
  uav_barrier(l, out);
  transition(l, out, kWrite, D3D12_RESOURCE_STATE_COPY_SOURCE);
  l->CopyResource(src_.Get(), out);
  transition(l, out, D3D12_RESOURCE_STATE_COPY_SOURCE, kWrite);
  transition(l, src_.Get(), D3D12_RESOURCE_STATE_COPY_DEST, kRead);

  ID3D12DescriptorHeap* heaps[] = {heap_.Get()};
  l->SetDescriptorHeaps(1, heaps);

  // ---- the band split, five passes over the half size
  const bool bands = look.bands();
  if (bands) {
    srv(in, DXGI_FORMAT_R8G8B8A8_UNORM, kSlotBand0);
    const UINT r = (UINT)std::clamp((long)std::lround(look.detail_radius / 100.0f * (float)h / 2.0f), 1L, 64L);
    BandConstants k = {};
    k.w = w;
    k.h = h;
    k.hw = hw_;
    k.hh = hh_;
    k.r = r;
    k.r_min = std::min(4u * r, 48u);
    k.r_mid = std::min(6u * r, 64u);
    k.eps = kEps;
    l->SetComputeRootSignature(band_root_.Get());
    l->SetPipelineState(band_pso_.Get());
    l->SetComputeRootDescriptorTable(1, gpu_slot(kSlotBand0));
    ID3D12Resource* written[5][2] = {{mom_[0].Get(), ext_[0].Get()}, {mom_[1].Get(), ext_[1].Get()},
                                     {coef_[0].Get(), ext_[0].Get()}, {coef_[1].Get(), nullptr},
                                     {coef_[0].Get(), nullptr}};
    for (UINT pass = 0; pass < 5; ++pass) {
      k.pass = pass;
      l->SetComputeRoot32BitConstants(0, sizeof(k) / 4, &k, 0);
      l->Dispatch((hw_ + 7) / 8, (hh_ + 7) / 8, 1);
      for (ID3D12Resource* t : written[pass]) {
        if (t) uav_barrier(l, t);
      }
    }
    ran_bands_ = true;
  }

  // ---- the compose
  ComposeConstants k = {};
  k.w = w;
  k.h = h;
  k.hw = hw_;
  k.hh = hh_;
  k.bands = bands ? 1u : 0u;
  k.tone = look.tone;
  k.detail = look.detail;
  k.halo = look.halo;
  k.halo_bright = look.halo_bright;
  k.max_brighten = look.max_brighten;
  k.max_darken = look.max_darken;
  k.max_colour = look.max_colour;
  // the filter: the stabiliser's own, or detail stability, which it replaces when on
  int kind = 0;
  if (look.stabilize != 0) {
    kind = 1;
    k.filter = (look.stabilize == 2 && vectors_) ? 2u : 1u;
    k.detail_filter = look.stabilize_detail ? 1u : 0u;
    k.range_test = 0;
    double dt = history_ ? now - last_now_ : 1.0 / 60.0;
    dt = std::clamp(dt, 1.0 / 240.0, kGap);
    k.alpha = 1.0f - (float)std::exp(-dt / std::max(look.stabilize_ms * 1e-3, 1e-3));
  } else if (look.detail_stability != 1) {
    kind = 2;
    k.filter = vectors_ ? 2u : 1u;
    k.detail_filter = 1;
    k.range_test = 1;
    k.alpha = kDetailAlpha;
  }
  bool history = history_ && !reset && kind != 0 && history_kind_ == kind;
  if (kind == 1 && history && now - last_now_ > kGap) history = false;
  k.history = history ? 1u : 0u;
  const int prev = ping_, next = 1 - ping_;
  if (kind != 0) {
    if (hist_state_[prev] != kRead) {
      transition(l, hist_a_[prev].Get(), hist_state_[prev], kRead);
      transition(l, hist_b_[prev].Get(), hist_state_[prev], kRead);
      hist_state_[prev] = kRead;
    }
    if (hist_state_[next] != kWrite) {
      transition(l, hist_a_[next].Get(), hist_state_[next], kWrite);
      transition(l, hist_b_[next].Get(), hist_state_[next], kWrite);
      hist_state_[next] = kWrite;
    }
  }
  const bool motion = k.filter == 2u;
  if (motion) {
    k.vec_w = vec_w_;
    k.vec_h = vec_h_;
    k.vec_cell = vec_cell_;
    k.vec_scale = vec_unit_;
    transition(l, vectors_, kCommon, kRead);
  }
  srv(in, DXGI_FORMAT_R8G8B8A8_UNORM, kSlotCompose0);
  srv(kind != 0 ? hist_a_[prev].Get() : nullptr, DXGI_FORMAT_R16G16B16A16_FLOAT, kSlotCompose0 + 3);
  srv(kind != 0 ? hist_b_[prev].Get() : nullptr, DXGI_FORMAT_R16G16_FLOAT, kSlotCompose0 + 4);
  srv(motion ? vectors_ : nullptr, DXGI_FORMAT_R16G16_SINT, kSlotCompose0 + 5);
  uav(out, DXGI_FORMAT_R8G8B8A8_UNORM, kSlotCompose0 + 7);
  uav(kind != 0 ? hist_a_[next].Get() : nullptr, DXGI_FORMAT_R16G16B16A16_FLOAT, kSlotCompose0 + 8);
  uav(kind != 0 ? hist_b_[next].Get() : nullptr, DXGI_FORMAT_R16G16_FLOAT, kSlotCompose0 + 9);
  l->SetComputeRootSignature(compose_root_.Get());
  l->SetPipelineState(compose_pso_.Get());
  l->SetComputeRoot32BitConstants(0, sizeof(k) / 4, &k, 0);
  l->SetComputeRootDescriptorTable(1, gpu_slot(kSlotCompose0));
  l->Dispatch((w + 7) / 8, (h + 7) / 8, 1);
  uav_barrier(l, out);
  if (motion) transition(l, vectors_, kRead, kCommon);
  transition(l, src_.Get(), kRead, D3D12_RESOURCE_STATE_COPY_DEST);

  if (kind != 0) {
    ping_ = next;
    history_ = true;
    history_kind_ = kind;
  } else {
    forget();
  }
  last_now_ = now;
  ran_ = true;
  return true;
}

void Look::shutdown() {
  for (int i = 0; i < 2; ++i) {
    mom_[i].Reset();
    ext_[i].Reset();
    coef_[i].Reset();
    hist_a_[i].Reset();
    hist_b_[i].Reset();
  }
  src_.Reset();
  heap_.Reset();
  band_pso_.Reset();
  compose_pso_.Reset();
  band_root_.Reset();
  compose_root_.Reset();
  w_ = h_ = hw_ = hh_ = 0;
  forget();
  vectors_ = nullptr;
  gpu_ = nullptr;
}
