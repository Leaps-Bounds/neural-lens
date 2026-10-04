// gpu.cpp: the engine's one D3D12 device, its one queue, and the small helpers every module
// records with. See gpu.h for the contract. It follows the Gpu struct of the probe, which
// proved the device, the fence wait and the timestamp queries this way.
#include "gpu.h"

#include <cstring>

using Microsoft::WRL::ComPtr;

namespace {

// Whether one of the adapter's outputs is this monitor.
bool shows(IDXGIAdapter1* adapter, HMONITOR monitor) {
  for (UINT i = 0;; ++i) {
    ComPtr<IDXGIOutput> output;
    if (FAILED(adapter->EnumOutputs(i, &output)) || !output) return false;
    DXGI_OUTPUT_DESC d = {};
    if (SUCCEEDED(output->GetDesc(&d)) && d.Monitor == monitor) return true;
  }
}

bool is_hardware(IDXGIAdapter1* adapter, DXGI_ADAPTER_DESC1& d) {
  d = {};
  return SUCCEEDED(adapter->GetDesc1(&d)) && !(d.Flags & DXGI_ADAPTER_FLAG_SOFTWARE);
}

constexpr UINT kNvidia = 0x10DE;  // the vendor id of an NVIDIA adapter

// The right to raise scheduling priorities, SE_INC_BASE_PRIORITY_NAME, switched on in this
// process's own token. A process run as administrator holds it switched off. Without it the
// scheduler keeps the classes and queues above high for the system. False where the token
// does not hold it.
bool raise_right() {
  HANDLE token = nullptr;
  if (!OpenProcessToken(GetCurrentProcess(), TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY, &token)) return false;
  TOKEN_PRIVILEGES tp = {};
  tp.PrivilegeCount = 1;
  tp.Privileges[0].Attributes = SE_PRIVILEGE_ENABLED;
  const bool ok = LookupPrivilegeValueW(nullptr, SE_INC_BASE_PRIORITY_NAME, &tp.Privileges[0].Luid) &&
                  AdjustTokenPrivileges(token, FALSE, &tp, sizeof(tp), nullptr, nullptr) &&
                  GetLastError() != ERROR_NOT_ALL_ASSIGNED;
  CloseHandle(token);
  return ok;
}

// LENS_FAST_GPU_CLASS=above, high or realtime: this process's class with the card's scheduler,
// through gdi32's D3DKMTSetProcessSchedulingPriorityClass, read back with its Get twin, since a
// call that succeeds may still leave the class where it was. An experiment for a game that keeps
// the card busy, off unless set. Only this process is named.
void gpu_class(const std::wstring& want, bool right) {
  if (want.empty()) return;
  const int level = _wcsicmp(want.c_str(), L"above") == 0      ? 3
                    : _wcsicmp(want.c_str(), L"high") == 0     ? 4
                    : _wcsicmp(want.c_str(), L"realtime") == 0 ? 5
                                                               : -1;
  if (level < 0) {
    note("gpu: LENS_FAST_GPU_CLASS=%s is not above, high or realtime", narrow(want).c_str());
    return;
  }
  typedef LONG(WINAPI * SetClass)(HANDLE, int);
  typedef LONG(WINAPI * GetClass)(HANDLE, int*);
  HMODULE gdi = LoadLibraryW(L"gdi32.dll");
  SetClass set = gdi ? reinterpret_cast<SetClass>(
                           reinterpret_cast<void*>(GetProcAddress(gdi, "D3DKMTSetProcessSchedulingPriorityClass")))
                     : nullptr;
  GetClass get = gdi ? reinterpret_cast<GetClass>(
                           reinterpret_cast<void*>(GetProcAddress(gdi, "D3DKMTGetProcessSchedulingPriorityClass")))
                     : nullptr;
  if (!set) {
    note("gpu: the scheduler class cannot be set on this system");
    return;
  }
  const LONG status = set(GetCurrentProcess(), level);
  int now = -1;
  const LONG read = get ? get(GetCurrentProcess(), &now) : -1;
  note("gpu: scheduler class %s %s, status 0x%08lX, with%s the right to raise priorities, the class is now %d "
       "(read 0x%08lX; 2 normal, 3 above, 4 high, 5 realtime)",
       narrow(want).c_str(), status == 0 ? "set" : "refused", (unsigned long)status, right ? "" : "out", now,
       (unsigned long)read);
}

}  // namespace

