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
//   per pass  with --passes 2 or more, the second pass at values of its own gives another
//             picture than every pass at the base's values, the base's values again give
//             the first picture back byte for byte, and the first pass at half the strength
//             gives another picture than the second at half, so each pass takes its own slot's
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

  bool init(Gpu& g, UINT width, UINT height, std::string& err) {
    gpu = &g;
    w = width;
    h = height;
    D3D12_RESOURCE_DESC d = {};
    d.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
    d.Width = w;
    d.Height = h;
    d.DepthOrArraySize = 1;
    d.MipLevels = 1;
    d.Format = DXGI_FORMAT_B8G8R8A8_UNORM;
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
    if (!gpu->make_texture(DXGI_FORMAT_B8G8R8A8_UNORM, w, h, D3D12_RESOURCE_FLAG_NONE, D3D12_RESOURCE_STATE_COMMON,
                           name, out, err))
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
    for (UINT y = 0; y < h; ++y)
      memcpy(p + fp.Offset + (size_t)y * fp.Footprint.RowPitch, bgra.data() + (size_t)y * w * 4, (size_t)w * 4);
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
                               plan.chosen ? "as asked" : "the default for this size",
                               plan.measured ? "a measured size" : "by the rule")
                        : strf("quality none, the work size was given by %s", plan.given_by);
  say("selftest picture %s %ux%u, work %dx%d, passes %d, %s", narrow(o.selftest_image).c_str(), W, H, work_w,
      work_h, o.passes, step_text.c_str());

  std::vector<uint8_t> original((size_t)W * H * 3);  // tight RGB8, what "nr off" must give back
  for (size_t i = 0, n = (size_t)W * H; i < n; ++i) {
    original[i * 3] = picture.bgra[i * 4 + 2];
    original[i * 3 + 1] = picture.bgra[i * 4 + 1];
    original[i * 3 + 2] = picture.bgra[i * 4];
  }

  // the base and each pass's own values, as the loop reads them, see NrPasses
  NrPasses pass_settings;
  if (!read_nr_passes(o.stack_dir, pass_settings, err, o.passes)) {
    note("selftest: %s, the runtime's defaults are used", err.c_str());
  }
  const NrSettings settings = pass_settings.base();

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
  if (o.passes >= 2) {
    const NrSettings base = settings;
    per_pass_at_zero = !(base.intensity > 0.0f);
    const float halved = base.intensity > 0.0f ? base.intensity * 0.5f : 0.5f;
    NrPasses equal(base);
    NrPasses half(base);
    half.pass[1].intensity = halved;
    NrPasses styled(base);
    styled.pass[1].style = (base.style + 1) % 3;
    NrPasses first(base);
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
                         zero_off_exact && switches_ok && joined_ok && times_bounded && per_pass_ok;
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
               "\"skin_structure\": %.2f, \"auto_mask\": %d},\n",
            settings.style, settings.intensity, settings.local_tone, settings.local_structure,
            settings.skin_structure, settings.auto_mask);
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
               "\"switches_same\": %s, \"joined_list\": %s, \"times_bounded\": %s, \"per_pass_values\": %s},\n",
            same_unchanged ? "true" : "false", found, (int)spots.size(), restored_unchanged ? "true" : "false",
            repaint_same ? "true" : "false", sparse_same ? "true" : "false", native_exact ? "true" : "false",
            all_unchanged ? "true" : "false", off_exact ? "true" : "false",
            zero_ran_exact && zero_off_exact ? "true" : "false", switches_ok ? "true" : "false",
            joined_ok ? "true" : "false", times_bounded ? "true" : "false", per_pass_ok ? "true" : "false");
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
