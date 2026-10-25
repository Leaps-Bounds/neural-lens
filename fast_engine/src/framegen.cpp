// framegen.cpp: pictures made between the frames, see framegen.h.
#include "framegen.h"

#include "proto.h"  // write_png, for the test aid

#include <algorithm>
#include <cmath>

#include "fullscreen_vs.h"
#include "gen_hdr_ps.h"
#include "gen_noise_hdr_cs.h"
#include "gen_noise_cs.h"
#include "gen_ps.h"
#include "nv12_cs.h"

using Microsoft::WRL::ComPtr;

namespace {

constexpr DWORD kWaitMs = 2000;
constexpr UINT kBlock = 8;         // the estimator's block, texels of its picture
constexpr UINT kMostSide = 4096;   // the largest picture the estimator takes, measured on an RTX 5090
constexpr UINT kSlotFrame = 0;     // the descriptor heap: the frame for the conversion
constexpr UINT kSlotLuma = 1;      // its two planes
constexpr UINT kSlotChroma = 2;
constexpr UINT kSlotFirst = 3;     // the draw's two pictures and the vectors, fine then the levels'
constexpr UINT kSlotSecond = 4;
constexpr UINT kSlotVectors = 5;
constexpr UINT kSlotLevelVectors = 6;  // one a level, kLevels of them
constexpr UINT kSlotLevelFrame = 6 + FrameGen::kLevels;  // the conversion again at each level's size:
                                                          // the frame, the luma, the chroma, a level at a time
constexpr UINT kSlots = kSlotLevelFrame + 3 * FrameGen::kLevels;

struct Nv12Constants {
  UINT me_w, me_h, fp16, taps;
  float white;  // the SDR white level, units of 80 nits, for a 16-bit frame
};

// The conversion's taps a side for planes out_w wide from a frame frame_w wide: one
// bilinear tap is the mean of a two by two of the frame, right up to twice the planes'
// size; a frame four times as large (the coarse planes, or a fine picture halved above
// kMostSide) takes two taps a side two frame texels apart, the mean of a four by four, and
// so on. Without it the planes alias on the texture the coarse estimate is to see past
static UINT taps_for(UINT frame_w, UINT out_w) {
  const UINT ratio = out_w ? frame_w / out_w : 1;
  return ratio >= 4 ? ratio / 2 : 1;
}

struct GenConstants {
  UINT w, h, vec_w, vec_h;
  float scale, block, part;
  UINT mode;
  UINT levels, adaptive;          // the coarser levels drawn from, 0 for none; adaptive 1, the
                                  // gate's threshold follows the frame's noise
  float white;                    // a 16-bit picture's SDR white in units of 80 nits, 1 for 8-bit
  UINT pad2;                      // keeps the vectors below on 16-byte bounds, as the cbuffer packs them
  UINT lvec_w[4];                 // each level's vectors, and the target's texels per texel of its picture
  UINT lvec_h[4];
  float lscale[4];
};

D3D12_RESOURCE_BARRIER barrier(ID3D12Resource* r, D3D12_RESOURCE_STATES before, D3D12_RESOURCE_STATES after) {
  D3D12_RESOURCE_BARRIER b = {};
  b.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
  b.Transition.pResource = r;
  b.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
  b.Transition.StateBefore = before;
  b.Transition.StateAfter = after;
  return b;
}

bool make_root(ID3D12Device* device, const D3D12_ROOT_PARAMETER* params, UINT count,
               D3D12_SHADER_VISIBILITY sampler_for, const char* what, ComPtr<ID3D12RootSignature>& out,
               std::string& err) {
  D3D12_STATIC_SAMPLER_DESC sampler = {};
  sampler.Filter = D3D12_FILTER_MIN_MAG_MIP_LINEAR;
  sampler.AddressU = sampler.AddressV = sampler.AddressW = D3D12_TEXTURE_ADDRESS_MODE_CLAMP;
  sampler.MaxLOD = D3D12_FLOAT32_MAX;
  sampler.ShaderVisibility = sampler_for;
  D3D12_ROOT_SIGNATURE_DESC d = {};
  d.NumParameters = count;
  d.pParameters = params;
  d.NumStaticSamplers = 1;
  d.pStaticSamplers = &sampler;
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

// The made picture's pipeline state for a target format: the composite's state, with the
// generation's shader, see pipeline.cpp.
bool make_gen_pso(ID3D12Device* device, ID3D12RootSignature* root, DXGI_FORMAT format,
                  ComPtr<ID3D12PipelineState>& out, std::string& err) {
  D3D12_GRAPHICS_PIPELINE_STATE_DESC d = {};
  d.pRootSignature = root;
  d.VS = {g_fullscreen_vs, sizeof(g_fullscreen_vs)};
  // the 16-bit form is its own blob, the gate's encode built in: a runtime switch there
  // stopped the warp's loops unrolling and cost it nearly three times its time
  if (format == DXGI_FORMAT_R16G16B16A16_FLOAT) {
    d.PS = {g_gen_hdr_ps, sizeof(g_gen_hdr_ps)};
  } else {
    d.PS = {g_gen_ps, sizeof(g_gen_ps)};
  }
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
  d.RTVFormats[0] = format;
  d.SampleDesc.Count = 1;
  const HRESULT hr = device->CreateGraphicsPipelineState(&d, IID_PPV_ARGS(&out));
  if (FAILED(hr)) {
    err = strf("the made picture's pipeline state for format %d failed %s", (int)format, hr_text(hr).c_str());
    return false;
  }
  return true;
}

}  // namespace

bool FrameGen::init(Gpu& g, UINT width, UINT height, DXGI_FORMAT target_format, std::string& err) {
  shutdown();
  gpu = &g;
  w = width;
  h = height;
  format = target_format;
  // the estimator's picture: the frame, halved until both sides fit, kept even for NV12
  me_w = w;
  me_h = h;
  while (me_w > kMostSide || me_h > kMostSide) {
    me_w = (me_w + 1) / 2;
    me_h = (me_h + 1) / 2;
  }
  me_w &= ~1u;
  me_h &= ~1u;
  if (me_w < 32 || me_h < 32) {
    err = "the picture is too small for the motion estimator";
    return false;
  }
  vec_w = (me_w + kBlock - 1) / kBlock;
  vec_h = (me_h + kBlock - 1) / kBlock;
  ID3D12Device* device = g.device.Get();

  // ---- the estimator and its queue
  HRESULT hr = g.device.As(&video);
  if (FAILED(hr)) {
    err = "this card has no motion estimator (no video device, " + hr_text(hr) + ")";
    return false;
  }
  D3D12_FEATURE_DATA_VIDEO_MOTION_ESTIMATOR f = {};
  f.InputFormat = DXGI_FORMAT_NV12;
  hr = video->CheckFeatureSupport(D3D12_FEATURE_VIDEO_MOTION_ESTIMATOR, &f, sizeof(f));
  if (FAILED(hr) || !(f.BlockSizeFlags & D3D12_VIDEO_MOTION_ESTIMATOR_SEARCH_BLOCK_SIZE_FLAG_8X8) ||
      !(f.PrecisionFlags & D3D12_VIDEO_MOTION_ESTIMATOR_VECTOR_PRECISION_FLAG_QUARTER_PEL)) {
    err = "this card has no motion estimator for NV12 in blocks of 8";
    return false;
  }
  if (me_w < f.SizeRange.MinWidth || me_h < f.SizeRange.MinHeight || me_w > f.SizeRange.MaxWidth ||
      me_h > f.SizeRange.MaxHeight) {
    err = strf("%ux%u is outside the motion estimator's sizes, %ux%u to %ux%u", me_w, me_h, f.SizeRange.MinWidth,
               f.SizeRange.MinHeight, f.SizeRange.MaxWidth, f.SizeRange.MaxHeight);
    return false;
  }
  D3D12_VIDEO_MOTION_ESTIMATOR_DESC ed = {};
  ed.InputFormat = DXGI_FORMAT_NV12;
  ed.BlockSize = D3D12_VIDEO_MOTION_ESTIMATOR_SEARCH_BLOCK_SIZE_8X8;
  ed.Precision = D3D12_VIDEO_MOTION_ESTIMATOR_VECTOR_PRECISION_QUARTER_PEL;
  ed.SizeRange.MaxWidth = ed.SizeRange.MinWidth = me_w;
  ed.SizeRange.MaxHeight = ed.SizeRange.MinHeight = me_h;
  hr = video->CreateVideoMotionEstimator(&ed, nullptr, IID_PPV_ARGS(&estimator));
  if (FAILED(hr)) {
    err = "the motion estimator failed " + hr_text(hr);
    return false;
  }
  D3D12_VIDEO_MOTION_VECTOR_HEAP_DESC hd = {};
  hd.InputFormat = ed.InputFormat;
  hd.BlockSize = ed.BlockSize;
  hd.Precision = ed.Precision;
  hd.SizeRange = ed.SizeRange;
  hr = video->CreateVideoMotionVectorHeap(&hd, nullptr, IID_PPV_ARGS(&mv_heap));
  if (FAILED(hr)) {
    err = "the motion vector heap failed " + hr_text(hr);
    return false;
  }
  D3D12_COMMAND_QUEUE_DESC qd = {};
  qd.Type = D3D12_COMMAND_LIST_TYPE_VIDEO_ENCODE;
  hr = device->CreateCommandQueue(&qd, IID_PPV_ARGS(&encode_queue));
  if (FAILED(hr)) {
    err = "the video encode queue failed " + hr_text(hr);
    return false;
  }
  encode_queue->SetName(L"framegen encode");
  // the estimates' timestamps, where the encode queue takes them (the video encoding
  // specification asks for timestamp queries on encode lists; probed, never assumed)
  encode_hz = 0;
  if (SUCCEEDED(encode_queue->GetTimestampFrequency(&encode_hz)) && encode_hz > 0) {
    D3D12_QUERY_HEAP_DESC qh = {};
    qh.Type = D3D12_QUERY_HEAP_TYPE_TIMESTAMP;
    qh.Count = 3;
    std::string e;
    void* p = nullptr;
    if (FAILED(device->CreateQueryHeap(&qh, IID_PPV_ARGS(&encode_query_heap))) ||
        !g.make_buffer(3 * 8, D3D12_HEAP_TYPE_READBACK, D3D12_RESOURCE_STATE_COPY_DEST, D3D12_RESOURCE_FLAG_NONE,
                       L"framegen encode stamps", encode_stamps, e) ||
        FAILED(encode_stamps->Map(0, nullptr, &p)) || !p) {
      encode_query_heap.Reset();
      encode_stamps.Reset();
      encode_hz = 0;
    } else {
      memset(p, 0, 3 * 8);
      encode_ticks = (const UINT64*)p;
    }
  } else {
    encode_hz = 0;
  }
  hr = device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_VIDEO_ENCODE, IID_PPV_ARGS(&encode_allocator));
  if (SUCCEEDED(hr)) {
    hr = device->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_VIDEO_ENCODE, encode_allocator.Get(), nullptr,
                                   IID_PPV_ARGS(&encode_list));
  }
  if (FAILED(hr)) {
    err = "the video encode list failed " + hr_text(hr);
    return false;
  }
  encode_list->Close();
  hr = device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&encode_fence));
  if (FAILED(hr)) {
    err = "the encode fence failed " + hr_text(hr);
    return false;
  }
  encode_event = CreateEventW(nullptr, FALSE, FALSE, nullptr);
  if (!encode_event) {
    err = "the encode event could not be made";
    return false;
  }

  // ---- the lists on the engine's queue
  if (!g.make_list(prep_allocator, prep_list, L"framegen prepare", err) ||
      !g.make_list(keep_allocator, keep_list, L"framegen keep", err) ||
      !g.make_list(draw_allocator, draw_list, L"framegen draw", err)) {
    return false;
  }

  // ---- the textures
  for (int i = 0; i < 2; ++i) {
    if (!g.make_texture(DXGI_FORMAT_NV12, me_w, me_h, D3D12_RESOURCE_FLAG_NONE, D3D12_RESOURCE_STATE_COMMON,
                        i ? L"framegen nv12 1" : L"framegen nv12 0", nv[i], err)) {
      return false;
    }
  }
  if (!g.make_texture(DXGI_FORMAT_R8_UNORM, me_w, me_h, D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS,
                      D3D12_RESOURCE_STATE_COMMON, L"framegen luma", luma, err) ||
      !g.make_texture(DXGI_FORMAT_R8G8_UNORM, me_w / 2, me_h / 2, D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS,
                      D3D12_RESOURCE_STATE_COMMON, L"framegen chroma", chroma, err) ||
      !g.make_texture(DXGI_FORMAT_R16G16_SINT, vec_w, vec_h, D3D12_RESOURCE_FLAG_NONE, D3D12_RESOURCE_STATE_COMMON,
                      L"framegen vectors", vectors, err)) {
    return false;
  }
  {
    // the two planes travel through a buffer laid out as the NV12 texture's own copy
    const D3D12_RESOURCE_DESC nd = nv[0]->GetDesc();
    UINT64 bytes = 0;
    device->GetCopyableFootprints(&nd, 0, 2, 0, plane_fp, nullptr, nullptr, &bytes);
    if (!g.make_buffer(bytes, D3D12_HEAP_TYPE_DEFAULT, D3D12_RESOURCE_STATE_COMMON, D3D12_RESOURCE_FLAG_NONE,
                       L"framegen planes", planes, err)) {
      return false;
    }
  }
  // ---- the coarser estimates, each at half the size of the one before, while that is large
  // enough; where one cannot be made the finer ones go on alone, with a line in the log
  level_count = 0;
  {
    const auto make_level = [&](Level& v, int i, std::string& e) -> bool {
      v.vec_w = (v.me_w + kBlock - 1) / kBlock;
      v.vec_h = (v.me_h + kBlock - 1) / kBlock;
      D3D12_VIDEO_MOTION_ESTIMATOR_DESC edl = ed;
      edl.SizeRange.MaxWidth = edl.SizeRange.MinWidth = v.me_w;
      edl.SizeRange.MaxHeight = edl.SizeRange.MinHeight = v.me_h;
      HRESULT h = video->CreateVideoMotionEstimator(&edl, nullptr, IID_PPV_ARGS(&v.estimator));
      D3D12_VIDEO_MOTION_VECTOR_HEAP_DESC hdl = hd;
      hdl.SizeRange = edl.SizeRange;
      if (SUCCEEDED(h)) h = video->CreateVideoMotionVectorHeap(&hdl, nullptr, IID_PPV_ARGS(&v.mv_heap));
      if (FAILED(h)) {
        e = "the motion estimator of level " + std::to_string(i + 1) + " failed " + hr_text(h);
        return false;
      }
      const std::wstring tag = L"framegen level " + std::to_wstring(i + 1);
      for (int k = 0; k < 2; ++k) {
        if (!g.make_texture(DXGI_FORMAT_NV12, v.me_w, v.me_h, D3D12_RESOURCE_FLAG_NONE, D3D12_RESOURCE_STATE_COMMON,
                            (tag + (k ? L" nv12 1" : L" nv12 0")).c_str(), v.nv[k], e)) {
          return false;
        }
      }
      if (!g.make_texture(DXGI_FORMAT_R8_UNORM, v.me_w, v.me_h, D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS,
                          D3D12_RESOURCE_STATE_COMMON, (tag + L" luma").c_str(), v.luma, e) ||
          !g.make_texture(DXGI_FORMAT_R8G8_UNORM, v.me_w / 2, v.me_h / 2, D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS,
                          D3D12_RESOURCE_STATE_COMMON, (tag + L" chroma").c_str(), v.chroma, e) ||
          !g.make_texture(DXGI_FORMAT_R16G16_SINT, v.vec_w, v.vec_h, D3D12_RESOURCE_FLAG_NONE,
                          D3D12_RESOURCE_STATE_COMMON, (tag + L" vectors").c_str(), v.vectors, e)) {
        return false;
      }
      const D3D12_RESOURCE_DESC ndl = v.nv[0]->GetDesc();
      UINT64 bytesl = 0;
      device->GetCopyableFootprints(&ndl, 0, 2, 0, v.plane_fp, nullptr, nullptr, &bytesl);
      return g.make_buffer(bytesl, D3D12_HEAP_TYPE_DEFAULT, D3D12_RESOURCE_STATE_COMMON, D3D12_RESOURCE_FLAG_NONE,
                           (tag + L" planes").c_str(), v.planes, e);
    };
    UINT lw = me_w, lh = me_h;
    for (int i = 0; i < kLevels && i < lab_levels; ++i) {
      lw = (lw / 2) & ~1u;
      lh = (lh / 2) & ~1u;
      if (lw < 32 || lh < 32 || lw < f.SizeRange.MinWidth || lh < f.SizeRange.MinHeight) break;
      levels_[i].me_w = lw;
      levels_[i].me_h = lh;
      std::string e;
      if (!make_level(levels_[i], i, e)) {
        note("framegen: the coarser estimate %d is not made, %s", i + 1, e.c_str());
        drop_levels(i);
        break;
      }
      level_count = i + 1;
    }
  }
  // The two copies of the finished picture are made at the first keep(), not here: the
  // estimator also serves the Look stage's filter and the network's motion vectors, which
  // never read them, and at 6144x2560 they take 126 MB in 8 bits and 252 MB in 16
  {
    // the timer is for the self test's figures: without one the figures are 0
    std::string e;
    if (!timer.init(g, 4, e)) {
      note("framegen: no GPU timer, %s", e.c_str());
      timer.shutdown();
    }
  }

  // ---- the shaders
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
    params[0].Constants.Num32BitValues = sizeof(Nv12Constants) / 4;
    params[1].ParameterType = D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
    params[1].DescriptorTable.NumDescriptorRanges = 2;
    params[1].DescriptorTable.pDescriptorRanges = ranges;
    if (!make_root(device, params, 2, D3D12_SHADER_VISIBILITY_ALL, "NV12 conversion", nv12_root, err)) return false;
    D3D12_COMPUTE_PIPELINE_STATE_DESC d = {};
    d.pRootSignature = nv12_root.Get();
    d.CS = {g_nv12_cs, sizeof(g_nv12_cs)};
    hr = device->CreateComputePipelineState(&d, IID_PPV_ARGS(&nv12_pso));
    if (FAILED(hr)) {
      err = "the NV12 conversion's pipeline state failed " + hr_text(hr);
      return false;
    }
  }
  {
    D3D12_DESCRIPTOR_RANGE range = {};
    range.RangeType = D3D12_DESCRIPTOR_RANGE_TYPE_SRV;
    range.NumDescriptors = 3 + (UINT)kLevels;
    D3D12_ROOT_PARAMETER params[3] = {};
    params[0].ParameterType = D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS;
    params[0].Constants.Num32BitValues = sizeof(GenConstants) / 4;
    params[0].ShaderVisibility = D3D12_SHADER_VISIBILITY_PIXEL;
    params[1].ParameterType = D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
    params[1].DescriptorTable.NumDescriptorRanges = 1;
    params[1].DescriptorTable.pDescriptorRanges = &range;
    params[1].ShaderVisibility = D3D12_SHADER_VISIBILITY_PIXEL;
    params[2].ParameterType = D3D12_ROOT_PARAMETER_TYPE_SRV;   // the noise pass's sum, t6
    params[2].Descriptor.ShaderRegister = 6;
    params[2].ShaderVisibility = D3D12_SHADER_VISIBILITY_PIXEL;
    if (!make_root(device, params, 3, D3D12_SHADER_VISIBILITY_PIXEL, "made picture", gen_root, err)) return false;
    if (!make_gen_pso(device, gen_root.Get(), DXGI_FORMAT_B8G8R8A8_UNORM, gen_pso_8, err) ||
        !make_gen_pso(device, gen_root.Get(), DXGI_FORMAT_R16G16B16A16_FLOAT, gen_pso_16, err)) {
      return false;
    }
    // the noise pass: the same constants and pictures, its sum as a root UAV
    D3D12_ROOT_PARAMETER nparams[3] = {};
    nparams[0] = params[0];
    nparams[0].ShaderVisibility = D3D12_SHADER_VISIBILITY_ALL;
    nparams[1] = params[1];
    nparams[1].ShaderVisibility = D3D12_SHADER_VISIBILITY_ALL;
    nparams[2].ParameterType = D3D12_ROOT_PARAMETER_TYPE_UAV;
    nparams[2].Descriptor.ShaderRegister = 0;
    nparams[2].ShaderVisibility = D3D12_SHADER_VISIBILITY_ALL;
    if (!make_root(device, nparams, 3, D3D12_SHADER_VISIBILITY_ALL, "noise pass", noise_root, err)) return false;
    // one blob for 8-bit pictures and one for 16-bit, whose samples are encoded first, as the warp's
    D3D12_COMPUTE_PIPELINE_STATE_DESC nd = {};
    nd.pRootSignature = noise_root.Get();
    nd.CS = {g_gen_noise_cs, sizeof(g_gen_noise_cs)};
    hr = device->CreateComputePipelineState(&nd, IID_PPV_ARGS(&noise_pso_8));
    if (SUCCEEDED(hr)) {
      nd.CS = {g_gen_noise_hdr_cs, sizeof(g_gen_noise_hdr_cs)};
      hr = device->CreateComputePipelineState(&nd, IID_PPV_ARGS(&noise_pso_16));
    }
    if (FAILED(hr)) {
      err = "the noise pass's pipeline state failed " + hr_text(hr);
      return false;
    }
    // sixteen bins and the count, 68 bytes, in a buffer of 256
    if (!g.make_buffer(256, D3D12_HEAP_TYPE_DEFAULT, D3D12_RESOURCE_STATE_COMMON,
                       D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS, L"framegen noise histogram", noise_acc, err) ||
        !g.make_buffer(256, D3D12_HEAP_TYPE_UPLOAD, D3D12_RESOURCE_STATE_GENERIC_READ, D3D12_RESOURCE_FLAG_NONE,
                       L"framegen noise zeros", noise_zero, err)) {
      return false;
    }
    void* zp = nullptr;
    if (FAILED(noise_zero->Map(0, nullptr, &zp)) || !zp) {
      err = "mapping the noise pass's zeros failed";
      return false;
    }
    memset(zp, 0, 256);
    noise_zero->Unmap(0, nullptr);
  }
  {
    D3D12_DESCRIPTOR_HEAP_DESC d = {};
    d.Type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;
    d.NumDescriptors = kSlots;
    d.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
    hr = device->CreateDescriptorHeap(&d, IID_PPV_ARGS(&heap));
    if (FAILED(hr)) {
      err = "the frame generation's descriptor heap failed " + hr_text(hr);
      return false;
    }
    heap_step = device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
    // the conversion's planes never change
    D3D12_CPU_DESCRIPTOR_HANDLE at = heap->GetCPUDescriptorHandleForHeapStart();
    D3D12_UNORDERED_ACCESS_VIEW_DESC ud = {};
    ud.ViewDimension = D3D12_UAV_DIMENSION_TEXTURE2D;
    ud.Format = DXGI_FORMAT_R8_UNORM;
    at.ptr += kSlotLuma * heap_step;
    device->CreateUnorderedAccessView(luma.Get(), nullptr, &ud, at);
    ud.Format = DXGI_FORMAT_R8G8_UNORM;
    at.ptr += heap_step;
    device->CreateUnorderedAccessView(chroma.Get(), nullptr, &ud, at);
    for (int i = 0; i < level_count; ++i) {
      at = heap->GetCPUDescriptorHandleForHeapStart();
      at.ptr += (kSlotLevelFrame + 3 * i + 1) * heap_step;
      ud.Format = DXGI_FORMAT_R8_UNORM;
      device->CreateUnorderedAccessView(levels_[i].luma.Get(), nullptr, &ud, at);
      ud.Format = DXGI_FORMAT_R8G8_UNORM;
      at.ptr += heap_step;
      device->CreateUnorderedAccessView(levels_[i].chroma.Get(), nullptr, &ud, at);
    }
  }
  cur = 0;
  have = 0;
  shot_dir = env_text(L"LENS_FAST_FRAMEGEN_SHOT");
  shots_left = shot_dir.empty() ? 0 : 3;
  return true;
}