bool Gpu::init(HMONITOR monitor, std::string& err) {
  shutdown();
  err.clear();

  HRESULT hr = CreateDXGIFactory2(0, IID_PPV_ARGS(&factory));
  if (FAILED(hr)) {
    err = "CreateDXGIFactory2 failed " + hr_text(hr);
    return false;
  }

  // The adapter that draws the monitor, so that with an NVIDIA card there nothing crosses
  // from one card to another.
  ComPtr<IDXGIAdapter1> pick;
  DXGI_ADAPTER_DESC1 desc = {};
  if (monitor) {
    for (UINT i = 0;; ++i) {
      ComPtr<IDXGIAdapter1> a;
      if (FAILED(factory->EnumAdapters1(i, &a)) || !a) break;
      DXGI_ADAPTER_DESC1 d;
      if (is_hardware(a.Get(), d) && shows(a.Get(), monitor)) {
        pick = a;
        desc = d;
        break;
      }
    }
  }

  // The network runs only on an NVIDIA card. Where another card draws the monitor, as the
  // built-in one does for a laptop's own screen or for a monitor on the mainboard's socket,
  // the first NVIDIA card in the high performance order takes the work, and Windows carries
  // the captured frames to it and the finished picture back. With no NVIDIA card in the
  // computer the monitor's own stays, and the network says what it needs.
  if (pick && desc.VendorId != kNvidia) {
    for (UINT i = 0;; ++i) {
      ComPtr<IDXGIAdapter1> a;
      if (FAILED(factory->EnumAdapterByGpuPreference(i, DXGI_GPU_PREFERENCE_HIGH_PERFORMANCE,
                                                     IID_PPV_ARGS(&a))) || !a)
        break;
      DXGI_ADAPTER_DESC1 d;
      if (is_hardware(a.Get(), d) && d.VendorId == kNvidia) {
        note("gpu: %s draws the monitor, so %s takes the work", ascii(desc.Description).c_str(),
             ascii(d.Description).c_str());
        pick = a;
        desc = d;
        break;
      }
    }
  }

  HRESULT last = S_OK;
  bool any_hardware = false;
  if (pick) {
    any_hardware = true;
    last = D3D12CreateDevice(pick.Get(), D3D_FEATURE_LEVEL_12_0, IID_PPV_ARGS(&device));
  } else {
    // No adapter lists the monitor, or there is none to ask for (the self test): the first
    // hardware adapter, in the system's high performance order, that gives a device.
    for (UINT i = 0;; ++i) {
      ComPtr<IDXGIAdapter1> a;
      if (FAILED(factory->EnumAdapterByGpuPreference(i, DXGI_GPU_PREFERENCE_HIGH_PERFORMANCE,
                                                     IID_PPV_ARGS(&a))) || !a)
        break;
      DXGI_ADAPTER_DESC1 d;
      if (!is_hardware(a.Get(), d)) continue;
      any_hardware = true;
      last = D3D12CreateDevice(a.Get(), D3D_FEATURE_LEVEL_12_0, IID_PPV_ARGS(&device));
      if (SUCCEEDED(last) && device) {
        pick = a;
        desc = d;
        break;
      }
      device.Reset();
    }
  }
  if (!device) {
    err = any_hardware ? "D3D12CreateDevice failed " + hr_text(last) : std::string("no hardware adapter");
    shutdown();
    return false;
  }
  pick.As(&adapter);  // without it only vram_bytes() is lost
  luid = desc.AdapterLuid;
  vendor_id = desc.VendorId;
  name = ascii(desc.Description);
  device->SetName(L"lens-fast device");

  // LENS_FAST_QUEUE_PRIORITY=high asks for a queue ahead of normal ones, and =realtime for one
  // ahead of every other process's, which needs the right to raise priorities, the other
  // experiment for a game that keeps the card busy. A refusal falls back to a normal queue.
  const std::wstring queue_want = env_text(L"LENS_FAST_QUEUE_PRIORITY");
  const std::wstring class_want = env_text(L"LENS_FAST_GPU_CLASS");
  const bool right = (!queue_want.empty() || !class_want.empty()) && raise_right();
  D3D12_COMMAND_QUEUE_DESC qd = {};
  qd.Type = D3D12_COMMAND_LIST_TYPE_DIRECT;
  if (_wcsicmp(queue_want.c_str(), L"high") == 0) qd.Priority = D3D12_COMMAND_QUEUE_PRIORITY_HIGH;
  if (_wcsicmp(queue_want.c_str(), L"realtime") == 0) qd.Priority = D3D12_COMMAND_QUEUE_PRIORITY_GLOBAL_REALTIME;
  hr = device->CreateCommandQueue(&qd, IID_PPV_ARGS(&queue));
  if (FAILED(hr) && qd.Priority != D3D12_COMMAND_QUEUE_PRIORITY_NORMAL) {
    note("gpu: a %s priority queue was refused, %s, with%s the right to raise priorities, so a normal one",
         narrow(queue_want).c_str(), hr_text(hr).c_str(), right ? "" : "out");
    qd.Priority = D3D12_COMMAND_QUEUE_PRIORITY_NORMAL;
    hr = device->CreateCommandQueue(&qd, IID_PPV_ARGS(&queue));
  } else if (SUCCEEDED(hr) && qd.Priority != D3D12_COMMAND_QUEUE_PRIORITY_NORMAL) {
    note("gpu: the queue has %s priority", narrow(queue_want).c_str());
  }
  if (FAILED(hr)) {
    err = "CreateCommandQueue failed " + hr_text(hr);
    shutdown();
    return false;
  }
  queue->SetName(L"lens-fast queue");
  gpu_class(class_want, right);

  hr = device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&fence));
  if (FAILED(hr)) {
    err = "CreateFence failed " + hr_text(hr);
    shutdown();
    return false;
  }
  fence_value = 0;
  fence_event = CreateEventW(nullptr, FALSE, FALSE, nullptr);
  if (!fence_event) {
    err = strf("CreateEvent failed %lu", GetLastError());
    shutdown();
    return false;
  }
  if (FAILED(queue->GetTimestampFrequency(&timestamp_hz))) timestamp_hz = 0;
  return true;
}

