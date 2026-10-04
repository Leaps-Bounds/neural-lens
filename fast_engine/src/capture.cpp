// capture.cpp: Windows Graphics Capture of one monitor on a D3D11 device of the capture's
// own, with the crop under the lens copied on the GPU into slots the D3D12 device reads.
// The contract is capture.h.
//
// How the two devices meet:
//   - The slots are four D3D11 textures created with SHARED_NTHANDLE | SHARED, each opened
//     once on the engine's D3D12 device with OpenSharedHandle. D3D11 creates them because
//     it is the side that writes them. D3D12 sees them in COMMON, with the flags
//     ALLOW_RENDER_TARGET | ALLOW_SIMULTANEOUS_ACCESS (0x21), and reads them between a
//     transition out of COMMON and one back.
//   - The fence is an ID3D11Fence created shared and opened on the D3D12 device. After
//     each copy the callback signals it with the next value and flushes, and the reader's
//     queue waits for that value before it touches the slot. The wait is not a formality:
//     the loop wakes sooner than the GPU copies, and in the capture test the fence had not
//     yet reached a frame's value at acquire() for 50 frames of 51.
//
// Four slots, because four frames can be spoken for at one moment: the one handed out
// (HELD), the one handed out before it (PREV), one complete and waiting (READY), and the
// one the callback is writing (WRITING). So the callback always finds a free one and never
// has to wait for the main thread.
//
// The frame rate limit, whose rule is in capture.h. The callback asks the beat whether the
// frame's turn has come. When it has not, nothing is copied and the system's frame object
// is kept open instead, which holds one of the pool's two buffers and costs no GPU time.
// The next frame to arrive lets it go. When none arrives, the main thread copies it once it
// is due, release_held(), with the same code the callback copies with. Measured at a limit
// of 80 over a screen that changed at every refresh, 80 of the 117 frames that arrived in a
// second were copied, and all 117 went on arriving with one buffer held.
//
// Threads: Windows calls the frame callback on a thread of its own pool. Everything else is
// the main thread. Two locks keep them apart:
//   - the gate, one for each session, held by a callback for as long as it runs. stop()
//     takes it once to shut the gate: that waits for a callback that is running and turns
//     every later one, which Windows may still deliver after the handler is revoked, into
//     nothing. The callback holds a reference to the gate, not to the capture, so one that
//     comes after destroy() touches no freed memory. The capture item's Closed event has a
//     gate of the same kind. The main thread also takes the gate where it handles the frame
//     the limit has kept back, so that frame and the fence's counter always have one user.
//   - the state lock, held for a few instructions at a time by either thread: the slots'
//     states, the crop, the counters and the limit's beat.
// Whoever takes both takes the gate first. A callback never waits for the main thread
// longer than one copy takes, and stop() holds no lock while it waits for the gate, so the
// two cannot deadlock.
//
// Measured with lens-fast-capturetest.exe on an RTX 5090, a 6144x2560 monitor at 120 Hz and
// a lens of 6144x2526, over a still desktop. Only 2 to 12 frames a second arrive there, so
// none of this is a figure for a screen that changes at every refresh:
//   - the callback takes 0.12 ms of the CPU a frame; the 62 MB copy is the GPU's work
//   - a D3D12 read of a slot, the wait for the fence included, is done 0.30 ms after
//     acquire()
//   - the first frame, read back whole through D3D12, equals what GDI reads from the same
//     rectangle of the screen, texel for texel
//   - the first start() takes 70 to 260 ms (the D3D11 device, the first use of the capture
//     API), a later one 6 ms, and its first frame is there 9 to 17 ms after the call
//   - stop() takes 4 to 20 ms, nearly all of it the wait for the pool's buffer to go
//   - video memory: 237 MiB for the four slots, 60 MiB for the frame pool while a session
//     runs, some 30 MiB for the D3D11 device. The card's total rose by 347 MiB capturing
//     and 287 MiB stopped. The process's own figure from DXGI reads higher, 511 and 451,
//     because it counts a slot a second time once the D3D12 device has used it.
//
// No exception leaves this file: every C++/WinRT call is inside try and catch.
#include "capture.h"

#include <objbase.h>

#include <d3d11_4.h>
#include <dxgi1_6.h>
#include <windows.graphics.capture.interop.h>
#include <windows.graphics.directx.direct3d11.interop.h>
#include <wrl/client.h>

#include <winrt/base.h>
#include <winrt/Windows.Foundation.h>
#include <winrt/Windows.Graphics.h>
#include <winrt/Windows.Graphics.Capture.h>
#include <winrt/Windows.Graphics.DirectX.h>
#include <winrt/Windows.Graphics.DirectX.Direct3D11.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <memory>
#include <mutex>
#include <new>

using Microsoft::WRL::ComPtr;
namespace wf = winrt::Windows::Foundation;
namespace wgc = winrt::Windows::Graphics::Capture;
namespace wgdx = winrt::Windows::Graphics::DirectX;

namespace {

// The HRESULT behind whatever is being handled, for a reason text. Only inside a catch.
HRESULT thrown_hr() noexcept {
  try {
    throw;
  } catch (winrt::hresult_error const& e) {
    return e.code();
  } catch (std::bad_alloc const&) {
    return E_OUTOFMEMORY;
  } catch (...) {
    return E_FAIL;
  }
}

// Attached to each of the frame pool's textures as private data, which D3D11 releases when
// the texture is destroyed: so the count says how many of the pool's buffers still exist.
// stop() waits on that count, see there. The GUID only has to be this file's own.
const GUID kPoolBufferTag = {
    0x6c3f1b52, 0x9e0a, 0x4c1d, {0x8a, 0x55, 0x1e, 0x2b, 0x7c, 0x90, 0x43, 0xd1}};

struct BufferTag final : IUnknown {
  std::atomic<ULONG> refs{1};
  std::shared_ptr<std::atomic<int>> alive;

