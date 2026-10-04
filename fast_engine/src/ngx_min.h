// ngx_min.h: the few declarations nr.cpp needs to call the Neural Rendering runtime.
// Only nr.cpp includes it.
//
// Nothing in this file is copied from NVIDIA's SDK, and the engine includes no SDK header.
// What is here is declared by hand and is only what calling the DLL takes: the names of five
// exported functions, the way they are called, a few numbers, and the shape of the one
// interface the runtime calls back into. Keep it that way: when the runtime needs something
// more, declare that one thing here in the engine's own words.
//
// The call order, the application id and the parameter names nr.cpp uses follow the openNR
// benchmark adapter (MIT, Copyright (c) 2026 Carlos Lopez Jr.). openNR's adapter comes from
// RenoDX (MIT, Copyright (c) 2025 Carlos Lopez Jr.). nr.cpp carries the notice where it
// adapts lines.
//
// cl /d1reportSingleClassLayoutParams shows the seventeen slots of Params in the order the
// runtime calls them. With LENS_FAST_NR_READS=1 nr.cpp lists every name the runtime read
// and the getter it used, which is the check on the real runtime.
#pragma once

#include <d3d12.h>

struct ID3D11Resource;  // only named in two slots of Params, never used by the engine

namespace ngx {

// A result is a 32 bit code. 1 is success, failures are 0xBAD00000 plus a small number.
typedef int Result;
constexpr Result kSuccess = 1;
// What nr.cpp reports when a call raised a structured exception instead of returning.
constexpr Result kRaised = (Result)0xBADFFFFF;

constexpr bool ok(Result r) { return ((unsigned)r & 0xFFF00000u) != 0xBAD00000u; }

// A failure in words, for err texts. The numbers are the runtime's, the words are ours.
inline const char* result_text(Result r) {
  switch ((unsigned)r) {
    case 0x00000001u: return "success";
    case 0xBAD00000u: return "failed";
    case 0xBAD00001u: return "feature not supported";
    case 0xBAD00002u: return "platform error";
    case 0xBAD00003u: return "feature already exists";
    case 0xBAD00004u: return "feature not found";
    case 0xBAD00005u: return "invalid parameter";
    case 0xBAD00006u: return "scratch buffer too small";
    case 0xBAD00007u: return "not initialised";
    case 0xBAD00008u: return "unsupported input format";
    case 0xBAD00009u: return "read and write flag missing";
    case 0xBAD0000Au: return "missing input";
    case 0xBAD0000Bu: return "unable to initialise the feature";
    case 0xBAD0000Cu: return "out of date";
    case 0xBAD0000Du: return "out of GPU memory";
    case 0xBAD0000Eu: return "unsupported format";
    case 0xBAD0000Fu: return "unable to write to the data path";
    case 0xBAD00010u: return "unsupported parameter";
    case 0xBAD00011u: return "denied";
    case 0xBAD00012u: return "not implemented";
    case 0xBADFFFFFu: return "the call raised an exception";
    default: return "unknown result";
  }
}

// The application id openNR and RenoDX pass, which the runtime accepts.
constexpr unsigned long long kAppId = 0x876232CULL;
// The interface version passed to the init call.
constexpr int kApiVersion = 0x15;
// Neural Rendering's feature number.
constexpr int kFeatureNeuralRendering = 18;

// A created feature. Only its address is ever used.
struct Handle;

// The parameter object. The runtime reads everything through it: the engine hands over its
// own implementation (no NGX core library is loaded at all) and the runtime calls Get on it
// by name. In the probe it asked for 55 names and used one getter for each: resources
// through void**, sizes as unsigned int, the subrects, switches and the preset as int,
// strengths and scales as float.
//
// The layout is the contract here, and it depends on the ORDER OF THESE DECLARATIONS: MSVC
// puts overloads of one name next to each other in the table in the reverse of the order
// they are declared in, so moving a line changes the slots, and so would building with
// another compiler. Seventeen virtual functions, no data members, no virtual destructor.
struct Params {
  virtual void Set(const char* name, unsigned long long value) = 0;
  virtual void Set(const char* name, float value) = 0;
  virtual void Set(const char* name, double value) = 0;
  virtual void Set(const char* name, unsigned int value) = 0;
  virtual void Set(const char* name, int value) = 0;
  virtual void Set(const char* name, ID3D11Resource* value) = 0;
  virtual void Set(const char* name, ID3D12Resource* value) = 0;
  virtual void Set(const char* name, void* value) = 0;
  virtual Result Get(const char* name, unsigned long long* value) const = 0;
  virtual Result Get(const char* name, float* value) const = 0;
  virtual Result Get(const char* name, double* value) const = 0;
  virtual Result Get(const char* name, unsigned int* value) const = 0;
  virtual Result Get(const char* name, int* value) const = 0;
  virtual Result Get(const char* name, ID3D11Resource** value) const = 0;
  virtual Result Get(const char* name, ID3D12Resource** value) const = 0;
  virtual Result Get(const char* name, void** value) const = 0;
  virtual void Reset() = 0;
};

// The exported functions, by the names GetProcAddress takes. On x64 there is one calling
// convention, so __cdecl only documents it.
constexpr const char* kInitName = "NVSDK_NGX_D3D12_Init_Ext";
constexpr const char* kCreateName = "NVSDK_NGX_D3D12_CreateFeature";
constexpr const char* kEvaluateName = "NVSDK_NGX_D3D12_EvaluateFeature";
constexpr const char* kReleaseName = "NVSDK_NGX_D3D12_ReleaseFeature";
constexpr const char* kShutdownName = "NVSDK_NGX_D3D12_Shutdown1";

// Init: application id, a writable folder for the runtime's logs, the device, kApiVersion,
// and a feature description that may be null.
typedef Result(__cdecl* InitFn)(unsigned long long app_id, const wchar_t* data_path,
                                ID3D12Device* device, int api_version, const void* feature_info);
// Create: recorded on a command list that the caller then runs and waits for. The probe's
// create took 257 ms on the CPU.
typedef Result(__cdecl* CreateFn)(ID3D12GraphicsCommandList* list, int feature,
                                  const Params* params, Handle** out);
// Evaluate: recorded on the caller's list. The last argument is a progress callback, null.
typedef Result(__cdecl* EvaluateFn)(ID3D12GraphicsCommandList* list, const Handle* handle,
                                    const Params* params, void* progress);
// Release: the Cost Scaler proxy's export returns nothing (it parks the feature and
// releases it later), so no result may be read from it.
typedef void(__cdecl* ReleaseFn)(Handle* handle);
// Shutdown: forwarded by the proxy to the runtime. The probe got success from it.
typedef Result(__cdecl* ShutdownFn)(ID3D12Device* device);

// The runtime looks up a callback under the name "DLSSNRComputeScalingRatioCallback" (set
// as void*) and calls it with the parameter object. The engine's sets
// "DLSSNR.ScalingRatio" to 1 and returns kSuccess: the network works at the size it is given.
typedef Result(__cdecl* ScalingRatioFn)(Params* params);

}  // namespace ngx