void Gpu::shutdown() {
  if (fence_event) CloseHandle(fence_event);
  fence_event = nullptr;
  fence.Reset();
  queue.Reset();
  device.Reset();
  adapter.Reset();
  factory.Reset();
  fence_value = 0;
  luid = {};
  vendor_id = 0;
  name.clear();
  timestamp_hz = 0;
}

bool Gpu::make_list(ComPtr<ID3D12CommandAllocator>& allocator, ComPtr<ID3D12GraphicsCommandList>& list,
                    const wchar_t* name_w, std::string& err) {
  allocator.Reset();
  list.Reset();
  if (!device) {
    err = "no device";
    return false;
  }
  HRESULT hr = device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT, IID_PPV_ARGS(&allocator));
  if (FAILED(hr)) {
    err = "CreateCommandAllocator failed " + hr_text(hr);
    return false;
  }
  hr = device->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_DIRECT, allocator.Get(), nullptr,
                                 IID_PPV_ARGS(&list));
  if (FAILED(hr)) {
    allocator.Reset();
    err = "CreateCommandList failed " + hr_text(hr);
    return false;
  }
  list->Close();  // a new list is open, and every use starts with Reset
  if (name_w) {
    allocator->SetName(name_w);
    list->SetName(name_w);
  }
  return true;
}

bool Gpu::execute(ID3D12GraphicsCommandList* list, UINT64& value, std::string& err) {
  value = 0;
  if (!queue || !list) {
    err = "no device";
    return false;
  }
  HRESULT hr = list->Close();
  if (FAILED(hr)) {
    // a removed device fails every Close, and that is the reason worth reporting
    if (alive(err)) err = "the command list did not close " + hr_text(hr);
    return false;
  }
  ID3D12CommandList* lists[] = {list};
  queue->ExecuteCommandLists(1, lists);
  hr = queue->Signal(fence.Get(), fence_value + 1);
  if (FAILED(hr)) {
    if (alive(err)) err = "the queue's Signal failed " + hr_text(hr);
    return false;
  }
  value = ++fence_value;
  return true;
}

