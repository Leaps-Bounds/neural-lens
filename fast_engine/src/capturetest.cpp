// capturetest.cpp: the capture on its own, read from a bare D3D12 device. The contract is
// capturetest.h.
//
// What a run shows, with no window and no network:
//   - That the D3D12 side reads real pixels. The first frame is read back whole, written to
//     build\capturetest\first-frame.png for a person to look at, and compared with what GDI
//     reads from the same rectangle of the screen. After that a 64x64 block from the middle
//     of every frame is read and averaged, and once a second set against GDI's read of the
//     same block, so the numbers follow the screen.
//   - That the slots keep their promise: the frame handed out before is read again while
//     the new one is in use and must not have changed, and what was handed out before a
//     stop must still be there after the next start.
//   - What arrives: frames a second, drops, the callback's cost, how old a frame is when
//     the loop gets it, and whether the copy into the slot is already done by then.
//   - That start and stop can be repeated: five more sessions, each has to deliver a frame,
//     and the video memory and the handles in use must not grow.
//
// The reader is a plain D3D12 device and queue of the test's own, used the way the pipeline
// will use the engine's: the queue waits for the shared fence, then reads the slot between
// a transition from COMMON and one back to it.
#include "capturetest.h"

#include "capture.h"

#include <objbase.h>

#include <d3d12.h>
#include <dxgi1_6.h>
#include <wincodec.h>
#include <wrl/client.h>

#include <algorithm>
#include <cmath>
#include <cstring>
#include <limits>
#include <string>
#include <vector>

using Microsoft::WRL::ComPtr;