// The test aid: the made picture and the two it came from, read back and written as PNGs.
void FrameGen::shot(const Target& target, ID3D12Resource* first, ID3D12Resource* second) {
  std::string err;
  if (format != DXGI_FORMAT_B8G8R8A8_UNORM || !gpu->wait(draw_value, kWaitMs, err)) return;
  const D3D12_RESOURCE_DESC td = target.texture->GetDesc();
  D3D12_PLACED_SUBRESOURCE_FOOTPRINT fp = {};
  UINT64 bytes = 0;
  gpu->device->GetCopyableFootprints(&td, 0, 1, 0, &fp, nullptr, nullptr, &bytes);
  ID3D12Resource* sources[5] = {target.texture, first, second, luma.Get(), vectors.Get()};
  const wchar_t* names[3] = {L"made", L"first", L"second"};
  D3D12_PLACED_SUBRESOURCE_FOOTPRINT fps[5] = {fp, fp, fp};
  UINT64 sizes[5] = {bytes, bytes, bytes};
  for (int i = 3; i < 5; ++i) {
    const D3D12_RESOURCE_DESC sd = sources[i]->GetDesc();
    gpu->device->GetCopyableFootprints(&sd, 0, 1, 0, &fps[i], nullptr, nullptr, &sizes[i]);
  }
  for (int i = 0; i < 5; ++i) {
    if (!shot_buffer[i] && !gpu->make_buffer(sizes[i], D3D12_HEAP_TYPE_READBACK, D3D12_RESOURCE_STATE_COPY_DEST,
                                             D3D12_RESOURCE_FLAG_NONE, L"framegen shot", shot_buffer[i], err)) {
      return;
    }
  }
  if (FAILED(draw_allocator->Reset()) || FAILED(draw_list->Reset(draw_allocator.Get(), nullptr))) return;
  ID3D12GraphicsCommandList* l = draw_list.Get();
  for (int i = 0; i < 5; ++i) {
    const D3D12_RESOURCE_STATES rest = i == 0 ? D3D12_RESOURCE_STATE_PRESENT : D3D12_RESOURCE_STATE_COMMON;
    transition(l, sources[i], rest, D3D12_RESOURCE_STATE_COPY_SOURCE);
    D3D12_TEXTURE_COPY_LOCATION dst = {};
    dst.pResource = shot_buffer[i].Get();
    dst.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
    dst.PlacedFootprint = fps[i];
    D3D12_TEXTURE_COPY_LOCATION src = {};
    src.pResource = sources[i];
    src.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
    l->CopyTextureRegion(&dst, 0, 0, 0, &src, nullptr);
    transition(l, sources[i], D3D12_RESOURCE_STATE_COPY_SOURCE, rest);
  }
  if (!gpu->execute(l, draw_value, err) || !gpu->wait(draw_value, kWaitMs, err)) return;
  std::vector<uint8_t> rgb((size_t)w * h * 3);
  const int n = 3 - shots_left;
  for (int i = 0; i < 3; ++i) {
    void* p = nullptr;
    const D3D12_RANGE whole = {0, (SIZE_T)bytes};
    if (FAILED(shot_buffer[i]->Map(0, &whole, &p)) || !p) return;
    for (UINT y = 0; y < h; ++y) {
      const uint8_t* in = (const uint8_t*)p + fp.Offset + (size_t)y * fp.Footprint.RowPitch;
      uint8_t* out_row = rgb.data() + (size_t)y * w * 3;
      for (UINT x = 0; x < w; ++x, in += 4, out_row += 3) {
        out_row[0] = in[2];
        out_row[1] = in[1];
        out_row[2] = in[0];
      }
    }
    const D3D12_RANGE none = {0, 0};
    shot_buffer[i]->Unmap(0, &none);
    const std::wstring path = path_join(shot_dir, std::wstring(names[i]) + L"-" + std::to_wstring(n) + L".png");
    if (!write_png(path, rgb.data(), (int)w, (int)h, err)) note("framegen: %s", err.c_str());
  }
  // the luma plane as a grey picture, and the vectors' statistics
  {
    void* p = nullptr;
    const D3D12_RANGE whole = {0, (SIZE_T)sizes[3]};
    if (SUCCEEDED(shot_buffer[3]->Map(0, &whole, &p)) && p) {
      std::vector<uint8_t> grey((size_t)me_w * me_h * 3);
      for (UINT y = 0; y < me_h; ++y) {
        const uint8_t* in = (const uint8_t*)p + fps[3].Offset + (size_t)y * fps[3].Footprint.RowPitch;
        for (UINT x = 0; x < me_w; ++x) grey[((size_t)y * me_w + x) * 3] = grey[((size_t)y * me_w + x) * 3 + 1] = grey[((size_t)y * me_w + x) * 3 + 2] = in[x];
      }
      const D3D12_RANGE none = {0, 0};
      shot_buffer[3]->Unmap(0, &none);
      write_png(path_join(shot_dir, L"luma-" + std::to_wstring(n) + L".png"), grey.data(), (int)me_w, (int)me_h, err);
    }
    const D3D12_RANGE whole_v = {0, (SIZE_T)sizes[4]};
    if (SUCCEEDED(shot_buffer[4]->Map(0, &whole_v, &p)) && p) {
      double sum = 0.0, most = 0.0;
      size_t zero = 0, count = 0;
      long long sx = 0, sy = 0;
      for (UINT y = 0; y < vec_h; ++y) {
        const int16_t* v = (const int16_t*)((const uint8_t*)p + fps[4].Offset + (size_t)y * fps[4].Footprint.RowPitch);
        for (UINT x = 0; x < vec_w; ++x, ++count) {
          const double len = std::sqrt((double)v[2 * x] * v[2 * x] + (double)v[2 * x + 1] * v[2 * x + 1]) / 4.0;
          sum += len;
          if (len > most) most = len;
          if (v[2 * x] == 0 && v[2 * x + 1] == 0) ++zero;
          sx += v[2 * x];
          sy += v[2 * x + 1];
        }
      }
      const D3D12_RANGE none = {0, 0};
      shot_buffer[4]->Unmap(0, &none);
      note("framegen: vectors %ux%u, mean length %.2f texels, longest %.2f, zero %.1f%%, mean (%.2f, %.2f)", vec_w,
           vec_h, sum / (double)count, most, 100.0 * (double)zero / (double)count, (double)sx / (4.0 * count),
           (double)sy / (4.0 * count));
    }
  }
  note("framegen: made picture %d written to %s", n, narrow(shot_dir).c_str());
}

