// selftest.cpp: the pipeline run on a picture from a file, with no window and no capture.
// See selftest.h.
//
// The picture is uploaded as if it were a captured frame and taken through the pipeline
// exactly as the loop does it: ingest, then render into a target of full size that stands
// in for the back buffer. What it proves and measures:
//
//   compare   the same picture in two textures reads unchanged, and a copy with one texel
//             changed by one level reads changed, wherever the texel is
//   timing    120 frames to warm up, 300 timed: GPU milliseconds of each stage from
//             timestamp queries, and what the calls cost the CPU
//   pictures  composite.png, nr_in.png and nr_out.png, for tools\score_selftest.py
//   repaint   gives the picture render gave
//   nr off    gives the original, byte for byte
//   tiles     a single texel changed is reported in the one tile it lies in
//   settle    the picture scrolled for ten frames and then stopped: how far the first picture
//             after the stop is from the network's settled one, and how far after each of
//             the four further runs of the network the loop's settle gives it
//   strength  at a strength of 0 the network gives its input back, so leaving it out there,
//             as the pipeline does, changes no byte
//   above 1   at a strength above 1 the pipeline scales the change the passes made together,
//             once, after the last pass, since the runtime holds its own at 1: the picture at
//             1, at 1.5, at 2 and at 1 again, the last the first byte for byte, and at any pass
//             count the network's output at 1.5 and at 2 the output at 1 scaled on the CPU as
//             the shader scales it, against the network's input, byte for byte
//   per pass  with --passes 2 or more, the second pass at values of its own gives another
//             picture than every pass at the base's values, the base's values again give
//             the first picture back byte for byte, and the first pass at half the strength
//             gives another picture than the second at half, so each pass takes its own slot's.
//             With SharedNetwork=1 in the stack's [NeuralLens.Passes] (or LENS_FAST_ONE_FEATURE=1)
//             the passes run through the first pass's feature, which the first line and
//             timings.json say, and the pictures are that mode's: tools\run_selftest.py --shared
//             holds them against their own reference
//   remake    with --passes 2 or more, the shared state flipped and the next preset take
//             effect once the features are made again at the same size, as the loop does on a
//             reload: after four frames of one picture the other mode's picture differs, and
//             flipped back the picture is the same again byte for byte
//   switches  with --switches, one quality step after another in one run, each with the
//             time the switch took, the network's time at the new size, the video memory
//             in use and a picture. While a new network is being made, frames are drawn as
//             the loop draws them, and each must be the picture from before the switch
//   rest      with --switch-rest, seconds with repaints alone after the last switch and
//             then frames again, with the video memory in use at each point
//
// The frames alternate between two textures, as the capture's slots do. The two hold the
// same colours and differ in every texel's alpha, so each ingest finds a changed frame, the
// worst case for the flag, while the network is shown the same picture every time, as it
// was in the probe whose picture this one is scored against.
#include "selftest.h"

#include "gpu.h"
#include "pipeline.h"

#include <objbase.h>
#include <wincodec.h>

#include "flow.h"
#include "framegen.h"
#include "model_motion.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>

using Microsoft::WRL::ComPtr;

namespace {

constexpr int kWarmFrames = 120;
constexpr int kTimedFrames = 300;
constexpr int kUnchangedRuns = 100;
constexpr DWORD kWaitMs = 5000;
constexpr int kScrollFrames = 10;  // the settle's proof: frames scrolled before the stop
constexpr int kScrollStep = 8;     // texels a frame
constexpr int kSettleRuns = 4;     // as the loop's settle runs the network again

struct Picture {
  UINT w = 0, h = 0;
  std::vector<uint8_t> bgra;  // tight, top row first
};

bool load_picture(const std::wstring& path, Picture& out, std::string& err) {
  ComPtr<IWICImagingFactory> factory;
  HRESULT hr = CoCreateInstance(CLSID_WICImagingFactory, nullptr, CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&factory));
  ComPtr<IWICBitmapDecoder> decoder;
  if (SUCCEEDED(hr))
    hr = factory->CreateDecoderFromFilename(path.c_str(), nullptr, GENERIC_READ, WICDecodeMetadataCacheOnDemand,
                                            &decoder);
  ComPtr<IWICBitmapFrameDecode> frame;
  if (SUCCEEDED(hr)) hr = decoder->GetFrame(0, &frame);
  ComPtr<IWICFormatConverter> converter;
  if (SUCCEEDED(hr)) hr = factory->CreateFormatConverter(&converter);
  if (SUCCEEDED(hr))
    hr = converter->Initialize(frame.Get(), GUID_WICPixelFormat32bppBGRA, WICBitmapDitherTypeNone, nullptr, 0.0,
                               WICBitmapPaletteTypeCustom);
  if (SUCCEEDED(hr)) hr = converter->GetSize(&out.w, &out.h);
  if (SUCCEEDED(hr) && (out.w < 1 || out.h < 1 || out.w > 16384 || out.h > 16384)) hr = E_INVALIDARG;
  if (SUCCEEDED(hr)) {
    out.bgra.resize((size_t)out.w * out.h * 4);
    // in bands: one CopyPixels call takes a 32 bit byte count
    const UINT band = 256;
    for (UINT y = 0; y < out.h && SUCCEEDED(hr); y += band) {
      const UINT rows = std::min(band, out.h - y);
      const WICRect rect = {0, (INT)y, (INT)out.w, (INT)rows};
      hr = converter->CopyPixels(&rect, out.w * 4, out.w * 4 * rows, out.bgra.data() + (size_t)y * out.w * 4);
    }
  }
  if (FAILED(hr)) {
    err = "cannot read the picture " + narrow(path) + " " + hr_text(hr);
    return false;
  }
  return true;
}

// Tight RGB8 as a 24 bit PNG. proto.cpp has one for the screenshots, but the self test
// program is built without it.
bool save_png(const std::wstring& path, const std::vector<uint8_t>& rgb, UINT w, UINT h, std::string& err) {
  if (rgb.size() != (size_t)w * h * 3) {
    err = "cannot write " + narrow(path) + ", the picture has the wrong size";
    return false;
  }
  ComPtr<IWICImagingFactory> factory;
  HRESULT hr = CoCreateInstance(CLSID_WICImagingFactory, nullptr, CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&factory));
  ComPtr<IWICStream> stream;
  if (SUCCEEDED(hr)) hr = factory->CreateStream(&stream);
  if (SUCCEEDED(hr)) hr = stream->InitializeFromFilename(path.c_str(), GENERIC_WRITE);
  ComPtr<IWICBitmapEncoder> encoder;
  if (SUCCEEDED(hr)) hr = factory->CreateEncoder(GUID_ContainerFormatPng, nullptr, &encoder);
  if (SUCCEEDED(hr)) hr = encoder->Initialize(stream.Get(), WICBitmapEncoderNoCache);
  ComPtr<IWICBitmapFrameEncode> frame;
  if (SUCCEEDED(hr)) hr = encoder->CreateNewFrame(&frame, nullptr);
  if (SUCCEEDED(hr)) hr = frame->Initialize(nullptr);
  if (SUCCEEDED(hr)) hr = frame->SetSize(w, h);
  WICPixelFormatGUID format = GUID_WICPixelFormat24bppBGR;
  if (SUCCEEDED(hr)) hr = frame->SetPixelFormat(&format);
  if (SUCCEEDED(hr) && format != GUID_WICPixelFormat24bppBGR) hr = E_FAIL;
  // row by row, turned to the BGR order the encoder takes
  std::vector<uint8_t> row((size_t)w * 3);
  for (UINT y = 0; y < h && SUCCEEDED(hr); ++y) {
    const uint8_t* in = rgb.data() + (size_t)y * w * 3;
    for (UINT x = 0; x < w; ++x) {
      row[(size_t)x * 3] = in[(size_t)x * 3 + 2];
      row[(size_t)x * 3 + 1] = in[(size_t)x * 3 + 1];
      row[(size_t)x * 3 + 2] = in[(size_t)x * 3];
    }
    hr = frame->WritePixels(1, w * 3, w * 3, row.data());
  }
  if (SUCCEEDED(hr)) hr = frame->Commit();
  if (SUCCEEDED(hr)) hr = encoder->Commit();
  if (FAILED(hr)) {
    err = "cannot write " + narrow(path) + " " + hr_text(hr);
    return false;
  }
  return true;
}

// The textures the test hands the pipeline, made as the capture's slots are: B8G8R8A8 in
// COMMON. One list and one upload buffer serve every upload, each waited for.
struct Loader {
  Gpu* gpu = nullptr;
  ComPtr<ID3D12CommandAllocator> allocator;
  ComPtr<ID3D12GraphicsCommandList> list;
  ComPtr<ID3D12Resource> upload;  // a whole frame
  ComPtr<ID3D12Resource> dot;     // one texel
  D3D12_PLACED_SUBRESOURCE_FOOTPRINT fp = {};
  UINT64 bytes = 0;
  UINT w = 0, h = 0;
  DXGI_FORMAT format = DXGI_FORMAT_B8G8R8A8_UNORM;  // or R16G16B16A16_FLOAT, 8 bytes a texel
  UINT texel = 4;

  bool init(Gpu& g, UINT width, UINT height, std::string& err, DXGI_FORMAT fmt = DXGI_FORMAT_B8G8R8A8_UNORM) {
    gpu = &g;
    w = width;
    h = height;
    format = fmt;
    texel = fmt == DXGI_FORMAT_R16G16B16A16_FLOAT ? 8 : 4;
    D3D12_RESOURCE_DESC d = {};
    d.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
    d.Width = w;
    d.Height = h;
    d.DepthOrArraySize = 1;
    d.MipLevels = 1;
    d.Format = format;
    d.SampleDesc.Count = 1;
    g.device->GetCopyableFootprints(&d, 0, 1, 0, &fp, nullptr, nullptr, &bytes);
    return g.make_list(allocator, list, L"selftest uploads", err) &&
           g.make_buffer(bytes, D3D12_HEAP_TYPE_UPLOAD, D3D12_RESOURCE_STATE_GENERIC_READ,
                         D3D12_RESOURCE_FLAG_NONE, L"selftest upload", upload, err) &&
           g.make_buffer(512, D3D12_HEAP_TYPE_UPLOAD, D3D12_RESOURCE_STATE_GENERIC_READ, D3D12_RESOURCE_FLAG_NONE,
                         L"selftest dot", dot, err);
  }

  bool run(std::string& err) {
    UINT64 done = 0;
    return gpu->execute(list.Get(), done, err) && gpu->wait(done, kWaitMs, err);
  }

  bool begin(std::string& err) {
    if (FAILED(allocator->Reset()) || FAILED(list->Reset(allocator.Get(), nullptr))) {
      err = "resetting the upload list failed";
      return false;
    }
    return true;
  }

  // A new frame texture holding the picture.
  bool frame(const std::vector<uint8_t>& bgra, const wchar_t* name, ComPtr<ID3D12Resource>& out, std::string& err) {
    if (!gpu->make_texture(format, w, h, D3D12_RESOURCE_FLAG_NONE, D3D12_RESOURCE_STATE_COMMON, name, out, err))
      return false;
    return fill(bgra, out.Get(), err);
  }

  // The picture into a frame texture that exists, as a capture slot gets its next frame.
  bool fill(const std::vector<uint8_t>& bgra, ID3D12Resource* out, std::string& err) {
    uint8_t* p = nullptr;
    const D3D12_RANGE none = {0, 0};
    if (FAILED(upload->Map(0, &none, (void**)&p)) || !p) {
      err = "mapping the upload failed";
      return false;
    }
    for (UINT y = 0; y < h; ++y) {
      memcpy(p + fp.Offset + (size_t)y * fp.Footprint.RowPitch, bgra.data() + (size_t)y * w * texel,
             (size_t)w * texel);
    }
    upload->Unmap(0, nullptr);
    if (!begin(err)) return false;
    transition(list.Get(), out, D3D12_RESOURCE_STATE_COMMON, D3D12_RESOURCE_STATE_COPY_DEST);
    D3D12_TEXTURE_COPY_LOCATION dst = {};
    dst.pResource = out;
    dst.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
    D3D12_TEXTURE_COPY_LOCATION src = {};
    src.pResource = upload.Get();
    src.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
    src.PlacedFootprint = fp;
    list->CopyTextureRegion(&dst, 0, 0, 0, &src, nullptr);
    transition(list.Get(), out, D3D12_RESOURCE_STATE_COPY_DEST, D3D12_RESOURCE_STATE_COMMON);
    return run(err);
  }

  // Writes one texel of a frame texture.
  bool poke(ID3D12Resource* texture, UINT x, UINT y, const uint8_t* bgra, std::string& err) {
    uint8_t* p = nullptr;
    const D3D12_RANGE none = {0, 0};
    if (FAILED(dot->Map(0, &none, (void**)&p)) || !p) {
      err = "mapping the upload failed";
      return false;
    }
    memcpy(p, bgra, 4);
    dot->Unmap(0, nullptr);
    if (!begin(err)) return false;
    transition(list.Get(), texture, D3D12_RESOURCE_STATE_COMMON, D3D12_RESOURCE_STATE_COPY_DEST);
    D3D12_TEXTURE_COPY_LOCATION dst = {};
    dst.pResource = texture;
    dst.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
    D3D12_TEXTURE_COPY_LOCATION src = {};
    src.pResource = dot.Get();
    src.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
    src.PlacedFootprint.Footprint.Format = DXGI_FORMAT_B8G8R8A8_UNORM;
    src.PlacedFootprint.Footprint.Width = 1;
    src.PlacedFootprint.Footprint.Height = 1;
    src.PlacedFootprint.Footprint.Depth = 1;
    src.PlacedFootprint.Footprint.RowPitch = D3D12_TEXTURE_DATA_PITCH_ALIGNMENT;
    list->CopyTextureRegion(&dst, x, y, 0, &src, nullptr);
    transition(list.Get(), texture, D3D12_RESOURCE_STATE_COPY_DEST, D3D12_RESOURCE_STATE_COMMON);
    return run(err);
  }
};

struct Spread {
  double median = 0.0, p95 = 0.0, least = 0.0, most = 0.0;
  size_t n = 0;
};

Spread spread(std::vector<double> v) {
  Spread s;
  s.n = v.size();
  if (v.empty()) return s;
  std::sort(v.begin(), v.end());
  auto at = [&](double q) {
    const double i = q * (double)(v.size() - 1);
    const size_t lo = (size_t)std::floor(i), hi = (size_t)std::ceil(i);
    return v[lo] + (v[hi] - v[lo]) * (i - (double)lo);
  };
  s.median = at(0.5);
  s.p95 = at(0.95);
  s.least = v.front();
  s.most = v.back();
  return s;
}

std::string json(const Spread& s) {
  return strf("{\"n\": %zu, \"median\": %.4f, \"p95\": %.4f, \"min\": %.4f, \"max\": %.4f}", s.n, s.median, s.p95,
              s.least, s.most);
}

// The mean absolute difference of two pictures of the same size, over every byte, out of 255.
double mean_abs(const std::vector<uint8_t>& a, const std::vector<uint8_t>& b) {
  if (a.size() != b.size() || a.empty()) return -1.0;
  unsigned long long sum = 0;
  for (size_t i = 0; i < a.size(); ++i) sum += (unsigned)std::abs((int)a[i] - (int)b[i]);
  return (double)sum / (double)a.size();
}

std::string json_text(const std::string& text) {
  std::string out;
  for (char c : text) {
    if (c == '\\' || c == '"') out.push_back('\\');
    out.push_back(c);
  }
  return out;
}