namespace {

constexpr int kBlock = 64;            // the side of the block read from every frame
constexpr DWORD kGpuWaitMs = 2000;    // as Pipeline::ingest: give up after 2 s
constexpr UINT64 kSecondBlock = 65536;  // where the second block of one read goes in the buffer

const double kNan = std::numeric_limits<double>::quiet_NaN();

double median_of(std::vector<double> v) {
  if (v.empty()) return kNan;
  std::sort(v.begin(), v.end());
  return v[v.size() / 2];
}

double largest_of(const std::vector<double>& v) {
  return v.empty() ? kNan : *std::max_element(v.begin(), v.end());
}

double smallest_of(const std::vector<double>& v) {
  return v.empty() ? kNan : *std::min_element(v.begin(), v.end());
}

double mean_of(const std::vector<double>& v) {
  if (v.empty()) return kNan;
  double sum = 0.0;
  for (double x : v) sum += x;
  return sum / (double)v.size();
}

// The mean of blue, green and red over a BGRA picture, out of 255.
double mean_bgr(const std::vector<uint8_t>& bgra) {
  if (bgra.size() < 4) return kNan;
  unsigned long long sum = 0;
  for (size_t i = 0; i + 3 < bgra.size(); i += 4) sum += bgra[i] + bgra[i + 1] + bgra[i + 2];
  return (double)sum / (double)(bgra.size() / 4 * 3);
}

// How alike two BGRA pictures of one size are, alpha left out.
struct Likeness {
  double mean_abs = kNan;     // mean absolute difference of the colour bytes, out of 255
  double equal_share = kNan;  // the share of texels whose three colour bytes are all equal
};

Likeness compare_bgr(const std::vector<uint8_t>& a, const std::vector<uint8_t>& b) {
  Likeness out;
  if (a.size() != b.size() || a.size() < 4) return out;
  unsigned long long sum = 0;
  size_t equal = 0;
  const size_t texels = a.size() / 4;
  for (size_t i = 0; i < texels; ++i) {
    const uint8_t* p = &a[i * 4];
    const uint8_t* q = &b[i * 4];
    const int d = std::abs(p[0] - q[0]) + std::abs(p[1] - q[1]) + std::abs(p[2] - q[2]);
    sum += (unsigned)d;
    if (d == 0) ++equal;
  }
  out.mean_abs = (double)sum / (double)(texels * 3);
  out.equal_share = (double)equal / (double)texels;
  return out;
}

// What GDI reads from a rectangle of the screen: BGRA, top row first. It is a second way
// to the same pixels that owes nothing to the capture or to D3D, and it shows nothing.
// Like the capture it leaves out the cursor and windows excluded from capture.
bool gdi_read(int x, int y, int w, int h, std::vector<uint8_t>& bgra) {
  bool ok = false;
  HDC screen = GetDC(nullptr);
  HDC memory = screen ? CreateCompatibleDC(screen) : nullptr;
  BITMAPINFO info = {};
  info.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
  info.bmiHeader.biWidth = w;
  info.bmiHeader.biHeight = -h;  // top row first
  info.bmiHeader.biPlanes = 1;
  info.bmiHeader.biBitCount = 32;
  info.bmiHeader.biCompression = BI_RGB;
  void* bits = nullptr;
  HBITMAP bitmap =
      memory ? CreateDIBSection(memory, &info, DIB_RGB_COLORS, &bits, nullptr, 0) : nullptr;
  if (bitmap && bits) {
    HGDIOBJ old = SelectObject(memory, bitmap);
    if (BitBlt(memory, 0, 0, w, h, screen, x, y, SRCCOPY)) {
      GdiFlush();
      bgra.resize((size_t)w * (size_t)h * 4);
      memcpy(bgra.data(), bits, bgra.size());
      ok = true;
    }
    SelectObject(memory, old);
  }
  if (bitmap) DeleteObject(bitmap);
  if (memory) DeleteDC(memory);
  if (screen) ReleaseDC(nullptr, screen);
  return ok;
}

// Whether the desktop programs draw on is the one a person sees. With the workstation
// locked the input desktop is the logon screen's and a capture shows no real picture.
bool desktop_is_the_users() {
  HDESK desk = OpenInputDesktop(0, FALSE, DESKTOP_READOBJECTS);
  if (!desk) return false;
  wchar_t name[64] = {};
  DWORD need = 0;
  GetUserObjectInformationW(desk, UOI_NAME, name, sizeof(name) - sizeof(wchar_t), &need);
  CloseDesktop(desk);
  return _wcsicmp(name, L"Default") == 0;
}

// An 8 bit BGR picture as a PNG, through the Windows Imaging Component. bgr is tight:
// w * h * 3 bytes, top row first.
bool write_png(const std::wstring& path, const std::vector<uint8_t>& bgr, int w, int h,
               std::string& err) {
  const HRESULT com = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
  HRESULT hr = S_OK;
  {
    ComPtr<IWICImagingFactory> factory;
    ComPtr<IWICStream> stream;
    ComPtr<IWICBitmapEncoder> encoder;
    ComPtr<IWICBitmapFrameEncode> frame;
    WICPixelFormatGUID format = GUID_WICPixelFormat24bppBGR;
    hr = CoCreateInstance(CLSID_WICImagingFactory, nullptr, CLSCTX_INPROC_SERVER,
                          IID_PPV_ARGS(&factory));
    if (SUCCEEDED(hr)) hr = factory->CreateStream(&stream);
    if (SUCCEEDED(hr)) hr = stream->InitializeFromFilename(path.c_str(), GENERIC_WRITE);
    if (SUCCEEDED(hr)) hr = factory->CreateEncoder(GUID_ContainerFormatPng, nullptr, &encoder);
    if (SUCCEEDED(hr)) hr = encoder->Initialize(stream.Get(), WICBitmapEncoderNoCache);
    if (SUCCEEDED(hr)) hr = encoder->CreateNewFrame(&frame, nullptr);
    if (SUCCEEDED(hr)) hr = frame->Initialize(nullptr);
    if (SUCCEEDED(hr)) hr = frame->SetSize((UINT)w, (UINT)h);
    if (SUCCEEDED(hr)) hr = frame->SetPixelFormat(&format);
    if (SUCCEEDED(hr) && !IsEqualGUID(format, GUID_WICPixelFormat24bppBGR)) hr = E_FAIL;
    if (SUCCEEDED(hr)) {
      hr = frame->WritePixels((UINT)h, (UINT)w * 3, (UINT)bgr.size(),
                              const_cast<BYTE*>(bgr.data()));
    }
    if (SUCCEEDED(hr)) hr = frame->Commit();
    if (SUCCEEDED(hr)) hr = encoder->Commit();
  }
  if (SUCCEEDED(com)) CoUninitialize();
  if (FAILED(hr)) {
    err = "cannot write " + narrow(path) + " " + hr_text(hr);
    return false;
  }
  return true;
}

// BGRA to tight BGR, shrunk by a whole factor with a box filter. factor 1 only drops alpha.
std::vector<uint8_t> to_bgr(const std::vector<uint8_t>& bgra, int w, int h, int factor, int& out_w,
                            int& out_h) {
  out_w = w / factor;
  out_h = h / factor;
  std::vector<uint8_t> out((size_t)out_w * (size_t)out_h * 3);
  const unsigned area = (unsigned)(factor * factor);
  for (int y = 0; y < out_h; ++y) {
    for (int x = 0; x < out_w; ++x) {
      unsigned sum[3] = {0, 0, 0};
      for (int j = 0; j < factor; ++j) {
        const uint8_t* p = &bgra[((size_t)(y * factor + j) * (size_t)w + (size_t)(x * factor)) * 4];
        for (int i = 0; i < factor; ++i, p += 4) {
          sum[0] += p[0];
          sum[1] += p[1];
          sum[2] += p[2];
        }
      }
      uint8_t* q = &out[((size_t)y * (size_t)out_w + (size_t)x) * 3];
      q[0] = (uint8_t)((sum[0] + area / 2) / area);
      q[1] = (uint8_t)((sum[1] + area / 2) / area);
      q[2] = (uint8_t)((sum[2] + area / 2) / area);
    }
  }
  return out;
}

// Where the pictures go: fast_engine\build\capturetest when the program runs from
// fast_engine\bin, where build.cmd puts it, and the temporary folder anywhere else.
std::wstring picture_dir() {
  std::wstring dir;
  const std::wstring build = path_join(exe_dir(), L"..\\build");
  if (dir_exists(build)) {
    dir = path_join(build, L"capturetest");
  } else {
    wchar_t temp[MAX_PATH + 2] = {};
    const DWORD n = GetTempPathW(MAX_PATH + 1, temp);
    dir = path_join(path_join(n ? std::wstring(temp, n) : std::wstring(L"."), L"lens-fast"),
                    L"capturetest");
  }
  wchar_t full[MAX_PATH * 2] = {};
  const DWORD n = GetFullPathNameW(dir.c_str(), MAX_PATH * 2, full, nullptr);
  return n > 0 && n < MAX_PATH * 2 ? std::wstring(full, n) : dir;
}

// ---------------------------------------------------------------- the D3D12 side

// The device and queue the test reads slots with. It does not come from gpu.cpp: the
// capture is to be proven against plain D3D12, with nothing of the engine in between.
struct Reader {
  ComPtr<IDXGIAdapter3> adapter;
  ComPtr<ID3D12Device> device;
  ComPtr<ID3D12CommandQueue> queue;
  ComPtr<ID3D12CommandAllocator> allocator;
  ComPtr<ID3D12GraphicsCommandList> list;
  ComPtr<ID3D12Fence> fence;
  HANDLE fence_event = nullptr;
  UINT64 fence_value = 0;
  ComPtr<ID3D12Resource> readback;  // room for the whole slot, or for two blocks
  LUID luid = {};
  std::string name;
  bool shows_monitor = false;