// The two copies of the finished picture, both or neither. Where the second cannot be made
// the first goes too, so keep() never finds a pair half made.
bool FrameGen::make_outs(std::string& err) {
  for (int i = 0; i < 2; ++i) {
    out[i].Reset();
    if (!gpu->make_texture(format, w, h, D3D12_RESOURCE_FLAG_NONE, D3D12_RESOURCE_STATE_COMMON,
                           i ? L"framegen picture 1" : L"framegen picture 0", out[i], err)) {
      out[0].Reset();
      out[1].Reset();
      return false;
    }
  }
  return true;
}

bool FrameGen::retarget(DXGI_FORMAT target_format, std::string& err) {
  if (!gpu) {
    err = "frame generation is not set up";
    return false;
  }
  if (!gpu->wait(prep_value, kWaitMs, err) || !gpu->wait(keep_value, kWaitMs, err) ||
      !gpu->wait(draw_value, kWaitMs, err))
    return false;
  format = target_format;
  have = 0;
  // made again in the new format at the next keep(), see init()
  out[0].Reset();
  out[1].Reset();
  return true;
}

void FrameGen::forget() { have = 0; }

void FrameGen::drop_levels(int from) {
  for (int i = from < 0 ? 0 : from; i < kLevels; ++i) {
    Level& v = levels_[i];
    v.vectors.Reset();
    v.planes.Reset();
    v.luma.Reset();
    v.chroma.Reset();
    v.nv[0].Reset();
    v.nv[1].Reset();
    v.mv_heap.Reset();
    v.estimator.Reset();
    v.me_w = v.me_h = v.vec_w = v.vec_h = 0;
  }
  if (level_count > from) level_count = from < 0 ? 0 : from;
  if (level_count == 0) have_coarse = false;
}

