// nr.cpp: Neural Rendering (NGX feature 18) called directly through the stack's DLL, with
// the engine's own parameter object. See nr.h for the contract and ngx_min.h for the few
// declarations the calls take.
//
// The probe measured this way of calling the runtime on an RTX 5090 at 2560x1053: evaluate
// 3.35 ms on the GPU, create 257 ms on the CPU, 690 MiB of video memory.
// The call order (Init_Ext, CreateFeature(18) on a command list, EvaluateFeature),
// the application id and the parameter names and types set in create_params() and
// eval_params() follow, and in places adapt, the openNR native benchmark adapter
// (benchmarks/native/include/neural_rendering_direct.hpp), which carries this notice:
//
//   MIT License
//
//   Copyright (c) 2026 Carlos Lopez Jr.
//
//   Permission is hereby granted, free of charge, to any person obtaining a copy
//   of this software and associated documentation files (the "Software"), to deal
//   in the Software without restriction, including without limitation the rights
//   to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
//   copies of the Software, and to permit persons to whom the Software is
//   furnished to do so, subject to the following conditions:
//
//   The above copyright notice and this permission notice shall be included in all
//   copies or substantial portions of the Software.
//
//   THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
//   IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
//   FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
//   AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
//   LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
//   OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
//   SOFTWARE.
//
// openNR states that this adapter originates in or is adapted from RenoDX
// (https://github.com/clshortfuse/renodx), Copyright (c) 2025 Carlos Lopez Jr., under the
// same MIT terms.
//
// No NVIDIA header is included and nothing of the SDK is copied: the runtime is reached
// through GetProcAddress and the hand written declarations in ngx_min.h.
#include "nr.h"

#include "ngx_min.h"

#include <cstdio>
#include <cstring>
#include <cwchar>
#include <map>
#include <mutex>
#include <string_view>

using Microsoft::WRL::ComPtr;

namespace {

// ---------------------------------------------------------------- the parameter object

// What the runtime asked for, by name: "type:found" or "type:missing", the last getter that
// asked winning. Only filled with LENS_FAST_NR_READS=1, and written to
// <data folder>\nr-reads.txt at shutdown in the format of the probe's own list, so
// the two can be compared line by line. That comparison is the proof on the real runtime
// that every getter sits in the slot the runtime calls: a getter in the wrong slot would
// show up under another type.
bool g_record_reads = false;
std::mutex g_reads_lock;
std::map<std::string, std::string> g_reads;

// The engine's implementation of the interface the runtime reads its inputs through.
// Every number is kept both as a whole number and as a real one, filled in when it is set,
// so each getter hands back the shape it was asked for whatever shape the value came in:
// the engine sets a size as unsigned and the runtime reads it as unsigned or as int, and
// the proxy, when it scales, writes sizes and scales back into this object.
// The runtime may call from a thread of its own, so every access takes the lock.
class Store final : public ngx::Params {
 public:
  void Set(const char* name, unsigned long long v) override { number(name, (long long)v, (double)v); }
  void Set(const char* name, float v) override { number(name, (long long)v, (double)v); }
  void Set(const char* name, double v) override { number(name, (long long)v, v); }
  void Set(const char* name, unsigned int v) override { number(name, (long long)v, (double)v); }
  void Set(const char* name, int v) override { number(name, (long long)v, (double)v); }
  void Set(const char* name, ID3D11Resource* v) override { pointer(name, v); }
  void Set(const char* name, ID3D12Resource* v) override { pointer(name, v); }
  void Set(const char* name, void* v) override { pointer(name, v); }