  ~Reader() {
    if (fence_event) CloseHandle(fence_event);
  }

  // The adapter whose output shows the monitor, as Gpu::init picks it, or the first
  // hardware adapter in the high performance order when none lists it.
  bool init(HMONITOR monitor, int W, int H, std::string& err) {
    ComPtr<IDXGIFactory6> factory;
    HRESULT hr = CreateDXGIFactory1(IID_PPV_ARGS(&factory));
    if (FAILED(hr)) {
      err = "CreateDXGIFactory1 failed " + hr_text(hr);
      return false;
    }
    ComPtr<IDXGIAdapter1> chosen;
    ComPtr<IDXGIAdapter1> first;
    for (UINT a = 0; !chosen; ++a) {
      ComPtr<IDXGIAdapter1> candidate;
      if (FAILED(factory->EnumAdapterByGpuPreference(a, DXGI_GPU_PREFERENCE_HIGH_PERFORMANCE,
                                                     IID_PPV_ARGS(&candidate)))) {
        break;
      }
      DXGI_ADAPTER_DESC1 desc = {};
      candidate->GetDesc1(&desc);
      if (desc.Flags & DXGI_ADAPTER_FLAG_SOFTWARE) continue;
      if (!first) first = candidate;
      for (UINT i = 0;; ++i) {
        ComPtr<IDXGIOutput> output;
        if (FAILED(candidate->EnumOutputs(i, &output))) break;
        DXGI_OUTPUT_DESC shown = {};
        output->GetDesc(&shown);
        if (shown.Monitor == monitor) {
          chosen = candidate;
          shows_monitor = true;
          break;
        }
      }
    }
    if (!chosen) chosen = first;
    if (!chosen) {
      err = "no hardware adapter";
      return false;
    }
    DXGI_ADAPTER_DESC1 desc = {};
    chosen->GetDesc1(&desc);
    luid = desc.AdapterLuid;
    name = ascii(desc.Description);
    chosen.As(&adapter);

    hr = D3D12CreateDevice(chosen.Get(), D3D_FEATURE_LEVEL_12_0, IID_PPV_ARGS(&device));
    if (FAILED(hr)) {
      err = "D3D12CreateDevice failed " + hr_text(hr);
      return false;
    }
    D3D12_COMMAND_QUEUE_DESC qd = {};
    qd.Type = D3D12_COMMAND_LIST_TYPE_DIRECT;
    hr = device->CreateCommandQueue(&qd, IID_PPV_ARGS(&queue));
    if (SUCCEEDED(hr)) {
      hr = device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT, IID_PPV_ARGS(&allocator));
    }
    if (SUCCEEDED(hr)) {
      hr = device->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_DIRECT, allocator.Get(), nullptr,
                                     IID_PPV_ARGS(&list));
    }
    if (SUCCEEDED(hr)) hr = list->Close();
    if (SUCCEEDED(hr)) hr = device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&fence));
    if (FAILED(hr)) {
      err = "the D3D12 queue could not be made " + hr_text(hr);
      return false;
    }
    fence_event = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    if (!fence_event) {
      err = "no event for the D3D12 fence";
      return false;
    }

    // a row of a readback is padded to 256 bytes
    const UINT64 whole = (((UINT64)W * 4 + 255) & ~255ull) * (UINT64)H;
    const UINT64 bytes = std::max<UINT64>(whole, kSecondBlock * 2);
    D3D12_HEAP_PROPERTIES heap = {};
    heap.Type = D3D12_HEAP_TYPE_READBACK;
    D3D12_RESOURCE_DESC rd = {};
    rd.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
    rd.Width = bytes;
    rd.Height = 1;
    rd.DepthOrArraySize = 1;
    rd.MipLevels = 1;
    rd.SampleDesc.Count = 1;
    rd.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
    hr = device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &rd,
                                         D3D12_RESOURCE_STATE_COPY_DEST, nullptr,
                                         IID_PPV_ARGS(&readback));
    if (FAILED(hr)) {
      err = strf("no readback buffer of %llu bytes %s", (unsigned long long)bytes,
                 hr_text(hr).c_str());
      return false;
    }
    return true;
  }

  bool begin(std::string& err) {
    HRESULT hr = allocator->Reset();
    if (SUCCEEDED(hr)) hr = list->Reset(allocator.Get(), nullptr);
    if (FAILED(hr)) {
      err = "the command list could not be reset " + hr_text(hr);
      return false;
    }
    return true;
  }

  // Records the copy of the w x h box at (x, y) of a slot into the readback buffer at
  // offset, a multiple of 512. The slot is in COMMON, as the capture hands it out, and
  // is put back there.
  void copy(ID3D12Resource* texture, int x, int y, int w, int h, UINT64 offset) {
    D3D12_RESOURCE_BARRIER barrier = {};
    barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    barrier.Transition.pResource = texture;
    barrier.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
    barrier.Transition.StateBefore = D3D12_RESOURCE_STATE_COMMON;
    barrier.Transition.StateAfter = D3D12_RESOURCE_STATE_COPY_SOURCE;
    list->ResourceBarrier(1, &barrier);
    D3D12_TEXTURE_COPY_LOCATION to = {};
    to.pResource = readback.Get();
    to.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
    to.PlacedFootprint.Offset = offset;
    to.PlacedFootprint.Footprint.Format = DXGI_FORMAT_B8G8R8A8_UNORM;
    to.PlacedFootprint.Footprint.Width = (UINT)w;
    to.PlacedFootprint.Footprint.Height = (UINT)h;
    to.PlacedFootprint.Footprint.Depth = 1;
    to.PlacedFootprint.Footprint.RowPitch = ((UINT)w * 4 + 255) & ~255u;
    D3D12_TEXTURE_COPY_LOCATION from = {};
    from.pResource = texture;
    from.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
    from.SubresourceIndex = 0;
    const D3D12_BOX box = {(UINT)x, (UINT)y, 0, (UINT)(x + w), (UINT)(y + h), 1};
    list->CopyTextureRegion(&to, 0, 0, 0, &from, &box);
    barrier.Transition.StateBefore = D3D12_RESOURCE_STATE_COPY_SOURCE;
    barrier.Transition.StateAfter = D3D12_RESOURCE_STATE_COMMON;
    list->ResourceBarrier(1, &barrier);
  }

  // Runs what was recorded and waits for it. With a shared fence the queue first waits for
  // it to reach value, on the GPU's side, as Pipeline::ingest does: that is the capture's
  // copy into the slot finishing on the other device.
  bool submit(ID3D12Fence* shared, UINT64 value, std::string& err) {
    HRESULT hr = list->Close();
    if (FAILED(hr)) {
      err = "the command list could not be closed " + hr_text(hr);
      return false;
    }
    if (shared) {
      hr = queue->Wait(shared, value);
      if (FAILED(hr)) {
        err = "the queue could not wait for the shared fence " + hr_text(hr);
        return false;
      }
    }
    ID3D12CommandList* lists[] = {list.Get()};
    queue->ExecuteCommandLists(1, lists);
    hr = queue->Signal(fence.Get(), ++fence_value);
    if (SUCCEEDED(hr) && fence->GetCompletedValue() < fence_value) {
      hr = fence->SetEventOnCompletion(fence_value, fence_event);
      if (SUCCEEDED(hr) && WaitForSingleObject(fence_event, kGpuWaitMs) != WAIT_OBJECT_0) {
        const HRESULT removed = device->GetDeviceRemovedReason();
        err = FAILED(removed) ? "device removed " + hr_text(removed)
                              : strf("the GPU did not finish in %lu ms", (unsigned long)kGpuWaitMs);
        return false;
      }
    }
    if (FAILED(hr)) {
      err = "the queue could not be waited for " + hr_text(hr);
      return false;
    }
    return true;
  }

  // The w x h picture a copy() put at offset, as tight BGRA.
  bool fetch(UINT64 offset, int w, int h, std::vector<uint8_t>& bgra, std::string& err) {
    const size_t pitch = ((size_t)w * 4 + 255) & ~(size_t)255;
    const D3D12_RANGE range = {(SIZE_T)offset,
                               (SIZE_T)(offset + pitch * (size_t)(h - 1) + (size_t)w * 4)};
    void* mapped = nullptr;
    const HRESULT hr = readback->Map(0, &range, &mapped);
    if (FAILED(hr)) {
      err = "the readback buffer could not be mapped " + hr_text(hr);
      return false;
    }
    bgra.resize((size_t)w * (size_t)h * 4);
    const uint8_t* base = (const uint8_t*)mapped + offset;
    for (int row = 0; row < h; ++row) {
      memcpy(&bgra[(size_t)row * (size_t)w * 4], base + (size_t)row * pitch, (size_t)w * 4);
    }
    const D3D12_RANGE none = {0, 0};
    readback->Unmap(0, &none);
    return true;
  }

  // MiB of this process's video memory on the adapter, both devices together.
  double video_memory_mib() const {
    DXGI_QUERY_VIDEO_MEMORY_INFO info = {};
    if (!adapter ||
        FAILED(adapter->QueryVideoMemoryInfo(0, DXGI_MEMORY_SEGMENT_GROUP_LOCAL, &info))) {
      return kNan;
    }
    return (double)info.CurrentUsage / 1048576.0;
  }
};

