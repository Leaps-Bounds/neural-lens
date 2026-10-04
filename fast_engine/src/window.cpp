// window.cpp: the engine's one window and its swapchain. The contract is window.h.
//
// This file has been compiled and read, and has not been on screen yet. What only the
// screen can decide, and what the code does about each:
//   - Whether a layered window takes a flip model swapchain made for the window itself.
//     When CreateSwapChainForHwnd refuses, the composition path is tried before giving up,
//     and a note says which of the two is in use. Should it accept and show nothing,
//     --present dcomp asks for the other path outright.
//   - Whether the picture presented while the window was hidden is on screen at the moment
//     it is shown. The loop presents again right after show(), see window.h.
//   - Whether SetWindowRgn, which the lens uses for the A/B split, clips a flip model
//     picture. Window regions do apply to DirectComposition content, so --present dcomp is
//     the path to try if it does not.
#include "window.h"

#include <dcomp.h>

#include <atomic>
#include <new>

using Microsoft::WRL::ComPtr;

namespace {

// SetWindowDisplayAffinity's value for "leave this window out of every capture". The SDK
// has the name from 10.0.19041 on.
#ifndef WDA_EXCLUDEFROMCAPTURE
#define WDA_EXCLUDEFROMCAPTURE 0x00000011
#endif

// D3DDDIERR_DEVICEREMOVED, which Present may return in place of DXGI_ERROR_DEVICE_REMOVED
// when the card was taken out or its driver replaced. The name lives in the driver kit's
// headers, the number is all that is needed of it.
constexpr HRESULT kDeviceRemovedByDriver = (HRESULT)0x88760870L;

// Borderless, so the client area is the whole window and --size is the picture's size.
constexpr DWORD kStyle = WS_POPUP;

// TOPMOST keeps it over the region it shows. TOOLWINDOW and NOACTIVATE: no taskbar button,
// and never the active window. LAYERED and TRANSPARENT together let the mouse through to
// whatever lies beneath, in other programs too, which answering WM_NCHITTEST alone cannot:
// that answer only hands the mouse on to windows of this same thread.
constexpr DWORD kExStyle =
    WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_LAYERED | WS_EX_TRANSPARENT;

// The refresh rate of a monitor's current mode, 60 when it cannot be read. Windows reports
// whole numbers here, 119.88 Hz as 119 or 120, which capture_interval_ms() allows for.
// Finding the monitor and reading its mode took 2 microseconds together when measured
// (the same three calls through Python's ctypes), so nothing is remembered between calls.
double monitor_hz(HMONITOR monitor) {
  MONITORINFOEXW info = {};
  info.cbSize = sizeof(info);
  if (!monitor || !GetMonitorInfoW(monitor, &info)) return 60.0;
  DEVMODEW mode = {};
  mode.dmSize = sizeof(mode);
  if (!EnumDisplaySettingsW(info.szDevice, ENUM_CURRENT_SETTINGS, &mode)) return 60.0;
  // 0 and 1 both stand for "the display's default rate", which says nothing
  if (!(mode.dmFields & DM_DISPLAYFREQUENCY) || mode.dmDisplayFrequency <= 1) return 60.0;
  return (double)mode.dmDisplayFrequency;
}

// What pump() is doing, for Window::pump_state(). Written by the loop's thread, read by the
// watchdog's.
std::atomic<UINT> g_pump_message{0};              // the last message taken
std::atomic<HWND> g_pump_hwnd{nullptr};           // the window it was for, null for the thread
std::atomic<unsigned long long> g_pump_same{0};   // that message to that window, in a row
std::atomic<bool> g_pump_dispatching{false};
std::atomic<unsigned long long> g_pump_taken{0};  // by the pump() call running now
std::atomic<UINT> g_proc_message{0};              // our own procedure's, 0 outside it

// The most messages one pump() call takes before it hands the turn back. A queue that
// never runs dry would otherwise keep the loop in here for good: the picture would stop
// and the watchdog would end the process.
constexpr unsigned long long kPumpMost = 1000;

// Seconds in one tick of QueryPerformanceCounter, the unit the frame statistics and the
// compositor's statistics give their moments in. now_s() counts the same ticks.
double tick_s() {
  static double tick = 0.0;
  if (tick == 0.0) {
    LARGE_INTEGER hz = {};
    QueryPerformanceFrequency(&hz);
    tick = hz.QuadPart > 0 ? 1.0 / (double)hz.QuadPart : 1e-7;
  }
  return tick;
}

// The compositor's own frame statistics: three functions of dcomp.dll that came with
// Windows 11. They are looked up by name when first wanted and not imported, because an
// import the system does not have keeps the whole program from starting.
struct CompositorStats {
  using FrameId = HRESULT(WINAPI*)(COMPOSITION_FRAME_ID_TYPE, COMPOSITION_FRAME_ID*);
  using Statistics = HRESULT(WINAPI*)(COMPOSITION_FRAME_ID, COMPOSITION_FRAME_STATS*, UINT,
                                      COMPOSITION_TARGET_ID*, UINT*);
  using TargetStatistics = HRESULT(WINAPI*)(COMPOSITION_FRAME_ID, const COMPOSITION_TARGET_ID*,
                                            COMPOSITION_TARGET_STATS*);
  bool looked = false;
  FrameId frame_id = nullptr;
  Statistics statistics = nullptr;
  TargetStatistics target_statistics = nullptr;
  COMPOSITION_FRAME_ID last = 0;  // the newest frame handed out so far
};

}  // namespace