// One step of the self test failed: the reason goes out as the protocol's failure line.
int failed(const std::string& why) {
  fail("%s", why.c_str());
  return exit_code::failed;
}

}  // namespace

int run_selftest(const Options& o) {
  std::string err;
  const HRESULT com = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
  if (FAILED(com) && com != RPC_E_CHANGED_MODE) return failed("COM did not start " + hr_text(com));

  // ---- the picture
  Picture picture;
  if (!load_picture(o.selftest_image, picture, err)) return failed(err);
  const UINT W = picture.w, H = picture.h;
  const WorkPlan plan = work_plan((int)W, (int)H, o);
  const int work_w = plan.w, work_h = plan.h;
  if (!make_dirs(o.selftest_outdir)) return failed("cannot create " + narrow(o.selftest_outdir));
  const std::string step_text =
      plan.quality >= 0 ? strf("quality %d %s, %s, %s", plan.quality, quality_name(plan.quality),
                               plan.held ? "Full was asked, which the picture is too large for"
                                         : (plan.chosen ? "as asked" : "the default for this size"),
                               plan.measured ? "a measured size"
                                             : (plan.quality == kQualityFull ? "the picture's own size" : "by the rule"))
                        : strf("quality none, the work size was given by %s", plan.given_by);

  // the base and each pass's own values, as the loop reads them, see NrPasses
  NrPasses pass_settings;
  if (!read_nr_passes(o.stack_dir, pass_settings, err, o.passes)) {
    note("selftest: %s, the runtime's defaults are used", err.c_str());
  }
  // as the loop takes it, though the self test makes no motion estimate: every evaluate here
  // hands the network zero vectors, whatever the source says
  take_motion_option(o, pass_settings);
  const NrSettings settings = pass_settings.base();
  // the shared state as the features are made with it: off with one pass whatever the file says
  const bool shared = pass_settings.shared && o.passes > 1;
  say("selftest picture %s %ux%u, work %dx%d, passes %d, %s, shared %s, preset %u, ui correction %d",
      narrow(o.selftest_image).c_str(), W, H, work_w, work_h, o.passes, step_text.c_str(), shared ? "on" : "off",
      pass_settings.preset, settings.ui_correction);

  std::vector<uint8_t> original((size_t)W * H * 3);  // tight RGB8, what "nr off" must give back
  for (size_t i = 0, n = (size_t)W * H; i < n; ++i) {
    original[i * 3] = picture.bgra[i * 4 + 2];
    original[i * 3 + 1] = picture.bgra[i * 4 + 1];
    original[i * 3 + 2] = picture.bgra[i * 4];
  }

  // ---- the device and the textures
  Gpu gpu;
  if (!gpu.init(nullptr, err)) return failed(err);
  say("selftest adapter %s", gpu.name.c_str());
  const UINT64 vram_device = gpu.vram_bytes();

  Loader loader;
  if (!loader.init(gpu, W, H, err)) return failed(err);
  // a: the picture. b: the same colours, every alpha one off, so a and b always compare as
  // changed. c: the picture again, for the frames that must compare as unchanged.
  ComPtr<ID3D12Resource> a, b, c, target;
  if (!loader.frame(picture.bgra, L"selftest frame a", a, err)) return failed(err);
  {
    std::vector<uint8_t> other = picture.bgra;
    for (size_t i = 3; i < other.size(); i += 4) other[i] ^= 1;
    if (!loader.frame(other, L"selftest frame b", b, err)) return failed(err);
  }
  if (!loader.frame(picture.bgra, L"selftest frame c", c, err)) return failed(err);

  // the stand-in for the back buffer
  if (!gpu.make_texture(DXGI_FORMAT_B8G8R8A8_UNORM, W, H, D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET,
                        D3D12_RESOURCE_STATE_PRESENT, L"selftest target", target, err))
    return failed(err);
  ComPtr<ID3D12DescriptorHeap> rtv_heap;
  {
    D3D12_DESCRIPTOR_HEAP_DESC d = {};
    d.Type = D3D12_DESCRIPTOR_HEAP_TYPE_RTV;
    d.NumDescriptors = 1;
    const HRESULT hr = gpu.device->CreateDescriptorHeap(&d, IID_PPV_ARGS(&rtv_heap));
    if (FAILED(hr)) return failed("the target's descriptor heap failed " + hr_text(hr));
  }
  Target back;
  back.texture = target.Get();
  back.rtv = rtv_heap->GetCPUDescriptorHandleForHeapStart();
  back.width = W;
  back.height = H;
  gpu.device->CreateRenderTargetView(target.Get(), nullptr, back.rtv);

  // ---- the pipeline
  // What the runtime reads through the engine's parameter object is recorded, for the
  // comparison with the probe's list (see nr.cpp).
  SetEnvironmentVariableW(L"LENS_FAST_NR_READS", L"1");
  PipelineDesc desc;
  desc.width = W;
  desc.height = H;
  desc.work_w = (UINT)work_w;
  desc.work_h = (UINT)work_h;
  desc.passes = o.passes;
  desc.stack_dir = o.stack_dir;
  desc.data_dir = o.data_dir;
  desc.settings = pass_settings;
  Pipeline pipeline;
  const double t_init = now_s();
  if (!pipeline.init(gpu, desc, err)) return failed(err);
  pipeline.keep_times(true);
  const double init_ms = (now_s() - t_init) * 1000.0;
  const double create_ms = pipeline.network_create_ms();
  say("selftest network created in %.0f ms on the CPU, pipeline ready in %.0f ms", create_ms, init_ms);

  bool changed = false;

  // ---- the comparison
  // The same picture in two textures must read unchanged.
  if (!pipeline.ingest(c.Get(), a.Get(), nullptr, 0, changed, err)) return failed(err);
  const bool same_unchanged = !changed;
  // One texel of the copy changed by one level must read changed: the first texel, the
  // last one of the last row, three places in between, then the other corners, the texels
  // round the middle and a spread of others, each channel in turn.
  struct Spot {
    UINT x, y;
  };
  std::vector<Spot> spots = {{0, 0}, {W - 1, H - 1}, {W / 2, H / 2}, {W / 3, H / 4}, {(W * 2) / 3, (H * 3) / 4},
                             {W - 1, 0}, {0, H - 1}, {1, 0}, {0, 1}, {W - 2, H - 1}, {W - 1, H - 2}};
  {
    unsigned seed = 12345;
    auto next = [&seed]() {
      seed = seed * 1664525u + 1013904223u;
      return seed >> 8;
    };
    for (int i = 0; i < 96; ++i) spots.push_back({next() % W, next() % H});
  }
  int found = 0;
  int tiled = 0;  // of those, reported in the one tile the texel lies in and in no other
  std::string missed;
  for (size_t i = 0; i < spots.size(); ++i) {
    const UINT x = spots[i].x, y = spots[i].y;
    const uint8_t* was = &picture.bgra[((size_t)y * W + x) * 4];
    uint8_t now[4] = {was[0], was[1], was[2], was[3]};
    const int channel = (int)(i % 4);
    now[channel] = (uint8_t)(now[channel] == 255 ? 254 : now[channel] + 1);
    if (!loader.poke(c.Get(), x, y, now, err)) return failed(err);
    if (!pipeline.ingest(c.Get(), a.Get(), nullptr, 0, changed, err)) return failed(err);
    if (changed) ++found;
    else if (missed.size() < 200) missed += strf(" (%u,%u)", x, y);
    {
      // the tile of the work texel that owns this texel: work texel floor(x * w / W) across
      uint8_t tiles[Pipeline::kTiles] = {};
      pipeline.add_changed_tiles(tiles);
      int set = 0;
      for (const uint8_t tile : tiles) set += tile;
      const UINT across = (UINT)((UINT64)x * (UINT)work_w / W) * Pipeline::kTilesAcross / (UINT)work_w;
      const UINT down = (UINT)((UINT64)y * (UINT)work_h / H) * Pipeline::kTilesAcross / (UINT)work_h;
      if (set == 1 && tiles[down * Pipeline::kTilesAcross + across]) ++tiled;
    }
    if (!loader.poke(c.Get(), x, y, was, err)) return failed(err);
  }
  // and put back, it must read unchanged again
  if (!pipeline.ingest(c.Get(), a.Get(), nullptr, 0, changed, err)) return failed(err);
  const bool restored_unchanged = !changed;
  say("selftest compare: the same picture reads %s, %d of %d single texel changes found, put back it reads %s",
      same_unchanged ? "unchanged" : "CHANGED", found, (int)spots.size(), restored_unchanged ? "unchanged" : "CHANGED");
  say("selftest tiles: %d of %d single texel changes reported in their own tile and no other", tiled,
      (int)spots.size());
  if (!same_unchanged || !restored_unchanged) return failed("the comparison calls two equal pictures different");
  if (found != (int)spots.size()) return failed("the comparison missed a changed texel at" + missed);
  if (tiled != (int)spots.size()) return failed("a changed texel was not reported in its own tile alone");

  // ---- the frames, as the loop runs them
  std::vector<double> g_ingest, g_nr, g_composite, g_frame, c_ingest, c_render, c_frame;
  for (int i = 0; i < kWarmFrames + kTimedFrames; ++i) {
    ID3D12Resource* cur = (i % 2 == 0) ? a.Get() : b.Get();
    ID3D12Resource* prev = i == 0 ? nullptr : ((i % 2 == 0) ? b.Get() : a.Get());
    const double t0 = now_s();
    if (!pipeline.ingest(cur, prev, nullptr, 0, changed, err)) return failed(err);
    const double t1 = now_s();
    if (!changed) return failed("a changed frame was read as unchanged");
    if (!pipeline.render(cur, back, false, false, err)) return failed(err);
    const double t2 = now_s();
    // the loop would present here and go back to waiting; the test waits for the GPU so
    // that the timestamps it reads next are this frame's
    if (!gpu.flush(kWaitMs, err)) return failed(err);
    const double t3 = now_s();
    if (i >= kWarmFrames) {
      const StageTimes t = pipeline.times();
      g_ingest.push_back(t.ingest_ms);
      g_nr.push_back(t.nr_ms);
      g_composite.push_back(t.composite_ms);
      g_frame.push_back(t.ingest_ms + t.nr_ms + t.composite_ms);
      c_ingest.push_back((t1 - t0) * 1000.0);
      c_render.push_back((t2 - t1) * 1000.0);
      c_frame.push_back((t3 - t0) * 1000.0);
    }
  }
  const Spread s_ingest = spread(g_ingest), s_nr = spread(g_nr), s_composite = spread(g_composite),
               s_frame = spread(g_frame), s_cingest = spread(c_ingest), s_crender = spread(c_render),
               s_cframe = spread(c_frame);
  say("selftest %d frames after %d to warm up, GPU ms median (95th): ingest %.3f (%.3f) nr %.3f (%.3f) composite "
      "%.3f (%.3f) frame %.3f (%.3f)",
      kTimedFrames, kWarmFrames, s_ingest.median, s_ingest.p95, s_nr.median, s_nr.p95, s_composite.median,
      s_composite.p95, s_frame.median, s_frame.p95);
  say("selftest CPU ms median (95th): ingest call %.3f (%.3f) render call %.3f (%.3f) frame start to GPU done %.3f "
      "(%.3f)",
      s_cingest.median, s_cingest.p95, s_crender.median, s_crender.p95, s_cframe.median, s_cframe.p95);
  const UINT64 vram = gpu.vram_bytes();

  // ---- the pictures: one more frame of the picture itself, with the copies kept
  std::vector<uint8_t> composite, native, work_in, work_out;
  UINT ww = 0, wh = 0;
  if (!pipeline.ingest(a.Get(), b.Get(), nullptr, 0, changed, err)) return failed(err);
  if (!pipeline.render(a.Get(), back, false, true, err)) return failed(err);
  if (!pipeline.read_target(composite, err) || !pipeline.read_native(native, err)) return failed(err);
  if (!pipeline.read_work(false, work_in, ww, wh, err) || !pipeline.read_work(true, work_out, ww, wh, err))
    return failed(err);
  const bool native_exact = native == original;

  // ---- repaint gives the picture render gave, and the sparse read is every 4th texel of it
  std::vector<uint8_t> again, sparse;
  UINT sw = 0, sh = 0;
  if (!pipeline.repaint(back, true, err)) return failed(err);
  if (!pipeline.read_target(again, err) || !pipeline.read_target_sparse(sparse, sw, sh, err)) return failed(err);
  const bool repaint_same = again == composite;
  bool sparse_same = sw == (W + 3) / 4 && sh == (H + 3) / 4 && sparse.size() == (size_t)sw * sh * 3;
  for (UINT y = 0; sparse_same && y < sh; ++y)
    for (UINT x = 0; x < sw; ++x)
      if (memcmp(&sparse[((size_t)y * sw + x) * 3], &composite[((size_t)(y * 4) * W + x * 4) * 3], 3) != 0) {
        sparse_same = false;
        break;
      }
  say("selftest repaint gives the picture render gave: %s, the sparse read is every 4th texel of it: %s, the kept "
      "native copy is the original: %s",
      repaint_same ? "yes" : "NO", sparse_same ? "yes" : "NO", native_exact ? "yes" : "NO");

  // ---- the frame that comes back after every present: the same picture, nothing to do
  std::vector<double> g_same, c_same;
  bool all_unchanged = true;
  for (int i = 0; i < kUnchangedRuns; ++i) {
    ID3D12Resource* cur = (i % 2 == 0) ? c.Get() : a.Get();
    ID3D12Resource* prev = (i % 2 == 0) ? a.Get() : c.Get();
    const double t0 = now_s();
    if (!pipeline.ingest(cur, prev, nullptr, 0, changed, err)) return failed(err);
    c_same.push_back((now_s() - t0) * 1000.0);
    g_same.push_back(pipeline.last_ingest_ms());
    if (changed) all_unchanged = false;
  }
  const Spread s_gsame = spread(g_same), s_csame = spread(c_same);
  say("selftest unchanged frame, %d times: ingest GPU ms median %.3f (95th %.3f), the call %.3f (%.3f), all read "
      "unchanged: %s",
      kUnchangedRuns, s_gsame.median, s_gsame.p95, s_csame.median, s_csame.p95, all_unchanged ? "yes" : "NO");

  // ---- a strength of 0. The network run at it gives its input back, so the composite is
  // the original, and the pipeline, which then leaves the network out, gives the same.
  bool zero_ran_exact = false, zero_off_exact = false;
  double zero_ran_ms = 0.0, zero_off_ms = 0.0;
  {
    NrSettings zero = settings;
    zero.intensity = 0.0f;
    std::vector<uint8_t> shown;
    pipeline.set_settings(zero);
    pipeline.set_run_at_zero(true);
    if (!pipeline.ingest(a.Get(), nullptr, nullptr, 0, changed, err)) return failed(err);
    if (!pipeline.render(a.Get(), back, false, true, err)) return failed(err);
    if (!pipeline.read_target(shown, err)) return failed(err);
    zero_ran_exact = shown == original;
    zero_ran_ms = pipeline.times().nr_ms;
    pipeline.set_run_at_zero(false);
    if (!pipeline.ingest(a.Get(), nullptr, nullptr, 0, changed, err)) return failed(err);
    if (!pipeline.render(a.Get(), back, false, true, err)) return failed(err);
    if (!pipeline.read_target(shown, err)) return failed(err);
    zero_off_exact = shown == original && !pipeline.network_runs();
    zero_off_ms = pipeline.times().nr_ms;
    pipeline.set_settings(pass_settings);
    say("selftest strength 0: the network run at it gives the original: %s, in %.3f ms. Left out, as the "
        "pipeline does at that strength, the picture is the original: %s, in %.3f ms",
        zero_ran_exact ? "yes" : "NO", zero_ran_ms, zero_off_exact ? "yes" : "NO", zero_off_ms);
  }

  // ---- the strength above 1, the lens's own scaling of the change the passes made
  // together, see NrPasses in common.h: every pass at the base's values with the intensity
  // at 1, at a strength of 1, then 1.5, then 2, and 1 again, each the network's first picture
  // of this frame. The picture at 1 again must be the first byte for byte. At any pass count
  // the network's output at 1.5 and at 2 must be the output at 1 scaled on the CPU the way
  // the shader scales it, against the network's input, byte for byte, which the two factors
  // allow since every value of theirs is exact in a float. The pictures at 1.5 and 2 must
  // each differ from the one at 1 and from each other. The mean absolute change from the
  // original at each is reported, so the scaling can be read as a ratio: it is not the factor
  // itself, since each level is rounded and held inside 0 to 255.
  bool above_ok = true, above_back = false, above_exact = true;
  double above_change[3] = {};  // at 1, 1.5 and 2
  {
    NrPasses one = pass_settings;
    for (NrSettings& p : one.pass) {
      p = settings;
      p.intensity = 1.0f;
    }
    one.strength = 1.0f;
    one.look = NrLook();  // the arithmetic needs the change unshaped: the Look stage, see look.h, stays off here
    NrPasses half = one, two = one;
    half.strength = 1.5f;
    two.strength = 2.0f;
    std::vector<uint8_t> pic[3], again, out_one, out_scaled;
    UINT ow = 0, oh = 0;
    auto draw = [&](const NrPasses& with, std::vector<uint8_t>& pic_out) {
      pipeline.set_settings(with);
      if (!pipeline.ingest(a.Get(), nullptr, nullptr, 0, changed, err)) return false;
      if (!pipeline.render(a.Get(), back, true, true, err)) return false;
      return pipeline.read_target(pic_out, err);
    };
    if (!draw(one, pic[0])) return failed(err);
    if (!pipeline.read_work(true, out_one, ow, oh, err)) return failed(err);
    const NrPasses* with[2] = {&half, &two};
    const float factor[2] = {1.5f, 2.0f};
    for (int k = 0; k < 2; ++k) {
      if (!draw(*with[k], pic[k + 1])) return failed(err);
      if (!pipeline.read_work(true, out_scaled, ow, oh, err)) return failed(err);
      if (out_scaled.size() != out_one.size() || out_one.size() != work_in.size()) above_exact = false;
      // the shader's arithmetic: in + (out - in) * factor, a half going up, held in 0 to 255
      for (size_t i = 0; i < out_one.size() && above_exact; ++i) {
        const float v = (float)work_in[i] + ((float)out_one[i] - (float)work_in[i]) * factor[k];
        float q = std::floor(v);
        if (v - q >= 0.5f) q += 1.0f;
        const int level = q < 0.0f ? 0 : (q > 255.0f ? 255 : (int)q);
        if (level != (int)out_scaled[i]) above_exact = false;
      }
    }
    if (!draw(one, again)) return failed(err);
    pipeline.set_settings(pass_settings);
    above_back = again == pic[0];
    for (int k = 0; k < 3; ++k) above_change[k] = mean_abs(pic[k], original);
    above_ok = above_back && above_exact && pic[1] != pic[0] && pic[2] != pic[0] && pic[2] != pic[1];
    say("selftest strength above 1: with every pass at the base's values the mean absolute change from the "
        "original is %.3f of 255 at a strength of 1, %.3f at 1.5 (%.2f times) and %.3f at 2 (%.2f times); at 1 "
        "again the picture is the first byte for byte: %s; the network's output at 1.5 and at 2 is the output "
        "at 1 scaled as the shader scales it, byte for byte: %s",
        above_change[0], above_change[1], above_change[0] > 0.0 ? above_change[1] / above_change[0] : 0.0,
        above_change[2], above_change[0] > 0.0 ? above_change[2] / above_change[0] : 0.0,
        above_back ? "yes" : "NO", above_exact ? "yes" : "NO");
  }

  // ---- each pass's own values, with two passes or more: the same picture drawn with every
  // pass at the base's values, then with the second pass at half the strength, then at the
  // base's values again, then with the second pass at another style, and last with the first
  // pass at half the strength and the second at the base's. The history is dropped before
  // each, so each is the network's first picture of this frame. Each with a pass at values of
  // its own must differ from the first, the third must be the first byte for byte, and the
  // last must differ from the one with the second pass at half, so each pass takes the values
  // of its own slot. An engine that gave every pass the second pass's values, or each pass
  // the next one's, draws the last as the first. A swap of the two passes' values is not
  // caught, since telling it apart needs a picture of one pass to compare with. With one pass
  // there is nothing to show, and the check counts as held. Where the file has a strength of
  // 0, a pass at the base's values gives its input back. The second pass at another style
  // then draws the equal picture, and the first pass at half draws what the second at half
  // draws, so those two are not judged, and the line says so.
  bool per_pass_ok = true;
  // mean abs from the equal picture, out of 255, and the last's from the one with the second at half
  double per_pass_half = -1.0, per_pass_style = -1.0, per_pass_first = -1.0, per_pass_first_half = -1.0;
  bool per_pass_again = false, per_pass_at_zero = false;
  // the remake check below: the other mode's picture from the equal one, and the way back
  bool remake_ok = true, remake_back = false;
  double remake_other = -1.0;
  if (o.passes >= 2) {
    const NrSettings base = settings;
    per_pass_at_zero = !(base.intensity > 0.0f);
    const float halved = base.intensity > 0.0f ? base.intensity * 0.5f : 0.5f;
    // every pass at the base's values, with the run's preset and shared state kept, so the
    // check runs the features as they were made
    NrPasses equal = pass_settings;
    for (NrSettings& p : equal.pass) p = base;
    NrPasses half = equal;
    half.pass[1].intensity = halved;
    NrPasses styled = equal;
    styled.pass[1].style = (base.style + 1) % 3;
    NrPasses first = equal;
    first.pass[0].intensity = halved;
    std::vector<uint8_t> pic_equal, pic_half, pic_again, pic_styled, pic_first;
    auto draw = [&](const NrPasses& with, std::vector<uint8_t>& pic) {
      pipeline.set_settings(with);
      if (!pipeline.ingest(a.Get(), nullptr, nullptr, 0, changed, err)) return false;
      if (!pipeline.render(a.Get(), back, true, true, err)) return false;
      return pipeline.read_target(pic, err);
    };
    if (!draw(equal, pic_equal) || !draw(half, pic_half) || !draw(equal, pic_again) || !draw(styled, pic_styled) ||
        !draw(first, pic_first))
      return failed(err);
    pipeline.set_settings(pass_settings);
    per_pass_half = mean_abs(pic_half, pic_equal);
    per_pass_style = mean_abs(pic_styled, pic_equal);
    per_pass_again = pic_again == pic_equal;
    per_pass_first = mean_abs(pic_first, pic_equal);
    per_pass_first_half = mean_abs(pic_first, pic_half);
    per_pass_ok = per_pass_half > 0.0 && per_pass_again && per_pass_first > 0.0 &&
                  (per_pass_at_zero || (per_pass_style > 0.0 && pic_first != pic_half));
    if (per_pass_at_zero) {
      say("selftest per pass: the base's strength is 0, at which a pass at the base's values gives its input back. "
          "With the second pass at half the strength the picture is %.3f of 255 from the one with every pass at the "
          "base's values, and at the base's values again it is the same picture: %s. With the first pass at half "
          "the strength it is %.3f from the equal one. Not judged at a strength of 0: the second pass at another "
          "style, which then draws the equal picture, and the first pass at half against the second at half, which "
          "then draw the same picture",
          per_pass_half, per_pass_again ? "yes" : "NO", per_pass_first);
    } else {
      say("selftest per pass: with the second pass at half the strength the picture is %.3f of 255 from the one "
          "with every pass at the base's values, at another style %.3f, and at the base's values again it is the "
          "same picture: %s. With the first pass at half the strength it is %.3f from the equal one and %.3f from "
          "the one with the second at half",
          per_pass_half, per_pass_style, per_pass_again ? "yes" : "NO", per_pass_first, per_pass_first_half);
    }

    // ---- the shared state and the preset take effect when the features are made again, which
    // the loop does on a reload through its quality switch, see main.cpp. The two modes draw
    // the same picture from a dropped history, since the second pass then starts afresh
    // either way: they part over frames, as the shared feature's history takes in the network's
    // own output. So each picture here is the frame drawn with the history dropped and then
    // three times more with it kept. First in the run's own mode. Then with the shared state
    // flipped and the next preset, the features made again at the same size and put in use,
    // as a quality switch does it: another picture, and the network must say it was made with
    // the new state. Flipped back the same way, the first picture again byte for byte. Before
    // each remake the pipeline must say one is due, and after it that none is. Where the file
    // has a strength of 0 the network does not run in either mode and both draw the original,
    // so the other mode's picture is not judged then, as the per pass check does not judge
    // its pictures at that strength, and the line says so. The states and the way back are.
    {
      NrPasses other = equal;
      other.shared = !equal.shared;
      other.preset = (equal.preset + 1) % 4;
      auto frames = [&](std::vector<uint8_t>& pic) {
        if (!pipeline.ingest(a.Get(), nullptr, nullptr, 0, changed, err)) return false;
        if (!pipeline.render(a.Get(), back, true, false, err)) return false;
        for (int i = 0; i < 3; ++i) {
          if (!pipeline.render(a.Get(), back, false, i == 2, err)) return false;
        }
        return pipeline.read_target(pic, err);
      };
      auto remake = [&](const NrPasses& with, std::vector<uint8_t>& pic, bool& due_before, bool& due_after) {
        pipeline.set_settings(with);
        due_before = pipeline.network_needs_remake();
        if (!pipeline.prepare_work((UINT)work_w, (UINT)work_h, err) || !pipeline.commit_work(err)) return false;
        due_after = pipeline.network_needs_remake();
        return frames(pic);
      };
      std::vector<uint8_t> pic_same, pic_other, pic_back;
      bool due1 = false, due1_after = true, due2 = false, due2_after = true;
      pipeline.set_settings(equal);
      if (!frames(pic_same)) return failed(err);
      if (!remake(other, pic_other, due1, due1_after)) return failed(err);
      const bool other_state = pipeline.shared_network() == other.shared && pipeline.preset() == other.preset;
      if (!remake(equal, pic_back, due2, due2_after)) return failed(err);
      const bool back_state = pipeline.shared_network() == equal.shared && pipeline.preset() == equal.preset;
      pipeline.set_settings(pass_settings);
      remake_other = mean_abs(pic_other, pic_same);
      remake_back = pic_back == pic_same;
      remake_ok = due1 && !due1_after && due2 && !due2_after && other_state && back_state &&
                  (per_pass_at_zero || remake_other > 0.0) && remake_back;
      say("selftest remake: with the shared state flipped to %s and preset %u the features made again at the same "
          "size give, after four frames, a picture %.3f of 255 from this mode's%s, the network says it was made so: "
          "%s; flipped back it is this mode's picture again: %s, made so: %s; a remake was due before each and "
          "none after: %s",
          other.shared ? "on" : "off", other.preset, remake_other,
          per_pass_at_zero ? " (not judged at a strength of 0, where the network does not run in either mode)" : "",
          other_state ? "yes" : "NO", remake_back ? "yes" : "NO", back_state ? "yes" : "NO",
          due1 && !due1_after && due2 && !due2_after ? "yes" : "NO");
    }
  }

  // ---- the network off gives the original
  std::vector<uint8_t> plain;
  pipeline.set_nr(false);
  if (!pipeline.ingest(a.Get(), nullptr, nullptr, 0, changed, err)) return failed(err);
  if (!pipeline.render(a.Get(), back, false, true, err)) return failed(err);
  if (!pipeline.read_target(plain, err)) return failed(err);
  const bool off_exact = plain == original;
  // and on again it still draws: the history starts afresh, so the picture is not compared
  pipeline.set_nr(true);
  if (!pipeline.ingest(b.Get(), a.Get(), nullptr, 0, changed, err)) return failed(err);
  if (!pipeline.render(b.Get(), back, false, false, err)) return failed(err);
  if (!gpu.flush(kWaitMs, err)) return failed(err);
  say("selftest nr off gives the original: %s", off_exact ? "yes" : "NO");
  say("selftest video memory %.0f MiB after the timed frames (%.0f MiB with the device alone)", vram / 1048576.0,
      vram_device / 1048576.0);

  // ---- the settle: the picture scrolls 8 texels a frame for ten frames and then stands still.
  // The first picture of the still frame is what the loop shows right after a stop. The
  // loop's settle then runs the network on that frame four more times. Each picture is held
  // against the composite above, which the network made of this same frame after 420 runs
  // on it: its settled state.
  double settle_from[kSettleRuns + 1] = {};
  {
    std::vector<uint8_t> scrolled(picture.bgra.size());
    ID3D12Resource* before = b.Get();  // the frame the last render above drew
    for (int k = kScrollFrames; k >= 1; --k) {
      const size_t by = (size_t)k * kScrollStep % W;
      for (UINT y = 0; y < H; ++y) {
        const uint8_t* row = picture.bgra.data() + (size_t)y * W * 4;
        uint8_t* out = scrolled.data() + (size_t)y * W * 4;
        memcpy(out, row + by * 4, ((size_t)W - by) * 4);
        memcpy(out + ((size_t)W - by) * 4, row, by * 4);
      }
      // the two textures take turns, as the capture's slots do
      ID3D12Resource* cur = before == c.Get() ? b.Get() : c.Get();
      if (!loader.fill(scrolled, cur, err)) return failed(err);
      if (!pipeline.ingest(cur, before, nullptr, 0, changed, err)) return failed(err);
      if (!pipeline.render(cur, back, false, false, err)) return failed(err);
      before = cur;
    }
    std::vector<uint8_t> shown;
    if (!pipeline.ingest(a.Get(), before, nullptr, 0, changed, err)) return failed(err);
    if (!pipeline.render(a.Get(), back, false, true, err)) return failed(err);
    if (!pipeline.read_target(shown, err)) return failed(err);
    settle_from[0] = mean_abs(shown, composite);
    for (int run = 1; run <= kSettleRuns; ++run) {
      // no ingest: the network's input still holds this frame, as in the loop
      if (!pipeline.render(a.Get(), back, false, true, err)) return failed(err);
      if (!pipeline.read_target(shown, err)) return failed(err);
      settle_from[run] = mean_abs(shown, composite);
    }
    say("selftest settle: after %d frames scrolling %d texels each the first still picture is %.3f of 255 from the "
        "settled one on average, after 1 to %d more runs of the network %.3f %.3f %.3f %.3f",
        kScrollFrames, kScrollStep, settle_from[0], kSettleRuns, settle_from[1], settle_from[2], settle_from[3],
        settle_from[4]);
  }

  // ---- the joined list: the ingest and the render in one list, see Pipeline::render_joined.
  // Its picture must be the one the two calls make. With the network off that is the
  // original. With the network on, the two are held against each other from the same
  // start: a render with the network's history dropped, and a joined draw with it dropped
  // again, both of the same frame. Then the answer that comes back: unchanged for the same
  // picture in another texture, one tile for one changed texel, and the times of the draw
  // with its own ingest.
  bool joined_off_exact = false, joined_on_same = false, joined_unchanged = false, joined_tiled = false,
       joined_timed = false, times_bounded = false;
  {
    std::vector<uint8_t> shown, careful;
    uint8_t tiles[Pipeline::kTiles] = {};
    bool flag = true;
    // the frames: a holds the picture, b and c scrolled pictures from the settle's proof, so
    // c is given the picture again, as the capture gives the same picture in another slot
    if (!loader.fill(picture.bgra, c.Get(), err)) return failed(err);
    pipeline.set_nr(false);
    if (!pipeline.render_joined(a.Get(), b.Get(), nullptr, 0, back, false, true, err)) return failed(err);
    if (!pipeline.read_target(shown, err)) return failed(err);
    joined_off_exact = shown == original;
    pipeline.set_nr(true);
    // every draw so far has been waited for: their times go, so that the joined draw's are alone
    StageTimes t;
    while (pipeline.take_times(t)) {
    }
    while (pipeline.take_flag(flag, tiles)) {
    }
    if (!pipeline.ingest(a.Get(), b.Get(), nullptr, 0, changed, err)) return failed(err);
    if (!pipeline.render(a.Get(), back, true, true, err)) return failed(err);
    if (!pipeline.read_target(careful, err)) return failed(err);
    if (!pipeline.render_joined(a.Get(), b.Get(), nullptr, 0, back, true, true, err)) return failed(err);
    if (!pipeline.read_target(shown, err)) return failed(err);
    joined_on_same = shown == careful;
    // the answer: the frame differed from b, the scrolled picture, in tiles
    flag = false;
    const bool answered = pipeline.take_flag(flag, tiles);
    int set = 0;
    for (const uint8_t tile : tiles) set += tile;
    const bool changed_right = answered && flag && set >= 1;
    // the times: the careful render's, then the joined draw's with its own ingest
    int timed = 0;
    bool joined_seen = false;
    while (pipeline.take_times(t)) {
      ++timed;
      if (t.joined && t.ingest_ms > 0.0 && t.nr_ms > 0.0 && t.composite_ms > 0.0 && t.ran_network) joined_seen = true;
    }
    joined_timed = timed == 2 && joined_seen;
    // the same picture in another texture: drawn, and found unchanged afterwards
    for (uint8_t& tile : tiles) tile = 0;
    if (!pipeline.render_joined(c.Get(), a.Get(), nullptr, 0, back, false, false, err)) return failed(err);
    if (!gpu.flush(kWaitMs, err)) return failed(err);
    flag = true;
    set = 0;
    joined_unchanged = pipeline.take_flag(flag, tiles) && !flag;
    for (const uint8_t tile : tiles) set += tile;
    joined_unchanged = joined_unchanged && set == 0;
    // one texel changed: found, in its tile alone
    {
      const UINT x = W / 3, y = H / 4;
      const uint8_t* was = &picture.bgra[((size_t)y * W + x) * 4];
      uint8_t now[4] = {was[0], was[1], was[2], was[3]};
      now[1] = (uint8_t)(now[1] == 255 ? 254 : now[1] + 1);
      if (!loader.poke(c.Get(), x, y, now, err)) return failed(err);
      for (uint8_t& tile : tiles) tile = 0;
      if (!pipeline.render_joined(c.Get(), a.Get(), nullptr, 0, back, false, false, err)) return failed(err);
      if (!gpu.flush(kWaitMs, err)) return failed(err);
      flag = false;
      set = 0;
      const bool got = pipeline.take_flag(flag, tiles);
      for (const uint8_t tile : tiles) set += tile;
      const UINT across = (UINT)((UINT64)x * (UINT)work_w / W) * Pipeline::kTilesAcross / (UINT)work_w;
      const UINT down = (UINT)((UINT64)y * (UINT)work_h / H) * Pipeline::kTilesAcross / (UINT)work_h;
      joined_tiled = got && flag && set == 1 && tiles[down * Pipeline::kTilesAcross + across];
      if (!loader.poke(c.Get(), x, y, was, err)) return failed(err);
    }
    // and nothing is left waiting
    while (pipeline.take_times(t)) {
    }
    joined_unchanged = joined_unchanged && !pipeline.take_flag(flag, tiles);
    // the times queue is bounded: twice kTimesKept repaints without a take hand out at most
    // kTimesKept times and at least one, and with keep_times off none at all
    int times_on = 0, times_off = 0;
    for (int i = 0; i < 2 * Pipeline::kTimesKept; ++i) {
      if (!pipeline.repaint(back, false, err)) return failed(err);
    }
    if (!gpu.flush(kWaitMs, err)) return failed(err);
    while (pipeline.take_times(t)) ++times_on;
    pipeline.keep_times(false);
    for (int i = 0; i < 2 * Pipeline::kTimesKept; ++i) {
      if (!pipeline.repaint(back, false, err)) return failed(err);
    }
    if (!gpu.flush(kWaitMs, err)) return failed(err);
    while (pipeline.take_times(t)) ++times_off;
    pipeline.keep_times(true);
    times_bounded = times_on >= 1 && times_on <= Pipeline::kTimesKept && times_off == 0;
    say("selftest times queue: %d repaints without a take hand out %d times (at most %d), with keep_times off %d",
        2 * Pipeline::kTimesKept, times_on, Pipeline::kTimesKept, times_off);
    // the frame on screen is the picture again, through the two calls, as the loop draws it
    if (!pipeline.ingest(a.Get(), c.Get(), nullptr, 0, changed, err)) return failed(err);
    if (!pipeline.render(a.Get(), back, false, false, err)) return failed(err);
    if (!gpu.flush(kWaitMs, err)) return failed(err);
    say("selftest joined list: with the network off the picture is the original: %s, with it on and the history "
        "dropped it is the render's: %s, its answer says changed, in tiles: %s, the same picture in another "
        "texture reads unchanged: %s, one changed texel is found in its own tile alone: %s, its times come with "
        "its own ingest: %s",
        joined_off_exact ? "yes" : "NO", joined_on_same ? "yes" : "NO", changed_right ? "yes" : "NO",
        joined_unchanged ? "yes" : "NO", joined_tiled ? "yes" : "NO", joined_timed ? "yes" : "NO");
    joined_on_same = joined_on_same && changed_right;
  }

  // ---- what is written
  const std::wstring out = o.selftest_outdir;
  if (!save_png(path_join(out, L"composite.png"), composite, W, H, err) ||
      !save_png(path_join(out, L"nr_in.png"), work_in, ww, wh, err) ||
      !save_png(path_join(out, L"nr_out.png"), work_out, ww, wh, err))
    return failed(err);

  // ---- the switches, --switches LIST. Each step in turn, as the loop switches on "quality
  // N". The network for the new size is made beside the one in use, the two change over,
  // then the frames follow. The first frame comes with no frame before it, as the loop draws
  // the picture on screen again after a switch, and the network starts on it without a
  // history. With the default count of frames a step draws exactly what a fresh start at
  // that step has drawn when it keeps its composite, so the two pictures can be held against
  // each other.
  struct Switched {
    int quality = 0;
    UINT w = 0, h = 0;
    double at_s = 0.0;        // when the switch began, in seconds from the first one
    bool resized = false;     // the step has another work size than the one before it
    double prepare_ms = 0.0;  // the whole of prepare_work()
    double create_ms = 0.0;   // of it, the feature creation on the CPU
    double commit_ms = 0.0;   // commit_work(): the wait for the GPU and the release of the old
    double first_ms = 0.0;    // the first frame's ingest and render calls and the GPU's work
    int held = 0;             // frames drawn while the network was being made
    bool held_same = true;    // and whether they were the picture from before the switch
    double held_gap_ms = 0.0; // the longest time from one of them to the next
    Spread nr;                // GPU ms of the network over the timed frames
    double vram_before = 0.0; // video memory in use before the switch, MiB
    double vram_both = 0.0;   // with the new network made and the old one still there
    double vram_after = 0.0;  // with the old one released
    double vram_mib = 0.0;    // after the frames
    // mean absolute differences out of 255, -1 when no pictures were kept
    double first_from_before = -1.0;  // the first picture at the step, from the one before the switch
    double first_from_plain = -1.0;   // and from the original, where 0 would be the plain picture
    double rest_from_first = -1.0;    // the picture after all the frames, from the first one
    double rest_from_plain = -1.0;    // and from the original
    uint64_t picture = 0;     // a hash of the composite, 0 when none was kept
    int same_as = -1;         // the earlier switch to the same step, -1 for none
    bool same = false;        // and whether the two composites are the same
    std::string file;         // the picture's name, empty when none was written
  };
  std::vector<Switched> switched;
  bool switches_ok = true;
  double rest_mib[6] = {};  // the video memory round a rest, see --switch-rest below
  const int switch_frames = o.switch_frames > 0 ? o.switch_frames : kWarmFrames + kTimedFrames + 1;
  const bool switch_pictures = switch_frames >= 100;  // a quick loop is for the memory alone
  if (!o.switches.empty()) {
    // The settle's proof left scrolled pictures in b and c. The frames below take turns
    // between a and b, which have to hold the same colours again.
    std::vector<uint8_t> other = picture.bgra;
    for (size_t i = 3; i < other.size(); i += 4) other[i] ^= 1;
    if (!loader.fill(other, b.Get(), err)) return failed(err);
    // with LENS_FAST_SWITCH_SYNC=1 the network is made on this thread, as the loop does then
    const bool sync = env_text(L"LENS_FAST_SWITCH_SYNC") == L"1";
    // the picture as it stands before a switch, which is the last one drawn, read from a repaint
    std::vector<uint8_t> before_switch;
    if (switch_pictures) {
      if (!pipeline.repaint(back, true, err) || !pipeline.read_target(before_switch, err)) return failed(err);
    }
    const double t_switches = now_s();
    UINT cur_w = (UINT)work_w, cur_h = (UINT)work_h;
    for (size_t k = 0; k < o.switches.size(); ++k) {
      Switched s;
      s.quality = o.switches[k];
      // Full above the network's largest size is Quality, as the loop holds it
      if (s.quality == kQualityFull && !full_fits((int)W, (int)H)) s.quality = kQualityFull - 1;
      s.at_s = now_s() - t_switches;
      int w = 0, h = 0;
      quality_work_size((int)W, (int)H, s.quality, w, h);
      s.w = (UINT)w;
      s.h = (UINT)h;
      s.resized = s.w != cur_w || s.h != cur_h;
      s.vram_before = gpu.vram_bytes() / 1048576.0;
      s.vram_both = s.vram_after = s.vram_before;
      if (s.resized) {
        const double t0 = now_s();
        if (sync) {
          if (!pipeline.prepare_work(s.w, s.h, err)) return failed(err);
        } else {
          // As the loop does it. The network is made on the pipeline's thread, and frames are
          // drawn meanwhile, which make no call into the runtime. Each is the native frame
          // with the network's change as it stood, so over this still picture each must be
          // the picture from before the switch, byte for byte.
          if (!pipeline.begin_work(s.w, s.h, err)) return failed(err);
          int state = pipeline.work_state(err);
          double t_last = now_s();
          std::vector<uint8_t> held;
          for (int i = 0; state == 1; ++i) {
            ID3D12Resource* cur = (i % 2 == 0) ? a.Get() : b.Get();
            ID3D12Resource* prev = i == 0 ? nullptr : ((i % 2 == 0) ? b.Get() : a.Get());
            const bool keep = switch_pictures && (i == 0 || i == 7);
            if (!pipeline.ingest(cur, prev, nullptr, 0, changed, err)) return failed(err);
            if (!pipeline.render(cur, back, false, keep, err)) return failed(err);
            if (!gpu.flush(kWaitMs, err)) return failed(err);
            if (keep) {
              if (!pipeline.read_target(held, err)) return failed(err);
              if (held != before_switch) s.held_same = false;
            }
            if (pipeline.network_runs()) s.held_same = false;  // it must say so while it holds
            ++s.held;
            const double t = now_s();
            s.held_gap_ms = std::max(s.held_gap_ms, (t - t_last) * 1000.0);
            t_last = t;
            state = pipeline.work_state(err);
          }
          if (state != 2) return failed("the network for the new size could not be made: " + err);
          if (!s.held_same) switches_ok = false;
        }
        const double t1 = now_s();
        s.vram_both = gpu.vram_bytes() / 1048576.0;
        if (!pipeline.commit_work(err)) return failed(err);
        s.prepare_ms = (t1 - t0) * 1000.0;
        s.create_ms = pipeline.prepare_ms();
        s.commit_ms = (now_s() - t1) * 1000.0;
        s.vram_after = gpu.vram_bytes() / 1048576.0;
        cur_w = s.w;
        cur_h = s.h;
      } else {
        // The same size. The loop makes nothing new, and the picture is not drawn again.
        pipeline.set_nr(false);
        pipeline.set_nr(true);  // so that this step starts without a history all the same
      }
      std::vector<double> nr_ms;
      std::vector<uint8_t> shown, first;
      for (int i = 0; i < switch_frames; ++i) {
        ID3D12Resource* cur = (i % 2 == 0) ? a.Get() : b.Get();
        ID3D12Resource* prev = i == 0 ? nullptr : ((i % 2 == 0) ? b.Get() : a.Get());
        const bool last = i == switch_frames - 1;
        const double t0 = now_s();
        if (!pipeline.ingest(cur, prev, nullptr, 0, changed, err)) return failed(err);
        if (!pipeline.render(cur, back, false, (last || i == 0) && switch_pictures, err)) return failed(err);
        if (!gpu.flush(kWaitMs, err)) return failed(err);
        if (i == 0) s.first_ms = (now_s() - t0) * 1000.0;
        if (i >= switch_frames - kTimedFrames) nr_ms.push_back(pipeline.times().nr_ms);
        // the first picture at the step: how far it is from the picture before the switch,
        // and from the original, which it would equal had the network's change been left out
        if (i == 0 && switch_pictures) {
          if (!pipeline.read_target(first, err)) return failed(err);
          s.first_from_before = mean_abs(first, before_switch);
          s.first_from_plain = mean_abs(first, original);
        }
      }
      s.nr = spread(nr_ms);
      s.vram_mib = gpu.vram_bytes() / 1048576.0;
      if (switch_pictures) {
        if (!pipeline.read_target(shown, err)) return failed(err);
        s.rest_from_first = mean_abs(shown, first);
        s.rest_from_plain = mean_abs(shown, original);
        before_switch = shown;
        s.picture = 1469598103934665603ull;  // FNV-1a over every byte
        for (const uint8_t byte : shown) s.picture = (s.picture ^ byte) * 1099511628211ull;
        for (size_t e = 0; e < switched.size(); ++e) {
          if (switched[e].quality == s.quality && switched[e].picture != 0) {
            s.same_as = (int)e;
            s.same = switched[e].picture == s.picture;
            if (!s.same) switches_ok = false;
            break;
          }
        }
        s.file = strf("composite-switch-%02zu-q%d.png", k, s.quality);
        if (!save_png(path_join(out, widen(s.file)), shown, W, H, err)) return failed(err);
      }
      std::string line = strf("selftest switch %zu: quality %d %s, work %ux%u", k, s.quality,
                              quality_name(s.quality), s.w, s.h);
      if (s.resized) {
        line += strf(", made in %.0f ms beside the old one (creation %.0f ms on the CPU), put in use in %.1f ms",
                     s.prepare_ms, s.create_ms, s.commit_ms);
        if (!sync) {
          line += strf(", %d frames drawn meanwhile, the longest %.1f ms after the one before it", s.held,
                       s.held_gap_ms);
          if (switch_pictures)
            line += s.held_same ? ", each the picture from before the switch" : ", NOT the picture from before the switch";
        }
      } else {
        line += ", the size in use already";
      }
      line += strf(", the first frame took %.1f ms, nr %.3f ms (95th %.3f) over %zu frames, video memory %.0f MiB "
                   "before, %.0f with both, %.0f with the old one released, %.0f after the frames",
                   s.first_ms, s.nr.median, s.nr.p95, s.nr.n, s.vram_before, s.vram_both, s.vram_after, s.vram_mib);
      if (switch_pictures) {
        line += strf(". The first picture is %.3f of 255 from the one before the switch and %.3f from the "
                     "original, the picture at rest %.3f from the first and %.3f from the original",
                     s.first_from_before, s.first_from_plain, s.rest_from_first, s.rest_from_plain);
      }
      if (s.same_as >= 0) {
        line += s.same ? ", the same picture as the first time at this step"
                       : ", NOT the picture of the first time at this step";
      }
      say("%s", line.c_str());
      switched.push_back(s);
    }

    // ---- the rest, --switch-rest S. For S seconds no frame is drawn, only repaints as the
    // loop's heartbeat makes them over a still screen, fifteen a second, which make no call
    // into the runtime. Then frames again. The video memory in use is read at each point. It
    // shows whether the memory of the network that was replaced comes back by itself or only
    // once the runtime is called again.
    if (o.switch_rest_s > 0.0) {
      rest_mib[0] = gpu.vram_bytes() / 1048576.0;
      const double t_end = now_s() + o.switch_rest_s;
      while (now_s() < t_end) {
        if (!pipeline.repaint(back, false, err) || !gpu.flush(kWaitMs, err)) return failed(err);
        Sleep(66);
      }
      rest_mib[1] = gpu.vram_bytes() / 1048576.0;
      for (int i = 0; i < 300; ++i) {
        ID3D12Resource* cur = (i % 2 == 0) ? b.Get() : a.Get();
        ID3D12Resource* prev = (i % 2 == 0) ? a.Get() : b.Get();
        if (!pipeline.ingest(cur, prev, nullptr, 0, changed, err)) return failed(err);
        if (!pipeline.render(cur, back, false, false, err)) return failed(err);
        if (!gpu.flush(kWaitMs, err)) return failed(err);
        if (i == 0) rest_mib[2] = gpu.vram_bytes() / 1048576.0;
        if (i == 9) rest_mib[3] = gpu.vram_bytes() / 1048576.0;
        if (i == 99) rest_mib[4] = gpu.vram_bytes() / 1048576.0;
      }
      rest_mib[5] = gpu.vram_bytes() / 1048576.0;
      say("selftest rest: video memory %.0f MiB after the last switch's frames, %.0f after %.0f s with repaints "
          "alone, then %.0f after 1 frame, %.0f after 10, %.0f after 100 and %.0f after 300",
          rest_mib[0], rest_mib[1], o.switch_rest_s, rest_mib[2], rest_mib[3], rest_mib[4], rest_mib[5]);
    }
  }

  const bool joined_ok = joined_off_exact && joined_on_same && joined_unchanged && joined_tiled && joined_timed;
  const bool checks_ok = same_unchanged && restored_unchanged && found == (int)spots.size() && repaint_same &&
                         sparse_same && native_exact && all_unchanged && off_exact && zero_ran_exact &&
                         zero_off_exact && above_ok && switches_ok && joined_ok && times_bounded && per_pass_ok &&
                         remake_ok;
  {
    FILE* f = _wfopen(path_join(out, L"timings.json").c_str(), L"w");
    if (!f) return failed("cannot write timings.json in " + narrow(out));
    fprintf(f, "{\n");
    fprintf(f, " \"version\": \"%s\",\n", LENS_FAST_VERSION);
    fprintf(f, " \"picture\": \"%s\",\n", json_text(narrow(o.selftest_image)).c_str());
    fprintf(f, " \"adapter\": \"%s\",\n", json_text(gpu.name).c_str());
    fprintf(f, " \"size\": [%u, %u],\n \"work\": [%u, %u],\n \"passes\": %d,\n", W, H, ww, wh, o.passes);
    // the step, and what the table has for it where the picture size is in the table
    if (plan.quality >= 0) {
      fprintf(f, " \"quality\": {\"step\": %d, \"name\": \"%s\", \"asked\": %s, \"measured\": %s", plan.quality,
              quality_name(plan.quality), plan.chosen ? "true" : "false", plan.measured ? "true" : "false");
      double table_ms = 0.0, table_kept = 0.0;
      if (quality_figures((int)W, (int)H, plan.quality, table_ms, table_kept))
        fprintf(f, ", \"table_ms\": %.3f, \"table_kept\": %.4f", table_ms, table_kept);
      fprintf(f, "},\n");
    } else {
      fprintf(f, " \"quality\": null,\n \"work_given_by\": \"%s\",\n", plan.given_by);
    }
    fprintf(f, " \"settings\": {\"style\": %u, \"intensity\": %.2f, \"local_tone\": %.2f, \"local_structure\": %.2f, "
               "\"skin_structure\": %.2f, \"auto_mask\": %d, \"ui_correction\": %d, \"preset\": %u},\n",
            settings.style, settings.intensity, settings.local_tone, settings.local_structure,
            settings.skin_structure, settings.auto_mask, settings.ui_correction, pass_settings.preset);
    // whether the passes ran through the first pass's feature, as the features were made, see NrPasses
    fprintf(f, " \"shared\": %s,\n", pipeline.shared_network() ? "true" : "false");
    // each pass's own values as the file gave them, and what the per pass check found
    fprintf(f, " \"pass_own\": {");
    for (int p = 1; p < o.passes && p < kNrMaxPasses; ++p) {
      fprintf(f, "%s\"%d\": \"%s\"", p > 1 ? ", " : "", p + 1,
              json_text(own_values_text(settings, pass_settings.pass[p])).c_str());
    }
    fprintf(f, "},\n");
    if (o.passes >= 2) {
      // at a strength of 0 in the file the two comparisons named are not judged, see the per pass check
      fprintf(f,
              " \"per_pass\": {\"half_from_equal\": %.4f, \"style_from_equal\": %.4f, \"equal_again_same\": %s, "
              "\"first_from_equal\": %.4f, \"first_from_half\": %.4f%s},\n",
              per_pass_half, per_pass_style, per_pass_again ? "true" : "false", per_pass_first, per_pass_first_half,
              per_pass_at_zero ? ", \"not_judged_at_strength_0\": [\"style_from_equal\", \"first_from_half\"]" : "");
      fprintf(f, " \"remake\": {\"other_from_equal\": %.4f, \"back_same\": %s, \"ok\": %s%s},\n", remake_other,
              remake_back ? "true" : "false", remake_ok ? "true" : "false",
              per_pass_at_zero ? ", \"not_judged_at_strength_0\": [\"other_from_equal\"]" : "");
    }
    fprintf(f, " \"frames\": {\"warm\": %d, \"timed\": %d},\n", kWarmFrames, kTimedFrames);
    fprintf(f, " \"gpu_ms\": {\n  \"ingest\": %s,\n  \"nr\": %s,\n  \"composite\": %s,\n  \"frame\": %s\n },\n",
            json(s_ingest).c_str(), json(s_nr).c_str(), json(s_composite).c_str(), json(s_frame).c_str());
    fprintf(f, " \"cpu_ms\": {\n  \"ingest_call\": %s,\n  \"render_call\": %s,\n  \"frame_start_to_gpu_done\": %s\n },\n",
            json(s_cingest).c_str(), json(s_crender).c_str(), json(s_cframe).c_str());
    fprintf(f, " \"unchanged_frame\": {\n  \"ingest_gpu_ms\": %s,\n  \"ingest_call_cpu_ms\": %s\n },\n",
            json(s_gsame).c_str(), json(s_csame).c_str());
    fprintf(f, " \"create_ms\": %.1f,\n \"init_ms\": %.1f,\n", create_ms, init_ms);
    fprintf(f, " \"vram_mib\": {\"device\": %.1f, \"after_timed_frames\": %.1f},\n", vram_device / 1048576.0,
            vram / 1048576.0);
    fprintf(f, " \"settle\": {\"scroll_frames\": %d, \"scroll_step\": %d, \"mean_abs_from_settled\": [%.4f, %.4f, "
               "%.4f, %.4f, %.4f]},\n",
            kScrollFrames, kScrollStep, settle_from[0], settle_from[1], settle_from[2], settle_from[3],
            settle_from[4]);
    fprintf(f, " \"single_texel_in_its_tile\": %d,\n", tiled);
    fprintf(f, " \"zero_strength\": {\"run_gives_original\": %s, \"run_nr_ms\": %.4f, \"left_out_gives_original\": %s, "
               "\"left_out_nr_ms\": %.4f},\n",
            zero_ran_exact ? "true" : "false", zero_ran_ms, zero_off_exact ? "true" : "false", zero_off_ms);
    // the change from the original with every pass at the base's values and the strength at
    // 1, 1.5 and 2, see the check: the ratios read the scaling, and the outputs were held
    // against the CPU's scaling byte for byte
    fprintf(f, " \"strength_above_1\": {\"change_at_1\": %.4f, \"change_at_1_5\": %.4f, \"change_at_2\": %.4f, "
               "\"ratio_1_5\": %.4f, \"ratio_2\": %.4f, \"back_same\": %s, \"outputs_exact\": %s, \"ok\": %s},\n",
            above_change[0], above_change[1], above_change[2],
            above_change[0] > 0.0 ? above_change[1] / above_change[0] : 0.0,
            above_change[0] > 0.0 ? above_change[2] / above_change[0] : 0.0, above_back ? "true" : "false",
            above_exact ? "true" : "false", above_ok ? "true" : "false");
    if (!switched.empty()) {
      fprintf(f, " \"switch_frames\": %d,\n \"switches\": [\n", switch_frames);
      for (size_t k = 0; k < switched.size(); ++k) {
        const Switched& s = switched[k];
        fprintf(f, "  {\"quality\": %d, \"work\": [%u, %u], \"at_s\": %.3f, \"resized\": %s, \"prepare_ms\": %.1f, "
                   "\"create_ms\": %.1f, "
                   "\"commit_ms\": %.2f, \"first_frame_ms\": %.2f, \"nr_ms\": %s, \"vram_before_mib\": %.1f, "
                   "\"vram_both_mib\": %.1f, \"vram_released_mib\": %.1f, \"vram_mib\": %.1f, "
                   "\"first_from_before\": %.4f, \"first_from_plain\": %.4f, \"rest_from_first\": %.4f, "
                   "\"rest_from_plain\": %.4f, \"held_frames\": %d, \"held_gap_ms\": %.2f, \"held_same\": %s, "
                   "\"file\": \"%s\", \"same_as\": %d, \"same\": %s}%s\n",
                s.quality, s.w, s.h, s.at_s, s.resized ? "true" : "false", s.prepare_ms, s.create_ms, s.commit_ms,
                s.first_ms, json(s.nr).c_str(), s.vram_before, s.vram_both, s.vram_after, s.vram_mib,
                s.first_from_before, s.first_from_plain, s.rest_from_first, s.rest_from_plain, s.held,
                s.held_gap_ms, s.held_same ? "true" : "false", s.file.c_str(), s.same_as,
                s.same_as < 0 ? "null" : (s.same ? "true" : "false"), k + 1 < switched.size() ? "," : "");
      }
      fprintf(f, " ],\n");
      if (o.switch_rest_s > 0.0) {
        fprintf(f, " \"rest\": {\"seconds\": %.1f, \"vram_mib\": {\"before\": %.1f, \"after_rest\": %.1f, "
                   "\"after_1_frame\": %.1f, \"after_10_frames\": %.1f, \"after_100_frames\": %.1f, "
                   "\"after_300_frames\": %.1f}},\n",
                o.switch_rest_s, rest_mib[0], rest_mib[1], rest_mib[2], rest_mib[3], rest_mib[4], rest_mib[5]);
      }
    }
    fprintf(f, " \"checks\": {\"same_picture_unchanged\": %s, \"single_texel_found\": %d, \"single_texel_tried\": %d, "
               "\"put_back_unchanged\": %s, \"repaint_same\": %s, \"sparse_same\": %s, \"native_copy_exact\": %s, "
               "\"unchanged_frames_unchanged\": %s, \"nr_off_exact\": %s, \"zero_strength_exact\": %s, "
               "\"strength_above_1\": %s, \"switches_same\": %s, \"joined_list\": %s, \"times_bounded\": %s, "
               "\"per_pass_values\": %s, \"remake\": %s},\n",
            same_unchanged ? "true" : "false", found, (int)spots.size(), restored_unchanged ? "true" : "false",
            repaint_same ? "true" : "false", sparse_same ? "true" : "false", native_exact ? "true" : "false",
            all_unchanged ? "true" : "false", off_exact ? "true" : "false",
            zero_ran_exact && zero_off_exact ? "true" : "false", above_ok ? "true" : "false",
            switches_ok ? "true" : "false", joined_ok ? "true" : "false", times_bounded ? "true" : "false",
            per_pass_ok ? "true" : "false", remake_ok ? "true" : "false");
    fprintf(f, " \"ok\": %s\n}\n", checks_ok ? "true" : "false");
    fclose(f);
  }

  // ---- down in order: the GPU idle, the network, then the device
  if (!gpu.flush(kWaitMs, err)) note("selftest: %s", err.c_str());
  pipeline.shutdown();
  // the runtime's reads were written when the network shut down
  CopyFileW(path_join(o.data_dir, L"nr-reads.txt").c_str(), path_join(out, L"nr-reads.txt").c_str(), FALSE);
  say("selftest wrote composite.png, nr_in.png, nr_out.png, timings.json and nr-reads.txt in %s", narrow(out).c_str());

  // the textures above are released when this function returns: they keep the device
  // alive until then, whatever order they go in
  gpu.shutdown();

  if (!checks_ok) return failed("a check of the self test did not hold, see the lines above");
  say("selftest ok");
  return exit_code::ok;
}