// ---------------------------------------------------------------- what a run keeps

struct Run {
  Reader& reader;
  Capture& capture;
  int W = 0;
  int H = 0;
  int bx = 0, by = 0, bw = 0, bh = 0;  // the block: the middle of the slot

  // the frame handed out last, and its block as it read when the frame was new
  ID3D12Resource* last_texture = nullptr;
  std::vector<uint8_t> last_block;
  double last_stamp = 0.0;
  bool follows = false;  // whether the next frame follows the last without a gap of the
                         // test's own making: the long first read, or a stop and a start

  unsigned acquired = 0;
  unsigned copy_done_at_acquire = 0;  // the shared fence had already reached the frame's value
  unsigned prev_checks = 0;           // times the frame before was read again
  unsigned prev_changed = 0;          // of those, times it no longer held what it held
  unsigned same_twice = 0;            // the same texture handed out twice running
  std::vector<ID3D12Resource*> textures;  // the distinct ones seen
  std::vector<double> interval_ms;    // between consecutive frames, by their own timestamps
  std::vector<double> age_ms;         // acquire minus the frame's timestamp
  std::vector<double> read_ms;        // the fence wait, the copy and the readback together
  double block_mean = kNan;

  Run(Reader& r, Capture& c, int w, int h) : reader(r), capture(c), W(w), H(h) {
    bw = std::min(kBlock, W);
    bh = std::min(kBlock, H);
    bx = (W - bw) / 2;
    by = (H - bh) / 2;
  }