struct Window::Impl {
  Gpu* gpu = nullptr;
  HINSTANCE instance = nullptr;
  bool own_class = false;  // this object registered the class, and takes it away again
  HWND hwnd = nullptr;
  int width = 0;           // the size asked for, which the swapchain keeps whatever the
  int height = 0;          // window does
  int seen_w = 0;          // the client size last seen in WM_SIZE, so a change is noted once
  int seen_h = 0;
  bool closed = false;     // WM_CLOSE, WM_DESTROY, WM_QUIT or the end of the session came
  bool flood_said = false; // a queue that did not run dry has been noted once

  PresentPath path = PresentPath::Hwnd;  // the one in use, not always the one asked for
  bool sequential = false;               // flip sequential had to stand in for flip discard
  ComPtr<IDXGISwapChain3> swapchain;
  ComPtr<ID3D12Resource> buffers[Window::kBuffers];
  ComPtr<ID3D12DescriptorHeap> rtv_heap;
  D3D12_CPU_DESCRIPTOR_HANDLE rtv[Window::kBuffers] = {};
  ComPtr<IDCompositionDevice> dcomp;  // only on the composition path
  ComPtr<IDCompositionTarget> dcomp_target;
  ComPtr<IDCompositionVisual> dcomp_visual;

  static LRESULT CALLBACK proc(HWND hwnd, UINT message, WPARAM wparam, LPARAM lparam);
  DXGI_SWAP_CHAIN_DESC1 describe(DXGI_SCALING scaling) const;
  bool chain_for_hwnd(std::string& err);
  bool chain_for_composition(std::string& err);
  bool make_views(std::string& err);
};

// ---------------------------------------------------------------- the window procedure