  ngx::Result Get(const char* name, unsigned long long* out) const override {
    Value v;
    if (!find(name, "ull", false, v) || !out) return (ngx::Result)0xBAD00000;
    *out = (unsigned long long)v.whole;
    return ngx::kSuccess;
  }
  ngx::Result Get(const char* name, float* out) const override {
    Value v;
    if (!find(name, "float", false, v) || !out) return (ngx::Result)0xBAD00000;
    *out = (float)v.real;
    return ngx::kSuccess;
  }
  ngx::Result Get(const char* name, double* out) const override {
    Value v;
    if (!find(name, "double", false, v) || !out) return (ngx::Result)0xBAD00000;
    *out = v.real;
    return ngx::kSuccess;
  }
  ngx::Result Get(const char* name, unsigned int* out) const override {
    Value v;
    if (!find(name, "uint", false, v) || !out) return (ngx::Result)0xBAD00000;
    *out = (unsigned int)v.whole;
    return ngx::kSuccess;
  }
  ngx::Result Get(const char* name, int* out) const override {
    Value v;
    if (!find(name, "int", false, v) || !out) return (ngx::Result)0xBAD00000;
    *out = (int)v.whole;
    return ngx::kSuccess;
  }
  ngx::Result Get(const char* name, ID3D11Resource** out) const override {
    Value v;
    if (!find(name, "d3d11", true, v) || !out) return (ngx::Result)0xBAD00000;
    *out = (ID3D11Resource*)v.ptr;
    return ngx::kSuccess;
  }
  ngx::Result Get(const char* name, ID3D12Resource** out) const override {
    Value v;
    if (!find(name, "d3d12", true, v) || !out) return (ngx::Result)0xBAD00000;
    *out = (ID3D12Resource*)v.ptr;
    return ngx::kSuccess;
  }
  ngx::Result Get(const char* name, void** out) const override {
    Value v;
    if (!find(name, "void*", true, v) || !out) return (ngx::Result)0xBAD00000;
    *out = v.ptr;
    return ngx::kSuccess;
  }
  void Reset() override {
    std::lock_guard<std::mutex> hold(lock_);
    values_.clear();
  }

 private:
  struct Value {
    bool is_pointer = false;
    long long whole = 0;
    double real = 0.0;
    void* ptr = nullptr;
  };

  void put(const char* name, const Value& v) {
    if (!name) return;
    std::lock_guard<std::mutex> hold(lock_);
    // looked up without building a string: after the first frame every name is there
    auto it = values_.find(std::string_view(name));
    if (it != values_.end()) it->second = v;
    else values_.emplace(name, v);
  }
  void number(const char* name, long long whole, double real) {
    Value v;
    v.whole = whole;
    v.real = real;
    put(name, v);
  }
  void pointer(const char* name, void* p) {
    Value v;
    v.is_pointer = true;
    v.ptr = p;
    put(name, v);
  }

  // A number is never handed out as a pointer nor a pointer as a number.
  bool find(const char* name, const char* type, bool want_pointer, Value& out) const {
    if (!name) return false;
    bool found = false;
    {
      std::lock_guard<std::mutex> hold(lock_);
      auto it = values_.find(std::string_view(name));
      found = it != values_.end();
      if (found) out = it->second;
    }
    if (g_record_reads) {
      std::lock_guard<std::mutex> hold(g_reads_lock);
      g_reads[name] = std::string(type) + (found ? ":found" : ":missing");
    }
    return found && out.is_pointer == want_pointer;
  }