// ---- the sequence mode, see selftest.h: frame generation with no window, frames from PNGs

namespace {

// Reads a texture of the target's size back into tight RGB8, through a readback buffer of
// its own and a list of its own, waiting for the GPU each time.
struct Reader {
  Gpu* gpu = nullptr;
  ComPtr<ID3D12CommandAllocator> allocator;
  ComPtr<ID3D12GraphicsCommandList> list;
  ComPtr<ID3D12Resource> buffer;
  D3D12_PLACED_SUBRESOURCE_FOOTPRINT fp = {};
  UINT64 bytes = 0;
  UINT64 value = 0;

  bool init(Gpu& g, ID3D12Resource* like, std::string& err) {
    gpu = &g;
    const D3D12_RESOURCE_DESC td = like->GetDesc();
    gpu->device->GetCopyableFootprints(&td, 0, 1, 0, &fp, nullptr, nullptr, &bytes);
    return g.make_list(allocator, list, L"sequence reads", err) &&
           g.make_buffer(bytes, D3D12_HEAP_TYPE_READBACK, D3D12_RESOURCE_STATE_COPY_DEST, D3D12_RESOURCE_FLAG_NONE,
                         L"sequence readback", buffer, err);
  }

  // texture in the state rest, returned to it
  bool read(ID3D12Resource* texture, D3D12_RESOURCE_STATES rest, UINT w, UINT h, std::vector<uint8_t>& rgb,
            std::string& err) {
    if (FAILED(allocator->Reset()) || FAILED(list->Reset(allocator.Get(), nullptr))) {
      err = "resetting the reader's list failed";
      return false;
    }
    transition(list.Get(), texture, rest, D3D12_RESOURCE_STATE_COPY_SOURCE);
    D3D12_TEXTURE_COPY_LOCATION dst = {};
    dst.pResource = buffer.Get();
    dst.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
    dst.PlacedFootprint = fp;
    D3D12_TEXTURE_COPY_LOCATION src = {};
    src.pResource = texture;
    src.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
    list->CopyTextureRegion(&dst, 0, 0, 0, &src, nullptr);
    transition(list.Get(), texture, D3D12_RESOURCE_STATE_COPY_SOURCE, rest);
    if (!gpu->execute(list.Get(), value, err) || !gpu->wait(value, kWaitMs, err)) return false;
    void* p = nullptr;
    const D3D12_RANGE whole = {0, (SIZE_T)bytes};
    if (FAILED(buffer->Map(0, &whole, &p)) || !p) {
      err = "mapping the readback failed";
      return false;
    }
    rgb.resize((size_t)w * h * 3);
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
    buffer->Unmap(0, &none);
    return true;
  }