std::string FrameGen::level_text() const {
  std::string s;
  for (int i = 0; i < level_count; ++i) {
    s += (i ? ", " : "") + std::to_string(levels_[i].me_w) + "x" + std::to_string(levels_[i].me_h);
  }
  return s.empty() ? "none" : s;
}

double FrameGen::last_estimate_ms() const {
  if (!encode_ticks || encode_hz == 0) return 0.0;
  const UINT64 a = encode_ticks[0], b = encode_ticks[1];
  return a && b && b >= a ? (double)(b - a) * 1000.0 / (double)encode_hz : 0.0;
}

double FrameGen::last_coarse_estimate_ms() const {
  if (!encode_ticks || encode_hz == 0) return 0.0;
  const UINT64 a = encode_ticks[1], b = encode_ticks[2];
  return a && b && b >= a ? (double)(b - a) * 1000.0 / (double)encode_hz : 0.0;
}

void FrameGen::srv(ID3D12Resource* r, DXGI_FORMAT f, UINT slot) {
  D3D12_SHADER_RESOURCE_VIEW_DESC d = {};
  d.Format = f;
  d.ViewDimension = D3D12_SRV_DIMENSION_TEXTURE2D;
  d.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
  d.Texture2D.MipLevels = 1;
  D3D12_CPU_DESCRIPTOR_HANDLE at = heap->GetCPUDescriptorHandleForHeapStart();
  at.ptr += slot * heap_step;
  gpu->device->CreateShaderResourceView(r, &d, at);
}