  mutable std::mutex lock_;
  std::map<std::string, Value, std::less<>> values_;
};

// The runtime may look this up and call it. The network works at the size it is given.
ngx::Result __cdecl scaling_ratio(ngx::Params* params) {
  if (!params) return (ngx::Result)0xBAD00005;
  params->Set("DLSSNR.ScalingRatio", 1.0f);
  return ngx::kSuccess;
}

// What the probe ran with and the reference picture was made with: preset 0 (the stack's
// NRPreset) and openNR's default performance mode.
constexpr unsigned kRenderPreset = 0;
constexpr int kPerfQualityValue = 2;

void sizes(ngx::Params* p, unsigned w, unsigned h) {
  p->Set("Width", w);
  p->Set("Height", h);
  p->Set("OutWidth", w);
  p->Set("OutHeight", h);
  p->Set("DLSSNR.Width", w);
  p->Set("DLSSNR.Height", h);
  p->Set("DLSSNR.InputWidth", w);
  p->Set("DLSSNR.InputHeight", h);
  p->Set("DLSSNR.OutputWidth", w);
  p->Set("DLSSNR.OutputHeight", h);
  p->Set("DLSSNR.Output.Width", w);
  p->Set("DLSSNR.Output.Height", h);
}

void create_params(ngx::Params* p, unsigned w, unsigned h) {
  p->Set("CreationNodeMask", 1u);
  p->Set("VisibilityNodeMask", 1u);
  sizes(p, w, h);
  p->Set("DLSSNR.Hint.Render.Preset", kRenderPreset);
  p->Set("PerfQualityValue", kPerfQualityValue);
  p->Set("DLSSNRComputeScalingRatioCallback", reinterpret_cast<void*>(&scaling_ratio));
  p->Set("DLSSNR.ScalingRatio", 1.0f);
  p->Set("DLSSNR.Scale", 1.0f);
  p->Set("DLSSNR.Upscaling", 0);
}

void subrect(ngx::Params* p, const char* base_x, const char* base_y, const char* width, const char* height,
             unsigned w, unsigned h) {
  p->Set(base_x, 0u);
  p->Set(base_y, 0u);
  p->Set(width, w);
  p->Set(height, h);
}

// The zero motion and zero depth textures are this many texels each way. Measured at
// 2560x1053 over 300 runs after 120 to warm up, textures of one texel against textures of
// the work size gave the same output byte for byte, in 3.346 ms against 3.355, on 21 MiB
// less video memory. The self test's reference pictures were made with the large ones, and
// the engine's pictures are still theirs byte for byte.
constexpr unsigned kZeroSide = 1;

// Everything the runtime reads at an evaluate is set afresh every time, as the probe did:
// the proxy writes sizes and textures into this object when it scales, and nothing of that
// may be left over. Some fifty values, a few microseconds.
void eval_params(ngx::Params* p, ID3D12Resource* in, ID3D12Resource* out, ID3D12Resource* motion,
                 ID3D12Resource* depth, unsigned w, unsigned h, bool reset, const NrSettings& s) {
  sizes(p, w, h);
  p->Set("DLSSNR.Color", in);
  p->Set("DLSSNR.Output", out);
  p->Set("DLSSNR.MVec", motion);
  p->Set("DLSSNR.Depth", depth);
  // the runtime asks for both; null is what the probe handed over
  p->Set("DLSSNR.UI", static_cast<ID3D12Resource*>(nullptr));
  p->Set("DLSSNR.UIAlpha", static_cast<ID3D12Resource*>(nullptr));
  subrect(p, "DLSSNR.ColorSubrectBaseX", "DLSSNR.ColorSubrectBaseY", "DLSSNR.ColorSubrectWidth",
          "DLSSNR.ColorSubrectHeight", w, h);
  // The whole of the two zero textures, with the motion scale that maps them onto the work
  // size. The vectors are zero, so the scale changes no value, and it is set to match all
  // the same.
  subrect(p, "DLSSNR.MVecSubrectBaseX", "DLSSNR.MVecSubrectBaseY", "DLSSNR.MVecSubrectWidth",
          "DLSSNR.MVecSubrectHeight", kZeroSide, kZeroSide);
  subrect(p, "DLSSNR.DepthSubrectBaseX", "DLSSNR.DepthSubrectBaseY", "DLSSNR.DepthSubrectWidth",
          "DLSSNR.DepthSubrectHeight", kZeroSide, kZeroSide);
  subrect(p, "DLSSNR.OutputSubrectBaseX", "DLSSNR.OutputSubrectBaseY", "DLSSNR.OutputSubrectWidth",
          "DLSSNR.OutputSubrectHeight", w, h);
  p->Set("Jitter.Offset.X", 0.0f);
  p->Set("Jitter.Offset.Y", 0.0f);
  p->Set("DLSSNR.JitterOffsetX", 0.0f);
  p->Set("DLSSNR.JitterOffsetY", 0.0f);
  p->Set("DLSSNR.MVecScaleX", (float)w / (float)kZeroSide);
  p->Set("DLSSNR.MVecScaleY", (float)h / (float)kZeroSide);
  p->Set("DLSSNR.DepthInverted", 0);
  p->Set("DLSSNR.Enabled", 1);
  p->Set("DLSSNR.Reset", reset ? 1 : 0);
  p->Set("DLSSNR.Intensity", s.intensity);
  p->Set("DLSSNR.LocalToneStrength", s.local_tone);
  p->Set("DLSSNR.LocalStructureStrength", s.local_structure);
  p->Set("DLSSNR.UseAutoMask", s.auto_mask);
  p->Set("DLSSNR.SkinStructureStrength", s.skin_structure);
  p->Set("DLSSNR.Style", s.style);
  p->Set("DLSSNR.UICorrection", 0);
  p->Set("DLSS.Indicator.Invert.X.Axis", 0);
  p->Set("DLSS.Indicator.Invert.Y.Axis", 0);
}

// ---------------------------------------------------------------- calls into the DLL
//
// Each one in a function of its own with nothing in it that needs unwinding, which is what
// a structured exception handler asks for. A crash inside the DLL comes back as kRaised.

DWORD g_raised = 0;  // the code of the last exception a call raised

ngx::Result call_init(ngx::InitFn f, const wchar_t* data_path, ID3D12Device* device) {
  __try {
    return f(ngx::kAppId, data_path, device, ngx::kApiVersion, nullptr);
  } __except (EXCEPTION_EXECUTE_HANDLER) {
    g_raised = GetExceptionCode();
    return ngx::kRaised;
  }
}

ngx::Result call_create(ngx::CreateFn f, ID3D12GraphicsCommandList* list, const ngx::Params* params,
                        ngx::Handle** out) {
  __try {
    return f(list, ngx::kFeatureNeuralRendering, params, out);
  } __except (EXCEPTION_EXECUTE_HANDLER) {
    g_raised = GetExceptionCode();
    return ngx::kRaised;
  }
}

ngx::Result call_evaluate(ngx::EvaluateFn f, ID3D12GraphicsCommandList* list, const ngx::Handle* handle,
                          const ngx::Params* params) {
  __try {
    return f(list, handle, params, nullptr);
  } __except (EXCEPTION_EXECUTE_HANDLER) {
    g_raised = GetExceptionCode();
    return ngx::kRaised;
  }
}

bool call_release(ngx::ReleaseFn f, ngx::Handle* handle) {
  __try {
    f(handle);
    return true;
  } __except (EXCEPTION_EXECUTE_HANDLER) {
    g_raised = GetExceptionCode();
    return false;
  }
}

ngx::Result call_shutdown(ngx::ShutdownFn f, ID3D12Device* device) {
  __try {
    return f(device);
  } __except (EXCEPTION_EXECUTE_HANDLER) {
    g_raised = GetExceptionCode();
    return ngx::kRaised;
  }
}

// The proxy answers -1 when it could not load the runtime beside it, and the SDK's own
// test for success would let that through.
bool good(ngx::Result r) { return ngx::ok(r) && r != (ngx::Result)-1; }

std::string outcome(const char* call, ngx::Result r) {
  if (r == ngx::kRaised) return strf("%s raised an exception 0x%08lX", call, (unsigned long)g_raised);
  if (r == (ngx::Result)-1)
    return strf("%s failed, the proxy could not load nvngx_dlssnr_real.dll beside it", call);
  return strf("%s failed 0x%08X %s", call, (unsigned)r, ngx::result_text(r));
}

// ---------------------------------------------------------------- the proxy's ini

// Whether two paths name the same folder: by identity, so another spelling, a short name
// or a junction still counts.
bool same_folder(const std::wstring& a, const std::wstring& b) {
  auto identity = [](const std::wstring& path, BY_HANDLE_FILE_INFORMATION& info) {
    HANDLE h = CreateFileW(path.c_str(), 0, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr,
                           OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS, nullptr);
    if (h == INVALID_HANDLE_VALUE) return false;
    const bool got = GetFileInformationByHandle(h, &info) != 0;
    CloseHandle(h);
    return got;
  };
  BY_HANDLE_FILE_INFORMATION ia = {}, ib = {};
  if (identity(a, ia) && identity(b, ib))
    return ia.dwVolumeSerialNumber == ib.dwVolumeSerialNumber && ia.nFileIndexHigh == ib.nFileIndexHigh &&
           ia.nFileIndexLow == ib.nFileIndexLow;
  return _wcsicmp(a.c_str(), b.c_str()) == 0;
}

// A switch of the proxy's, read as the proxy reads it: a missing key or file counts as on.
bool proxy_key_on(const std::wstring& ini, const wchar_t* key) {
  return GetPrivateProfileIntW(L"DLSSNR_Proxy", key, 1, ini.c_str()) != 0;
}

// Makes sure the proxy passes straight through in this process. It reads nvngx_dlssnr.ini
// next to the EXE when there is one and only otherwise the one next to itself (proved by
// the self test, both ways round), so the engine keeps an ini of its own next to
// lens-fast.exe with the proxy and its hotkeys off, and never touches the stack's.
// false with err only when the proxy would rescale and nothing can be done about it.
bool private_proxy_ini(const std::wstring& stack_dir, std::string& err) {
  const std::wstring here = exe_dir();
  const std::wstring theirs = path_join(stack_dir, L"nvngx_dlssnr.ini");
  if (here.empty() || same_folder(here, stack_dir)) {
    // the exe's ini and the stack's are one file here, and that one is the lens's to set
    note("nr: the exe is in the stack folder, nvngx_dlssnr.ini is left as the lens set it (proxy %s)",
         proxy_key_on(theirs, L"EnableProxy") ? "ON, it will rescale" : "off");
    return true;
  }
  const std::wstring mine = path_join(here, L"nvngx_dlssnr.ini");
  if (env_text(L"LENS_FAST_KEEP_PROXY_INI") == L"1") {
    note("nr: LENS_FAST_KEEP_PROXY_INI is set, %s is left alone", narrow(mine).c_str());
    return true;
  }
  auto off = [](const std::wstring& ini) {
    return file_exists(ini) && !proxy_key_on(ini, L"EnableProxy") && !proxy_key_on(ini, L"EnableHotkeys");
  };
  if (off(mine)) return true;

  // Missing, or not what it has to be: the stack's ini as the base, so every other key
  // stays as the lens set it, then the two switches. The profile functions are the ones
  // the proxy reads with, so what is written here is read there the same way.
  bool based = false;
  if (file_exists(theirs)) {
    based = CopyFileW(theirs.c_str(), mine.c_str(), FALSE) != 0;
    if (based) SetFileAttributesW(mine.c_str(), FILE_ATTRIBUTE_NORMAL);  // a read-only copy could not be edited
  }
  WritePrivateProfileStringW(L"DLSSNR_Proxy", L"EnableProxy", L"0", mine.c_str());
  WritePrivateProfileStringW(L"DLSSNR_Proxy", L"EnableHotkeys", L"0", mine.c_str());
  WritePrivateProfileStringW(nullptr, nullptr, nullptr, mine.c_str());  // nothing stays cached
  if (off(mine)) {
    note("nr: wrote %s with the proxy and its hotkeys off%s", narrow(mine).c_str(),
         based ? ", from the stack's ini" : "");
    return true;
  }

  // The folder cannot be written. What the proxy will read is then the ini here when
  // there is one and the stack's otherwise.
  const std::wstring& read = file_exists(mine) ? mine : theirs;
  if (file_exists(read) && !proxy_key_on(read, L"EnableProxy")) {
    note("nr: could not write %s, the proxy is off in %s all the same%s", narrow(mine).c_str(),
         narrow(read).c_str(), proxy_key_on(read, L"EnableHotkeys") ? ", its hotkeys are on" : "");
    return true;
  }
  err = "cannot write " + narrow(mine) + ", and without it the proxy would rescale the picture";
  return false;
}

// The runtime is initialised once for the device and is not known to take a second time.
bool g_started_once = false;

// Feature creation took 257 ms on the CPU in the probe for the first feature of a process,
// and takes 118 to 135 ms for a later one, with the GPU work behind it. The wait has a limit
// because every wait in this process has one.
constexpr DWORD kCreateWaitMs = 20000;

// The features of one work size, one for each pass.
struct Features {
  UINT w = 0, h = 0;
  ngx::Handle* feature[kNrMaxPasses] = {};
  // One parameter object for each feature, so that what one pass was told can never be
  // read by another: when the runtime reads is its own business.
  Store* params[kNrMaxPasses] = {};
  double create_ms = 0.0;
  bool made = false;
};

}  // namespace