  // The texture's rows as they are, row_bytes each, into out
  bool read_raw(ID3D12Resource* texture, D3D12_RESOURCE_STATES rest, UINT rows, UINT row_bytes,
                std::vector<uint8_t>& out, std::string& err) {
    if (FAILED(allocator->Reset()) || FAILED(list->Reset(allocator.Get(), nullptr))) {
      err = "resetting the reader's list failed";
      return false;
    }
    transition(list.Get(), texture, rest, D3D12_RESOURCE_STATE_COPY_SOURCE);
    D3D12_TEXTURE_COPY_LOCATION dst = {};
    dst.pResource = buffer.Get();
    dst.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
    dst.PlacedFootprint = fp;
    D3D12_TEXTURE_COPY_LOCATION src = {};
    src.pResource = texture;
    src.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
    list->CopyTextureRegion(&dst, 0, 0, 0, &src, nullptr);
    transition(list.Get(), texture, D3D12_RESOURCE_STATE_COPY_SOURCE, rest);
    if (!gpu->execute(list.Get(), value, err) || !gpu->wait(value, kWaitMs, err)) return false;
    void* p = nullptr;
    const D3D12_RANGE whole = {0, (SIZE_T)bytes};
    if (FAILED(buffer->Map(0, &whole, &p)) || !p) {
      err = "mapping the readback failed";
      return false;
    }
    out.resize((size_t)rows * row_bytes);
    for (UINT y = 0; y < rows; ++y) {
      memcpy(out.data() + (size_t)y * row_bytes, (const uint8_t*)p + fp.Offset + (size_t)y * fp.Footprint.RowPitch,
             row_bytes);
    }
    const D3D12_RANGE none = {0, 0};
    buffer->Unmap(0, &none);
    return true;
  }
};

bool write_file(const std::wstring& path, const std::vector<uint8_t>& data, std::string& err) {
  FILE* f = _wfopen(path.c_str(), L"wb");
  if (!f) {
    err = "cannot write " + narrow(path);
    return false;
  }
  const bool ok = fwrite(data.data(), 1, data.size(), f) == data.size();
  fclose(f);
  if (!ok) err = "writing " + narrow(path) + " failed";
  return ok;
}

std::wstring frame_name(const wchar_t* stem, int n) {
  wchar_t name[32];
  swprintf(name, 32, L"%s%04d.png", stem, n);
  return name;
}

}  // namespace