  explicit BufferTag(std::shared_ptr<std::atomic<int>> count) : alive(std::move(count)) {
    alive->fetch_add(1);
  }
  HRESULT STDMETHODCALLTYPE QueryInterface(REFIID iid, void** out) override {
    if (!out) return E_POINTER;
    if (iid == __uuidof(IUnknown)) {
      *out = static_cast<IUnknown*>(this);
      AddRef();
      return S_OK;
    }
    *out = nullptr;
    return E_NOINTERFACE;
  }
  ULONG STDMETHODCALLTYPE AddRef() override { return ++refs; }
  ULONG STDMETHODCALLTYPE Release() override {
    const ULONG left = --refs;
    if (left == 0) {
      alive->fetch_sub(1);
      delete this;
    }
    return left;
  }
};

}  // namespace

struct Capture::Impl {
  enum class State { Free, Writing, Ready, Held, Prev };

  struct Slot {
    ComPtr<ID3D11Texture2D> tex11;  // the capture's side, which the callback writes
    ComPtr<ID3D12Resource> tex12;   // the same memory as the engine's device sees it
    State state = State::Free;
    UINT64 fence_value = 0;         // the copy into it is done when the fence reaches this
    double timestamp_s = 0.0;
    double arrived_s = 0.0;
  };

  // A frame the limit has kept back. It is the system's frame, open, and what a later copy
  // needs.
  struct Held {
    wgc::Direct3D11CaptureFrame frame{nullptr};
    ComPtr<ID3D11Texture2D> texture;
    int w = 0;             // the picture inside the texture
    int h = 0;
    double stamp = 0.0;    // its own timestamp
    double beat = 0.0;     // the moment the limit's beat judged it by, see take_newest
    double arrived = 0.0;  // now_s() when it came
    explicit operator bool() const { return (bool)frame; }
  };

  // All a callback may reach, see the top of the file.
  struct Gate {
    std::mutex mu;
    Impl* owner = nullptr;  // null once stop() has shut the gate
  };

  static constexpr int kSlots = 4;

  // ---- made by the first start(), kept until destroy()
  ComPtr<ID3D12Device> device12;
  int W = 0;
  int H = 0;
  ComPtr<ID3D11Device5> device11;
  ComPtr<ID3D11DeviceContext4> context11;
  winrt::Windows::Graphics::DirectX::Direct3D11::IDirect3DDevice winrt_device{nullptr};
  ComPtr<ID3D11Fence> fence11;
  ComPtr<ID3D12Fence> fence12;
  Slot slots[kSlots];
  bool shared_ready = false;
  CO_MTA_USAGE_COOKIE mta = nullptr;

  // ---- the monitor as something to capture. Kept from session to session, see keep_item()
  wgc::GraphicsCaptureItem item{nullptr};
  HMONITOR item_monitor = nullptr;
  std::shared_ptr<Gate> item_gate;  // for the item's Closed event, shut when the item goes
  winrt::event_token closed_token{};
  bool have_closed_token = false;
  std::atomic<bool> item_closed{false};   // Windows closed it: the next start() makes another
  std::atomic<bool> session_live{false};  // whether a closing item ends a running capture

  // ---- one session, from start() to stop(). Main thread only.
  std::shared_ptr<Gate> gate;
  wgc::Direct3D11CaptureFramePool pool{nullptr};
  wgc::GraphicsCaptureSession session{nullptr};
  winrt::event_token frame_token{};
  bool have_frame_token = false;
  bool running = false;
  bool border_off = false;
  int interval_taken = 0;        // the interval the session has, in ms, 0 when it took none
  HANDLE frame_event = nullptr;  // the caller's. Set before a session starts, read by the callback

  // ---- these belong to whoever holds the gate, a callback or the main thread in
  // release_held(), set_limit() and stop_session()
  UINT64 fence_counter = 0;  // the last value signalled. It runs on across sessions
  bool said_error = false;
  Held held;                 // the frame the limit has kept back, if any
  std::atomic<double> held_due{0.0};  // now_s() from which it is handed on, 0 with none held

  // how many of the frame pools' textures exist, see BufferTag
  std::shared_ptr<std::atomic<int>> pool_buffers = std::make_shared<std::atomic<int>>(0);

  // ---- shared by the two threads
  mutable std::mutex state_mu;  // the slots' states, the crop, the counters and the limit
  int crop_x = 0;
  int crop_y = 0;
  CaptureCounters counters;
  std::atomic<bool> closed{false};
  std::atomic<double> last_arrival{0.0};

  // the frame rate limit, see capture.h
  double limit_period = 0.0;  // 0: no limit
  double limit_early = 0.0;
  double limit_newer = 0.0;
  double turn = 0.0;          // when the limit last gave a frame its turn, on the frames' clock
  double turn_before = 0.0;   // what it was before that frame, for turn_back()
  UINT64 turn_value = 0;      // that frame's fence value, 0 once its turn was given back

  std::string said_session;  // the last session line on stderr, see start_session