struct Nr::Impl {
  Gpu* gpu = nullptr;
  HMODULE dll = nullptr;  // never freed, see shutdown()
  ngx::InitFn init = nullptr;
  ngx::CreateFn create = nullptr;
  ngx::EvaluateFn evaluate = nullptr;
  ngx::ReleaseFn release = nullptr;
  ngx::ShutdownFn shutdown = nullptr;
  bool initialised = false;  // Init_Ext succeeded, so Shutdown1 is owed
  bool ready = false;
  int passes = 0;
  NrPasses settings;              // each pass's own, pass p evaluates with settings.pass[p]
  Features now;                   // what evaluate() uses
  Features next;                  // what prepare() made, until use_prepared() takes it
  ComPtr<ID3D12Resource> motion;  // R16G16_FLOAT, one texel, zero
  ComPtr<ID3D12Resource> depth;   // R32_FLOAT, one texel, zero
  // The list the features are created on, kept for the ones a new work size needs, and a
  // fence of its own to wait for it by. prepare() may run on another thread than the one
  // that draws, and Gpu's own fence and its count belong to the drawing thread alone. The
  // queue itself takes lists from any thread.
  ComPtr<ID3D12CommandAllocator> allocator;
  ComPtr<ID3D12GraphicsCommandList> list;
  ComPtr<ID3D12Fence> fence;
  HANDLE fence_event = nullptr;
  UINT64 fence_value = 0;
  double create_ms = 0.0;         // of init's features
  double prepare_ms = 0.0;        // of the last prepare()'s
  std::wstring data_dir;