// It never paints, never takes the mouse, never becomes active and never starts a modal
// loop of the system's: every one of those would either show something that is not the
// picture or stop the main loop, which this thread is.
LRESULT CALLBACK Window::Impl::proc(HWND hwnd, UINT message, WPARAM wparam, LPARAM lparam) {
  // the message in hand, put back on every way out (a procedure can be entered again)
  struct InProc {
    UINT before;
    explicit InProc(UINT m) : before(g_proc_message.exchange(m)) {}
    ~InProc() { g_proc_message.store(before); }
  } in_proc(message);

  if (message == WM_NCCREATE) {
    const CREATESTRUCTW* made = (const CREATESTRUCTW*)lparam;
    SetWindowLongPtrW(hwnd, GWLP_USERDATA, (LONG_PTR)made->lpCreateParams);
    return DefWindowProcW(hwnd, message, wparam, lparam);
  }
  Impl* w = (Impl*)GetWindowLongPtrW(hwnd, GWLP_USERDATA);

  switch (message) {
    case WM_ERASEBKGND:
      return 1;  // "erased": there is no background, the picture is the swapchain's
    case WM_PAINT: {
      // Nothing to draw, the picture is the swapchain's, but the update region has to be
      // emptied or the message comes for ever. ValidateRect alone did not do it for this
      // hidden layered window: WM_PAINT came back a thousand times in a row in the first
      // turn (measured), and before pump() had a cap the loop never left it. BeginPaint and
      // EndPaint are the whole of the system's own answer.
      PAINTSTRUCT ps;
      if (BeginPaint(hwnd, &ps)) EndPaint(hwnd, &ps);
      return 0;
    }
    case WM_NCHITTEST:
      return HTTRANSPARENT;
    case WM_MOUSEACTIVATE:
      return MA_NOACTIVATE;
    case WM_DPICHANGED:
      // The suggested rectangle is not taken: the lens places this window in physical
      // pixels and its size is the picture's.
      return 0;
    case WM_CLOSE:
      // not destroyed here: the loop sees pump() return false, and leaves in its own order
      if (w) w->closed = true;
      return 0;
    case WM_ENDSESSION:
      if (wparam && w) w->closed = true;
      return 0;
    case WM_SYSCOMMAND: {
      const WPARAM what = wparam & 0xFFF0;
      if (what == SC_CLOSE) {
        if (w) w->closed = true;
        return 0;
      }
      // the screen saver and the display's power are the system's business, not ours to stop
      if (what == SC_SCREENSAVE || what == SC_MONITORPOWER) break;
      // No move, no size, no menu: DefWindowProc runs those in a loop of its own, and the
      // main loop would stand still inside it until the watchdog ended the process.
      return 0;
    }
    case WM_SIZE:
      if (w) {
        const int cw = (int)LOWORD(lparam), ch = (int)HIWORD(lparam);
        if (cw != w->seen_w || ch != w->seen_h) {
          w->seen_w = cw;
          w->seen_h = ch;
          if (cw == w->width && ch == w->height) {
            note("window: the window is %dx%d again", cw, ch);
          } else {
            note("window: Windows made the window %dx%d, the swapchain stays %dx%d", cw, ch,
                 w->width, w->height);
          }
        }
      }
      return 0;
    case WM_DESTROY:
      if (w) w->closed = true;
      return 0;
    case WM_NCDESTROY:
      if (w) w->hwnd = nullptr;
      SetWindowLongPtrW(hwnd, GWLP_USERDATA, 0);
      return DefWindowProcW(hwnd, message, wparam, lparam);
    default:
      break;
  }

  // Keys: the lens posts WM_KEYDOWN and WM_KEYUP to its presenter for ReShade to read.
  // Nothing reads them here, and DefWindowProc must not either: it turns Alt+F4 into a
  // close and F10 into a menu loop.
  if (message >= WM_KEYFIRST && message <= WM_KEYLAST) return 0;

  return DefWindowProcW(hwnd, message, wparam, lparam);
}

// ---------------------------------------------------------------- the swapchain

DXGI_SWAP_CHAIN_DESC1 Window::Impl::describe(DXGI_SCALING scaling) const {
  DXGI_SWAP_CHAIN_DESC1 d = {};
  d.Width = (UINT)width;
  d.Height = (UINT)height;
  d.Format = Window::kFormat;
  d.Stereo = FALSE;
  d.SampleDesc.Count = 1;  // the flip model takes no multisampling
  d.SampleDesc.Quality = 0;
  d.BufferUsage = DXGI_USAGE_RENDER_TARGET_OUTPUT;
  d.BufferCount = Window::kBuffers;
  d.Scaling = scaling;
  d.SwapEffect = DXGI_SWAP_EFFECT_FLIP_DISCARD;
  // The picture is opaque. A swapchain made for a window cannot be blended anyway, and for
  // composition this saves the compositor a blend over the whole screen.
  d.AlphaMode = DXGI_ALPHA_MODE_IGNORE;
  d.Flags = 0;
  return d;
}