bool Gpu::wait(UINT64 value, DWORD timeout_ms, std::string& err) {
  if (!fence) {
    err = "no device";
    return false;
  }
  const double start = now_s();
  for (;;) {
    const UINT64 done = fence->GetCompletedValue();
    if (done == UINT64_MAX) {  // what a fence reports once its device is removed
      if (alive(err)) err = "device removed";
      return false;
    }
    if (done >= value) return true;
    const double spent_ms = (now_s() - start) * 1000.0;
    if (spent_ms >= (double)timeout_ms) break;
    const HRESULT hr = fence->SetEventOnCompletion(value, fence_event);
    if (FAILED(hr)) {
      if (alive(err)) err = "SetEventOnCompletion failed " + hr_text(hr);
      return false;
    }
    // The event is shared by every wait, so one that timed out earlier can still set it:
    // the loop looks at the fence again after every wake and does not trust the event.
    DWORD left = (DWORD)((double)timeout_ms - spent_ms);
    WaitForSingleObject(fence_event, left ? left : 1);
  }
  if (alive(err)) err = strf("the GPU did not finish in %lu ms", (unsigned long)timeout_ms);
  return false;
}

bool Gpu::flush(DWORD timeout_ms, std::string& err) {
  if (!queue || !fence) {
    err = "no device";
    return false;
  }
  const HRESULT hr = queue->Signal(fence.Get(), fence_value + 1);
  if (FAILED(hr)) {
    if (alive(err)) err = "the queue's Signal failed " + hr_text(hr);
    return false;
  }
  ++fence_value;
  return wait(fence_value, timeout_ms, err);
}

bool Gpu::alive(std::string& err) const {
  if (!device) {
    err = "no device";
    return false;
  }
  const HRESULT reason = device->GetDeviceRemovedReason();
  if (reason == S_OK) return true;
  err = "device removed " + hr_text(reason);
  return false;
}

bool Gpu::make_texture(DXGI_FORMAT format, UINT width, UINT height, D3D12_RESOURCE_FLAGS flags,
                       D3D12_RESOURCE_STATES state, const wchar_t* name_w, ComPtr<ID3D12Resource>& out,
                       std::string& err, const D3D12_CLEAR_VALUE* clear) {
  out.Reset();
  if (!device) {
    err = "no device";
    return false;
  }
  D3D12_HEAP_PROPERTIES hp = {};
  hp.Type = D3D12_HEAP_TYPE_DEFAULT;
  D3D12_RESOURCE_DESC d = {};
  d.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
  d.Width = width;
  d.Height = height;
  d.DepthOrArraySize = 1;
  d.MipLevels = 1;
  d.Format = format;
  d.SampleDesc.Count = 1;
  d.Flags = flags;
  const HRESULT hr =
      device->CreateCommittedResource(&hp, D3D12_HEAP_FLAG_NONE, &d, state, clear, IID_PPV_ARGS(&out));
  if (FAILED(hr)) {
    out.Reset();
    err = strf("texture %s %ux%u format %d failed %s", name_w ? narrow(name_w).c_str() : "?", width, height,
               (int)format, hr_text(hr).c_str());
    return false;
  }
  if (name_w) out->SetName(name_w);
  return true;
}

bool Gpu::make_buffer(UINT64 bytes, D3D12_HEAP_TYPE heap, D3D12_RESOURCE_STATES state,
                      D3D12_RESOURCE_FLAGS flags, const wchar_t* name_w, ComPtr<ID3D12Resource>& out,
                      std::string& err) {
  out.Reset();
  if (!device) {
    err = "no device";
    return false;
  }
  // upload and readback heaps allow one state each, whatever the caller passed
  if (heap == D3D12_HEAP_TYPE_UPLOAD) state = D3D12_RESOURCE_STATE_GENERIC_READ;
  if (heap == D3D12_HEAP_TYPE_READBACK) state = D3D12_RESOURCE_STATE_COPY_DEST;
  D3D12_HEAP_PROPERTIES hp = {};
  hp.Type = heap;
  D3D12_RESOURCE_DESC d = {};
  d.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
  d.Width = bytes ? bytes : 1;
  d.Height = 1;
  d.DepthOrArraySize = 1;
  d.MipLevels = 1;
  d.SampleDesc.Count = 1;
  d.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
  d.Flags = flags;
  const HRESULT hr =
      device->CreateCommittedResource(&hp, D3D12_HEAP_FLAG_NONE, &d, state, nullptr, IID_PPV_ARGS(&out));
  if (FAILED(hr)) {
    out.Reset();
    err = strf("buffer %s of %llu bytes failed %s", name_w ? narrow(name_w).c_str() : "?",
               (unsigned long long)bytes, hr_text(hr).c_str());
    return false;
  }
  if (name_w) out->SetName(name_w);
  return true;
}