  bool make_shared_parts(ID3D12Device* device, LUID adapter_luid, int w, int h, std::string& err);
  void release_shared_parts();
  void keep_item(HMONITOR monitor);
  void drop_item();
  bool start_session(HMONITOR monitor, int min_interval_ms, std::string& err);
  void stop_session();
  void on_frame(wgc::Direct3D11CaptureFramePool const& sender);
  bool take_newest(wgc::Direct3D11CaptureFramePool const& sender);
  bool copy_out(ID3D11Texture2D* texture, int frame_w, int frame_h, double stamp, double beat,
                double came, unsigned replaced, bool was_held);
  void let_go(Held& frame);
};

// ---------------------------------------------------------------- the two devices

// The D3D11 device, the fence and the slots. All or nothing: after a failure nothing is
// kept and the next start() begins again from the top.
bool Capture::Impl::make_shared_parts(ID3D12Device* device, LUID adapter_luid, int w, int h,
                                      std::string& err) {
  // The device goes on the engine's own adapter, so the copy into a slot never crosses to
  // another card. BGRA support is what Windows Graphics Capture asks of its device.
  ComPtr<IDXGIFactory4> factory;
  ComPtr<IDXGIAdapter1> adapter;
  ComPtr<ID3D11Device> device_plain;
  ComPtr<ID3D11DeviceContext> context_plain;
  D3D_FEATURE_LEVEL level = D3D_FEATURE_LEVEL_11_0;
  HRESULT hr = CreateDXGIFactory1(IID_PPV_ARGS(&factory));
  if (SUCCEEDED(hr)) hr = factory->EnumAdapterByLuid(adapter_luid, IID_PPV_ARGS(&adapter));
  if (SUCCEEDED(hr)) {
    static const D3D_FEATURE_LEVEL levels[] = {D3D_FEATURE_LEVEL_11_1, D3D_FEATURE_LEVEL_11_0};
    hr = D3D11CreateDevice(adapter.Get(), D3D_DRIVER_TYPE_UNKNOWN, nullptr,
                           D3D11_CREATE_DEVICE_BGRA_SUPPORT, levels, 2, D3D11_SDK_VERSION,
                           &device_plain, &level, &context_plain);
  }
  // ID3D11Device5 makes the fence and ID3D11DeviceContext4 signals it: Windows 10 1703 on
  if (SUCCEEDED(hr)) hr = device_plain.As(&device11);
  if (SUCCEEDED(hr)) hr = context_plain.As(&context11);
  if (FAILED(hr)) {
    release_shared_parts();
    err = "no D3D11 device on the adapter " + hr_text(hr);
    return false;
  }
  // The frame pool works on this device from threads of its own while the callback uses
  // the immediate context, so the context takes its lock: three calls a frame pay for it.
  ComPtr<ID3D11Multithread> multithread;
  if (SUCCEEDED(context_plain.As(&multithread))) multithread->SetMultithreadProtected(TRUE);

  // the same device as the capture API wants to be handed it
  try {
    ComPtr<IDXGIDevice> dxgi;
    winrt::check_hresult(device11.As(&dxgi));
    winrt::com_ptr<::IInspectable> wrapped;
    winrt::check_hresult(CreateDirect3D11DeviceFromDXGIDevice(dxgi.Get(), wrapped.put()));
    winrt_device = wrapped.as<winrt::Windows::Graphics::DirectX::Direct3D11::IDirect3DDevice>();
  } catch (...) {
    note("capture: the D3D11 device could not be wrapped for the capture API %s",
         hr_text(thrown_hr()).c_str());
    release_shared_parts();
    err = "Windows Graphics Capture is not available";
    return false;
  }

  // ---- the fence
  const char* step = "creating the fence";
  hr = device11->CreateFence(0, D3D11_FENCE_FLAG_SHARED, IID_PPV_ARGS(&fence11));
  if (SUCCEEDED(hr)) {
    step = "the fence's shared handle";
    HANDLE handle = nullptr;
    hr = fence11->CreateSharedHandle(nullptr, GENERIC_ALL, nullptr, &handle);
    if (SUCCEEDED(hr)) {
      step = "opening the fence on the D3D12 device";
      hr = device->OpenSharedHandle(handle, IID_PPV_ARGS(&fence12));
      CloseHandle(handle);
    }
  }

  // ---- the slots. A shared D3D11 texture has to be bindable, and render target plus
  // shader resource is the pair every driver shares. The reader only ever reads them.
  D3D11_TEXTURE2D_DESC td = {};
  td.Width = (UINT)w;
  td.Height = (UINT)h;
  td.MipLevels = 1;
  td.ArraySize = 1;
  td.Format = DXGI_FORMAT_B8G8R8A8_UNORM;
  td.SampleDesc.Count = 1;
  td.Usage = D3D11_USAGE_DEFAULT;
  td.BindFlags = D3D11_BIND_RENDER_TARGET | D3D11_BIND_SHADER_RESOURCE;
  td.MiscFlags = D3D11_RESOURCE_MISC_SHARED_NTHANDLE | D3D11_RESOURCE_MISC_SHARED;
  for (int i = 0; SUCCEEDED(hr) && i < kSlots; ++i) {
    step = "creating a slot";
    hr = device11->CreateTexture2D(&td, nullptr, &slots[i].tex11);
    ComPtr<IDXGIResource1> resource;
    if (SUCCEEDED(hr)) hr = slots[i].tex11.As(&resource);
    HANDLE handle = nullptr;
    if (SUCCEEDED(hr)) {
      step = "a slot's shared handle";
      hr = resource->CreateSharedHandle(
          nullptr, DXGI_SHARED_RESOURCE_READ | DXGI_SHARED_RESOURCE_WRITE, nullptr, &handle);
    }
    if (SUCCEEDED(hr)) {
      step = "opening a slot on the D3D12 device";
      hr = device->OpenSharedHandle(handle, IID_PPV_ARGS(&slots[i].tex12));
      CloseHandle(handle);
    }
    if (SUCCEEDED(hr)) slots[i].tex12->SetName(widen(strf("capture slot %d", i)).c_str());
  }
  if (FAILED(hr)) {
    release_shared_parts();
    err = strf("sharing the slots failed %s at %s", hr_text(hr).c_str(), step);
    return false;
  }

  device12 = device;
  W = w;
  H = h;
  shared_ready = true;
  const D3D12_RESOURCE_DESC seen = slots[0].tex12->GetDesc();
  note("capture: D3D11 device at feature level 0x%x, %d slots of %dx%d shared with the D3D12 "
       "device (%.0f MiB, D3D12 resource flags 0x%x)",
       (unsigned)level, kSlots, w, h, (double)kSlots * w * h * 4.0 / 1048576.0,
       (unsigned)seen.Flags);
  return true;
}