// CreateSwapChainForHwnd. A D3D12 swapchain is made on the command queue, not the device:
// its presents take their place in that queue's order, behind the draw before them.
bool Window::Impl::chain_for_hwnd(std::string& err) {
  // NONE: should the window ever have another size than the buffers, the picture is shown
  // as it is, from the top left, and not stretched.
  const DXGI_SWAP_CHAIN_DESC1 d = describe(DXGI_SCALING_NONE);
  ComPtr<IDXGISwapChain1> chain;
  HRESULT hr = gpu->factory->CreateSwapChainForHwnd(gpu->queue.Get(), hwnd, &d, nullptr, nullptr,
                                                    &chain);
  if (FAILED(hr)) {
    err = "CreateSwapChainForHwnd failed " + hr_text(hr);
    return false;
  }
  // DXGI leaves the window alone: no Alt+Enter to fullscreen, no watching of its messages.
  // It has to be asked of the factory that made the swapchain. Not fatal when refused: no
  // key ever reaches this window anyway.
  hr = gpu->factory->MakeWindowAssociation(hwnd, DXGI_MWA_NO_ALT_ENTER | DXGI_MWA_NO_WINDOW_CHANGES);
  if (FAILED(hr)) note("window: MakeWindowAssociation failed %s", hr_text(hr).c_str());
  hr = chain.As(&swapchain);
  if (FAILED(hr)) {
    err = "the swapchain has no IDXGISwapChain3 " + hr_text(hr);
    return false;
  }
  path = PresentPath::Hwnd;
  return true;
}

// CreateSwapChainForComposition, shown through a DirectComposition visual on a target for
// the window. The window may be layered, and its region clips the visual as it clips the
// window.
bool Window::Impl::chain_for_composition(std::string& err) {
  // STRETCH is the only scaling a composition swapchain takes. The visual has no transform
  // and the buffers have the window's size, so nothing is in fact stretched.
  DXGI_SWAP_CHAIN_DESC1 d = describe(DXGI_SCALING_STRETCH);
  ComPtr<IDXGISwapChain1> chain;
  HRESULT hr = gpu->factory->CreateSwapChainForComposition(gpu->queue.Get(), &d, nullptr, &chain);
  if (FAILED(hr)) {
    // The documentation of this call names FLIP_SEQUENTIAL as the swap effect it takes, in
    // words older than FLIP_DISCARD. Should the newer one be refused here, the older one
    // serves the engine as well: every texel of every frame is written, so nothing rests on
    // the buffers being discarded.
    const HRESULT refused = hr;
    d.SwapEffect = DXGI_SWAP_EFFECT_FLIP_SEQUENTIAL;
    hr = gpu->factory->CreateSwapChainForComposition(gpu->queue.Get(), &d, nullptr, &chain);
    if (FAILED(hr)) {
      err = "CreateSwapChainForComposition failed " + hr_text(refused);
      return false;
    }
    sequential = true;
    note("window: flip discard was refused for composition (%s), using flip sequential",
         hr_text(refused).c_str());
  }
  // No DXGI device is handed over: that one is for DirectComposition's own surfaces, of
  // which there are none here, and a D3D12 device is not one.
  hr = DCompositionCreateDevice(nullptr, IID_PPV_ARGS(&dcomp));
  if (FAILED(hr)) {
    err = "DCompositionCreateDevice failed " + hr_text(hr);
    return false;
  }
  // TRUE: above whatever the window itself holds, which is nothing, since it never paints
  hr = dcomp->CreateTargetForHwnd(hwnd, TRUE, &dcomp_target);
  if (FAILED(hr)) {
    err = "CreateTargetForHwnd failed " + hr_text(hr);
    return false;
  }
  hr = dcomp->CreateVisual(&dcomp_visual);
  if (FAILED(hr)) {
    err = "CreateVisual failed " + hr_text(hr);
    return false;
  }
  hr = dcomp_visual->SetContent(chain.Get());
  if (FAILED(hr)) {
    err = "the visual did not take the swapchain " + hr_text(hr);
    return false;
  }
  hr = dcomp_target->SetRoot(dcomp_visual.Get());
  if (FAILED(hr)) {
    err = "the target did not take the visual " + hr_text(hr);
    return false;
  }
  // Once: the tree does not change after this, and a present needs no commit.
  hr = dcomp->Commit();
  if (FAILED(hr)) {
    err = "the DirectComposition commit failed " + hr_text(hr);
    return false;
  }
  hr = chain.As(&swapchain);
  if (FAILED(hr)) {
    err = "the swapchain has no IDXGISwapChain3 " + hr_text(hr);
    return false;
  }
  path = PresentPath::Dcomp;
  return true;
}