  void seen(const CaptureFrame& f, double at) {
    age_ms.push_back((at - f.timestamp_s) * 1000.0);
    if (follows) interval_ms.push_back((f.timestamp_s - last_stamp) * 1000.0);
    ID3D12Fence* shared = capture.fence();
    if (shared && shared->GetCompletedValue() >= f.fence_value) ++copy_done_at_acquire;
    if (f.texture == last_texture) ++same_twice;
    if (std::find(textures.begin(), textures.end(), f.texture) == textures.end()) {
      textures.push_back(f.texture);
    }
  }

  // The first frame: the whole slot is read back, and the block is cut out of it.
  bool take_whole(const CaptureFrame& f, std::vector<uint8_t>& whole, std::string& err) {
    const double at = now_s();
    seen(f, at);
    if (!reader.begin(err)) return false;
    reader.copy(f.texture, 0, 0, W, H, 0);
    if (!reader.submit(capture.fence(), f.fence_value, err)) return false;
    if (!reader.fetch(0, W, H, whole, err)) return false;
    read_ms.push_back((now_s() - at) * 1000.0);
    last_block.resize((size_t)bw * (size_t)bh * 4);
    for (int row = 0; row < bh; ++row) {
      memcpy(&last_block[(size_t)row * (size_t)bw * 4],
             &whole[((size_t)(by + row) * (size_t)W + (size_t)bx) * 4], (size_t)bw * 4);
    }
    block_mean = mean_bgr(last_block);
    last_texture = f.texture;
    last_stamp = f.timestamp_s;
    follows = false;
    ++acquired;
    return true;
  }

  // Every other frame: its block, and in the same list the block of the frame before,
  // which the capture promises is still valid and unchanged.
  bool take(const CaptureFrame& f, std::string& err) {
    const double at = now_s();
    seen(f, at);
    const bool check_prev = last_texture && last_texture != f.texture;
    if (!reader.begin(err)) return false;
    reader.copy(f.texture, bx, by, bw, bh, 0);
    if (check_prev) reader.copy(last_texture, bx, by, bw, bh, kSecondBlock);
    if (!reader.submit(capture.fence(), f.fence_value, err)) return false;
    std::vector<uint8_t> block;
    if (!reader.fetch(0, bw, bh, block, err)) return false;
    if (check_prev) {
      std::vector<uint8_t> again;
      if (!reader.fetch(kSecondBlock, bw, bh, again, err)) return false;
      ++prev_checks;
      if (again != last_block) ++prev_changed;
    }
    read_ms.push_back((now_s() - at) * 1000.0);
    block_mean = mean_bgr(block);
    last_block.swap(block);
    last_texture = f.texture;
    last_stamp = f.timestamp_s;
    follows = true;
    ++acquired;
    return true;
  }

  // Reads the block of the frame handed out last once more and says whether it still holds
  // what it held. For the promise that a stop and a start leave it alone.
  bool last_still_there(bool& same, std::string& err) {
    same = true;
    if (!last_texture) return true;
    if (!reader.begin(err)) return false;
    reader.copy(last_texture, bx, by, bw, bh, 0);
    if (!reader.submit(nullptr, 0, err)) return false;
    std::vector<uint8_t> again;
    if (!reader.fetch(0, bw, bh, again, err)) return false;
    same = again == last_block;
    return true;
  }
};