void Capture::Impl::release_shared_parts() {
  for (Slot& s : slots) {
    s.tex12.Reset();
    s.tex11.Reset();
    s.state = State::Free;
    s.fence_value = 0;
    s.timestamp_s = 0.0;
  }
  fence12.Reset();
  fence11.Reset();
  winrt_device = nullptr;
  if (context11) {
    // what the callback queued last may still hold the textures: let go of it now
    context11->ClearState();
    context11->Flush();
  }
  context11.Reset();
  device11.Reset();
  device12.Reset();
  shared_ready = false;
  W = 0;
  H = 0;
}

// ---------------------------------------------------------------- the capture item

// Makes sure there is an item for the monitor, and that Windows has not closed it.
// It throws, inside start_session()'s try.
//
// The item is kept from one session to the next, because making one is not free of
// residue: every CreateForMonitor leaves two ALPC port handles in the process that
// releasing the item does not close. Measured over 40 stops and starts: 83 more handles
// with a new item for each session, all of them ports, and none with the item kept.
void Capture::Impl::keep_item(HMONITOR monitor) {
  if (item && (item_monitor != monitor || item_closed.load())) drop_item();
  if (item) return;
  const auto interop =
      winrt::get_activation_factory<wgc::GraphicsCaptureItem, IGraphicsCaptureItemInterop>();
  winrt::check_hresult(interop->CreateForMonitor(
      monitor, winrt::guid_of<wgc::IGraphicsCaptureItem>(), winrt::put_abi(item)));
  item_monitor = monitor;
  item_closed.store(false);
  // Windows closes a monitor's item when the displays change. A capture that is running is
  // over then, and only a new presenter on the new layout helps: the loop says "capture
  // lost closed". Closed while no session runs, it only means a new item at the next start.
  item_gate = std::make_shared<Gate>();
  item_gate->owner = this;
  closed_token = item.Closed(
      [g = item_gate](wgc::GraphicsCaptureItem const&, wf::IInspectable const&) {
        try {
          std::lock_guard<std::mutex> hold(g->mu);
          if (!g->owner) return;
          g->owner->item_closed.store(true);
          if (g->owner->session_live.load()) g->owner->closed.store(true);
        } catch (...) {
        }
      });
  have_closed_token = true;
}

void Capture::Impl::drop_item() {
  if (item_gate) {
    std::lock_guard<std::mutex> hold(item_gate->mu);
    item_gate->owner = nullptr;
  }
  try {
    if (have_closed_token && item) item.Closed(closed_token);
  } catch (...) {
  }
  have_closed_token = false;
  item = nullptr;
  item_monitor = nullptr;
  item_gate.reset();
  item_closed.store(false);
}

// ---------------------------------------------------------------- one session