// The buffers and one render target view for each, the same for either path.
bool Window::Impl::make_views(std::string& err) {
  DXGI_SWAP_CHAIN_DESC1 got = {};
  HRESULT hr = swapchain->GetDesc1(&got);
  if (FAILED(hr)) {
    err = "the swapchain's description cannot be read " + hr_text(hr);
    return false;
  }
  if (got.Width != (UINT)width || got.Height != (UINT)height || got.Format != Window::kFormat ||
      got.BufferCount != Window::kBuffers) {
    err = strf("the swapchain came as %ux%u, format %d, %u buffers, not as asked", got.Width,
               got.Height, (int)got.Format, got.BufferCount);
    return false;
  }

  D3D12_DESCRIPTOR_HEAP_DESC heap = {};
  heap.Type = D3D12_DESCRIPTOR_HEAP_TYPE_RTV;
  heap.NumDescriptors = Window::kBuffers;
  heap.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_NONE;
  hr = gpu->device->CreateDescriptorHeap(&heap, IID_PPV_ARGS(&rtv_heap));
  if (FAILED(hr)) {
    err = "the heap for the back buffers' views failed " + hr_text(hr);
    return false;
  }
  rtv_heap->SetName(L"window: back buffer views");
  const UINT step = gpu->device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_RTV);
  D3D12_CPU_DESCRIPTOR_HANDLE at = rtv_heap->GetCPUDescriptorHandleForHeapStart();
  for (UINT i = 0; i < Window::kBuffers; ++i) {
    hr = swapchain->GetBuffer(i, IID_PPV_ARGS(&buffers[i]));
    if (FAILED(hr)) {
      err = strf("back buffer %u cannot be had ", i) + hr_text(hr);
      return false;
    }
    buffers[i]->SetName(i == 0 ? L"window: back buffer 0" : L"window: back buffer 1");
    // a null description: the buffer's own format, its one mip
    gpu->device->CreateRenderTargetView(buffers[i].Get(), nullptr, at);
    rtv[i] = at;
    at.ptr += step;
  }
  return true;
}

// ---------------------------------------------------------------- Window

Window::Window() {}

Window::~Window() { destroy(); }