// Waits until the capture has a frame to hand out, timeout_ms at most.
bool wait_frame(Capture& capture, HANDLE event, DWORD timeout_ms, CaptureFrame& out) {
  const double end = now_s() + (double)timeout_ms / 1000.0;
  for (;;) {
    if (capture.acquire(out)) return true;
    const double left = end - now_s();
    if (left <= 0.0) return false;
    WaitForSingleObject(event, (DWORD)std::min(100.0, std::ceil(left * 1000.0)));
  }
}

void add(CaptureCounters& total, const CaptureCounters& c) {
  total.arrived += c.arrived;
  total.dropped += c.dropped;
  total.unfit += c.unfit;
  if (c.unfit) {
    total.unfit_w = c.unfit_w;
    total.unfit_h = c.unfit_h;
  }
  total.callback_ms += c.callback_ms;
  total.callbacks += c.callbacks;
}

DWORD handle_count() {
  DWORD n = 0;
  GetProcessHandleCount(GetCurrentProcess(), &n);
  return n;
}

}  // namespace

int run_capturetest(const Options& o) {
  set_dpi_aware();
  std::string err;
  const int W = o.width;
  const int H = o.height;

  const HMONITOR monitor = monitor_under(o.x, o.y, W, H);
  MONITORINFOEXW mi = {};
  mi.cbSize = sizeof(mi);
  if (!monitor || !GetMonitorInfoW(monitor, &mi)) {
    fail("no monitor under the rectangle");
    return exit_code::failed;
  }
  const int mon_w = mi.rcMonitor.right - mi.rcMonitor.left;
  const int mon_h = mi.rcMonitor.bottom - mi.rcMonitor.top;
  double hz = 60.0;
  DEVMODEW mode = {};
  mode.dmSize = sizeof(mode);
  if (EnumDisplaySettingsW(mi.szDevice, ENUM_CURRENT_SETTINGS, &mode) &&
      mode.dmDisplayFrequency > 1) {
    hz = (double)mode.dmDisplayFrequency;
  }
  const int interval = capture_interval_ms(o.max_fps, hz);
  // where the capture will put the crop, and so where on the screen GDI has to look
  const int crop_x = std::clamp(o.crop_x, 0, std::max(0, mon_w - W));
  const int crop_y = std::clamp(o.crop_y, 0, std::max(0, mon_h - H));
  const int screen_x = mi.rcMonitor.left + crop_x;
  const int screen_y = mi.rcMonitor.top + crop_y;

  Reader reader;
  if (!reader.init(monitor, W, H, err)) {
    fail("%s", err.c_str());
    return exit_code::failed;
  }
  say("capturetest monitor %dx%d at (%d,%d), %.0f Hz, shown by %s%s", mon_w, mon_h,
      (int)mi.rcMonitor.left, (int)mi.rcMonitor.top, hz, reader.name.c_str(),
      reader.shows_monitor ? "" : " (not the adapter that shows it)");
  say("capturetest lens %dx%d, crop (%d,%d) which is (%d,%d) in the monitor, interval %d ms, "
      "for %.1f s",
      W, H, o.crop_x, o.crop_y, crop_x, crop_y, interval, o.capturetest_seconds);
  if (!desktop_is_the_users()) {
    say("capturetest warning: the input desktop is not the user's, the workstation is probably "
        "locked and the picture will not be the screen");
  }

  HANDLE frame_event = CreateEventW(nullptr, FALSE, FALSE, nullptr);
  if (!frame_event) {
    fail("no event for the frames");
    return exit_code::failed;
  }
  Capture capture;
  Run run(reader, capture, W, H);
  auto failed = [&](const std::string& why) {
    fail("%s", why.c_str());
    capture.destroy();
    CloseHandle(frame_event);
    return (int)exit_code::failed;
  };

  // ---- the first session, and the first frame read back whole
  const double mib_before = reader.video_memory_mib();
  const double t_start = now_s();
  if (!capture.start(reader.device.Get(), reader.luid, monitor, W, H, o.crop_x, o.crop_y, interval,
                     frame_event, err)) {
    return failed(err);
  }
  const double start_ms = (now_s() - t_start) * 1000.0;
  const bool border_off = capture.borderless();
  const double mib_started = reader.video_memory_mib();

  CaptureFrame frame;
  if (!wait_frame(capture, frame_event, 5000, frame)) {
    const CaptureCounters c = capture.take_counters();
    if (c.unfit) {
      return failed(
          strf("frames of %dx%d do not cover a lens of %dx%d", c.unfit_w, c.unfit_h, W, H));
    }
    return failed("no frame arrived within 5 s of the start");
  }
  const double first_frame_ms = (now_s() - t_start) * 1000.0;
  std::vector<uint8_t> whole;
  if (!run.take_whole(frame, whole, err)) return failed(err);
  const double whole_read_ms = run.read_ms.back();
  std::vector<uint8_t> gdi_whole;
  const bool gdi_ok = gdi_read(screen_x, screen_y, W, H, gdi_whole);
  const double mib_first = reader.video_memory_mib();
  say("capturetest start took %.1f ms, the first frame was there after %.1f ms, reading all of "
      "it back took %.1f ms",
      start_ms, first_frame_ms, whole_read_ms);

  // ---- the timed part. What piled up behind the long read above is not the measurement.
  capture.take_counters();
  run.interval_ms.clear();
  run.age_ms.clear();
  run.read_ms.clear();
  run.copy_done_at_acquire = 0;
  const unsigned acquired_before = run.acquired;
  CaptureCounters total;
  unsigned acquired_at_line = run.acquired;
  const double t_begin = now_s();
  const double t_end = t_begin + o.capturetest_seconds;
  double t_line = t_begin + 1.0;
  int second = 0;
  for (;;) {
    const double now = now_s();
    if (now >= t_end) break;
    const double until = std::min(t_end, t_line) - now;
    WaitForSingleObject(frame_event,
                        until > 0.0 ? (DWORD)std::min(100.0, std::ceil(until * 1000.0)) : 0);
    while (capture.acquire(frame)) {
      if (!run.take(frame, err)) return failed(err);
    }
    if (now_s() >= t_line) {
      const CaptureCounters c = capture.take_counters();
      add(total, c);
      // the block as GDI reads it from the screen right now, against the newest frame's
      std::vector<uint8_t> gdi_block;
      Likeness like;
      if (gdi_read(screen_x + run.bx, screen_y + run.by, run.bw, run.bh, gdi_block)) {
        like = compare_bgr(run.last_block, gdi_block);
      }
      ++second;
      say("capturetest second=%d arrived=%u acquired=%u dropped=%u unfit=%u handler_ms=%.3f "
          "block=%.2f gdi_diff=%.2f video_mib=%.0f",
          second, c.arrived, run.acquired - acquired_at_line, c.dropped, c.unfit,
          c.callbacks ? c.callback_ms / c.callbacks : kNan, run.block_mean, like.mean_abs,
          reader.video_memory_mib());
      acquired_at_line = run.acquired;
      t_line += 1.0;
    }
  }

  // ---- stop, and whether it is really over
  const double mib_capturing = reader.video_memory_mib();
  const double t_stop = now_s();
  capture.stop();
  const double stop_ms = (now_s() - t_stop) * 1000.0;
  const double seconds = t_stop - t_begin;
  add(total, capture.take_counters());
  Sleep(300);
  const CaptureCounters late = capture.take_counters();
  const bool quiet = late.callbacks == 0 && late.arrived == 0 && late.unfit == 0 &&
                     !capture.pending() && !capture.running();
  const unsigned acquired = run.acquired - acquired_before;

  say("capturetest total seconds=%.2f arrived=%u acquired=%u dropped=%u unfit=%u "
      "arrived_per_s=%.1f",
      seconds, total.arrived, acquired, total.dropped, total.unfit,
      seconds > 0.0 ? total.arrived / seconds : kNan);
  say("capturetest interval between frames, by their own timestamps: mean %.2f ms, shortest "
      "%.2f, median %.2f, longest %.2f",
      mean_of(run.interval_ms), smallest_of(run.interval_ms), median_of(run.interval_ms),
      largest_of(run.interval_ms));
  say("capturetest age of a frame when the loop gets it: median %.2f ms, longest %.2f",
      median_of(run.age_ms), largest_of(run.age_ms));
  say("capturetest handler: %.3f ms a frame over %u calls",
      total.callbacks ? total.callback_ms / total.callbacks : kNan, total.callbacks);
  say("capturetest D3D12 read of the block (fence wait, copy, readback): median %.2f ms, longest "
      "%.2f; the copy into the slot was already done at acquire for %u of %u frames",
      median_of(run.read_ms), largest_of(run.read_ms), run.copy_done_at_acquire, acquired);
  say("capturetest slots: %u distinct textures handed out, the same one twice running %u times, "
      "the frame before read again %u times and found changed %u times",
      (unsigned)run.textures.size(), run.same_twice, run.prev_checks, run.prev_changed);
  say("capturetest border: %s", border_off ? "off, as the session reports it"
                                           : "could not be switched off");
  say("capturetest stop: returned in %.1f ms, %s", stop_ms,
      quiet ? "and nothing came after it" : "but callbacks or frames still came after it");
  if (capture.closed()) say("capturetest warning: Windows closed the capture during the run");

  // ---- five more sessions in a row. LENS_CAPTURETEST_RESTARTS asks for another number,
  // to tell a leak, which grows with every session, from what Windows sets up once.
  int restarts = 5;
  {
    const std::wstring asked = env_text(L"LENS_CAPTURETEST_RESTARTS");
    if (!asked.empty()) restarts = std::clamp(_wtoi(asked.c_str()), 0, 200);
  }
  const double mib_stopped = reader.video_memory_mib();
  const DWORD handles_before = handle_count();
  int delivered = 0;
  int kept = 0;
  for (int k = 1; k <= restarts; ++k) {
    ResetEvent(frame_event);
    const double a = now_s();
    if (!capture.start(reader.device.Get(), reader.luid, monitor, W, H, o.crop_x, o.crop_y,
                       interval, frame_event, err)) {
      say("capturetest restart=%d start failed: %s", k, err.c_str());
      continue;
    }
    const double b = now_s();
    // what was handed out before the stop is still valid and unchanged after the start
    bool same = false;
    if (!run.last_still_there(same, err)) return failed(err);
    if (same) ++kept;
    const bool got = wait_frame(capture, frame_event, 3000, frame);
    const double c = now_s();
    if (got) {
      run.follows = false;
      if (!run.take(frame, err)) return failed(err);
      ++delivered;
    }
    const double d = now_s();
    capture.stop();
    const double e = now_s();
    say("capturetest restart=%d start_ms=%.1f first_frame_ms=%s block=%.2f held_frame_kept=%s "
        "stop_ms=%.1f video_mib=%.0f handles=%lu",
        k, (b - a) * 1000.0, got ? strf("%.1f", (c - a) * 1000.0).c_str() : "none",
        got ? run.block_mean : kNan, same ? "yes" : "no", (e - d) * 1000.0,
        reader.video_memory_mib(), (unsigned long)handle_count());
  }
  const double mib_restarted = reader.video_memory_mib();
  const DWORD handles_after = handle_count();
  say("capturetest restarts: %d of %d starts delivered a frame, the held frame was kept through "
      "%d of %d",
      delivered, restarts, kept, restarts);

  capture.destroy();
  CloseHandle(frame_event);
  const double mib_destroyed = reader.video_memory_mib();
  const DWORD handles_destroyed = handle_count();
  say("capturetest memory: video memory of this process %.0f MiB before, %.0f started, %.0f "
      "after the first frame, %.0f capturing, %.0f stopped, %.0f after the restarts, %.0f "
      "destroyed; handles %lu before the restarts, %lu after, %lu destroyed",
      mib_before, mib_started, mib_first, mib_capturing, mib_stopped, mib_restarted, mib_destroyed,
      (unsigned long)handles_before, (unsigned long)handles_after,
      (unsigned long)handles_destroyed);

  // ---- the first frame: what it holds, and the picture for a person to look at
  size_t not_opaque = 0;
  int lowest = 255, highest = 0;
  for (size_t i = 0; i + 3 < whole.size(); i += 4) {
    if (whole[i + 3] != 255) ++not_opaque;
    const int grey = (whole[i] + whole[i + 1] + whole[i + 2]) / 3;
    lowest = std::min(lowest, grey);
    highest = std::max(highest, grey);
  }
  const Likeness like = gdi_ok ? compare_bgr(whole, gdi_whole) : Likeness();
  const std::wstring dir = picture_dir();
  std::string where = "not written";
  if (make_dirs(dir)) {
    int w = 0, h = 0;
    const std::wstring path = path_join(dir, L"first-frame.png");
    const std::vector<uint8_t> full = to_bgr(whole, W, H, 1, w, h);
    if (write_png(path, full, w, h, err)) {
      where = narrow(path);
    } else {
      where = err;
    }
    // a copy small enough to look at in one piece
    const int factor = std::max(1, (std::max(W, H) + 1599) / 1600);
    if (factor > 1) {
      const std::vector<uint8_t> shrunk = to_bgr(whole, W, H, factor, w, h);
      if (!write_png(path_join(dir, L"first-frame-small.png"), shrunk, w, h, err)) {
        note("capturetest: %s", err.c_str());
      }
    }
  }
  say("capturetest first frame: %dx%d, mean %.2f, grey from %d to %d, %llu texels not opaque, "
      "picture %s",
      W, H, mean_bgr(whole), lowest, highest, (unsigned long long)not_opaque, where.c_str());
  if (gdi_ok) {
    say("capturetest first frame against GDI's read of the same rectangle of the screen: mean "
        "difference %.3f of 255, %.2f percent of the texels equal",
        like.mean_abs, like.equal_share * 100.0);
  } else {
    say("capturetest first frame against GDI: GDI could not read the screen");
  }

  // ---- the verdict
  const bool detail = highest > lowest;
  const bool agrees = gdi_ok && like.mean_abs < 1.0;
  const char* pixels = "a picture with detail, with nothing to compare it against";
  if (!detail) {
    pixels = "cannot be told from numbers, the frame is one flat colour";
  } else if (agrees) {
    pixels = "yes, a picture with detail that matches the screen";
  } else if (gdi_ok) {
    pixels = "a picture with detail, but not what GDI read: the screen changed in between or "
             "the crop is off, look at the picture";
  }
  say("capturetest D3D12 read real pixels: %s", pixels);
  // "ok" needs the picture to match the screen. Over a screen that moves the two reads are
  // of different moments and it will not: the lines above then say which part held.
  const bool all_good = agrees && run.prev_changed == 0 && run.same_twice == 0 && quiet &&
                        delivered == restarts && kept == restarts;
  say("capturetest result: %s", all_good ? "ok" : "see the lines above");
  return exit_code::ok;
}