D3D12_GPU_DESCRIPTOR_HANDLE FrameGen::gpu_slot(UINT slot) const {
  D3D12_GPU_DESCRIPTOR_HANDLE at = heap->GetGPUDescriptorHandleForHeapStart();
  at.ptr += slot * heap_step;
  return at;
}

// The encode queue has finished the last estimate: true at once nearly always, since an
// estimate takes two milliseconds and frames come further apart than that.
bool FrameGen::wait_encode(std::string& err) {
  if (!encode_fence || encode_fence->GetCompletedValue() >= encode_value) return true;
  encode_fence->SetEventOnCompletion(encode_value, encode_event);
  if (WaitForSingleObject(encode_event, kWaitMs) != WAIT_OBJECT_0) {
    err = strf("the motion estimate did not finish in %lu ms", (unsigned long)kWaitMs);
    return false;
  }
  return true;
}

bool FrameGen::after_fresh(ID3D12Resource* frame, const Target& target, bool& ready, UINT64& read_value,
                           std::string& err) {
  return estimate(frame, ready, read_value, err) && keep(target, err);
}

bool FrameGen::wait_estimate_on_queue(std::string& err) {
  if (!gpu || have < 2) return true;
  const HRESULT hr = gpu->queue->Wait(encode_fence.Get(), encode_value);
  if (FAILED(hr)) {
    err = "the queue's wait for the estimate failed " + hr_text(hr);
    return false;
  }
  return true;
}