bool Window::create(Gpu& gpu, const WindowDesc& desc, std::string& err) {
  destroy();
  err.clear();
  if (desc.width < 1 || desc.height < 1) {
    err = strf("a window of %dx%d cannot be made", desc.width, desc.height);
    return false;
  }
  if (!gpu.factory || !gpu.device || !gpu.queue) {
    err = "the window needs the GPU, and Gpu::init has not run";
    return false;
  }
  impl_ = new (std::nothrow) Impl;
  if (!impl_) {
    err = "out of memory";
    return false;
  }
  Impl& w = *impl_;
  w.gpu = &gpu;
  w.instance = GetModuleHandleW(nullptr);
  w.width = w.seen_w = desc.width;
  w.height = w.seen_h = desc.height;

  // Every failure below leaves through here, so that nothing is left behind. destroy()
  // frees w: nothing may touch it afterwards.
  auto give_up = [&](std::string reason) {
    destroy();
    err = std::move(reason);
    return false;
  };

  // Windows replaces a window whose thread has not answered for five seconds with a
  // "ghost", a frozen copy that does take the mouse. Over the whole screen that is the
  // frozen computer the watchdog exists to prevent, so no ghost is ever made.
  DisableProcessWindowsGhosting();

  WNDCLASSEXW wc = {};
  wc.cbSize = sizeof(wc);
  wc.lpfnWndProc = Impl::proc;
  wc.hInstance = w.instance;
  wc.hCursor = LoadCursorW(nullptr, IDC_ARROW);
  wc.hbrBackground = nullptr;  // nothing is ever painted
  wc.lpszClassName = kClassName;
  if (RegisterClassExW(&wc)) {
    w.own_class = true;
  } else {
    const DWORD code = GetLastError();
    if (code != ERROR_CLASS_ALREADY_EXISTS) {
      return give_up(strf("RegisterClassEx failed, error %lu", code));
    }
  }

  // No WS_VISIBLE: hidden until show(). All the styles go on here, at birth, so no taskbar
  // button flashes and no click ever lands on it. The process is per monitor DPI aware, so
  // the position and the size are physical pixels on whichever monitor they name.
  HWND hwnd = CreateWindowExW(kExStyle, kClassName, desc.title.c_str(), kStyle, desc.x, desc.y,
                              desc.width, desc.height, nullptr, nullptr, w.instance, &w);
  if (!hwnd) {
    const DWORD code = GetLastError();
    return give_up(strf("CreateWindowEx failed, error %lu", code));
  }
  w.hwnd = hwnd;

  // A layered window shows nothing at all until its attributes are set. 255 is opaque.
  if (!SetLayeredWindowAttributes(hwnd, 0, 255, LWA_ALPHA)) {
    const DWORD code = GetLastError();
    return give_up(strf("SetLayeredWindowAttributes failed, error %lu", code));
  }

  // Before the window is ever visible, so not one captured frame holds it. A refusal is a
  // failure and not a note: seen by its own capture, the engine would take its own output
  // for a new frame and put it through the network again, for ever.
  if (desc.exclude && !SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)) {
    const DWORD code = GetLastError();
    return give_up(strf("SetWindowDisplayAffinity failed, error %lu", code));
  }

  std::string why;
  bool made = false;
  if (desc.path == PresentPath::Hwnd) {
    made = w.chain_for_hwnd(why);
    if (!made) {
      // The window refused a swapchain of its own, which a layered window may. The
      // composition path does not need the window to take one.
      note("window: %s, trying DirectComposition", why.c_str());
      std::string second;
      made = w.chain_for_composition(second);
      if (!made) why += ", and then " + second;
    }
  } else {
    // Asked for outright, so no falling back: a log then says plainly whether this path
    // works here.
    made = w.chain_for_composition(why);
  }
  if (!made) return give_up(why);
  if (!w.make_views(why)) return give_up(why);

  note("window: %dx%d at (%d,%d), swapchain made for %s, %u buffers, flip %s%s", desc.width,
       desc.height, desc.x, desc.y,
       w.path == PresentPath::Hwnd ? "the window" : "DirectComposition", kBuffers,
       w.sequential ? "sequential" : "discard", desc.exclude ? ", excluded from capture" : "");
  return true;
}

HWND Window::hwnd() const { return impl_ ? impl_->hwnd : nullptr; }

bool Window::back_buffer(Target& out, std::string& err) {
  out = Target();
  if (!impl_ || !impl_->swapchain) {
    err = "the window has no swapchain";
    return false;
  }
  Impl& w = *impl_;
  const HRESULT reason = w.gpu->device->GetDeviceRemovedReason();
  if (reason != S_OK) {
    err = "device removed " + hr_text(reason);
    return false;
  }
  // It changes with every present, so it is asked for every time.
  const UINT index = w.swapchain->GetCurrentBackBufferIndex();
  if (index >= kBuffers) {
    err = strf("the swapchain names back buffer %u of %u", index, kBuffers);
    return false;
  }
  out.texture = w.buffers[index].Get();
  out.rtv = w.rtv[index];
  out.width = (UINT)w.width;
  out.height = (UINT)w.height;
  return true;
}