bool Capture::Impl::start_session(HMONITOR monitor, int min_interval_ms, std::string& err) {
  try {
    if (!wgc::GraphicsCaptureSession::IsSupported()) {
      err = "Windows Graphics Capture is not available";
      return false;
    }
  } catch (...) {
    note("capture: asking whether capture is supported failed %s", hr_text(thrown_hr()).c_str());
    err = "Windows Graphics Capture is not available";
    return false;
  }

  winrt::Windows::Graphics::SizeInt32 size = {};
  try {
    keep_item(monitor);
    size = item.Size();
    // Free threaded: the frames come on a thread of the system's pool and nothing here
    // needs a dispatcher or a message loop. Two buffers: one being composed into, one for
    // the callback, which hands its frame back before it returns.
    pool = wgc::Direct3D11CaptureFramePool::CreateFreeThreaded(
        winrt_device, wgdx::DirectXPixelFormat::B8G8R8A8UIntNormalized, 2, size);
    session = pool.CreateCaptureSession(item);
  } catch (...) {
    err = "the monitor cannot be captured " + hr_text(thrown_hr());
    // whatever was wrong, the next start() begins with a new item
    drop_item();
    return false;
  }

  // The cursor stays out of the picture: the lens draws over the screen, the real cursor
  // is above it, and a captured one would show twice.
  std::string cursor = "off";
  try {
    session.IsCursorCaptureEnabled(false);
  } catch (...) {
    cursor = "could not be switched off " + hr_text(thrown_hr());
  }

  // The border: left on, Windows draws a yellow frame round the whole monitor for as long
  // as the capture runs. The request is the same plain one the Vulkan presenter's capture
  // library makes. Access is not asked for first (GraphicsCaptureAccess), because that call
  // may put a prompt on screen, and this program shows nothing but its one window.
  border_off = false;
  std::string border;
  try {
    session.IsBorderRequired(false);
    border_off = !session.IsBorderRequired();
    border = border_off ? "off" : "still required";
  } catch (...) {
    border = "could not be switched off " + hr_text(thrown_hr());
  }

  // The property came with Windows 11 24H2; without it every composition is delivered and
  // the limit's own rule does the limiting. It can be changed while the session runs, see
  // set_interval().
  // With no limit 1 ms is asked for all the same: left unset the session has 16 ms, and
  // delivered 59 to 60 frames a second at 120 Hz over a source that changed at every
  // refresh.
  std::string interval = "none";
  const int ask_ms = min_interval_ms > 0 ? min_interval_ms : 1;
  interval_taken = 0;
  try {
    session.MinUpdateInterval(std::chrono::milliseconds(ask_ms));
    interval = strf("%d ms", ask_ms);
    interval_taken = ask_ms;
  } catch (...) {
    interval = strf("%d ms not taken %s", ask_ms, hr_text(thrown_hr()).c_str());
  }

  try {
    gate = std::make_shared<Gate>();
    gate->owner = this;
    said_error = false;
    frame_token = pool.FrameArrived(
        [g = gate](wgc::Direct3D11CaptureFramePool const& sender, wf::IInspectable const&) {
          try {
            std::lock_guard<std::mutex> hold(g->mu);
            if (g->owner) g->owner->on_frame(sender);
          } catch (...) {
          }
        });
    have_frame_token = true;
    session_live.store(true);
    session.StartCapture();
  } catch (...) {
    err = "the monitor cannot be captured " + hr_text(thrown_hr());
    drop_item();
    return false;
  }

  // Said when something in it is new: the loop starts a quiet capture again every few
  // seconds over a still screen to see that it still delivers, with the same settings.
  std::string said = strf("capture: session on a %dx%d monitor, cursor %s, border %s, interval %s",
                          size.Width, size.Height, cursor.c_str(), border.c_str(), interval.c_str());
  if (said != said_session) {
    note("%s", said.c_str());
    said_session = std::move(said);
  }
  return true;
}

void Capture::Impl::stop_session() {
  session_live.store(false);
  if (gate) {
    // Waits for a callback that is running and shuts the gate for any that comes later.
    // No lock of the main thread's is held here.
    std::lock_guard<std::mutex> hold(gate->mu);
    gate->owner = nullptr;
  }
  // No callback runs any more, so the frame the limit kept back is this thread's. It goes
  // with its session. After a pause it would be shown minutes late.
  let_go(held);
  held_due.store(0.0);
  interval_taken = 0;
  try {
    if (have_frame_token && pool) pool.FrameArrived(frame_token);
  } catch (...) {
  }
  have_frame_token = false;
  const bool had_pool = (bool)pool;
  try {
    if (session) session.Close();
  } catch (...) {
  }
  try {
    if (pool) pool.Close();
  } catch (...) {
  }
  session = nullptr;
  pool = nullptr;
  gate.reset();
  running = false;
  border_off = false;
  // D3D11 destroys what was released only at a flush, and nothing flushes this context
  // while no session runs, so a buffer of the pool, the size of the whole monitor (60 MiB
  // at 6144x2560), would stay through a pause. Windows lets go of it a moment after Close
  // returns, not before: measured over 13 stops, the flush straight after Close freed
  // nothing, and the next one, 4 to 15 ms later, freed the buffer every time. So flush,
  // look, and sleep a tick, until the buffers are gone or 100 ms have passed. The last
  // flush is for a buffer let go between a flush and the look that followed it.
  if (context11 && had_pool) {
    const double give_up = now_s() + 0.1;
    for (;;) {
      context11->Flush();
      if (pool_buffers->load() <= 0 || now_s() >= give_up) break;
      Sleep(1);
    }
    context11->Flush();
  }

  // A frame nobody took is from before the stop. After a pause it would come out first,
  // minutes old, and count against the meter. What was handed out stays as it is.
  std::lock_guard<std::mutex> hold(state_mu);
  for (Slot& s : slots) {
    if (s.state == State::Ready || s.state == State::Writing) s.state = State::Free;
  }
}

// ---------------------------------------------------------------- the frame callback

void Capture::Impl::on_frame(wgc::Direct3D11CaptureFramePool const& sender) {
  const double begun = now_s();
  bool took = false;
  try {
    took = take_newest(sender);
  } catch (...) {
    const HRESULT hr = thrown_hr();
    if (!said_error) {
      said_error = true;
      note("capture: a frame could not be taken %s", hr_text(hr).c_str());
    }
  }
  if (!took) return;
  const double ms = (now_s() - begun) * 1000.0;
  std::lock_guard<std::mutex> hold(state_mu);
  counters.callback_ms += ms;
  counters.callbacks += 1;
}

// Closes a frame the limit kept back, which gives its buffer back to the pool.
void Capture::Impl::let_go(Held& frame) {
  frame.texture.Reset();
  try {
    if (frame.frame) frame.frame.Close();
  } catch (...) {
  }
  frame = Held();
}