  // Closes the creation list, runs it on the queue and waits until the GPU has finished it.
  bool run_list(std::string& err) {
    HRESULT hr = list->Close();
    if (FAILED(hr)) {
      if (gpu->alive(err)) err = "the command list did not close " + hr_text(hr);
      return false;
    }
    ID3D12CommandList* lists[] = {list.Get()};
    gpu->queue->ExecuteCommandLists(1, lists);
    const UINT64 value = ++fence_value;
    hr = gpu->queue->Signal(fence.Get(), value);
    if (FAILED(hr)) {
      if (gpu->alive(err)) err = "the queue's Signal failed " + hr_text(hr);
      return false;
    }
    const double start = now_s();
    for (;;) {
      const UINT64 done = fence->GetCompletedValue();
      if (done == UINT64_MAX) {  // what a fence reports once its device is removed
        if (gpu->alive(err)) err = "device removed";
        return false;
      }
      if (done >= value) return true;
      if ((now_s() - start) * 1000.0 >= (double)kCreateWaitMs) break;
      if (FAILED(fence->SetEventOnCompletion(value, fence_event))) {
        Sleep(1);
        continue;
      }
      WaitForSingleObject(fence_event, 100);  // and the fence is looked at again
    }
    if (gpu->alive(err)) err = strf("the GPU did not finish in %lu ms", (unsigned long)kCreateWaitMs);
    return false;
  }