bool Window::present(std::string& err) {
  if (!impl_ || !impl_->swapchain) {
    err = "the window has no swapchain";
    return false;
  }
  // Interval 0 and no flags: the call does not wait for the display, and the compositor
  // shows the newest picture at its next turn, dropping any it never got to.
  const HRESULT hr = impl_->swapchain->Present(0, 0);
  // DXGI_STATUS_OCCLUDED and its kind are success codes: a hidden or covered window.
  if (SUCCEEDED(hr)) return true;
  if (hr == DXGI_ERROR_DEVICE_REMOVED || hr == kDeviceRemovedByDriver) {
    err = "device removed " + hr_text(impl_->gpu->device->GetDeviceRemovedReason());
  } else if (hr == DXGI_ERROR_DEVICE_RESET) {
    err = "device reset";
  } else {
    err = "Present failed " + hr_text(hr);
  }
  return false;
}

UINT Window::present_id() const {
  UINT id = 0;
  if (!impl_ || !impl_->swapchain || FAILED(impl_->swapchain->GetLastPresentCount(&id))) return 0;
  return id;
}

bool Window::shown(PresentShown& out) const {
  if (!impl_ || !impl_->swapchain) return false;
  DXGI_FRAME_STATISTICS st = {};
  // DXGI_ERROR_FRAME_STATISTICS_DISJOINT comes once after any break in the counting, and
  // nothing but zeros before the first present has been shown.
  if (FAILED(impl_->swapchain->GetFrameStatistics(&st)) || st.SyncQPCTime.QuadPart == 0) return false;
  out.id = st.PresentCount;
  out.refresh = st.PresentRefreshCount;
  out.sync_refresh = st.SyncRefreshCount;
  out.sync_s = (double)st.SyncQPCTime.QuadPart * tick_s();
  return true;
}

bool Window::compositor_frames(std::vector<CompositorFrame>& out) {
  static CompositorStats api;
  if (!api.looked) {
    api.looked = true;
    // dcomp.dll is in the process already: the composition path's functions come from it
    if (HMODULE dcomp = GetModuleHandleW(L"dcomp.dll")) {
      api.frame_id = (CompositorStats::FrameId)GetProcAddress(dcomp, "DCompositionGetFrameId");
      api.statistics =
          (CompositorStats::Statistics)GetProcAddress(dcomp, "DCompositionGetStatistics");
      api.target_statistics = (CompositorStats::TargetStatistics)GetProcAddress(
          dcomp, "DCompositionGetTargetStatistics");
    }
  }
  if (!api.frame_id || !api.statistics || !api.target_statistics) return false;

  COMPOSITION_FRAME_ID newest = 0;
  if (FAILED(api.frame_id(COMPOSITION_FRAME_ID_COMPLETED, &newest))) return true;
  if (api.last == 0 || newest < api.last) {
    api.last = newest;  // the first call: from here on
    return true;
  }
  const UINT64 most = 64;
  const double tick = tick_s();
  for (COMPOSITION_FRAME_ID id = newest - api.last > most ? newest - most + 1 : api.last + 1;
       id <= newest; ++id) {
    COMPOSITION_FRAME_STATS frame = {};
    COMPOSITION_TARGET_ID ids[CompositorFrame::kTargets] = {};
    UINT count = 0;
    if (FAILED(api.statistics(id, &frame, CompositorFrame::kTargets, ids, &count))) continue;
    CompositorFrame f;
    f.id = id;
    f.start_s = (double)frame.startTime * tick;
    f.target_s = (double)frame.targetTime * tick;
    f.period_s = (double)frame.framePeriod * tick;
    f.targets = count < (UINT)CompositorFrame::kTargets ? (int)count : CompositorFrame::kTargets;
    for (int t = 0; t < f.targets; ++t) {
      COMPOSITION_TARGET_STATS target = {};
      f.target[t].source = ids[t].vidPnSourceId;
      if (FAILED(api.target_statistics(id, &ids[t], &target))) continue;
      f.target[t].present_s = (double)target.presentTime * tick;
      f.target[t].shown_s = (double)target.presentedStats.time * tick;
      f.target[t].refresh = target.presentedStats.refreshCount;
      f.target[t].vblank_s = (double)target.vblankDuration * tick;
    }
    out.push_back(f);
  }
  api.last = newest;
  return true;
}