bool FrameGen::keep(const Target& target, std::string& err) {
  outs_failed = false;
  if (!gpu) {
    err = "frame generation is not set up";
    return false;
  }
  if (target.format != format && !retarget(target.format, err)) return false;
  if ((!out[0] || !out[1]) && !make_outs(err)) {  // the first keep since init() or a new format
    outs_failed = true;
    return false;
  }
  // the slot written held the picture before the last, which the last draw read as its first
  if (!gpu->wait(keep_value, kWaitMs, err) || !gpu->wait(draw_value, kWaitMs, err)) return false;
  if (FAILED(keep_allocator->Reset()) || FAILED(keep_list->Reset(keep_allocator.Get(), nullptr))) {
    err = "resetting the keep list failed";
    return false;
  }
  ID3D12GraphicsCommandList* l = keep_list.Get();
  transition(l, target.texture, D3D12_RESOURCE_STATE_PRESENT, D3D12_RESOURCE_STATE_COPY_SOURCE);
  transition(l, out[cur].Get(), D3D12_RESOURCE_STATE_COMMON, D3D12_RESOURCE_STATE_COPY_DEST);
  l->CopyResource(out[cur].Get(), target.texture);
  transition(l, out[cur].Get(), D3D12_RESOURCE_STATE_COPY_DEST, D3D12_RESOURCE_STATE_COMMON);
  transition(l, target.texture, D3D12_RESOURCE_STATE_COPY_SOURCE, D3D12_RESOURCE_STATE_PRESENT);
  return gpu->execute(l, keep_value, err);
}