// A .npy file of float16 RGBA, (h, w, 4), as NumPy writes it: the magic, version 1.0, a header
// line, then the halves tight, top row first. The sequence mode's frames in 16-bit scRGB.
bool load_npy_f16(const std::wstring& path, UINT& w, UINT& h, std::vector<uint8_t>& halves, std::string& err) {
  FILE* f = _wfopen(path.c_str(), L"rb");
  if (!f) {
    err = "cannot read " + narrow(path);
    return false;
  }
  uint8_t pre[10] = {};
  if (fread(pre, 1, 10, f) != 10 || memcmp(pre, "\x93NUMPY", 6) != 0 || pre[6] != 1) {
    fclose(f);
    err = narrow(path) + " is not a version 1 .npy file";
    return false;
  }
  const size_t header_len = (size_t)pre[8] | ((size_t)pre[9] << 8);
  std::string header(header_len, '\0');
  if (fread(&header[0], 1, header_len, f) != header_len) {
    fclose(f);
    err = narrow(path) + ": the header is short";
    return false;
  }
  const size_t shape_at = header.find("'shape': (");
  if (header.find("'<f2'") == std::string::npos || shape_at == std::string::npos) {
    fclose(f);
    err = narrow(path) + " is not float16 with a shape: " + header;
    return false;
  }
  unsigned hh = 0, ww = 0, cc = 0;
  if (sscanf_s(header.c_str() + shape_at + 10, "%u, %u, %u", &hh, &ww, &cc) != 3 || cc != 4 || !hh || !ww) {
    fclose(f);
    err = narrow(path) + ": the shape is not (h, w, 4): " + header;
    return false;
  }
  w = ww;
  h = hh;
  halves.resize((size_t)w * h * 8);
  const bool ok = fread(halves.data(), 1, halves.size(), f) == halves.size();
  fclose(f);
  if (!ok) err = narrow(path) + ": the data is short";
  return ok;
}