// Takes the newest frame the pool holds. Its crop is copied into a free slot and published,
// or, when the frame rate limit says its turn has not come, the frame is kept back without
// a copy. Returns whether the pool held a frame at all.
bool Capture::Impl::take_newest(wgc::Direct3D11CaptureFramePool const& sender) {
  wgc::Direct3D11CaptureFrame frame = sender.TryGetNextFrame();
  if (!frame) return false;
  const double came = now_s();

  // More than one waiting means this thread fell behind the screen. Only the newest is
  // worth a copy: an older one counts as arrived and dropped, as if a newer had replaced
  // it in its slot, without the 62 MB copy at 6144x2526 that nobody would read. They are
  // counted with the newest, and not at all when its copy fails.
  unsigned replaced = 0;
  for (;;) {
    wgc::Direct3D11CaptureFrame newer = sender.TryGetNextFrame();
    if (!newer) break;
    const auto old_size = frame.ContentSize();
    {
      std::lock_guard<std::mutex> hold(state_mu);
      if (old_size.Width >= W && old_size.Height >= H) {
        ++replaced;
      } else {
        counters.unfit += 1;
        counters.unfit_w = old_size.Width;
        counters.unfit_h = old_size.Height;
      }
    }
    try {
      frame.Close();
    } catch (...) {
    }
    frame = newer;
  }

  // Everything that can throw comes before a slot is taken, so a slot is never left
  // marked as being written.
  const auto access =
      frame.Surface().as<::Windows::Graphics::DirectX::Direct3D11::IDirect3DDxgiInterfaceAccess>();
  ComPtr<ID3D11Texture2D> texture;
  winrt::check_hresult(access->GetInterface(IID_PPV_ARGS(&texture)));
  D3D11_TEXTURE2D_DESC desc = {};
  texture->GetDesc(&desc);
  {
    // a buffer of the pool seen for the first time gets its tag
    IUnknown* tagged = nullptr;
    UINT size = sizeof(tagged);
    if (SUCCEEDED(texture->GetPrivateData(kPoolBufferTag, &size, &tagged)) && tagged) {
      tagged->Release();
    } else {
      BufferTag* tag = new BufferTag(pool_buffers);
      texture->SetPrivateDataInterface(kPoolBufferTag, tag);
      tag->Release();
    }
  }
  const auto content = frame.ContentSize();
  const double stamp = (double)frame.SystemRelativeTime().count() / 1e7;
  // The picture is the content size, and the texture is the pool's size, which stays what
  // it was when the session began. The copy must stay inside both.
  const int frame_w = std::min<int>(content.Width, (int)desc.Width);
  const int frame_h = std::min<int>(content.Height, (int)desc.Height);
  const bool fits = frame_w >= W && frame_h >= H;

  // The limit's beat judges the frame by its own timestamp. One that lies more than half a
  // second from the clock is not a moment on the refresh grid, whatever it is, and the
  // moment the frame came stands in for it.
  const double beat = std::fabs(stamp - came) < 0.5 ? stamp : came;

  // A frame the limit kept back has now had its newer one, and goes.
  Held gone = std::move(held);
  held = Held();
  held_due.store(0.0);

  bool keep_back = false;
  double due = 0.0;
  {
    std::lock_guard<std::mutex> hold(state_mu);
    if (gone) counters.dropped += 1;
    if (!fits) {
      counters.unfit += 1;
      counters.unfit_w = content.Width;
      counters.unfit_h = content.Height;
      counters.arrived += replaced;
      counters.dropped += replaced;
    } else if (limit_period > 0.0 && !limit_takes(turn, beat, limit_period, limit_early)) {
      keep_back = true;
      counters.arrived += 1 + replaced;
      counters.dropped += replaced;
      // Its turn comes as far from now as its timestamp lies before the turn. Until then,
      // and at least for as long as a newer frame may still be on its way, it is kept.
      due = came + std::max(turn + limit_period - beat, limit_newer);
    }
  }
  let_go(gone);

  if (!fits) {
    // too small, and still a sign that the capture delivers
    last_arrival.store(came);
    texture.Reset();
    try {
      frame.Close();
    } catch (...) {
    }
    return true;
  }
  if (keep_back) {
    held.frame = frame;
    held.texture = texture;
    held.w = frame_w;
    held.h = frame_h;
    held.stamp = stamp;
    held.beat = beat;
    held.arrived = came;
    held_due.store(due);
    last_arrival.store(came);
    // the loop wakes and puts the moment this frame is due into its wait
    SetEvent(frame_event);
    return true;
  }

  const bool handed = copy_out(texture.Get(), frame_w, frame_h, stamp, beat, came, replaced, false);
  // The frame goes back to the pool only now, after the flush in copy_out, when the copy
  // out of its buffer is on its way.
  texture.Reset();
  try {
    frame.Close();
  } catch (...) {
  }
  if (handed) SetEvent(frame_event);
  return true;
}