bool FrameGen::estimate(ID3D12Resource* frame, bool& ready, UINT64& read_value, std::string& err) {
  ready = false;
  read_value = 0;
  if (!gpu) {
    err = "frame generation is not set up";
    return false;
  }
  // The slot written now held the frame before the last, which the last estimate read as
  // its reference: that estimate is done, and so is the last conversion.
  if (!gpu->wait(prep_value, kWaitMs, err) || !wait_encode(err)) return false;
  const int next = 1 - cur;

  // ---- the frame to NV12 and the picture to its copy, on the engine's queue behind the draw
  if (FAILED(prep_allocator->Reset()) || FAILED(prep_list->Reset(prep_allocator.Get(), nullptr))) {
    err = "resetting the prepare list failed";
    return false;
  }
  ID3D12GraphicsCommandList* l = prep_list.Get();
  timer.mark(l, 0);
  const D3D12_RESOURCE_DESC fd = frame->GetDesc();
  const bool fp16 = fd.Format == DXGI_FORMAT_R16G16B16A16_FLOAT;
  srv(frame, fd.Format, kSlotFrame);
  const D3D12_RESOURCE_STATES kCommon = D3D12_RESOURCE_STATE_COMMON;
  const D3D12_RESOURCE_STATES kRead = D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
  const D3D12_RESOURCE_STATES kWrite = D3D12_RESOURCE_STATE_UNORDERED_ACCESS;
  const D3D12_RESOURCE_STATES kSource = D3D12_RESOURCE_STATE_COPY_SOURCE;
  const D3D12_RESOURCE_STATES kDest = D3D12_RESOURCE_STATE_COPY_DEST;
  transition(l, frame, kCommon, kRead);
  transition(l, luma.Get(), kCommon, kWrite);
  transition(l, chroma.Get(), kCommon, kWrite);
  ID3D12DescriptorHeap* heaps[] = {heap.Get()};
  l->SetDescriptorHeaps(1, heaps);
  l->SetComputeRootSignature(nv12_root.Get());
  l->SetPipelineState(nv12_pso.Get());
  const Nv12Constants k = {me_w, me_h, fp16 ? 1u : 0u, taps_for((UINT)fd.Width, me_w), sdr_white};
  l->SetComputeRoot32BitConstants(0, sizeof(k) / 4, &k, 0);
  l->SetComputeRootDescriptorTable(1, gpu_slot(kSlotFrame));
  l->Dispatch((me_w + 7) / 8, (me_h + 7) / 8, 1);
  transition(l, frame, kRead, kCommon);
  transition(l, luma.Get(), kWrite, kSource);
  transition(l, chroma.Get(), kWrite, kSource);
  // the planes into the buffer, and from it into the NV12 picture
  transition(l, planes.Get(), kCommon, kDest);
  for (int plane = 0; plane < 2; ++plane) {
    D3D12_TEXTURE_COPY_LOCATION dst = {};
    dst.pResource = planes.Get();
    dst.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
    dst.PlacedFootprint = plane_fp[plane];
    D3D12_TEXTURE_COPY_LOCATION src = {};
    src.pResource = plane ? chroma.Get() : luma.Get();
    src.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
    l->CopyTextureRegion(&dst, 0, 0, 0, &src, nullptr);
  }
  transition(l, planes.Get(), kDest, kSource);
  transition(l, nv[next].Get(), kCommon, kDest);
  for (int plane = 0; plane < 2; ++plane) {
    D3D12_TEXTURE_COPY_LOCATION dst = {};
    dst.pResource = nv[next].Get();
    dst.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
    dst.SubresourceIndex = (UINT)plane;
    D3D12_TEXTURE_COPY_LOCATION src = {};
    src.pResource = planes.Get();
    src.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
    src.PlacedFootprint = plane_fp[plane];
    l->CopyTextureRegion(&dst, 0, 0, 0, &src, nullptr);
  }
  transition(l, nv[next].Get(), kDest, kCommon);
  transition(l, planes.Get(), kSource, kCommon);
  transition(l, luma.Get(), kSource, kCommon);
  transition(l, chroma.Get(), kSource, kCommon);
  const bool do_coarse = level_count > 0 && coarse_on;
  for (int i = 0; do_coarse && i < level_count; ++i) {
    // the same again at each level's size, into its pictures
    Level& v = levels_[i];
    const UINT slot = kSlotLevelFrame + 3 * (UINT)i;
    srv(frame, fd.Format, slot);
    transition(l, frame, kCommon, kRead);
    transition(l, v.luma.Get(), kCommon, kWrite);
    transition(l, v.chroma.Get(), kCommon, kWrite);
    const Nv12Constants kl = {v.me_w, v.me_h, fp16 ? 1u : 0u, taps_for((UINT)fd.Width, v.me_w), sdr_white};
    l->SetComputeRoot32BitConstants(0, sizeof(kl) / 4, &kl, 0);
    l->SetComputeRootDescriptorTable(1, gpu_slot(slot));
    l->Dispatch((v.me_w + 7) / 8, (v.me_h + 7) / 8, 1);
    transition(l, frame, kRead, kCommon);
    transition(l, v.luma.Get(), kWrite, kSource);
    transition(l, v.chroma.Get(), kWrite, kSource);
    transition(l, v.planes.Get(), kCommon, kDest);
    for (int plane = 0; plane < 2; ++plane) {
      D3D12_TEXTURE_COPY_LOCATION dst = {};
      dst.pResource = v.planes.Get();
      dst.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
      dst.PlacedFootprint = v.plane_fp[plane];
      D3D12_TEXTURE_COPY_LOCATION src = {};
      src.pResource = plane ? v.chroma.Get() : v.luma.Get();
      src.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
      l->CopyTextureRegion(&dst, 0, 0, 0, &src, nullptr);
    }
    transition(l, v.planes.Get(), kDest, kSource);
    transition(l, v.nv[next].Get(), kCommon, kDest);
    for (int plane = 0; plane < 2; ++plane) {
      D3D12_TEXTURE_COPY_LOCATION dst = {};
      dst.pResource = v.nv[next].Get();
      dst.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
      dst.SubresourceIndex = (UINT)plane;
      D3D12_TEXTURE_COPY_LOCATION src = {};
      src.pResource = v.planes.Get();
      src.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
      src.PlacedFootprint = v.plane_fp[plane];
      l->CopyTextureRegion(&dst, 0, 0, 0, &src, nullptr);
    }
    transition(l, v.nv[next].Get(), kDest, kCommon);
    transition(l, v.planes.Get(), kSource, kCommon);
    transition(l, v.luma.Get(), kSource, kCommon);
    transition(l, v.chroma.Get(), kSource, kCommon);
  }
  timer.mark(l, 1);
  timer.resolve(l, 0, 2);
  if (!gpu->execute(l, prep_value, err)) return false;
  read_value = prep_value;

  // ---- the estimate, once there is a frame before: the encode queue waits for the
  // conversion, and nothing waits on the CPU
  if (have >= 1) {
    if (FAILED(encode_allocator->Reset()) || FAILED(encode_list->Reset(encode_allocator.Get()))) {
      err = "resetting the encode list failed";
      return false;
    }
    D3D12_RESOURCE_BARRIER in[3] = {
        barrier(nv[cur].Get(), kCommon, D3D12_RESOURCE_STATE_VIDEO_ENCODE_READ),
        barrier(nv[next].Get(), kCommon, D3D12_RESOURCE_STATE_VIDEO_ENCODE_READ),
        barrier(vectors.Get(), kCommon, D3D12_RESOURCE_STATE_VIDEO_ENCODE_WRITE),
    };
    encode_list->ResourceBarrier(3, in);
    if (encode_query_heap) encode_list->EndQuery(encode_query_heap.Get(), D3D12_QUERY_TYPE_TIMESTAMP, 0);
    D3D12_VIDEO_MOTION_ESTIMATOR_OUTPUT mo = {};
    mo.pMotionVectorHeap = mv_heap.Get();
    D3D12_VIDEO_MOTION_ESTIMATOR_INPUT mi = {};
    mi.pInputTexture2D = nv[next].Get();  // the new frame
    mi.pReferenceTexture2D = nv[cur].Get();  // the one before
    encode_list->EstimateMotion(estimator.Get(), &mo, &mi);
    D3D12_RESOLVE_VIDEO_MOTION_VECTOR_HEAP_OUTPUT ro = {};
    ro.pMotionVectorTexture2D = vectors.Get();
    D3D12_RESOLVE_VIDEO_MOTION_VECTOR_HEAP_INPUT ri = {};
    ri.pMotionVectorHeap = mv_heap.Get();
    ri.PixelWidth = me_w;
    ri.PixelHeight = me_h;
    encode_list->ResolveMotionVectorHeap(&ro, &ri);
    if (encode_query_heap) encode_list->EndQuery(encode_query_heap.Get(), D3D12_QUERY_TYPE_TIMESTAMP, 1);
    have_coarse = do_coarse;
    for (int i = 0; do_coarse && i < level_count; ++i) {
      Level& v = levels_[i];
      D3D12_RESOURCE_BARRIER inl[3] = {
          barrier(v.nv[cur].Get(), kCommon, D3D12_RESOURCE_STATE_VIDEO_ENCODE_READ),
          barrier(v.nv[next].Get(), kCommon, D3D12_RESOURCE_STATE_VIDEO_ENCODE_READ),
          barrier(v.vectors.Get(), kCommon, D3D12_RESOURCE_STATE_VIDEO_ENCODE_WRITE),
      };
      encode_list->ResourceBarrier(3, inl);
      D3D12_VIDEO_MOTION_ESTIMATOR_OUTPUT mol = {};
      mol.pMotionVectorHeap = v.mv_heap.Get();
      D3D12_VIDEO_MOTION_ESTIMATOR_INPUT mil = {};
      mil.pInputTexture2D = v.nv[next].Get();
      mil.pReferenceTexture2D = v.nv[cur].Get();
      encode_list->EstimateMotion(v.estimator.Get(), &mol, &mil);
      D3D12_RESOLVE_VIDEO_MOTION_VECTOR_HEAP_OUTPUT rol = {};
      rol.pMotionVectorTexture2D = v.vectors.Get();
      D3D12_RESOLVE_VIDEO_MOTION_VECTOR_HEAP_INPUT ril = {};
      ril.pMotionVectorHeap = v.mv_heap.Get();
      ril.PixelWidth = v.me_w;
      ril.PixelHeight = v.me_h;
      encode_list->ResolveMotionVectorHeap(&rol, &ril);
      D3D12_RESOURCE_BARRIER backl[3] = {
          barrier(v.nv[cur].Get(), D3D12_RESOURCE_STATE_VIDEO_ENCODE_READ, kCommon),
          barrier(v.nv[next].Get(), D3D12_RESOURCE_STATE_VIDEO_ENCODE_READ, kCommon),
          barrier(v.vectors.Get(), D3D12_RESOURCE_STATE_VIDEO_ENCODE_WRITE, kCommon),
      };
      encode_list->ResourceBarrier(3, backl);
    }
    if (encode_query_heap) {
      encode_list->EndQuery(encode_query_heap.Get(), D3D12_QUERY_TYPE_TIMESTAMP, 2);
      encode_list->ResolveQueryData(encode_query_heap.Get(), D3D12_QUERY_TYPE_TIMESTAMP, 0, 3, encode_stamps.Get(), 0);
    }
    D3D12_RESOURCE_BARRIER back[3] = {
        barrier(nv[cur].Get(), D3D12_RESOURCE_STATE_VIDEO_ENCODE_READ, kCommon),
        barrier(nv[next].Get(), D3D12_RESOURCE_STATE_VIDEO_ENCODE_READ, kCommon),
        barrier(vectors.Get(), D3D12_RESOURCE_STATE_VIDEO_ENCODE_WRITE, kCommon),
    };
    encode_list->ResourceBarrier(3, back);
    HRESULT hr = encode_list->Close();
    if (FAILED(hr)) {
      err = "closing the encode list failed " + hr_text(hr);
      return false;
    }
    hr = encode_queue->Wait(gpu->fence.Get(), prep_value);
    if (FAILED(hr)) {
      err = "the encode queue's wait failed " + hr_text(hr);
      return false;
    }
    ID3D12CommandList* lists[] = {encode_list.Get()};
    encode_queue->ExecuteCommandLists(1, lists);
    hr = encode_queue->Signal(encode_fence.Get(), ++encode_value);
    if (FAILED(hr)) {
      err = "signalling the encode fence failed " + hr_text(hr);
      return false;
    }
    ready = true;
  }
  cur = next;
  have = std::min(have + 1, 2);
  return true;
}