bool save_npy_f16(const std::wstring& path, UINT w, UINT h, const std::vector<uint8_t>& halves, std::string& err) {
  std::string dict = "{'descr': '<f2', 'fortran_order': False, 'shape': (" + std::to_string(h) + ", " +
                     std::to_string(w) + ", 4), }";
  while ((10 + dict.size() + 1) % 64 != 0) dict += ' ';
  dict += '\n';
  std::vector<uint8_t> out;
  out.reserve(10 + dict.size() + halves.size());
  const char magic[] = "\x93NUMPY";
  out.insert(out.end(), magic, magic + 6);
  out.push_back(1);
  out.push_back(0);
  out.push_back((uint8_t)(dict.size() & 0xff));
  out.push_back((uint8_t)(dict.size() >> 8));
  out.insert(out.end(), dict.begin(), dict.end());
  out.insert(out.end(), halves.begin(), halves.end());
  return write_file(path, out, err);
}

std::wstring npy_name(const wchar_t* stem, int n) {
  wchar_t name[48];
  swprintf(name, 48, L"%s%04d.npy", stem, n);
  return name;
}

namespace {

// A .npy file as the research's optical flow probe wrote its own: version 1.0, the header dict
// with descr, fortran_order False and the shape, padded with spaces so the data starts on a
// multiple of 64 bytes, then the data. So the flow and the luma the sequence mode writes compare
// whole with the probe's files.
bool save_npy(const std::wstring& path, const char* descr, std::initializer_list<size_t> shape, const void* data,
              size_t bytes, std::string& err) {
  std::string dict = std::string("{'descr': '") + descr + "', 'fortran_order': False, 'shape': (";
  int k = 0;
  for (const size_t s : shape) dict += (k++ ? ", " : "") + std::to_string(s);
  if (shape.size() == 1) dict += ",";
  dict += "), }";
  while ((10 + dict.size() + 1) % 64 != 0) dict += ' ';
  dict += '\n';
  std::vector<uint8_t> out;
  out.reserve(10 + dict.size() + bytes);
  const char magic[] = "\x93NUMPY";
  out.insert(out.end(), magic, magic + 6);
  out.push_back(1);
  out.push_back(0);
  out.push_back((uint8_t)(dict.size() & 0xff));
  out.push_back((uint8_t)(dict.size() >> 8));
  out.insert(out.end(), dict.begin(), dict.end());
  const uint8_t* p = static_cast<const uint8_t*>(data);
  out.insert(out.end(), p, p + bytes);
  return write_file(path, out, err);
}

// A luma for --flow-luma-file, as --sequence-dump luma and the probe's --save-luma write it:
// version 1, 'descr' '|u1', 'fortran_order' False and 'shape' (h, w), the session's padded size,
// then the bytes, top row first. Anything else, a missing file included, fails the run with the
// file named.
bool load_npy_luma(const std::wstring& path, UINT w, UINT h, std::vector<uint8_t>& bytes, std::string& err) {
  const std::string name = "--flow-luma-file: " + narrow(path);
  FILE* f = _wfopen(path.c_str(), L"rb");
  if (!f) {
    err = name + " cannot be read";
    return false;
  }
  uint8_t pre[10] = {};
  if (fread(pre, 1, 10, f) != 10 || memcmp(pre, "\x93NUMPY", 6) != 0 || pre[6] != 1) {
    fclose(f);
    err = name + " is not a version 1 .npy file";
    return false;
  }
  const size_t header_len = (size_t)pre[8] | ((size_t)pre[9] << 8);
  std::string header(header_len, '\0');
  if (fread(&header[0], 1, header_len, f) != header_len) {
    fclose(f);
    err = name + ": the header is short";
    return false;
  }
  const auto value_of = [&](const char* key) -> std::string {
    const size_t at = header.find(key);
    if (at == std::string::npos) return std::string();
    size_t from = at + strlen(key);
    while (from < header.size() && (header[from] == ':' || header[from] == ' ')) ++from;
    return header.substr(from);
  };
  const std::string descr = value_of("'descr'");
  const std::string order = value_of("'fortran_order'");
  const std::string shape = value_of("'shape'");
  unsigned hh = 0, ww = 0;
  char close = 0;
  if (descr.compare(0, 5, "'|u1'") != 0 || order.compare(0, 5, "False") != 0 ||
      sscanf_s(shape.c_str(), "(%u, %u%c", &hh, &ww, &close, 1u) != 3 || close != ')') {
    fclose(f);
    err = name + " is not uint8 ('|u1') in C order with a shape of two: " + header;
    return false;
  }
  if (hh != h || ww != w) {
    fclose(f);
    err = name + strf(" has the shape (%u, %u), and the unit wants (%u, %u)", hh, ww, h, w);
    return false;
  }
  bytes.resize((size_t)w * h);
  bool ok = fread(bytes.data(), 1, bytes.size(), f) == bytes.size();
  uint8_t more = 0;
  const bool longer = ok && fread(&more, 1, 1, f) == 1;
  fclose(f);
  if (!ok) err = name + ": the data is short";
  if (longer) err = name + ": the file is longer than its shape";
  return ok && !longer;
}

// The sequence mode's research switches for the network's motion vectors, from the comma list
// of --sequence-lab, each word whole. The words for frame generation (nocoarse, levels1,
// levels2, fixedgate) are looked up by run_sequence() itself, as they always were.
struct MotionLab {
  float factor = 1.0f;        // mvneg turns every vector round, mvscale:S multiplies it by S
  bool constant = false;      // mvconst:DX:DY one vector everywhere, in work texels, previous
  float cx = 0.0f, cy = 0.0f; // minus current; mvzero the same with zeros
  bool all_passes = false;    // mvallpasses: every pass handed the vectors in the shared mode
  bool no_estimator = false;  // noestimator: the estimator refused, as on a card without one
  bool no_flow = false;       // noflow refuses the optical flow unit, as on a card without one
  std::string words;          // the switches taken, for the first line
};

MotionLab motion_lab(const std::string& list) {
  MotionLab lab;
  size_t at = 0;
  while (at <= list.size()) {
    const size_t comma = std::min(list.find(',', at), list.size());
    const std::string word = list.substr(at, comma - at);
    at = comma + 1;
    bool taken = true;
    float a = 0.0f, b = 0.0f;
    if (word == "mvneg") {
      lab.factor = -lab.factor;
    } else if (sscanf_s(word.c_str(), "mvscale:%f", &a) == 1) {
      lab.factor *= a;
    } else if (sscanf_s(word.c_str(), "mvconst:%f:%f", &a, &b) == 2) {
      lab.constant = true;
      lab.cx = a;
      lab.cy = b;
    } else if (word == "mvzero") {
      lab.constant = true;
      lab.cx = lab.cy = 0.0f;
    } else if (word == "mvallpasses") {
      lab.all_passes = true;
    } else if (word == "noestimator") {
      lab.no_estimator = true;
    } else if (word == "noflow") {
      lab.no_flow = true;
    } else {
      taken = false;
    }
    if (taken) lab.words += (lab.words.empty() ? "" : ",") + word;
  }
  return lab;
}

// A half as a float, for the sums of a field read back: the sign, five bits of exponent, ten
// of fraction, the subnormals included. The field holds no infinity or NaN.
float half_value(uint16_t h) {
  const int exponent = (h >> 10) & 0x1F;
  const int fraction = h & 0x3FF;
  float v = exponent == 0 ? (float)fraction * (1.0f / 16777216.0f)
                          : std::ldexp(1.0f + (float)fraction / 1024.0f, exponent - 15);
  return (h & 0x8000) ? -v : v;
}

// The card's last estimate as the network's motion vectors, see Pipeline::set_model_motion, the
// research switches with it.
ModelMotion estimate_for_network(const FrameGen& gen, const MotionLab& lab) {
  ModelMotion m;
  m.vectors = gen.vectors.Get();
  m.vec_w = gen.vec_width();
  m.vec_h = gen.vec_height();
  m.me_w = gen.me_width();
  m.me_h = gen.me_height();
  m.factor = lab.factor;
  m.constant = lab.constant;
  m.cx = lab.cx;
  m.cy = lab.cy;
  m.all_passes = lab.all_passes;
  return m;
}

// One scripted run of frames for --motion-cases, through model_motion.h as the loop goes
// through it. Each letter is a draw or an event:
//   N  a new frame
//   R  a new frame whose render resets the network (a crop's jump, a resume, a settings change
//      that resets, the first frame at a new work size)
//   S  a settle run of the frame on screen, or an again run
//   F  the estimator forgets its frames: a pause, a recapture, a crop's step, the network
//      switched, a reload, frame generation switched
//   X  a new frame whose estimate fails
//   H  a new frame while another work size is being made: the network does not run, and
//      frame generation goes on estimating
//   J  a joined frame, LENS_FAST_JOIN, which wants no estimate for the network
//   Z  a new frame while NRMotionSource says none and nothing else wants the estimate
//   U  a new frame whose optical flow fails, with Edges cut
//   V  a new frame with Edges cut on a card whose optical flow unit is refused
// Frame generation is off but where H says otherwise, and the Look stage's filter off. With
// edges false NRMotionSource says Card, with edges true Edges cut, and the optical flow unit
// then runs on every new frame whose estimate the network is to be handed, after the
// estimate, and forgets with the estimator. What each draw hands the network, in order: cut
// (the estimate with the edges cut), card or zero.
std::string motion_case(const char* script, bool edges) {
  MotionPair pair;
  int have = 0;   // FrameGen's frames since it last forgot, 2 at most, see FrameGen::estimate
  int fhave = 0;  // the optical flow unit's, the same way, see Flow::submit
  std::string out;
  for (const char* c = script; *c; ++c) {
    const char e = *c;
    if (e == 'F') {
      have = 0;
      fhave = 0;
      continue;
    }
    if (!out.empty()) out += " ";
    if (e == 'S') {
      pair.drew(true);  // the same frame once more, with no estimate of its own
      out += "zero";
      continue;
    }
    pair.new_frame();
    const bool network = e != 'H';
    const bool model_wants = network && e != 'Z' && e != 'J';  // as estimate_motion() in main.cpp
    bool ready = false;
    bool estimated = false;
    if (motion_wanted(e == 'H' ? 1 : 0, false, model_wants)) {
      if (e == 'X') {
        pair.estimated(false, false);  // the estimate returns before the frames move on
      } else {
        ready = have >= 1;
        have = std::min(have + 1, 2);
        pair.estimated(true, ready);
        estimated = true;
      }
    }
    if (edges && model_wants && estimated && e != 'V') {
      if (e == 'U') {
        pair.flowed(false, false);  // the flow fails before the unit's frames move on
      } else {
        const bool flow_ready = fhave >= 1;
        fhave = std::min(fhave + 1, 2);
        pair.flowed(true, flow_ready);
      }
    }
    // a render that resets reads no history, see Pipeline::set_model_motion
    const bool fed = feed_model(pair, model_wants, e == 'J', ready) && e != 'R';
    const bool cut = fed && edges && pair.cut_ok();
    pair.drew(network);
    out += cut ? "cut" : fed ? "card" : "zero";
  }
  return out;
}

}  // namespace