// Copies the crop of one frame into a free slot and makes it the newest complete frame.
// The gate is held, by the callback or by the main thread for a frame the limit had kept
// back, which was counted as arrived when it came. Returns whether a frame was handed on.
// The turn the frame takes under a limit is used up here.
bool Capture::Impl::copy_out(ID3D11Texture2D* texture, int frame_w, int frame_h, double stamp,
                             double beat, double came, unsigned replaced, bool was_held) {
  int index = -1;
  int x = 0;
  int y = 0;
  {
    std::lock_guard<std::mutex> hold(state_mu);
    // as the Vulkan presenter does: a crop that would reach over the edge is pushed back
    x = std::clamp(crop_x, 0, frame_w - W);
    y = std::clamp(crop_y, 0, frame_h - H);
    for (int i = 0; i < kSlots; ++i) {
      if (slots[i].state == State::Free) {
        index = i;
        break;
      }
    }
    if (index >= 0) {
      slots[index].state = State::Writing;
    } else {
      // four slots rule this out, see the top of the file. Keep the books straight
      if (!was_held) counters.arrived += 1 + replaced;
      counters.dropped += was_held ? 1 : 1 + replaced;
    }
  }
  if (index < 0) {
    // no slot, and still a sign that the capture delivers
    if (!was_held) last_arrival.store(came);
    return false;
  }

  // The copy, then the fence's next value behind it, then the flush that sends both to the
  // GPU now and not when D3D11 next feels like it.
  const D3D11_BOX box = {(UINT)x, (UINT)y, 0, (UINT)(x + W), (UINT)(y + H), 1};
  context11->CopySubresourceRegion(slots[index].tex11.Get(), 0, 0, 0, 0, texture, 0, &box);
  const UINT64 value = ++fence_counter;
  const HRESULT signalled = context11->Signal(fence11.Get(), value);
  context11->Flush();

  {
    std::lock_guard<std::mutex> hold(state_mu);
    if (FAILED(signalled)) {
      // nothing would ever tell the reader this copy is done, so it is not handed out
      slots[index].state = State::Free;
      if (was_held) counters.dropped += 1;
    } else {
      if (!was_held) {
        counters.arrived += 1 + replaced;
        counters.dropped += replaced;
      }
      counters.copies += 1;
      for (Slot& s : slots) {
        if (s.state == State::Ready) {
          s.state = State::Free;
          counters.dropped += 1;
        }
      }
      slots[index].state = State::Ready;
      slots[index].fence_value = value;
      slots[index].timestamp_s = stamp;
      slots[index].arrived_s = came;
      if (limit_period > 0.0) {
        turn_before = turn;
        turn = limit_next_turn(turn, beat, limit_period);
        turn_value = value;
      }
      // Only a frame handed on shows the capture works. One whose copy failed leaves the
      // stamp alone, so the loop's quiet rule starts the capture again and reports it lost
      // when that does not help.
      if (!was_held) last_arrival.store(now_s());
    }
  }
  if (FAILED(signalled)) {
    if (!said_error) {
      said_error = true;
      note("capture: the fence could not be signalled %s", hr_text(signalled).c_str());
    }
    return false;
  }
  return true;
}

// ---------------------------------------------------------------- the contract

Capture::Capture() {}

Capture::~Capture() { destroy(); }

bool Capture::start(ID3D12Device* device, LUID adapter, HMONITOR monitor, int W, int H, int crop_x,
                    int crop_y, int min_interval_ms, HANDLE frame_event, std::string& err) {
  err.clear();
  if (!device || !monitor || !frame_event || W < 1 || H < 1) {
    err = "the capture was started without a device, a monitor, an event or a size";
    return false;
  }
  try {
    if (!impl_) impl_ = new Impl;
    Impl& m = *impl_;
    if (m.running || m.gate) m.stop_session();
    if (m.shared_ready && (m.device12.Get() != device || m.W != W || m.H != H)) {
      err = strf("the capture was made for %dx%d on another device and cannot change", m.W, m.H);
      return false;
    }
    // Keeps a multithreaded apartment alive for the capture API whatever the calling
    // thread has or has not initialised: a thread that never initialised COM is then in
    // that apartment, and the objects used here are agile, so one that did works too.
    if (!m.mta) CoIncrementMTAUsage(&m.mta);
    if (!m.shared_ready && !m.make_shared_parts(device, adapter, W, H, err)) return false;

    {
      std::lock_guard<std::mutex> hold(m.state_mu);
      m.crop_x = crop_x;
      m.crop_y = crop_y;
      // as the Vulkan presenter does when it captures afresh
      m.counters.unfit = 0;
      m.counters.unfit_w = 0;
      m.counters.unfit_h = 0;
    }
    m.frame_event = frame_event;
    m.closed.store(false);
    m.last_arrival.store(now_s());
    if (!m.start_session(monitor, min_interval_ms, err)) {
      m.stop_session();
      return false;
    }
    m.running = true;
    return true;
  } catch (...) {
    err = "the capture could not start " + hr_text(thrown_hr());
    if (impl_) impl_->stop_session();
    return false;
  }
}

void Capture::set_crop(int crop_x, int crop_y) {
  if (!impl_) return;
  std::lock_guard<std::mutex> hold(impl_->state_mu);
  impl_->crop_x = crop_x;
  impl_->crop_y = crop_y;
}

bool Capture::acquire(CaptureFrame& out) {
  if (!impl_) return false;
  Impl& m = *impl_;
  std::lock_guard<std::mutex> hold(m.state_mu);
  Impl::Slot* ready = nullptr;
  for (Impl::Slot& s : m.slots) {
    if (s.state == Impl::State::Ready) ready = &s;
  }
  if (!ready) return false;
  // the one before the last goes back to the capture, the last stays valid one more turn
  for (Impl::Slot& s : m.slots) {
    if (s.state == Impl::State::Prev) s.state = Impl::State::Free;
  }
  for (Impl::Slot& s : m.slots) {
    if (s.state == Impl::State::Held) s.state = Impl::State::Prev;
  }
  ready->state = Impl::State::Held;
  out.texture = ready->tex12.Get();
  out.fence_value = ready->fence_value;
  out.timestamp_s = ready->timestamp_s;
  out.arrived_s = ready->arrived_s;
  return true;
}