void Window::show() {
  // SW_SHOWNA and nothing else: shown where and as large as it is, not activated, the
  // focus left where it was.
  if (impl_ && impl_->hwnd) ShowWindow(impl_->hwnd, SW_SHOWNA);
}

bool Window::pump() {
  if (!impl_) return false;
  // PeekMessage never waits. On its way it also answers what other threads have sent,
  // which is how a SetWindowPos from the lens gets its reply. No TranslateMessage: no key
  // is ever read here, see the window procedure.
  MSG message;
  g_pump_taken.store(0);
  while (PeekMessageW(&message, nullptr, 0, 0, PM_REMOVE)) {
    const unsigned long long taken = g_pump_taken.fetch_add(1) + 1;
    if (message.message == g_pump_message.load() && message.hwnd == g_pump_hwnd.load()) {
      g_pump_same.fetch_add(1);
    } else {
      g_pump_message.store(message.message);
      g_pump_hwnd.store(message.hwnd);
      g_pump_same.store(1);
    }
    if (message.message == WM_QUIT) {
      impl_->closed = true;
    } else {
      g_pump_dispatching.store(true);
      DispatchMessageW(&message);
      g_pump_dispatching.store(false);
    }
    if (taken >= kPumpMost) {
      if (!impl_->flood_said) {
        impl_->flood_said = true;
        note("window: the message queue did not run dry after %llu messages, %s", taken,
             pump_state().c_str());
      }
      break;
    }
  }
  return !impl_->closed && impl_->hwnd != nullptr;
}

std::string Window::pump_state() {
  const UINT message = g_pump_message.load();
  const HWND to = g_pump_hwnd.load();
  wchar_t cls[96] = L"";
  if (to) GetClassNameW(to, cls, 96);
  std::string text = strf("%llu messages taken, the last 0x%04x (%llu of it in a row) for %s, %s",
                          g_pump_taken.load(), message, g_pump_same.load(),
                          to ? ("a window of class " + narrow(cls)).c_str() : "the thread",
                          g_pump_dispatching.load() ? "being dispatched" : "not being dispatched");
  if (const UINT own = g_proc_message.load()) {
    text += strf(", the engine's window procedure is in 0x%04x", own);
  }
  return text;
}

double Window::refresh_hz() const {
  if (!impl_ || !impl_->hwnd) return 60.0;
  RECT at = {};
  if (!GetWindowRect(impl_->hwnd, &at)) return 60.0;
  return monitor_hz(monitor_under(at.left, at.top, at.right - at.left, at.bottom - at.top));
}

void Window::destroy() {
  if (!impl_) return;
  Impl& w = *impl_;
  // The composition tree lets go of the swapchain first, then the views and the buffers,
  // and the swapchain last: it cannot go while a buffer of its own is still held.
  if (w.dcomp_target) w.dcomp_target->SetRoot(nullptr);
  if (w.dcomp_visual) w.dcomp_visual->SetContent(nullptr);
  if (w.dcomp) w.dcomp->Commit();
  w.dcomp_visual.Reset();
  w.dcomp_target.Reset();
  w.dcomp.Reset();
  for (ComPtr<ID3D12Resource>& buffer : w.buffers) buffer.Reset();
  w.rtv_heap.Reset();
  w.swapchain.Reset();
  // WM_NCDESTROY sets w.hwnd to null on the way, so the handle is kept here.
  if (HWND hwnd = w.hwnd) DestroyWindow(hwnd);
  if (w.own_class) UnregisterClassW(kClassName, w.instance);
  delete impl_;
  impl_ = nullptr;
}