int run_motion_cases() {
  struct Case {
    const char* name;
    const char* script;
  };
  const Case cases[] = {
      {"first frames", "NNN"},     {"settle", "NNSSN"},          {"forget", "NNFNN"},
      {"failed estimate", "NNXNN"}, {"hold", "NNHHRN"},           {"key none to card", "ZZFNN"},
      {"joined", "NNJJNN"},         {"reset", "NNRN"},
  };
  for (const Case& c : cases) say("motion case %s %s: %s", c.name, c.script, motion_case(c.script, false).c_str());
  // the same with Edges cut, where the optical flow unit's pair decides the cut, see model_motion.h
  const Case edge_cases[] = {
      {"edges first frames", "NNN"},     {"edges settle", "NNSSN"},     {"edges forget", "NNFNN"},
      {"edges failed estimate", "NNXNN"}, {"edges failed flow", "NNUNN"}, {"edges refused", "VVV"},
  };
  for (const Case& c : edge_cases) {
    say("motion case %s %s: %s", c.name, c.script, motion_case(c.script, true).c_str());
  }
  return exit_code::ok;
}

int run_sequence(const Options& o) {
  std::string err;
  const HRESULT com = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
  if (FAILED(com) && com != RPC_E_CHANGED_MODE) return failed("COM did not start " + hr_text(com));
  const int stride = o.sequence_stride > 0 ? o.sequence_stride : 2;
  const int mode = o.framegen == 1 ? 1 : 0;  // ahead, else between
  // Frame generation is off only where --framegen off was given: without --framegen the run is
  // between, as it always was
  const bool gen_on = !(o.framegen_given && o.framegen == 0);
  const bool settle_run = o.sequence_settle > 0;  // --sequence-settle, see below
  const bool hdr = o.sequence_white > 0.0;   // 16-bit scRGB frames through the HDR path
  const DXGI_FORMAT fmt = hdr ? DXGI_FORMAT_R16G16B16A16_FLOAT : DXGI_FORMAT_B8G8R8A8_UNORM;
  const MotionLab lab = motion_lab(o.sequence_lab);

  // ---- the sources: every stride-th frame, until one is missing
  std::vector<std::wstring> sources;
  for (int i = 0;; i += stride) {
    const std::wstring path = path_join(o.sequence_dir, hdr ? npy_name(L"f", i) : frame_name(L"f", i));
    if (GetFileAttributesW(path.c_str()) == INVALID_FILE_ATTRIBUTES) break;
    sources.push_back(path);
  }
  if (sources.size() < 2) {
    return failed("the sequence needs two source frames at least, f0000.png and f" + std::to_string(stride) +
                  " in " + narrow(o.sequence_dir));
  }
  if (!make_dirs(o.selftest_outdir)) return failed("cannot create " + narrow(o.selftest_outdir));
  Picture first;  // in HDR its bgra holds the halves, 8 bytes a texel
  if (hdr ? !load_npy_f16(sources[0], first.w, first.h, first.bgra, err) : !load_picture(sources[0], first, err))
    return failed(err);
  const UINT W = first.w, H = first.h;
  const WorkPlan plan = work_plan((int)W, (int)H, o);
  NrPasses pass_settings;
  if (!read_nr_passes(o.stack_dir, pass_settings, err, o.passes)) {
    note("sequence: %s, the runtime's defaults are used", err.c_str());
  }
  take_motion_option(o, pass_settings);

  // ---- the device, the target, the pipeline and the frame generation
  Gpu gpu;
  if (!gpu.init(nullptr, err)) return failed(err);
  Loader loader;
  if (!loader.init(gpu, W, H, err, fmt)) return failed(err);
  ComPtr<ID3D12Resource> target;
  if (!gpu.make_texture(fmt, W, H, D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET, D3D12_RESOURCE_STATE_PRESENT,
                        L"sequence target", target, err))
    return failed(err);
  ComPtr<ID3D12DescriptorHeap> rtv_heap;
  {
    D3D12_DESCRIPTOR_HEAP_DESC d = {};
    d.Type = D3D12_DESCRIPTOR_HEAP_TYPE_RTV;
    d.NumDescriptors = 1;
    const HRESULT hr = gpu.device->CreateDescriptorHeap(&d, IID_PPV_ARGS(&rtv_heap));
    if (FAILED(hr)) return failed("the target's descriptor heap failed " + hr_text(hr));
  }
  Target back;
  back.texture = target.Get();
  back.rtv = rtv_heap->GetCPUDescriptorHandleForHeapStart();
  back.width = W;
  back.height = H;
  back.format = fmt;
  gpu.device->CreateRenderTargetView(target.Get(), nullptr, back.rtv);
  PipelineDesc desc;
  desc.width = W;
  desc.height = H;
  desc.work_w = (UINT)plan.w;
  desc.work_h = (UINT)plan.h;
  desc.passes = o.passes;
  desc.stack_dir = o.stack_dir;
  desc.data_dir = o.data_dir;
  desc.settings = pass_settings;
  Pipeline pipeline;
  if (!pipeline.init(gpu, desc, err)) return failed(err);
  pipeline.set_nr(o.sequence_nr);
  if (hdr) pipeline.set_sdr_white(o.sequence_white);
  Reader reader;
  if (!reader.init(gpu, target.Get(), err)) return failed(err);
  std::vector<uint8_t> rgb;
  // A picture of the target, as it stands after the last draw, into OUTDIR as STEM-N
  const auto save_target = [&](const wchar_t* stem, int n) -> bool {
    if (hdr) {
      return reader.read_raw(target.Get(), D3D12_RESOURCE_STATE_PRESENT, H, W * 8, rgb, err) &&
             save_npy_f16(path_join(o.selftest_outdir, npy_name(stem, n)), W, H, rgb, err);
    }
    return reader.read(target.Get(), D3D12_RESOURCE_STATE_PRESENT, W, H, rgb, err) &&
           save_png(path_join(o.selftest_outdir, frame_name(stem, n)), rgb, W, H, err);
  };
  // A source as a frame texture of the capture's kind
  const auto load_source = [&](size_t k, ComPtr<ID3D12Resource>& out) -> bool {
    Picture pic;
    if (k == 0) {
      pic = first;
    } else if (hdr ? !load_npy_f16(sources[k], pic.w, pic.h, pic.bgra, err) : !load_picture(sources[k], pic, err)) {
      return false;
    }
    if (pic.w != W || pic.h != H) {
      err = "frame " + narrow(sources[k]) + " is not the first frame's size";
      return false;
    }
    out.Reset();
    return loader.frame(pic.bgra, L"sequence frame", out, err);
  };

  // ---- --sequence-settle K: the references a measure of the network in motion holds its
  // pictures against. Each source alone, from a reset, as if it had stood still: rendered K
  // times, as the loop's settle renders a picture at rest with zero vectors, and written as
  // settled-N, then 8 more times, written as settled2-N, whose distance from settled-N is the
  // network's own unrest at rest. No estimate and no made picture
  if (settle_run) {
    say("sequence %s: %zu sources, a stride of %d, %ux%u, work %dx%d, each source settled from a reset, %d runs "
        "and 8 more, network %s, motion none%s",
        narrow(o.sequence_dir).c_str(), sources.size(), stride, W, H, plan.w, plan.h, o.sequence_settle,
        o.sequence_nr ? "on" : "off",
        hdr ? strf(", 16-bit scRGB at an SDR white of %.2f", o.sequence_white).c_str() : "");
    const double t0 = now_s();
    for (size_t k = 0; k < sources.size(); ++k) {
      ComPtr<ID3D12Resource> cur;
      if (!load_source(k, cur)) return failed(err);
      bool changed = false;
      if (!pipeline.ingest(cur.Get(), nullptr, nullptr, 0, changed, err)) return failed(err);
      const int n = (int)(k * stride);
      for (int r = 0; r < o.sequence_settle + 8; ++r) {
        if (!pipeline.render(cur.Get(), back, r == 0, false, err)) return failed(err);
        if (r + 1 == o.sequence_settle && !save_target(L"settled-", n)) return failed(err);
      }
      if (!save_target(L"settled2-", n)) return failed(err);
      if (!gpu.flush(kWaitMs, err)) return failed(err);
    }
    say("sequence done: %zu sources settled in %.1f s, in %s", sources.size(), now_s() - t0,
        narrow(o.selftest_outdir).c_str());
    return 0;
  }

  // ---- what wants the motion estimate, as the loop has it (model_motion.h): frame generation,
  // the Look stage's filter, and the network where NRMotionSource says the card's estimate
  const bool look_wants = pass_settings.look.wants_motion();
  const bool source_card = takes_card_estimate(pass_settings.look.motion_source);
  const bool source_edges = pass_settings.look.motion_source == kMotionCardEdges;
  const bool model_wants = source_card && pipeline.network_runs();
  FrameGen gen;
  gen.lab_levels = o.sequence_lab.find("nocoarse") != std::string::npos ? 0
                   : o.sequence_lab.find("levels1") != std::string::npos ? 1
                   : o.sequence_lab.find("levels2") != std::string::npos ? 2 : FrameGen::kLevels;
  gen.lab_fixed_gate = o.sequence_lab.find("fixedgate") != std::string::npos;
  if (hdr) gen.sdr_white = (float)o.sequence_white;
  bool have_gen = false;
  std::string no_estimator;  // why there is none where one was wanted
  if (motion_wanted(gen_on ? 1 : 0, look_wants, model_wants)) {
    if (lab.no_estimator) {
      no_estimator = "the motion estimator is switched off for a test";
    } else if (gen.init(gpu, W, H, fmt, err)) {
      have_gen = true;
    } else {
      no_estimator = err;
    }
    if (!have_gen && gen_on) return failed("frame generation: " + no_estimator);
    if (!have_gen) gen.shutdown();  // said after the first line, as the loop says it, once
  }
  // the coarser levels only for frame generation, as in the loop: the network and the Look
  // stage take the fine estimate alone
  gen.coarse_on = gen_on;
  Reader vectors_reader, field_reader;
  if (have_gen && !vectors_reader.init(gpu, gen.vectors.Get(), err)) return failed(err);
  bool field_reader_made = false;
  std::vector<uint8_t> raw;
  // the optical flow unit for --motion edges where the network is handed the estimate, made
  // after the estimator, at whose picture it takes the luma, see flow.h. Refused, the run goes
  // on with the card's estimate whole, as the loop does. --sequence-lab noflow refuses it as on
  // a card without one, as LENS_FAST_NO_FLOW=1 does in the loop
  Flow flow;
  bool have_flow = false;
  std::string no_flow;  // why there is none where one was wanted
  if (source_edges && model_wants && have_gen) {
    if (hdr) flow.sdr_white = (float)o.sequence_white;
    if (lab.no_flow) {
      no_flow = "the optical flow unit is switched off for a test";
    } else if (flow.init(gpu, W, H, gen.me_width(), gen.me_height(), err)) {
      have_flow = true;
    } else {
      no_flow = err;
    }
    for (const std::string& line : flow.report()) note("sequence: flow: %s", line.c_str());
  }
  const bool flow_file = !o.sequence_flow_luma.empty();  // --flow-luma-file
  if ((flow_file || o.sequence_dump_flow || o.sequence_dump_luma || o.sequence_dump_zones) && !have_flow) {
    return failed(no_flow.empty() ? std::string("--sequence-dump flow, luma or zones and --flow-luma-file need the "
                                                "optical flow unit, which runs with --motion edges and the network on")
                                  : "--sequence-dump flow, luma or zones and --flow-luma-file need the optical flow "
                                    "unit, which is unavailable, " + no_flow);
  }
  const std::string motion_text =
      !source_card ? std::string("motion none")
      : (!have_gen && !no_estimator.empty()) ? "motion none, no motion estimator (" + no_estimator + ")"
      : have_flow ? strf("motion edges, the flow at %ux%u in %ux%u cells", flow.me_w, flow.me_h, flow.crop_w,
                         flow.crop_h)
      : !no_flow.empty() ? "motion card, no optical flow (" + no_flow + ")"
      : source_edges     ? std::string("motion edges")
                         : std::string("motion card");
  const std::string estimator_text =
      have_gen ? strf("the estimator at %ux%u in %ux%u blocks, the coarser ones %s", gen.me_width(), gen.me_height(),
                      gen.vec_width(), gen.vec_height(),
                      gen.has_coarse() && gen_on ? strf("at %s", gen.level_text().c_str()).c_str() : "not made")
               : std::string("no estimator");
  say("sequence %s: %zu sources, a stride of %d, %ux%u, work %dx%d, %s, network %s, %s, lab %s%s, %s",
      narrow(o.sequence_dir).c_str(), sources.size(), stride, W, H, plan.w, plan.h,
      gen_on ? (mode == 1 ? "ahead" : "between") : "frame generation off", o.sequence_nr ? "on" : "off",
      estimator_text.c_str(), o.sequence_lab.empty() ? "none" : o.sequence_lab.c_str(),
      hdr ? strf(", 16-bit scRGB at an SDR white of %.2f", o.sequence_white).c_str() : "", motion_text.c_str());
  if (!no_estimator.empty()) {
    note("sequence: framegen: %s, so no motion estimate", no_estimator.c_str());
    say("framegen unavailable %s", no_estimator.c_str());
  }
  if (!no_flow.empty()) {
    note("sequence: edges: %s, so the network gets the card's estimate whole", no_flow.c_str());
    say("edges unavailable %s", no_flow.c_str());
  }
  std::vector<uint8_t> file_luma, flow_raw;   // --flow-luma-file's bytes, and the unit's readbacks
  std::vector<float> flow_f;                  // a flow for its dump
  std::vector<double> flow_ms, copy_in_ms, execute_ms, copy_out_ms, luma_ms;  // the unit's cost, a frame each
  std::vector<double> zone_ms;                // the edge detector's three passes, a frame each
  std::vector<double> cut_ms;                 // the cut, a frame each where it ran
  Reader zone_reader;                         // the zone for its dump, made at the first
  bool zone_reader_made = false;

  // ---- the frames, in order, as the loop takes a capture's: every source is new to it
  ComPtr<ID3D12Resource> prev, cur;
  MotionPair pair;
  int made = 0, estimates = 0, fed_frames = 0;
  int cut_frames = 0;  // renders handed the field with the edges cut, a zone of one texel or more
  double prep_ms = 0.0, estimate_ms = 0.0, draw_ms = 0.0;  // the cost, summed over the frames
  double fine_gpu_ms = 0.0, coarse_gpu_ms = 0.0;           // the estimates by the encode queue's clock
  double nr_gpu_ms = 0.0;                                  // the network's passes, with the
  int nr_runs = 0;                                         // vectors' resolve where it ran
  const double t0 = now_s();
  for (size_t k = 0; k < sources.size(); ++k) {
    const int n = (int)(k * stride);  // the source's frame
    if (!load_source(k, cur)) return failed(err);
    pair.new_frame();
    bool ready = false;
    UINT64 read_value = 0;
    if (have_gen) {
      if (!gen.estimate(cur.Get(), ready, read_value, err)) return failed("estimate: " + err);
      pair.estimated(true, ready);
    }
    if (have_flow) {
      // the optical flow unit on the same frame after the estimator's conversion, the luma list
      // on the queue and the unit's work behind it, nothing waited for, see flow.h. With
      // --flow-luma-file the file's luma takes the luma pass's place
      if (flow_file && !load_npy_luma(path_join(o.sequence_flow_luma, npy_name(L"luma-", n)), flow.pad_w,
                                      flow.pad_h, file_luma, err))
        return failed(err);
      UINT64 flow_read = 0;
      if (!flow.submit(cur.Get(), flow_file ? file_luma.data() : nullptr, flow_read, err))
        return failed("flow: " + err);
      pair.flowed(true, flow.ready());
    }
    if (ready) {
      ++estimates;
      // the estimate's time by the clock: from the conversion's end, which the encode queue
      // waits for, to the estimate's fence
      if (!gpu.wait(gen.prep_value, kWaitMs, err)) return failed(err);
      const double te = now_s();
      if (gen.encode_fence && gen.encode_fence->GetCompletedValue() < gen.encode_value) {
        gen.encode_fence->SetEventOnCompletion(gen.encode_value, gen.encode_event);
        WaitForSingleObject(gen.encode_event, kWaitMs);
      }
      estimate_ms += (now_s() - te) * 1000.0;
    }
    bool changed = false;
    if (!pipeline.ingest(cur.Get(), prev.Get(), nullptr, 0, changed, err)) return failed(err);
    // the motion for the render, as the loop's estimate_motion() hands it over: the queue waits
    // for the estimate before the render reads it
    const bool feed = feed_model(pair, model_wants, false, ready);
    // the edge detector, where the network is handed the estimate and the unit's flow spans the
    // same two frames (cut_ok, model_motion.h), after the queue's wait for the flow and before
    // its wait for the estimate, see edges.h. Its zone is cut into the field after the resolve
    const bool detected = have_flow && feed && pair.cut_ok();
    if (detected) {
      if (!flow.wait_on_queue(err)) return failed("flow: " + err);
      if (!pipeline.detect_edges(edge_flow_of(flow), err)) return failed("edges: " + err);
    }
    const bool look_motion = ready && look_wants;
    if ((feed || look_motion) && !gen.wait_estimate_on_queue(err)) return failed(err);
    if (look_motion) {
      pipeline.set_motion(gen.vectors_texture(), gen.vec_width(), gen.vec_height(), gen.cell_texels((UINT)plan.w),
                          gen.unit_texels((UINT)plan.w));
    } else {
      pipeline.set_motion(nullptr, 0, 0, 1.0f, 0.0f);
    }
    if (feed) {
      ModelMotion mm = estimate_for_network(gen, lab);
      mm.cut = detected;
      pipeline.set_model_motion(mm);
    }
    if (!pipeline.render(cur.Get(), back, k == 0, false, err)) return failed(err);
    pair.drew(pipeline.network_runs());
    if (pipeline.motion_fed(0)) ++fed_frames;
    const bool cut = pipeline.motion_fed(0) && pipeline.motion_cut();
    if (o.sequence_save_nr && !save_target(L"nr-", n)) return failed(err);
    if (o.sequence_dump_fed) {
      // what each pass was handed, and the field itself where it was
      UINT fw = 0, fh = 0;
      ID3D12Resource* field = pipeline.motion_field(fw, fh);
      std::string field_text;
      if (pipeline.motion_fed(0) && field) {
        if (!field_reader_made) {
          if (!field_reader.init(gpu, field, err)) return failed(err);
          field_reader_made = true;
        }
        if (!field_reader.read_raw(field, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE, fh, fw * 4, raw, err))
          return failed(err);
        wchar_t name[32];
        swprintf(name, 32, L"fed-%04d.bin", n);
        if (!write_file(path_join(o.selftest_outdir, name), raw, err)) return failed(err);
        double sx = 0.0, sy = 0.0;
        size_t zero = 0;
        const uint16_t* v = (const uint16_t*)raw.data();
        const size_t count = (size_t)fw * fh;
        for (size_t i = 0; i < count; ++i) {
          sx += half_value(v[2 * i]);
          sy += half_value(v[2 * i + 1]);
          if ((v[2 * i] & 0x7FFF) == 0 && (v[2 * i + 1] & 0x7FFF) == 0) ++zero;
        }
        const ModelMotion mm = estimate_for_network(gen, lab);
        field_text = strf(", field %ux%u R16G16_FLOAT, subrect 0 0 %u %u, scale 1 1, unit %.6f %.6f, mean %.4f %.4f, "
                          "zero share %.2f%%",
                          fw, fh, fw, fh, mm.constant ? 0.0 : 0.25 * fw / mm.me_w * mm.factor,
                          mm.constant ? 0.0 : 0.25 * fh / mm.me_h * mm.factor, sx / (double)count,
                          sy / (double)count, 100.0 * (double)zero / (double)count);
        // the cut, by the detector's counts, whose list came before the render's and is done
        // with the field's readback
        if (cut) {
          EdgeCounts ec;
          if (!pipeline.edge_counts(ec)) return failed("edges: the detector's counts are not there after the render");
          field_text = (ec.guarded ? std::string(" (guarded)") : strf(", edges cut, zone %u texels", ec.zoned)) +
                       field_text;
        } else if (have_flow) {
          field_text = " (the flow does not span the same two frames)" + field_text;
        }
      }
      for (int p = 0; p < o.passes; ++p) {
        std::string what;
        if (pipeline.motion_fed(p)) what = "card" + field_text;
        else if (!source_card) what = strf("none (%s)", o.motion >= 0 ? "--motion" : "NRMotionSource");
        else if (!pipeline.network_runs()) what = "none (the network is off)";
        else if (!have_gen) what = "none (no motion estimator)";
        else if (k == 0) what = "zero (the first frame, a reset)";
        else if (!ready) what = "zero (no estimate)";
        else if (!feed) what = "zero (the estimate does not start from the network's last frame)";
        else if (p > 0) what = "zero (a later pass of the shared mode)";
        else what = "zero";
        say("sequence fed %04d pass %d %s", n, p + 1, what.c_str());
      }
    }
    if (o.sequence_dump_vectors && ready) {
      // the estimate for this source, int16 pairs, as the estimator gives them
      if (!vectors_reader.read_raw(gen.vectors.Get(), D3D12_RESOURCE_STATE_COMMON, gen.vec_height(),
                                   gen.vec_width() * 4, raw, err))
        return failed(err);
      wchar_t name[40];
      swprintf(name, 40, L"vectors-src-%04d.bin", n);
      if (!write_file(path_join(o.selftest_outdir, name), raw, err)) return failed(err);
    }
    if (gen_on) {
      if (!gen.keep(back, err)) return failed("keep: " + err);
      if (ready) {
        // drawn sixteen times over, so the card's clock is up by the last, whose time the cost
        // line reports: a frame at a time with the CPU waiting between, the card idles and
        // clocks down, and one cold draw measured two to three times its busy cost
        for (int r = 0; r < 16; ++r) {
          if (!gen.draw_made(back, mode, 0.5f, err)) return failed("draw: " + err);
        }
        const int at = mode == 0 ? (int)(k * stride) - stride / 2 : (int)(k * stride) + stride / 2;
        if (!save_target(L"made-", at)) return failed(err);
        // the vectors the picture was made from, int16 pairs, as the estimator gives them
        if (!vectors_reader.read_raw(gen.vectors.Get(), D3D12_RESOURCE_STATE_COMMON, gen.vec_height(),
                                     gen.vec_width() * 4, raw, err))
          return failed(err);
        {
          wchar_t name[32];
          swprintf(name, 32, L"vectors-%04d.bin", at);
          if (!write_file(path_join(o.selftest_outdir, name), raw, err)) return failed(err);
        }
        ++made;
      }
    }
    // the queue waits for the unit's frame too, so its readbacks and times follow the flush
    if (have_flow && !flow.wait_on_queue(err)) return failed("flow: " + err);
    if (!gpu.flush(kWaitMs, err)) return failed(err);
    if (have_flow) {
      if (o.sequence_dump_luma) {
        // the luma the unit was given, as the probe's --save-luma writes it
        if (!flow.read_luma(flow_raw, err) ||
            !save_npy(path_join(o.selftest_outdir, npy_name(L"luma-", n)), "|u1", {flow.pad_h, flow.pad_w},
                      flow_raw.data(), flow_raw.size(), err))
          return failed("flow: " + err);
      }
      if (flow.ready() && o.sequence_dump_flow) {
        // the int16 pairs over 32 into float32, over the cells of the picture alone, as the
        // probe's flow-N.npy
        if (!flow.read_flow(flow_raw, err)) return failed("flow: " + err);
        const int16_t* pairs = (const int16_t*)flow_raw.data();
        flow_f.resize((size_t)flow.crop_w * flow.crop_h * 2);
        for (UINT y = 0; y < flow.crop_h; ++y) {
          for (UINT x = 0; x < flow.crop_w; ++x) {
            const int16_t* p = pairs + ((size_t)y * flow.cells_w + x) * 2;
            flow_f[((size_t)y * flow.crop_w + x) * 2 + 0] = (float)p[0] / 32.0f;
            flow_f[((size_t)y * flow.crop_w + x) * 2 + 1] = (float)p[1] / 32.0f;
          }
        }
        if (!save_npy(path_join(o.selftest_outdir, npy_name(L"flow-", n)), "<f4", {flow.crop_h, flow.crop_w, 2},
                      flow_f.data(), flow_f.size() * 4, err))
          return failed("flow: " + err);
      }
      const FlowTimes ft = flow.times();
      if (ft.luma_valid) luma_ms.push_back(ft.luma_ms);
      if (flow.ready() && ft.unit_valid) {
        flow_ms.push_back(ft.copy_in_ms + ft.execute_ms + ft.copy_out_ms);
        copy_in_ms.push_back(ft.copy_in_ms);
        execute_ms.push_back(ft.execute_ms);
        copy_out_ms.push_back(ft.copy_out_ms);
      }
    }
    if (detected) {
      // what the edge detector found, its list done with the flush
      EdgeCounts ec;
      if (!pipeline.edge_counts(ec)) return failed("edges: the detector's counts are not there after the flush");
      zone_ms.push_back(ec.ms);
      if (cut) {
        if (!ec.guarded && ec.zoned > 0) ++cut_frames;
        double ms = 0.0;
        if (!pipeline.cut_ms(ms)) return failed("edges: the cut's time is not there after the flush");
        cut_ms.push_back(ms);
      }
      if (o.sequence_dump_zones) {
        // the zone, 1 inside and 0 elsewhere, as bool, work_h rows of work_w
        UINT zw = 0, zh = 0;
        ID3D12Resource* zone = pipeline.zone_texture(zw, zh);
        if (!zone || zw != ec.w || zh != ec.h) return failed("edges: no zone to read");
        if (!zone_reader_made) {
          if (!zone_reader.init(gpu, zone, err)) return failed(err);
          zone_reader_made = true;
        }
        if (!zone_reader.read_raw(zone, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE, zh, zw, raw, err) ||
            !save_npy(path_join(o.selftest_outdir, npy_name(L"zone-", n)), "|b1", {zh, zw}, raw.data(), raw.size(),
                      err))
          return failed("edges: " + err);
        say("sequence zone %04d count %u of %u, limit %u, guarded %s, zoned %u", n, ec.marked, ec.interior, ec.limit,
            ec.guarded ? "yes" : "no", ec.zoned);
      }
    }
    if (have_gen) prep_ms += gen.last_prep_ms();
    if (ready) {
      if (gen_on) draw_ms += gen.last_draw_ms();
      fine_gpu_ms += gen.last_estimate_ms();
      coarse_gpu_ms += gen.last_coarse_estimate_ms();
    }
    const StageTimes times = pipeline.times();
    if (times.ran_network) {
      nr_gpu_ms += times.nr_ms;
      ++nr_runs;
    }
    prev = cur;
  }
  say("sequence done: %d made pictures from %zu sources in %.1f s, in %s", made, sources.size(), now_s() - t0,
      narrow(o.selftest_outdir).c_str());
  // the optical flow unit's cost as medians over the frames, its own work on its queue for the
  // frames it compared and the luma pass for every frame, and the edge detector's for the
  // frames it ran on
  const auto median = [](std::vector<double> v) {
    if (v.empty()) return 0.0;
    std::sort(v.begin(), v.end());
    return v.size() % 2 ? v[v.size() / 2] : 0.5 * (v[v.size() / 2 - 1] + v[v.size() / 2]);
  };
  const std::string flow_cost =
      (flow_ms.empty() ? std::string()
                       : strf(", the flow %.3f ms (copy in %.3f, execute %.3f, copy out %.3f), the luma %.3f ms",
                              median(flow_ms), median(copy_in_ms), median(execute_ms), median(copy_out_ms),
                              median(luma_ms))) +
      (zone_ms.empty() ? std::string() : strf(", the zone %.3f ms", median(zone_ms))) +
      (cut_ms.empty() ? std::string() : strf(", the cut %.3f ms", median(cut_ms)));
  const std::string network_cost =
      (nr_runs > 0 ? strf(", the network %.3f ms", nr_gpu_ms / (double)nr_runs) : std::string()) + flow_cost;
  if (made > 0) {
    say("sequence cost a frame: the conversion %.3f ms, the estimate %.3f ms by the clock (%.3f fine + %.3f coarse "
        "on the card), the warp %.3f ms%s",
        prep_ms / (double)sources.size(), estimate_ms / (double)made, fine_gpu_ms / (double)made,
        coarse_gpu_ms / (double)made, draw_ms / (double)made, network_cost.c_str());
  } else {
    // no made picture: the estimates alone, where there were any, and the network
    say("sequence cost a frame: no made pictures, %d estimates%s%s", estimates,
        estimates > 0 ? strf(", the conversion %.3f ms, the estimate %.3f ms by the clock (%.3f fine + %.3f coarse "
                             "on the card)",
                             prep_ms / (double)sources.size(), estimate_ms / (double)estimates,
                             fine_gpu_ms / (double)estimates, coarse_gpu_ms / (double)estimates)
                                .c_str()
                      : "",
        network_cost.c_str());
  }
  if (model_wants) {
    // with the unit, how many of them had the edges cut, a zone of one texel or more
    say("sequence motion: %d of %zu sources handed the network the card's estimate%s", fed_frames, sources.size(),
        have_flow ? strf(", %d of them with the edges cut", cut_frames).c_str() : "");
  }
  flow.shutdown();
  gen.shutdown();
  return 0;
}