UINT64 Gpu::vram_bytes() const {
  DXGI_QUERY_VIDEO_MEMORY_INFO info = {};
  if (adapter && SUCCEEDED(adapter->QueryVideoMemoryInfo(0, DXGI_MEMORY_SEGMENT_GROUP_LOCAL, &info)))
    return info.CurrentUsage;
  return 0;
}

void transition(ID3D12GraphicsCommandList* list, ID3D12Resource* resource, D3D12_RESOURCE_STATES before,
                D3D12_RESOURCE_STATES after) {
  if (before == after || !list || !resource) return;
  D3D12_RESOURCE_BARRIER b = {};
  b.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
  b.Transition.pResource = resource;
  b.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
  b.Transition.StateBefore = before;
  b.Transition.StateAfter = after;
  list->ResourceBarrier(1, &b);
}

// ---------------------------------------------------------------- GPU timestamps

bool GpuTimer::init(Gpu& gpu, UINT n, std::string& err) {
  shutdown();
  if (!gpu.device || n == 0) {
    err = "no device";
    return false;
  }
  D3D12_QUERY_HEAP_DESC qh = {};
  qh.Type = D3D12_QUERY_HEAP_TYPE_TIMESTAMP;
  qh.Count = n;
  HRESULT hr = gpu.device->CreateQueryHeap(&qh, IID_PPV_ARGS(&heap));
  if (FAILED(hr)) {
    err = "CreateQueryHeap failed " + hr_text(hr);
    shutdown();
    return false;
  }
  if (!gpu.make_buffer((UINT64)n * 8, D3D12_HEAP_TYPE_READBACK, D3D12_RESOURCE_STATE_COPY_DEST,
                       D3D12_RESOURCE_FLAG_NONE, L"timestamps", readback, err)) {
    shutdown();
    return false;
  }
  void* p = nullptr;
  hr = readback->Map(0, nullptr, &p);
  if (FAILED(hr) || !p) {
    err = "mapping the timestamps failed " + hr_text(hr);
    shutdown();
    return false;
  }
  // 0 is how ms() knows a slot was never resolved
  memset(p, 0, (size_t)n * 8);
  ticks = (const UINT64*)p;
  count = n;
  return true;
}

void GpuTimer::shutdown() {
  if (readback && ticks) readback->Unmap(0, nullptr);
  ticks = nullptr;
  count = 0;
  readback.Reset();
  heap.Reset();
}

void GpuTimer::mark(ID3D12GraphicsCommandList* list, UINT slot) {
  if (!heap || slot >= count) return;
  list->EndQuery(heap.Get(), D3D12_QUERY_TYPE_TIMESTAMP, slot);
}

void GpuTimer::resolve(ID3D12GraphicsCommandList* list, UINT first, UINT n) {
  if (!heap || n == 0 || first >= count || n > count - first) return;
  list->ResolveQueryData(heap.Get(), D3D12_QUERY_TYPE_TIMESTAMP, first, n, readback.Get(), (UINT64)first * 8);
}

double GpuTimer::ms(const Gpu& gpu, UINT a, UINT b) const {
  if (!ticks || a >= count || b >= count || gpu.timestamp_hz == 0) return 0.0;
  const UINT64 t0 = ticks[a], t1 = ticks[b];
  if (t0 == 0 || t1 == 0 || t1 < t0) return 0.0;
  return (double)(t1 - t0) * 1000.0 / (double)gpu.timestamp_hz;
}