bool FrameGen::draw_made(const Target& target, int mode, float part, std::string& err) {
  if (!gpu) {
    err = "frame generation is not set up";
    return false;
  }
  if (have < 2) {
    err = "no estimate to draw a picture from";
    return false;
  }
  if (target.format != format) {
    err = "the target is not in the copies' format";
    return false;
  }
  if (!gpu->wait(draw_value, kWaitMs, err)) return false;
  if (FAILED(draw_allocator->Reset()) || FAILED(draw_list->Reset(draw_allocator.Get(), nullptr))) {
    err = "resetting the draw list failed";
    return false;
  }
  // the estimate is in before the draw reads the vectors: the queue waits on the GPU
  HRESULT hr = gpu->queue->Wait(encode_fence.Get(), encode_value);
  if (FAILED(hr)) {
    err = "the queue's wait for the estimate failed " + hr_text(hr);
    return false;
  }
  ID3D12GraphicsCommandList* l = draw_list.Get();
  timer.mark(l, 2);
  ID3D12Resource* first = out[1 - cur].Get();
  ID3D12Resource* second = out[cur].Get();
  srv(first, format, kSlotFirst);
  srv(second, format, kSlotSecond);
  srv(vectors.Get(), DXGI_FORMAT_R16G16_SINT, kSlotVectors);
  const int use_levels = have_coarse ? level_count : 0;  // the last estimate made them
  for (int i = 0; i < kLevels; ++i) {
    // every slot of the range holds a vectors picture, the fine one where a level is not drawn from
    srv(i < use_levels ? levels_[i].vectors.Get() : vectors.Get(), DXGI_FORMAT_R16G16_SINT,
        kSlotLevelVectors + (UINT)i);
  }
  const D3D12_RESOURCE_STATES kCommon = D3D12_RESOURCE_STATE_COMMON;
  // read by the noise pass (a compute shader) and then by the warp (a pixel shader)
  const D3D12_RESOURCE_STATES kPixel =
      D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE | D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
  transition(l, first, kCommon, kPixel);
  transition(l, second, kCommon, kPixel);
  transition(l, vectors.Get(), kCommon, kPixel);
  for (int i = 0; i < use_levels; ++i) transition(l, levels_[i].vectors.Get(), kCommon, kPixel);
  transition(l, target.texture, D3D12_RESOURCE_STATE_PRESENT, D3D12_RESOURCE_STATE_RENDER_TARGET);
  ID3D12DescriptorHeap* heaps[] = {heap.Get()};
  l->SetDescriptorHeaps(1, heaps);
  GenConstants k = {};
  k.w = w;
  k.h = h;
  k.vec_w = vec_w;
  k.vec_h = vec_h;
  k.scale = (float)w / (float)me_w;
  k.block = (float)kBlock;
  k.part = part;
  k.mode = (UINT)mode;
  k.levels = (UINT)use_levels;
  k.adaptive = lab_fixed_gate ? 0u : 1u;
  k.white = format == DXGI_FORMAT_R16G16B16A16_FLOAT ? sdr_white : 1.0f;
  for (int i = 0; i < 4; ++i) {
    const bool on = i < use_levels;
    k.lvec_w[i] = on ? levels_[i].vec_w : vec_w;
    k.lvec_h[i] = on ? levels_[i].vec_h : vec_h;
    k.lscale[i] = (float)w / (float)(on ? levels_[i].me_w : me_w);
  }
  // the noise pass: the sum zeroed, then one thread a 16x16 block of the target
  transition(l, noise_acc.Get(), kCommon, D3D12_RESOURCE_STATE_COPY_DEST);
  l->CopyBufferRegion(noise_acc.Get(), 0, noise_zero.Get(), 0, 256);
  transition(l, noise_acc.Get(), D3D12_RESOURCE_STATE_COPY_DEST, D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
  l->SetComputeRootSignature(noise_root.Get());
  l->SetPipelineState(format == DXGI_FORMAT_R16G16B16A16_FLOAT ? noise_pso_16.Get() : noise_pso_8.Get());
  l->SetComputeRoot32BitConstants(0, sizeof(k) / 4, &k, 0);
  l->SetComputeRootDescriptorTable(1, gpu_slot(kSlotFirst));
  l->SetComputeRootUnorderedAccessView(2, noise_acc->GetGPUVirtualAddress());
  l->Dispatch(((w + 15) / 16 + 7) / 8, ((h + 15) / 16 + 7) / 8, 1);
  transition(l, noise_acc.Get(), D3D12_RESOURCE_STATE_UNORDERED_ACCESS, D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);
  // the warp
  l->SetGraphicsRootSignature(gen_root.Get());
  l->SetPipelineState(format == DXGI_FORMAT_R16G16B16A16_FLOAT ? gen_pso_16.Get() : gen_pso_8.Get());
  l->SetGraphicsRoot32BitConstants(0, sizeof(k) / 4, &k, 0);
  l->SetGraphicsRootDescriptorTable(1, gpu_slot(kSlotFirst));
  l->SetGraphicsRootShaderResourceView(2, noise_acc->GetGPUVirtualAddress());
  D3D12_VIEWPORT view = {0.0f, 0.0f, (float)w, (float)h, 0.0f, 1.0f};
  D3D12_RECT all = {0, 0, (LONG)w, (LONG)h};
  l->RSSetViewports(1, &view);
  l->RSSetScissorRects(1, &all);
  l->OMSetRenderTargets(1, &target.rtv, FALSE, nullptr);
  l->IASetPrimitiveTopology(D3D_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
  l->DrawInstanced(3, 1, 0, 0);
  transition(l, first, kPixel, kCommon);
  transition(l, second, kPixel, kCommon);
  transition(l, vectors.Get(), kPixel, kCommon);
  for (int i = 0; i < use_levels; ++i) transition(l, levels_[i].vectors.Get(), kPixel, kCommon);
  transition(l, noise_acc.Get(), D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE, kCommon);
  transition(l, target.texture, D3D12_RESOURCE_STATE_RENDER_TARGET, D3D12_RESOURCE_STATE_PRESENT);
  timer.mark(l, 3);
  timer.resolve(l, 2, 2);
  if (!gpu->execute(l, draw_value, err)) return false;
  if (shots_left > 0) {
    shot(target, first, second);
    --shots_left;
  }
  return true;
}

void FrameGen::shutdown() {
  std::string err;
  if (gpu && gpu->device) {
    gpu->wait(prep_value, kWaitMs, err);
    gpu->wait(keep_value, kWaitMs, err);
    gpu->wait(draw_value, kWaitMs, err);
  }
  wait_encode(err);
  gen_pso_8.Reset();
  gen_pso_16.Reset();
  nv12_pso.Reset();
  gen_root.Reset();
  nv12_root.Reset();
  noise_pso_8.Reset();
  noise_pso_16.Reset();
  noise_root.Reset();
  noise_acc.Reset();
  noise_zero.Reset();
  heap.Reset();
  out[0].Reset();
  out[1].Reset();
  vectors.Reset();
  planes.Reset();
  luma.Reset();
  chroma.Reset();
  nv[0].Reset();
  nv[1].Reset();
  drop_levels(0);
  draw_list.Reset();
  draw_allocator.Reset();
  keep_list.Reset();
  keep_allocator.Reset();
  prep_list.Reset();
  prep_allocator.Reset();
  encode_list.Reset();
  encode_allocator.Reset();
  encode_fence.Reset();
  if (encode_stamps && encode_ticks) encode_stamps->Unmap(0, nullptr);
  encode_ticks = nullptr;
  encode_stamps.Reset();
  encode_query_heap.Reset();
  encode_hz = 0;
  encode_queue.Reset();
  mv_heap.Reset();
  estimator.Reset();
  timer.shutdown();
  video.Reset();
  if (encode_event) {
    CloseHandle(encode_event);
    encode_event = nullptr;
  }
  encode_value = prep_value = keep_value = draw_value = 0;
  cur = have = 0;
  gpu = nullptr;
}