  // Releases the features of a set. The parameter objects stay, see shutdown().
  void release_set(Features& set) {
    for (int i = 0; i < kNrMaxPasses; ++i) {
      if (set.feature[i] && release && !call_release(release, set.feature[i]))
        note("nr: ReleaseFeature raised an exception 0x%08lX", (unsigned long)g_raised);
      set.feature[i] = nullptr;
    }
    set.made = false;
  }

  // One feature for each pass at w x h, each created on a list of its own as the probe did,
  // run and waited for. false with err, and whatever was created is released again.
  bool create_set(UINT w, UINT h, Features& set, std::string& err) {
    set = Features();
    set.w = w;
    set.h = h;
    for (int i = 0; i < passes; ++i) {
      set.params[i] = new Store();
      create_params(set.params[i], w, h);
      if (FAILED(allocator->Reset()) || FAILED(list->Reset(allocator.Get(), nullptr))) {
        err = "resetting the list the features are created on failed";
        release_set(set);
        return false;
      }
      const double t0 = now_s();
      const ngx::Result r = call_create(create, list.Get(), set.params[i], &set.feature[i]);
      set.create_ms += (now_s() - t0) * 1000.0;
      if (!good(r) || !set.feature[i]) {
        // the list may hold part of the runtime's commands: it is closed and never run
        list->Close();
        err = good(r) ? std::string("CreateFeature gave no feature") : outcome("CreateFeature", r);
        err += strf(" at %ux%u", w, h);
        if (passes > 1) err += strf(" (pass %d of %d)", i + 1, passes);
        set.feature[i] = nullptr;
        release_set(set);
        return false;
      }
      std::string run_err;
      if (!run_list(run_err)) {
        err = "creating the feature: " + run_err;
        release_set(set);
        return false;
      }
    }
    set.made = true;
    return true;
  }
};

Nr::Nr() {}

Nr::~Nr() { shutdown(); }