bool Capture::set_interval(int min_interval_ms) {
  if (!impl_ || !impl_->running || !impl_->session) return false;
  Impl& m = *impl_;
  const int ask_ms = min_interval_ms > 0 ? min_interval_ms : 1;
  // a session that took none at its start has no such setting, so there is nothing to try
  if (m.interval_taken == 0) return false;
  if (m.interval_taken == ask_ms) return true;
  try {
    m.session.MinUpdateInterval(std::chrono::milliseconds(ask_ms));
    const auto got =
        std::chrono::duration_cast<std::chrono::milliseconds>(m.session.MinUpdateInterval());
    if (got.count() != ask_ms) {
      note("capture: the running session reads an interval of %lld ms back where %d ms was asked",
           (long long)got.count(), ask_ms);
      return false;
    }
  } catch (...) {
    note("capture: the running session did not take an interval of %d ms %s", ask_ms,
         hr_text(thrown_hr()).c_str());
    return false;
  }
  note("capture: the running session's interval is %d ms now, it was %d ms", ask_ms,
       m.interval_taken);
  m.interval_taken = ask_ms;
  return true;
}

int Capture::interval_ms() const { return impl_ && impl_->running ? impl_->interval_taken : 0; }

void Capture::set_limit(double period_s, double early_s, double newer_within_s) {
  try {
    if (!impl_) impl_ = new Impl;
    Impl& m = *impl_;
    const double period = period_s > 0.0 ? period_s : 0.0;
    // the gate first, so no callback judges a frame while the rule changes under it
    const std::shared_ptr<Impl::Gate> gate = m.gate;
    std::unique_lock<std::mutex> gate_hold;
    if (gate) gate_hold = std::unique_lock<std::mutex>(gate->mu);
    std::lock_guard<std::mutex> hold(m.state_mu);
    m.limit_early = early_s > 0.0 ? early_s : 0.0;
    m.limit_newer = newer_within_s > 0.0 ? newer_within_s : 0.0;
    if (period == m.limit_period) return;
    m.limit_period = period;
    m.turn = 0.0;
    m.turn_before = 0.0;
    m.turn_value = 0;
    // a frame kept back under the old limit is the newest there is, and is due now
    if (m.held) m.held_due.store(now_s());
  } catch (...) {
  }
}

double Capture::held_due_s() const { return impl_ ? impl_->held_due.load() : 0.0; }

bool Capture::release_held() {
  if (!impl_) return false;
  Impl& m = *impl_;
  try {
    const std::shared_ptr<Impl::Gate> gate = m.gate;
    if (!gate) return false;
    std::lock_guard<std::mutex> gate_hold(gate->mu);
    if (!m.held) {
      // a newer frame came in its place between the loop's look and this call
      m.held_due.store(0.0);
      return false;
    }
    const double now = now_s();
    if (now < m.held_due.load()) return false;
    Impl::Held frame = std::move(m.held);
    m.held = Impl::Held();
    m.held_due.store(0.0);
    // It takes its turn now, later than its own moment by as long as it was kept. The beat
    // goes on from where the clock is, not from where the frame was.
    const bool handed = m.copy_out(frame.texture.Get(), frame.w, frame.h, frame.stamp,
                                   frame.beat + (now - frame.arrived), frame.arrived, 0, true);
    m.let_go(frame);
    return handed;
  } catch (...) {
    return false;
  }
}

void Capture::turn_back(const CaptureFrame& frame) {
  if (!impl_ || frame.fence_value == 0) return;
  std::lock_guard<std::mutex> hold(impl_->state_mu);
  if (impl_->turn_value != frame.fence_value) return;
  impl_->turn = impl_->turn_before;
  impl_->turn_value = 0;
}

bool Capture::pending() const {
  if (!impl_) return false;
  std::lock_guard<std::mutex> hold(impl_->state_mu);
  for (const Impl::Slot& s : impl_->slots) {
    if (s.state == Impl::State::Ready) return true;
  }
  return false;
}

double Capture::pending_arrived_s() const {
  if (!impl_) return 0.0;
  std::lock_guard<std::mutex> hold(impl_->state_mu);
  for (const Impl::Slot& s : impl_->slots) {
    if (s.state == Impl::State::Ready) return s.arrived_s;
  }
  return 0.0;
}

ID3D12Fence* Capture::fence() const { return impl_ ? impl_->fence12.Get() : nullptr; }

CaptureCounters Capture::take_counters() {
  if (!impl_) return CaptureCounters();
  std::lock_guard<std::mutex> hold(impl_->state_mu);
  const CaptureCounters out = impl_->counters;
  impl_->counters = CaptureCounters();
  return out;
}

bool Capture::closed() const { return impl_ && impl_->closed.load(); }

double Capture::last_arrival_s() const { return impl_ ? impl_->last_arrival.load() : 0.0; }

bool Capture::running() const { return impl_ && impl_->running; }

bool Capture::borderless() const { return impl_ && impl_->border_off; }

void Capture::stop() {
  if (!impl_) return;
  try {
    impl_->stop_session();
  } catch (...) {
  }
}

void Capture::destroy() {
  if (!impl_) return;
  try {
    impl_->stop_session();
  } catch (...) {
  }
  impl_->drop_item();
  impl_->release_shared_parts();
  // C++/WinRT keeps the activation factories it has used. They belong to the apartment
  // that is given up on the next line, so they go first.
  winrt::clear_factory_cache();
  if (impl_->mta) CoDecrementMTAUsage(impl_->mta);
  impl_->mta = nullptr;
  delete impl_;
  impl_ = nullptr;
}