bool Nr::init(Gpu& gpu, const std::wstring& stack_dir, const std::wstring& data_dir, UINT work_w,
              UINT work_h, int passes, const NrPasses& settings, std::string& err) {
  shutdown();
  err.clear();
  if (g_started_once) {
    err = "Neural Rendering was already started once in this process";
    return false;
  }
  if (!gpu.device || !gpu.queue) {
    err = "no device";
    return false;
  }
  if (gpu.vendor_id != 0x10DE) {
    err = "the adapter is not an NVIDIA card";
    return false;
  }
  if (work_w == 0 || work_h == 0 || passes < 1 || passes > kNrMaxPasses) {
    err = strf("bad work size %ux%u or pass count %d", work_w, work_h, passes);
    return false;
  }
  const std::wstring dll_path = path_join(stack_dir, L"nvngx_dlssnr.dll");
  if (!file_exists(dll_path)) {
    err = "nvngx_dlssnr.dll not found in " + narrow(stack_dir);
    return false;
  }
  if (!make_dirs(data_dir)) {
    err = "cannot create the data folder " + narrow(data_dir);
    return false;
  }
  if (!private_proxy_ini(stack_dir, err)) return false;

  g_record_reads = env_text(L"LENS_FAST_NR_READS") == L"1";

  impl_ = new Impl();
  Impl& m = *impl_;
  m.gpu = &gpu;
  m.passes = passes;
  m.settings = settings;
  m.data_dir = data_dir;

  // By its full path, and with its own folder searched first for what it loads in turn.
  m.dll = LoadLibraryExW(dll_path.c_str(), nullptr, LOAD_WITH_ALTERED_SEARCH_PATH);
  if (!m.dll) {
    err = strf("loading %s failed, error %lu", narrow(dll_path).c_str(), GetLastError());
    shutdown();
    return false;
  }
  m.init = (ngx::InitFn)GetProcAddress(m.dll, ngx::kInitName);
  m.create = (ngx::CreateFn)GetProcAddress(m.dll, ngx::kCreateName);
  m.evaluate = (ngx::EvaluateFn)GetProcAddress(m.dll, ngx::kEvaluateName);
  m.release = (ngx::ReleaseFn)GetProcAddress(m.dll, ngx::kReleaseName);
  m.shutdown = (ngx::ShutdownFn)GetProcAddress(m.dll, ngx::kShutdownName);  // may be missing
  if (!m.init || !m.create || !m.evaluate || !m.release) {
    err = "nvngx_dlssnr.dll lacks one of the four functions the engine calls";
    shutdown();
    return false;
  }

  g_started_once = true;
  ngx::Result r = call_init(m.init, data_dir.c_str(), gpu.device.Get());
  if (!good(r)) {
    err = outcome("Init_Ext", r);
    shutdown();
    return false;
  }
  m.initialised = true;

  if (!gpu.make_list(m.allocator, m.list, L"nr features", err)) {
    shutdown();
    return false;
  }
  {
    const HRESULT hr = gpu.device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&m.fence));
    m.fence_event = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    if (FAILED(hr) || !m.fence_event) {
      err = "the fence for the feature's creation failed " + hr_text(hr);
      shutdown();
      return false;
    }
  }
  ID3D12GraphicsCommandList* list = m.list.Get();

  // ---- zero motion vectors and zero depth, one texel each, uploaded once
  const D3D12_RESOURCE_STATES kRead = D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
  if (!gpu.make_texture(DXGI_FORMAT_R16G16_FLOAT, kZeroSide, kZeroSide, D3D12_RESOURCE_FLAG_NONE,
                        D3D12_RESOURCE_STATE_COPY_DEST, L"nr zero motion", m.motion, err) ||
      !gpu.make_texture(DXGI_FORMAT_R32_FLOAT, kZeroSide, kZeroSide, D3D12_RESOURCE_FLAG_NONE,
                        D3D12_RESOURCE_STATE_COPY_DEST, L"nr zero depth", m.depth, err)) {
    shutdown();
    return false;
  }
  {
    ID3D12Resource* targets[2] = {m.motion.Get(), m.depth.Get()};
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT fp[2] = {};
    UINT64 bytes = 0;
    for (int i = 0; i < 2; ++i) {
      const D3D12_RESOURCE_DESC d = targets[i]->GetDesc();
      UINT64 total = 0;
      gpu.device->GetCopyableFootprints(&d, 0, 1, 0, &fp[i], nullptr, nullptr, &total);
      if (total > bytes) bytes = total;
    }
    ComPtr<ID3D12Resource> zeros;
    if (!gpu.make_buffer(bytes, D3D12_HEAP_TYPE_UPLOAD, D3D12_RESOURCE_STATE_GENERIC_READ,
                         D3D12_RESOURCE_FLAG_NONE, L"nr zeros", zeros, err)) {
      shutdown();
      return false;
    }
    void* p = nullptr;
    const D3D12_RANGE none = {0, 0};  // nothing is read through this mapping
    if (FAILED(zeros->Map(0, &none, &p)) || !p) {
      err = "mapping the zero upload failed";
      shutdown();
      return false;
    }
    memset(p, 0, (size_t)bytes);
    zeros->Unmap(0, nullptr);

    bool ok = SUCCEEDED(m.allocator->Reset()) && SUCCEEDED(list->Reset(m.allocator.Get(), nullptr));
    if (ok) {
      for (int i = 0; i < 2; ++i) {
        D3D12_TEXTURE_COPY_LOCATION dst = {};
        dst.pResource = targets[i];
        dst.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        D3D12_TEXTURE_COPY_LOCATION src = {};
        src.pResource = zeros.Get();
        src.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
        src.PlacedFootprint = fp[i];
        list->CopyTextureRegion(&dst, 0, 0, 0, &src, nullptr);
        transition(list, targets[i], D3D12_RESOURCE_STATE_COPY_DEST, kRead);
      }
      ok = m.run_list(err);
    } else {
      err = "resetting the init list failed";
    }
    if (!ok) {
      shutdown();
      return false;
    }
    // zeros goes out of scope here, after the GPU has finished the copies
  }

  // ---- one feature for each pass
  if (!m.create_set(work_w, work_h, m.now, err)) {
    shutdown();
    return false;
  }
  m.create_ms = m.now.create_ms;

  m.ready = true;
  const NrSettings& base = settings.base();
  note("nr: %ux%u, %d pass%s, created in %.0f ms on the CPU, style %u intensity %.2f tone %.2f structure %.2f "
       "skin %.2f mask %d",
       work_w, work_h, passes, passes == 1 ? "" : "es", m.create_ms, base.style, base.intensity, base.local_tone,
       base.local_structure, base.skin_structure, base.auto_mask);
  for (int p = 1; p < passes; ++p) {
    const std::string own = own_values_text(base, settings.pass[p]);
    if (!own.empty()) note("nr: pass %d has its own %s", p + 1, own.c_str());
  }
  return true;
}

bool Nr::ready() const { return impl_ && impl_->ready; }

bool Nr::prepare(UINT work_w, UINT work_h, std::string& err) {
  if (!ready()) {
    err = "the network is not loaded";
    return false;
  }
  Impl& m = *impl_;
  if (work_w == 0 || work_h == 0) {
    err = strf("bad work size %ux%u", work_w, work_h);
    return false;
  }
  drop_prepared();
  if (!m.create_set(work_w, work_h, m.next, err)) return false;
  m.prepare_ms = m.next.create_ms;
  note("nr: %ux%u made beside %ux%u, %d pass%s, created in %.0f ms on the CPU", work_w, work_h, m.now.w, m.now.h,
       m.passes, m.passes == 1 ? "" : "es", m.next.create_ms);
  return true;
}

void Nr::use_prepared() {
  if (!impl_ || !impl_->next.made) return;
  Impl& m = *impl_;
  Features old = m.now;
  m.now = m.next;
  m.next = Features();
  m.release_set(old);
}

void Nr::drop_prepared() {
  if (!impl_ || !impl_->next.made) return;
  impl_->release_set(impl_->next);
  impl_->next = Features();
}

bool Nr::evaluate(ID3D12GraphicsCommandList* list, int pass, ID3D12Resource* input, ID3D12Resource* output,
                  bool reset, std::string& err) {
  if (!ready()) {
    err = "the network is not loaded";
    return false;
  }
  Impl& m = *impl_;
  if (!list || !input || !output || input == output || pass < 0 || pass >= m.passes) {
    err = "evaluate was given a bad pass or bad textures";
    return false;
  }
  eval_params(m.now.params[pass], input, output, m.motion.Get(), m.depth.Get(), m.now.w, m.now.h, reset,
              m.settings.pass[pass]);
  const ngx::Result r = call_evaluate(m.evaluate, list, m.now.feature[pass], m.now.params[pass]);
  if (!good(r)) {
    err = outcome("EvaluateFeature", r);
    return false;
  }
  return true;
}

void Nr::set_settings(const NrPasses& settings) {
  if (impl_) impl_->settings = settings;
}

UINT Nr::work_width() const { return impl_ ? impl_->now.w : 0; }

UINT Nr::work_height() const { return impl_ ? impl_->now.h : 0; }

int Nr::passes() const { return impl_ ? impl_->passes : 0; }

double Nr::create_ms() const { return impl_ ? impl_->create_ms : 0.0; }

double Nr::prepare_ms() const { return impl_ ? impl_->prepare_ms : 0.0; }

void Nr::shutdown() {
  if (!impl_) return;
  Impl& m = *impl_;
  m.ready = false;
  m.release_set(m.next);
  m.release_set(m.now);
  if (m.initialised && m.shutdown && m.gpu && m.gpu->device) {
    const ngx::Result r = call_shutdown(m.shutdown, m.gpu->device.Get());
    if (!good(r)) note("nr: %s", outcome("Shutdown1", r).c_str());
  }
  if (g_record_reads && !m.data_dir.empty()) {
    const std::wstring path = path_join(m.data_dir, L"nr-reads.txt");
    FILE* f = _wfopen(path.c_str(), L"w");
    if (f) {
      std::lock_guard<std::mutex> hold(g_reads_lock);
      for (const auto& [name, how] : g_reads) fprintf(f, "%s %s\n", name.c_str(), how.c_str());
      fclose(f);
    }
  }
  // The parameter objects are never deleted and the DLL is not freed, on purpose: the proxy
  // only parks a released feature and the runtime's unload code is not known to be safe,
  // so nothing the runtime may still point at is taken away. That holds for the features a
  // new work size replaced as well. Each switch leaves one parameter object for each pass
  // behind, about 9 KB. The process leaves through leave_now().
  if (m.fence_event) CloseHandle(m.fence_event);
  delete impl_;
  impl_ = nullptr;
}
