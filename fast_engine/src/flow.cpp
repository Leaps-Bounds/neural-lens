// flow.cpp, the card's optical flow unit through Vulkan, see flow.h.
//
// Every Vulkan function is taken through vkGetInstanceProcAddr and vkGetDeviceProcAddr, so the
// headers are included with VK_NO_PROTOTYPES and nothing of Vulkan is linked.
#define VK_NO_PROTOTYPES
#define VK_USE_PLATFORM_WIN32_KHR

#include "flow.h"

#include <psapi.h>

#include <vulkan/vulkan.h>

#include <algorithm>
#include <cmath>
#include <cstring>
#include <cwctype>

#include "flowluma_cs.h"

using Microsoft::WRL::ComPtr;

namespace {

constexpr DWORD kWaitMs = 2000;   // the longest the CPU waits for the unit, as framegen.cpp's
constexpr UINT kMostSide = 4096;  // the motion estimator's largest side, as framegen.cpp's
// The loader that brought the layer filter, VK_LOADER_LAYERS_DISABLE. The loader reports the
// header version it was built with through vkEnumerateInstanceVersion
constexpr uint32_t kLoaderNeeded = VK_MAKE_API_VERSION(0, 1, 3, 234);
constexpr UINT kConstants = 11;   // flowluma_cs.hlsl's cbuffer, in 32-bit values
// the luma pass's descriptor heap: the frame (t0), the weights and the tie table (t1, t2), the
// luma buffer (u0)
constexpr UINT kSlotFrame = 0;
constexpr UINT kSlotWeights = 1;
constexpr UINT kSlotTies = 2;
constexpr UINT kSlotLuma = 3;
constexpr UINT kSlots = 4;

#define FLOW_GLOBAL_FUNCS(X) X(vkEnumerateInstanceVersion) X(vkCreateInstance)

#define FLOW_INSTANCE_FUNCS(X)                      \
  X(vkDestroyInstance)                              \
  X(vkEnumeratePhysicalDevices)                     \
  X(vkGetPhysicalDeviceProperties)                  \
  X(vkGetPhysicalDeviceProperties2)                 \
  X(vkGetPhysicalDeviceFeatures2)                   \
  X(vkEnumerateDeviceExtensionProperties)           \
  X(vkGetPhysicalDeviceQueueFamilyProperties)       \
  X(vkGetPhysicalDeviceMemoryProperties)            \
  X(vkGetPhysicalDeviceFormatProperties2)           \
  X(vkGetPhysicalDeviceImageFormatProperties2)      \
  X(vkGetPhysicalDeviceOpticalFlowImageFormatsNV)   \
  X(vkGetPhysicalDeviceExternalBufferProperties)    \
  X(vkGetPhysicalDeviceExternalSemaphoreProperties) \
  X(vkCreateDevice)                                 \
  X(vkGetDeviceProcAddr)

#define FLOW_DEVICE_FUNCS(X)              \
  X(vkDestroyDevice)                      \
  X(vkGetDeviceQueue)                     \
  X(vkDeviceWaitIdle)                     \
  X(vkCreateImage)                        \
  X(vkDestroyImage)                       \
  X(vkGetImageMemoryRequirements)         \
  X(vkBindImageMemory)                    \
  X(vkCreateImageView)                    \
  X(vkDestroyImageView)                   \
  X(vkCreateBuffer)                       \
  X(vkDestroyBuffer)                      \
  X(vkGetBufferMemoryRequirements)        \
  X(vkBindBufferMemory)                   \
  X(vkAllocateMemory)                     \
  X(vkFreeMemory)                         \
  X(vkCreateCommandPool)                  \
  X(vkDestroyCommandPool)                 \
  X(vkAllocateCommandBuffers)             \
  X(vkResetCommandBuffer)                 \
  X(vkBeginCommandBuffer)                 \
  X(vkEndCommandBuffer)                   \
  X(vkCmdPipelineBarrier2)                \
  X(vkCmdCopyBufferToImage)               \
  X(vkCmdCopyImageToBuffer)               \
  X(vkCmdWriteTimestamp2)                 \
  X(vkQueueSubmit2)                       \
  X(vkCreateFence)                        \
  X(vkDestroyFence)                       \
  X(vkWaitForFences)                      \
  X(vkResetFences)                        \
  X(vkCreateQueryPool)                    \
  X(vkDestroyQueryPool)                   \
  X(vkResetQueryPool)                     \
  X(vkGetQueryPoolResults)                \
  X(vkCreateSemaphore)                    \
  X(vkDestroySemaphore)                   \
  X(vkWaitSemaphores)                     \
  X(vkImportSemaphoreWin32HandleKHR)      \
  X(vkGetMemoryWin32HandlePropertiesKHR)  \
  X(vkCreateOpticalFlowSessionNV)         \
  X(vkDestroyOpticalFlowSessionNV)        \
  X(vkBindOpticalFlowSessionImageNV)      \
  X(vkCmdOpticalFlowExecuteNV)

struct VkFns {
  PFN_vkGetInstanceProcAddr vkGetInstanceProcAddr = nullptr;
#define FLOW_DECLARE(name) PFN_##name name = nullptr;
  FLOW_GLOBAL_FUNCS(FLOW_DECLARE)
  FLOW_INSTANCE_FUNCS(FLOW_DECLARE)
  FLOW_DEVICE_FUNCS(FLOW_DECLARE)
#undef FLOW_DECLARE
};

const char* vk_name(VkResult r) {
  switch (r) {
#define FLOW_NAME(x) \
  case x:            \
    return #x;
    FLOW_NAME(VK_SUCCESS)
    FLOW_NAME(VK_NOT_READY)
    FLOW_NAME(VK_TIMEOUT)
    FLOW_NAME(VK_INCOMPLETE)
    FLOW_NAME(VK_ERROR_OUT_OF_HOST_MEMORY)
    FLOW_NAME(VK_ERROR_OUT_OF_DEVICE_MEMORY)
    FLOW_NAME(VK_ERROR_INITIALIZATION_FAILED)
    FLOW_NAME(VK_ERROR_DEVICE_LOST)
    FLOW_NAME(VK_ERROR_MEMORY_MAP_FAILED)
    FLOW_NAME(VK_ERROR_LAYER_NOT_PRESENT)
    FLOW_NAME(VK_ERROR_EXTENSION_NOT_PRESENT)
    FLOW_NAME(VK_ERROR_FEATURE_NOT_PRESENT)
    FLOW_NAME(VK_ERROR_INCOMPATIBLE_DRIVER)
    FLOW_NAME(VK_ERROR_TOO_MANY_OBJECTS)
    FLOW_NAME(VK_ERROR_FORMAT_NOT_SUPPORTED)
    FLOW_NAME(VK_ERROR_FRAGMENTED_POOL)
    FLOW_NAME(VK_ERROR_UNKNOWN)
    FLOW_NAME(VK_ERROR_OUT_OF_POOL_MEMORY)
    FLOW_NAME(VK_ERROR_INVALID_EXTERNAL_HANDLE)
    FLOW_NAME(VK_ERROR_FRAGMENTATION)
    FLOW_NAME(VK_ERROR_NOT_PERMITTED)
#undef FLOW_NAME
    default:
      return "an unnamed VkResult";
  }
}

std::string vk_text(VkResult r) { return strf("%s (%d)", vk_name(r), (int)r); }

std::string version_text(uint32_t v) {
  return strf("%u.%u.%u", VK_API_VERSION_MAJOR(v), VK_API_VERSION_MINOR(v), VK_API_VERSION_PATCH(v));
}

std::string luid_text(const void* p) {
  LUID l;
  memcpy(&l, p, sizeof l);
  return strf("%08lx:%08lx", (unsigned long)l.HighPart, (unsigned long)l.LowPart);
}

std::string queue_text(VkQueueFlags f) {
  const struct {
    VkQueueFlags bit;
    const char* name;
  } names[] = {{VK_QUEUE_GRAPHICS_BIT, "GRAPHICS"},          {VK_QUEUE_COMPUTE_BIT, "COMPUTE"},
               {VK_QUEUE_TRANSFER_BIT, "TRANSFER"},          {VK_QUEUE_SPARSE_BINDING_BIT, "SPARSE_BINDING"},
               {VK_QUEUE_PROTECTED_BIT, "PROTECTED"},        {VK_QUEUE_VIDEO_DECODE_BIT_KHR, "VIDEO_DECODE"},
               {VK_QUEUE_VIDEO_ENCODE_BIT_KHR, "VIDEO_ENCODE"}, {VK_QUEUE_OPTICAL_FLOW_BIT_NV, "OPTICAL_FLOW"}};
  std::string s;
  VkQueueFlags known = 0;
  for (const auto& n : names) {
    known |= n.bit;
    if (f & n.bit) s += (s.empty() ? "" : " ") + std::string(n.name);
  }
  if (f & ~known) s += strf("%s0x%x", s.empty() ? "" : " ", (unsigned)(f & ~known));
  return s;
}

std::string memory_features_text(VkExternalMemoryFeatureFlags f) {
  std::string s;
  if (f & VK_EXTERNAL_MEMORY_FEATURE_DEDICATED_ONLY_BIT) s += " DEDICATED_ONLY";
  if (f & VK_EXTERNAL_MEMORY_FEATURE_EXPORTABLE_BIT) s += " EXPORTABLE";
  if (f & VK_EXTERNAL_MEMORY_FEATURE_IMPORTABLE_BIT) s += " IMPORTABLE";
  return s.empty() ? std::string("none") : s.substr(1);
}

// ---------------------------------------------------------------- the modules of this process

// The full paths of the modules this process holds, sorted. Only the engine's own process is
// listed, through GetCurrentProcess(), which needs no handle of another.
std::vector<std::wstring> module_paths() {
  std::vector<HMODULE> mods(512);
  DWORD need = 0;
  for (int attempt = 0; attempt < 5; ++attempt) {
    if (!K32EnumProcessModules(GetCurrentProcess(), mods.data(), (DWORD)(mods.size() * sizeof(HMODULE)), &need)) {
      need = 0;
      break;
    }
    if (need <= mods.size() * sizeof(HMODULE)) break;
    mods.resize(need / sizeof(HMODULE) + 32);
  }
  mods.resize(std::min(mods.size(), (size_t)(need / sizeof(HMODULE))));
  std::vector<std::wstring> paths;
  for (const HMODULE m : mods) {
    wchar_t name[1024] = {};
    const DWORD n = GetModuleFileNameW(m, name, 1024);
    paths.push_back(n ? std::wstring(name, n) : std::wstring(L"(a module with no name)"));
  }
  std::sort(paths.begin(), paths.end());
  return paths;
}

std::wstring lower(std::wstring s) {
  for (wchar_t& c : s) c = (wchar_t)towlower(c);
  return s;
}

// What after holds that before does not, by path in any case.
std::vector<std::wstring> modules_between(const std::vector<std::wstring>& before,
                                          const std::vector<std::wstring>& after) {
  std::vector<std::wstring> low, out;
  for (const auto& p : before) low.push_back(lower(p));
  for (const auto& p : after) {
    if (std::find(low.begin(), low.end(), lower(p)) == low.end()) out.push_back(p);
  }
  return out;
}

// The Windows folder with a backslash at its end, as C:\WINDOWS\.
std::wstring windows_folder() {
  wchar_t name[MAX_PATH] = {};
  const UINT n = GetWindowsDirectoryW(name, MAX_PATH);
  std::wstring folder = n && n < MAX_PATH ? std::wstring(name, n) : std::wstring(L"C:\\Windows");
  if (folder.back() != L'\\') folder += L'\\';
  return folder;
}

bool under(const std::wstring& path, const std::wstring& folder) {
  const std::wstring p = lower(path), f = lower(folder);
  return p.compare(0, f.size(), f) == 0;
}

// ---------------------------------------------------------------- the luma's numbers

// The luma of nv12_cs.hlsl on the encoded 8-bit values, BT.709 on 0 to 255, rounded. This is
// the research's optical flow probe's luma8, its body as it is, compiled with the engine's
// flags, which are the probe's.
uint8_t luma8(double r, double g, double b) {
  const double y = 0.2126 * r + 0.7152 * g + 0.0722 * b;
  return (uint8_t)std::min(255.0, std::max(0.0, std::floor(y + 0.5)));
}

// The tie table of flowluma_cs.hlsl, every colour whose exact luma lies on a half where luma8
// gives one less than the sum rounded up, as (R << 16) | (G << 8) | B, ascending. ties counts
// the colours on a half, other those where luma8 differs from the rounded sum in another way,
// which the shader would not mend.
std::vector<uint32_t> tie_table(uint32_t& ties, uint32_t& other) {
  std::vector<uint32_t> keys;
  ties = other = 0;
  for (uint32_t r = 0; r < 256; ++r) {
    for (uint32_t g = 0; g < 256; ++g) {
      for (uint32_t b = 0; b < 256; ++b) {
        const uint32_t s = 2126u * r + 7152u * g + 722u * b;
        if (s % 10000u != 5000u) continue;
        ++ties;
        const uint32_t up = (s + 5000u) / 10000u;
        const uint32_t probe = luma8(r, g, b);
        if (probe + 1u == up) {
          keys.push_back((r << 16) | (g << 8) | b);
        } else if (probe != up) {
          ++other;
        }
      }
    }
  }
  return keys;
}

// The weights of the area filter along one axis, appended to out, the same function as
// pipeline.cpp's area_weights for ingest_cs.hlsl. For each of the dst texels it appends taps
// weights, one for each source texel of its footprint in order, 0 for what a narrower footprint
// leaves unused, each the part of the source texel under the texel over the scale, in double and
// then rounded to float. taps is the widest footprint.
void area_weights(UINT src, UINT dst, UINT& taps, std::vector<float>& out) {
  taps = 1;
  for (UINT i = 0; i < dst; ++i) {
    const UINT first = (UINT)(((UINT64)i * src) / dst);
    const UINT end = (UINT)((((UINT64)i + 1) * src + dst - 1) / dst);
    if (end - first > taps) taps = end - first;
  }
  const size_t base = out.size();
  out.resize(base + (size_t)dst * taps, 0.0f);
  const double scale = (double)src / (double)dst;
  for (UINT i = 0; i < dst; ++i) {
    const UINT first = (UINT)(((UINT64)i * src) / dst);
    const UINT end = (UINT)((((UINT64)i + 1) * src + dst - 1) / dst);
    const double a = (double)i * scale, b = (double)(i + 1) * scale;
    for (UINT x = first; x < end; ++x) {
      const double lo = a > (double)x ? a : (double)x;
      const double hi = b < (double)x + 1.0 ? b : (double)x + 1.0;
      const double part = hi - lo;
      if (part > 0.0) out[base + (size_t)i * taps + (x - first)] = (float)(part / scale);
    }
  }
}

UINT pad8(UINT v) { return (v + 7u) & ~7u; }

// The motion estimator's picture for frames of w x h by FrameGen::init's rule, halved until both
// sides fit kMostSide and kept even.
void estimator_size(UINT w, UINT h, UINT& me_w, UINT& me_h) {
  me_w = w;
  me_h = h;
  while (me_w > kMostSide || me_h > kMostSide) {
    me_w = (me_w + 1) / 2;
    me_h = (me_h + 1) / 2;
  }
  me_w &= ~1u;
  me_h &= ~1u;
}

D3D12_RESOURCE_DESC buffer_desc(UINT64 bytes, D3D12_RESOURCE_FLAGS flags) {
  D3D12_RESOURCE_DESC d = {};
  d.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
  d.Width = bytes;
  d.Height = 1;
  d.DepthOrArraySize = 1;
  d.MipLevels = 1;
  d.Format = DXGI_FORMAT_UNKNOWN;
  d.SampleDesc.Count = 1;
  d.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
  d.Flags = flags;
  return d;
}

}  // namespace

// ---------------------------------------------------------------- the unit's parts

struct Flow::Impl {
  Gpu* gpu = nullptr;
  VkFns vk;
  HMODULE lib = nullptr;
  std::vector<std::wstring> mods_before;  // the modules before the loader was loaded
  VkInstance instance = VK_NULL_HANDLE;
  VkPhysicalDevice phys = VK_NULL_HANDLE;
  VkDevice device = VK_NULL_HANDLE;
  VkQueue queue = VK_NULL_HANDLE;
  uint32_t family = 0;
  uint32_t ts_bits = 64;
  double ts_period_ns = 1.0;
  VkPhysicalDeviceMemoryProperties mem = {};
  VkImageUsageFlags usage_input = 0, usage_flow = 0;
  VkCommandPool pool = VK_NULL_HANDLE;
  VkCommandBuffer cb[2] = {VK_NULL_HANDLE, VK_NULL_HANDLE};  // the frames', taking turns
  VkCommandBuffer once = VK_NULL_HANDLE;                     // the images' first barrier
  VkFence fence = VK_NULL_HANDLE;
  VkQueryPool queries = VK_NULL_HANDLE;  // two sets of four timestamps, taking turns
  VkOpticalFlowSessionNV session = VK_NULL_HANDLE;
  struct Image {
    VkImage image = VK_NULL_HANDLE;
    VkDeviceMemory memory = VK_NULL_HANDLE;
    VkImageView view = VK_NULL_HANDLE;
  };
  Image in[2], flow;

  // ---- the sharing
  ComPtr<ID3D12Resource> luma, flowbuf;  // D3D12 buffers on a shared heap
  ComPtr<ID3D12Fence> f1, f2;            // shared fences
  HANDLE f2_event = nullptr;
  VkBuffer vluma = VK_NULL_HANDLE, vflow = VK_NULL_HANDLE;
  VkDeviceMemory mluma = VK_NULL_HANDLE, mflow = VK_NULL_HANDLE;
  VkSemaphore s1 = VK_NULL_HANDLE, s2 = VK_NULL_HANDLE;
  uint64_t v = 0;  // the last value given to F1 and F2, one up a frame for the unit's life

  // ---- the luma pass on gpu.queue
  ComPtr<ID3D12RootSignature> root;
  ComPtr<ID3D12PipelineState> pso;
  ComPtr<ID3D12DescriptorHeap> heap;
  UINT heap_step = 0;
  ComPtr<ID3D12Resource> weights, ties;
  UINT taps_x = 1, taps_y = 1, tie_count = 0;
  ComPtr<ID3D12CommandAllocator> allocator;
  ComPtr<ID3D12GraphicsCommandList> list;
  UINT64 list_value = 0;  // gpu.queue's fence value after the last luma list
  GpuTimer timer;         // slots 0 and 1 round the luma pass
  bool luma_timed = false;  // the last luma list ran the pass with its marks

  // ---- for the tests, made at the first need
  ComPtr<ID3D12Resource> upload, rb_flow, rb_luma;
  ComPtr<ID3D12CommandAllocator> rb_allocator;
  ComPtr<ID3D12GraphicsCommandList> rb_list;

  uint32_t memory_type(uint32_t bits, VkMemoryPropertyFlags want) const {
    for (int pass = 0; pass < 2; ++pass) {
      for (uint32_t i = 0; i < mem.memoryTypeCount; ++i) {
        const VkMemoryPropertyFlags need = pass == 0 ? want : 0;
        if (((bits >> i) & 1u) && (mem.memoryTypes[i].propertyFlags & need) == need) return i;
      }
    }
    return UINT32_MAX;
  }

  bool make_image(Image& im, VkFormat format, UINT w, UINT h, VkImageUsageFlags usage,
                  VkOpticalFlowUsageFlagsNV of_usage, std::string& err) {
    VkOpticalFlowImageFormatInfoNV ofi{VK_STRUCTURE_TYPE_OPTICAL_FLOW_IMAGE_FORMAT_INFO_NV};
    ofi.usage = of_usage;
    VkImageCreateInfo ci{VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO};
    ci.pNext = &ofi;
    ci.imageType = VK_IMAGE_TYPE_2D;
    ci.format = format;
    ci.extent = {w, h, 1};
    ci.mipLevels = 1;
    ci.arrayLayers = 1;
    ci.samples = VK_SAMPLE_COUNT_1_BIT;
    ci.tiling = VK_IMAGE_TILING_OPTIMAL;
    ci.usage = usage;
    ci.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
    ci.initialLayout = VK_IMAGE_LAYOUT_UNDEFINED;
    VkResult r = vk.vkCreateImage(device, &ci, nullptr, &im.image);
    if (r != VK_SUCCESS) {
      err = strf("an image of %ux%u was refused, %s", w, h, vk_text(r).c_str());
      return false;
    }
    VkMemoryRequirements mr = {};
    vk.vkGetImageMemoryRequirements(device, im.image, &mr);
    VkMemoryAllocateInfo ai{VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO};
    ai.allocationSize = mr.size;
    ai.memoryTypeIndex = memory_type(mr.memoryTypeBits, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT);
    if (ai.memoryTypeIndex == UINT32_MAX) {
      err = "no memory type for an image";
      return false;
    }
    r = vk.vkAllocateMemory(device, &ai, nullptr, &im.memory);
    if (r == VK_SUCCESS) r = vk.vkBindImageMemory(device, im.image, im.memory, 0);
    if (r != VK_SUCCESS) {
      err = "an image's memory failed, " + vk_text(r);
      return false;
    }
    VkImageViewCreateInfo vi{VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO};
    vi.image = im.image;
    vi.viewType = VK_IMAGE_VIEW_TYPE_2D;
    vi.format = format;
    vi.components = {VK_COMPONENT_SWIZZLE_IDENTITY, VK_COMPONENT_SWIZZLE_IDENTITY, VK_COMPONENT_SWIZZLE_IDENTITY,
                     VK_COMPONENT_SWIZZLE_IDENTITY};
    vi.subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1};
    r = vk.vkCreateImageView(device, &vi, nullptr, &im.view);
    if (r != VK_SUCCESS) {
      err = "an image view failed, " + vk_text(r);
      return false;
    }
    return true;
  }

  void free_image(Image& im) {
    if (im.view) vk.vkDestroyImageView(device, im.view, nullptr);
    if (im.image) vk.vkDestroyImage(device, im.image, nullptr);
    if (im.memory) vk.vkFreeMemory(device, im.memory, nullptr);
    im = Image();
  }

  // A D3D12 buffer on a shared heap, imported into Vulkan as a dedicated allocation of a buffer
  // made for VK_EXTERNAL_MEMORY_HANDLE_TYPE_D3D12_RESOURCE_BIT. The NT handle is closed once
  // imported, since its import does not take it over.
  bool share_buffer(UINT64 bytes, D3D12_RESOURCE_FLAGS flags, VkBufferUsageFlags usage, const wchar_t* name,
                    ComPtr<ID3D12Resource>& out, VkBuffer& buffer, VkDeviceMemory& memory, std::string& note,
                    std::string& err) {
    const D3D12_HEAP_PROPERTIES hp = {D3D12_HEAP_TYPE_DEFAULT};
    const D3D12_RESOURCE_DESC rd = buffer_desc(bytes, flags);
    HRESULT hr = gpu->device->CreateCommittedResource(&hp, D3D12_HEAP_FLAG_SHARED, &rd, D3D12_RESOURCE_STATE_COMMON,
                                                      nullptr, IID_PPV_ARGS(&out));
    if (FAILED(hr)) {
      err = strf("a shared buffer of %llu bytes, %s", (unsigned long long)bytes, hr_text(hr).c_str());
      return false;
    }
    out->SetName(name);
    HANDLE handle = nullptr;
    hr = gpu->device->CreateSharedHandle(out.Get(), nullptr, GENERIC_ALL, nullptr, &handle);
    if (FAILED(hr)) {
      err = "the shared handle of a buffer, " + hr_text(hr);
      return false;
    }
    VkExternalMemoryBufferCreateInfo ebi{VK_STRUCTURE_TYPE_EXTERNAL_MEMORY_BUFFER_CREATE_INFO};
    ebi.handleTypes = VK_EXTERNAL_MEMORY_HANDLE_TYPE_D3D12_RESOURCE_BIT;
    VkBufferCreateInfo ci{VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO};
    ci.pNext = &ebi;
    ci.size = bytes;
    ci.usage = usage;
    ci.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
    VkResult r = vk.vkCreateBuffer(device, &ci, nullptr, &buffer);
    if (r != VK_SUCCESS) {
      CloseHandle(handle);
      err = "vkCreateBuffer for a shared buffer, " + vk_text(r);
      return false;
    }
    VkMemoryRequirements mr = {};
    vk.vkGetBufferMemoryRequirements(device, buffer, &mr);
    VkMemoryWin32HandlePropertiesKHR hpr{VK_STRUCTURE_TYPE_MEMORY_WIN32_HANDLE_PROPERTIES_KHR};
    r = vk.vkGetMemoryWin32HandlePropertiesKHR(device, VK_EXTERNAL_MEMORY_HANDLE_TYPE_D3D12_RESOURCE_BIT, handle, &hpr);
    uint32_t bits = mr.memoryTypeBits;
    if (r == VK_SUCCESS) bits &= hpr.memoryTypeBits;
    const uint32_t type = memory_type(bits, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT);
    if (type == UINT32_MAX) {
      CloseHandle(handle);
      err = strf("no memory type for a shared buffer in 0x%x", bits);
      return false;
    }
    note += strf("%s%llu bytes, memory type %u (handle types 0x%x, %s)", note.empty() ? "" : ", ",
                 (unsigned long long)bytes, type, hpr.memoryTypeBits, vk_name(r));
    VkMemoryDedicatedAllocateInfo dedicated{VK_STRUCTURE_TYPE_MEMORY_DEDICATED_ALLOCATE_INFO};
    dedicated.buffer = buffer;
    VkImportMemoryWin32HandleInfoKHR import{VK_STRUCTURE_TYPE_IMPORT_MEMORY_WIN32_HANDLE_INFO_KHR};
    import.pNext = &dedicated;
    import.handleType = VK_EXTERNAL_MEMORY_HANDLE_TYPE_D3D12_RESOURCE_BIT;
    import.handle = handle;
    VkMemoryAllocateInfo ai{VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO};
    ai.pNext = &import;
    ai.allocationSize = mr.size;
    ai.memoryTypeIndex = type;
    r = vk.vkAllocateMemory(device, &ai, nullptr, &memory);
    CloseHandle(handle);
    if (r == VK_SUCCESS) r = vk.vkBindBufferMemory(device, buffer, memory, 0);
    if (r != VK_SUCCESS) {
      err = "importing a shared buffer, " + vk_text(r);
      return false;
    }
    return true;
  }

  // A shared D3D12 fence imported as a timeline semaphore.
  bool share_fence(const wchar_t* name, ComPtr<ID3D12Fence>& out, VkSemaphore& semaphore, std::string& err) {
    HRESULT hr = gpu->device->CreateFence(0, D3D12_FENCE_FLAG_SHARED, IID_PPV_ARGS(&out));
    if (FAILED(hr)) {
      err = "a shared fence, " + hr_text(hr);
      return false;
    }
    out->SetName(name);
    HANDLE handle = nullptr;
    hr = gpu->device->CreateSharedHandle(out.Get(), nullptr, GENERIC_ALL, nullptr, &handle);
    if (FAILED(hr)) {
      err = "the shared handle of a fence, " + hr_text(hr);
      return false;
    }
    VkSemaphoreTypeCreateInfo tci{VK_STRUCTURE_TYPE_SEMAPHORE_TYPE_CREATE_INFO};
    tci.semaphoreType = VK_SEMAPHORE_TYPE_TIMELINE;
    tci.initialValue = 0;
    VkSemaphoreCreateInfo sci{VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO};
    sci.pNext = &tci;
    VkResult r = vk.vkCreateSemaphore(device, &sci, nullptr, &semaphore);
    if (r == VK_SUCCESS) {
      VkImportSemaphoreWin32HandleInfoKHR isi{VK_STRUCTURE_TYPE_IMPORT_SEMAPHORE_WIN32_HANDLE_INFO_KHR};
      isi.semaphore = semaphore;
      isi.handleType = VK_EXTERNAL_SEMAPHORE_HANDLE_TYPE_D3D12_FENCE_BIT;
      isi.handle = handle;
      r = vk.vkImportSemaphoreWin32HandleKHR(device, &isi);
    }
    CloseHandle(handle);
    if (r != VK_SUCCESS) {
      err = "importing a shared fence, " + vk_text(r);
      return false;
    }
    return true;
  }

  // F2 has reached value, waited for up to kWaitMs.
  bool wait_f2(uint64_t value, std::string& err) {
    if (value == 0 || f2->GetCompletedValue() >= value) return true;
    if (FAILED(f2->SetEventOnCompletion(value, f2_event)) || WaitForSingleObject(f2_event, kWaitMs) != WAIT_OBJECT_0) {
      err = strf("frame %llu did not finish in %lu ms", (unsigned long long)value, (unsigned long)kWaitMs);
      return false;
    }
    return true;
  }

  static VkImageMemoryBarrier2 image_barrier(VkImage image, VkPipelineStageFlags2 src_stage, VkAccessFlags2 src_access,
                                             VkPipelineStageFlags2 dst_stage, VkAccessFlags2 dst_access,
                                             VkImageLayout from = VK_IMAGE_LAYOUT_GENERAL,
                                             VkImageLayout to = VK_IMAGE_LAYOUT_GENERAL) {
    VkImageMemoryBarrier2 b{VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER_2};
    b.srcStageMask = src_stage;
    b.srcAccessMask = src_access;
    b.dstStageMask = dst_stage;
    b.dstAccessMask = dst_access;
    b.oldLayout = from;
    b.newLayout = to;
    b.srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    b.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    b.image = image;
    b.subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1};
    return b;
  }

  // A buffer moving between the unit's queue family and VK_QUEUE_FAMILY_EXTERNAL.
  static VkBufferMemoryBarrier2 buffer_barrier(VkBuffer buffer, VkPipelineStageFlags2 src_stage,
                                               VkAccessFlags2 src_access, VkPipelineStageFlags2 dst_stage,
                                               VkAccessFlags2 dst_access, uint32_t from, uint32_t to) {
    VkBufferMemoryBarrier2 b{VK_STRUCTURE_TYPE_BUFFER_MEMORY_BARRIER_2};
    b.srcStageMask = src_stage;
    b.srcAccessMask = src_access;
    b.dstStageMask = dst_stage;
    b.dstAccessMask = dst_access;
    b.srcQueueFamilyIndex = from;
    b.dstQueueFamilyIndex = to;
    b.buffer = buffer;
    b.offset = 0;
    b.size = VK_WHOLE_SIZE;
    return b;
  }

  void barrier(VkCommandBuffer c, const VkImageMemoryBarrier2* images, uint32_t image_count,
               const VkBufferMemoryBarrier2* buffers, uint32_t buffer_count) {
    if (!image_count && !buffer_count) return;
    VkDependencyInfo di{VK_STRUCTURE_TYPE_DEPENDENCY_INFO};
    di.imageMemoryBarrierCount = image_count;
    di.pImageMemoryBarriers = images;
    di.bufferMemoryBarrierCount = buffer_count;
    di.pBufferMemoryBarriers = buffers;
    vk.vkCmdPipelineBarrier2(c, &di);
  }

  VkOpticalFlowSessionCreateInfoNV session_info(UINT w, UINT h) const {
    VkOpticalFlowSessionCreateInfoNV si{VK_STRUCTURE_TYPE_OPTICAL_FLOW_SESSION_CREATE_INFO_NV};
    si.width = w;
    si.height = h;
    si.imageFormat = VK_FORMAT_R8_UNORM;
    si.flowVectorFormat = VK_FORMAT_R16G16_SFIXED5_NV;
    si.costFormat = VK_FORMAT_UNDEFINED;
    si.outputGridSize = VK_OPTICAL_FLOW_GRID_SIZE_4X4_BIT_NV;
    si.hintGridSize = 0;
    si.performanceLevel = VK_OPTICAL_FLOW_PERFORMANCE_LEVEL_MEDIUM_NV;
    si.flags = 0;  // forward only, no cost map, no hints
    return si;
  }

  // The unit's half of frame v, recorded and submitted with no CPU wait. It waits for F1 >= v,
  // copies the luma buffer into input slot, and where execute compares input slot with input
  // 1 - slot, the frame before, and copies the flow into the flow buffer. It signals F2 = v.
  // Timestamps 0 to 3 of set v % 2 bound the copy in, the run and the copy out.
  bool frame(uint64_t value, int slot, bool execute, UINT pw, UINT ph, UINT cw, UINT ch, std::string& err) {
    const uint32_t set = (uint32_t)(value % 2);
    VkResult r = VK_SUCCESS;
    if (execute) {
      // a host call, once frame v - 1 is done, see submit()
      r = vk.vkBindOpticalFlowSessionImageNV(device, session, VK_OPTICAL_FLOW_SESSION_BINDING_POINT_INPUT_NV,
                                             in[slot].view, VK_IMAGE_LAYOUT_GENERAL);
      if (r == VK_SUCCESS)
        r = vk.vkBindOpticalFlowSessionImageNV(device, session, VK_OPTICAL_FLOW_SESSION_BINDING_POINT_REFERENCE_NV,
                                               in[1 - slot].view, VK_IMAGE_LAYOUT_GENERAL);
      if (r == VK_SUCCESS)
        r = vk.vkBindOpticalFlowSessionImageNV(device, session, VK_OPTICAL_FLOW_SESSION_BINDING_POINT_FLOW_VECTOR_NV,
                                               flow.view, VK_IMAGE_LAYOUT_GENERAL);
      if (r != VK_SUCCESS) {
        err = "vkBindOpticalFlowSessionImageNV returned " + vk_text(r);
        return false;
      }
    }
    vk.vkResetQueryPool(device, queries, set * 4, 4);
    const VkCommandBuffer c = cb[set];
    r = vk.vkResetCommandBuffer(c, 0);
    VkCommandBufferBeginInfo bi{VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};
    bi.flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT;
    if (r == VK_SUCCESS) r = vk.vkBeginCommandBuffer(c, &bi);
    if (r != VK_SUCCESS) {
      err = "beginning the unit's commands, " + vk_text(r);
      return false;
    }
    const uint32_t q = set * 4;
    vk.vkCmdWriteTimestamp2(c, VK_PIPELINE_STAGE_2_ALL_COMMANDS_BIT, queries, q + 0);
    {
      // the input slot from the unit's last read of it to the copy, and the luma buffer taken
      // from the D3D12 side
      const VkImageMemoryBarrier2 ib =
          image_barrier(in[slot].image, VK_PIPELINE_STAGE_2_OPTICAL_FLOW_BIT_NV, VK_ACCESS_2_OPTICAL_FLOW_READ_BIT_NV,
                        VK_PIPELINE_STAGE_2_COPY_BIT, VK_ACCESS_2_TRANSFER_WRITE_BIT);
      const VkBufferMemoryBarrier2 bb =
          buffer_barrier(vluma, VK_PIPELINE_STAGE_2_NONE, 0, VK_PIPELINE_STAGE_2_COPY_BIT,
                         VK_ACCESS_2_TRANSFER_READ_BIT, VK_QUEUE_FAMILY_EXTERNAL, family);
      barrier(c, &ib, 1, &bb, 1);
    }
    VkBufferImageCopy copy_in = {};
    copy_in.bufferOffset = 0;
    copy_in.imageSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1};
    copy_in.imageExtent = {pw, ph, 1};
    vk.vkCmdCopyBufferToImage(c, vluma, in[slot].image, VK_IMAGE_LAYOUT_GENERAL, 1, &copy_in);
    {
      const VkImageMemoryBarrier2 ib =
          image_barrier(in[slot].image, VK_PIPELINE_STAGE_2_COPY_BIT, VK_ACCESS_2_TRANSFER_WRITE_BIT,
                        VK_PIPELINE_STAGE_2_OPTICAL_FLOW_BIT_NV, VK_ACCESS_2_OPTICAL_FLOW_READ_BIT_NV);
      barrier(c, &ib, 1, nullptr, 0);
    }
    vk.vkCmdWriteTimestamp2(c, VK_PIPELINE_STAGE_2_ALL_COMMANDS_BIT, queries, q + 1);
    if (execute) {
      const VkImageMemoryBarrier2 ib =
          image_barrier(flow.image, VK_PIPELINE_STAGE_2_COPY_BIT, VK_ACCESS_2_TRANSFER_READ_BIT,
                        VK_PIPELINE_STAGE_2_OPTICAL_FLOW_BIT_NV,
                        VK_ACCESS_2_OPTICAL_FLOW_READ_BIT_NV | VK_ACCESS_2_OPTICAL_FLOW_WRITE_BIT_NV);
      barrier(c, &ib, 1, nullptr, 0);
      VkOpticalFlowExecuteInfoNV ei{VK_STRUCTURE_TYPE_OPTICAL_FLOW_EXECUTE_INFO_NV};
      ei.flags = VK_OPTICAL_FLOW_EXECUTE_DISABLE_TEMPORAL_HINTS_BIT_NV;
      ei.regionCount = 0;
      ei.pRegions = nullptr;
      vk.vkCmdOpticalFlowExecuteNV(c, session, &ei);
    }
    vk.vkCmdWriteTimestamp2(c, VK_PIPELINE_STAGE_2_ALL_COMMANDS_BIT, queries, q + 2);
    VkBufferMemoryBarrier2 release[2];
    uint32_t releases = 0;
    if (execute) {
      const VkImageMemoryBarrier2 ib =
          image_barrier(flow.image, VK_PIPELINE_STAGE_2_OPTICAL_FLOW_BIT_NV, VK_ACCESS_2_OPTICAL_FLOW_WRITE_BIT_NV,
                        VK_PIPELINE_STAGE_2_COPY_BIT, VK_ACCESS_2_TRANSFER_READ_BIT);
      const VkBufferMemoryBarrier2 bb =
          buffer_barrier(vflow, VK_PIPELINE_STAGE_2_NONE, 0, VK_PIPELINE_STAGE_2_COPY_BIT,
                         VK_ACCESS_2_TRANSFER_WRITE_BIT, VK_QUEUE_FAMILY_EXTERNAL, family);
      barrier(c, &ib, 1, &bb, 1);
      VkBufferImageCopy copy_out = {};
      copy_out.bufferOffset = 0;
      copy_out.imageSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1};
      copy_out.imageExtent = {cw, ch, 1};
      vk.vkCmdCopyImageToBuffer(c, flow.image, VK_IMAGE_LAYOUT_GENERAL, vflow, 1, &copy_out);
      release[releases++] = buffer_barrier(vflow, VK_PIPELINE_STAGE_2_COPY_BIT, VK_ACCESS_2_TRANSFER_WRITE_BIT,
                                           VK_PIPELINE_STAGE_2_NONE, 0, family, VK_QUEUE_FAMILY_EXTERNAL);
    }
    release[releases++] = buffer_barrier(vluma, VK_PIPELINE_STAGE_2_COPY_BIT, 0, VK_PIPELINE_STAGE_2_NONE, 0, family,
                                         VK_QUEUE_FAMILY_EXTERNAL);
    barrier(c, nullptr, 0, release, releases);
    vk.vkCmdWriteTimestamp2(c, VK_PIPELINE_STAGE_2_ALL_COMMANDS_BIT, queries, q + 3);
    r = vk.vkEndCommandBuffer(c);
    if (r != VK_SUCCESS) {
      err = "ending the unit's commands, " + vk_text(r);
      return false;
    }
    VkSemaphoreSubmitInfo wait{VK_STRUCTURE_TYPE_SEMAPHORE_SUBMIT_INFO};
    wait.semaphore = s1;
    wait.value = value;
    wait.stageMask = VK_PIPELINE_STAGE_2_ALL_COMMANDS_BIT;  // so timestamp 0 follows the wait
    VkSemaphoreSubmitInfo signal{VK_STRUCTURE_TYPE_SEMAPHORE_SUBMIT_INFO};
    signal.semaphore = s2;
    signal.value = value;
    signal.stageMask = VK_PIPELINE_STAGE_2_ALL_COMMANDS_BIT;
    VkCommandBufferSubmitInfo cbi{VK_STRUCTURE_TYPE_COMMAND_BUFFER_SUBMIT_INFO};
    cbi.commandBuffer = c;
    VkSubmitInfo2 si{VK_STRUCTURE_TYPE_SUBMIT_INFO_2};
    si.waitSemaphoreInfoCount = 1;
    si.pWaitSemaphoreInfos = &wait;
    si.commandBufferInfoCount = 1;
    si.pCommandBufferInfos = &cbi;
    si.signalSemaphoreInfoCount = 1;
    si.pSignalSemaphoreInfos = &signal;
    r = vk.vkQueueSubmit2(queue, 1, &si, VK_NULL_HANDLE);
    if (r != VK_SUCCESS) {
      err = "vkQueueSubmit2 returned " + vk_text(r);
      return false;
    }
    return true;
  }
};

Flow::Flow() = default;

Flow::~Flow() { shutdown(); }

bool Flow::init(Gpu& g, UINT fw, UINT fh, UINT mw, UINT mh, std::string& err) {
  shutdown();
  report_.clear();
  frames_ = 0;
  executed_ = false;
  stopped_ = false;
  frame_w = fw;
  frame_h = fh;
  me_w = mw;
  me_h = mh;
  pad_w = pad8(mw);
  pad_h = pad8(mh);
  cells_w = pad_w / 4;
  cells_h = pad_h / 4;
  crop_w = (mw + 3) / 4;
  crop_h = (mh + 3) / 4;
  if (mw < 32 || mh < 32 || mw > fw || mh > fh) {
    err = strf("the optical flow unit takes no luma of %ux%u from frames of %ux%u", mw, mh, fw, fh);
    return false;
  }
  impl_ = std::make_unique<Impl>();
  Impl& m = *impl_;
  m.gpu = &g;
  VkFns& vk = m.vk;
  std::vector<std::string>& rep = report_;
  // Whatever goes wrong from here gives back what was made, the loader included, and keeps the
  // report.
  const auto refuse = [&](const std::string& why) {
    err = why;
    const std::vector<std::string> kept = report_;
    shutdown();
    report_ = kept;
    return false;
  };

  // ---- the layer filter, in this process, before the loader is loaded
  {
    const wchar_t* names[4] = {L"VK_LOADER_LAYERS_DISABLE", L"VK_LOADER_LAYERS_ENABLE", L"VK_LOADER_LAYERS_ALLOW",
                               L"VK_INSTANCE_LAYERS"};
    std::string was;
    for (const wchar_t* n : names) {
      const std::wstring value = env_text(n);
      was += strf("%s%s %s", was.empty() ? "" : ", ", narrow(n).c_str(),
                  value.empty() ? "unset" : ("'" + narrow(value) + "'").c_str());
    }
    SetEnvironmentVariableW(L"VK_LOADER_LAYERS_DISABLE", L"~all~");
    SetEnvironmentVariableW(L"VK_LOADER_LAYERS_ENABLE", nullptr);
    SetEnvironmentVariableW(L"VK_LOADER_LAYERS_ALLOW", nullptr);
    SetEnvironmentVariableW(L"VK_INSTANCE_LAYERS", nullptr);
    rep.push_back("the layer filter set in this process, VK_LOADER_LAYERS_DISABLE ~all~ and VK_LOADER_LAYERS_ENABLE, "
                  "VK_LOADER_LAYERS_ALLOW and VK_INSTANCE_LAYERS cleared, where before " + was);
  }
  m.mods_before = module_paths();
  rep.push_back(strf("modules before the loader %zu", m.mods_before.size()));

  // ---- the loader, from the system folder by its full path
  wchar_t system[MAX_PATH] = {};
  const UINT n = GetSystemDirectoryW(system, MAX_PATH);
  if (n == 0 || n >= MAX_PATH) return refuse("no Vulkan loader (vulkan-1.dll), the system folder is not known");
  const std::wstring loader = std::wstring(system) + L"\\vulkan-1.dll";
  m.lib = LoadLibraryW(loader.c_str());
  if (!m.lib) return refuse("no Vulkan loader (vulkan-1.dll)");
  vk.vkGetInstanceProcAddr = reinterpret_cast<PFN_vkGetInstanceProcAddr>(
      reinterpret_cast<void*>(GetProcAddress(m.lib, "vkGetInstanceProcAddr")));
  if (!vk.vkGetInstanceProcAddr) return refuse("no Vulkan loader (vulkan-1.dll has no vkGetInstanceProcAddr)");
#define FLOW_LOAD_GLOBAL(name) vk.name = reinterpret_cast<PFN_##name>(vk.vkGetInstanceProcAddr(VK_NULL_HANDLE, #name));
  FLOW_GLOBAL_FUNCS(FLOW_LOAD_GLOBAL)
#undef FLOW_LOAD_GLOBAL
  uint32_t version = VK_API_VERSION_1_0;
  if (vk.vkEnumerateInstanceVersion) vk.vkEnumerateInstanceVersion(&version);
  rep.push_back(strf("the loader %s, version %s, headers %d", narrow(loader).c_str(), version_text(version).c_str(),
                     VK_HEADER_VERSION));
  if (!vk.vkCreateInstance) return refuse("no Vulkan loader (vulkan-1.dll gives no vkCreateInstance)");
  if (version < kLoaderNeeded) return refuse("the Vulkan loader is older than 1.3.234");

  // ---- the instance at 1.3, no layer and no extension
  VkApplicationInfo app{VK_STRUCTURE_TYPE_APPLICATION_INFO};
  app.pApplicationName = "lens-fast";
  app.applicationVersion = 1;
  app.pEngineName = "lens-fast";
  app.engineVersion = 1;
  app.apiVersion = VK_API_VERSION_1_3;
  VkInstanceCreateInfo ici{VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO};
  ici.pApplicationInfo = &app;
  VkResult r = vk.vkCreateInstance(&ici, nullptr, &m.instance);
  if (r != VK_SUCCESS) return refuse("the Vulkan instance was refused (" + std::string(vk_name(r)) + ")");
#define FLOW_LOAD_INSTANCE(name)                                                          \
  vk.name = reinterpret_cast<PFN_##name>(vk.vkGetInstanceProcAddr(m.instance, #name)); \
  if (!vk.name) return refuse("the Vulkan loader gives no " #name);
  FLOW_INSTANCE_FUNCS(FLOW_LOAD_INSTANCE)
#undef FLOW_LOAD_INSTANCE

  // ---- the device on the D3D12 adapter's LUID
  uint32_t count = 0;
  r = vk.vkEnumeratePhysicalDevices(m.instance, &count, nullptr);
  std::vector<VkPhysicalDevice> devices(count);
  if (r == VK_SUCCESS && count) r = vk.vkEnumeratePhysicalDevices(m.instance, &count, devices.data());
  if (r != VK_SUCCESS && r != VK_INCOMPLETE)
    return refuse("no Vulkan device on the engine's adapter (" + vk_text(r) + ")");
  devices.resize(count);
  bool has_flow = false, has_memory = false, has_semaphore = false;
  uint32_t flow_revision = 0;
  for (uint32_t i = 0; i < count; ++i) {
    VkPhysicalDeviceIDProperties idp{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_ID_PROPERTIES};
    VkPhysicalDeviceProperties2 p2{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2};
    p2.pNext = &idp;
    vk.vkGetPhysicalDeviceProperties2(devices[i], &p2);
    const bool same = idp.deviceLUIDValid && memcmp(idp.deviceLUID, &g.luid, VK_LUID_SIZE) == 0;
    if (same && !m.phys) m.phys = devices[i];
    rep.push_back(strf("device %u %s, vendor 0x%04x, Vulkan %s, LUID %s%s", i, p2.properties.deviceName,
                       p2.properties.vendorID, version_text(p2.properties.apiVersion).c_str(),
                       idp.deviceLUIDValid ? luid_text(idp.deviceLUID).c_str() : "none",
                       m.phys == devices[i] ? ", the engine's adapter" : ""));
  }
  if (!m.phys) return refuse("no Vulkan device on the engine's adapter (LUID " + luid_text(&g.luid) + ")");
  VkPhysicalDeviceProperties props = {};
  vk.vkGetPhysicalDeviceProperties(m.phys, &props);
  if (props.vendorID != 0x10DE)
    return refuse(strf("the engine's adapter is not NVIDIA's (vendor 0x%04x)", props.vendorID));
  if (props.apiVersion < VK_API_VERSION_1_3)
    return refuse("this card's driver offers Vulkan " + version_text(props.apiVersion) + ", older than 1.3");
  {
    uint32_t ne = 0;
    r = vk.vkEnumerateDeviceExtensionProperties(m.phys, nullptr, &ne, nullptr);
    std::vector<VkExtensionProperties> ext(ne);
    if (r == VK_SUCCESS && ne) r = vk.vkEnumerateDeviceExtensionProperties(m.phys, nullptr, &ne, ext.data());
    ext.resize(ne);
    for (const auto& e : ext) {
      if (strcmp(e.extensionName, VK_NV_OPTICAL_FLOW_EXTENSION_NAME) == 0) {
        has_flow = true;
        flow_revision = e.specVersion;
      }
      if (strcmp(e.extensionName, VK_KHR_EXTERNAL_MEMORY_WIN32_EXTENSION_NAME) == 0) has_memory = true;
      if (strcmp(e.extensionName, VK_KHR_EXTERNAL_SEMAPHORE_WIN32_EXTENSION_NAME) == 0) has_semaphore = true;
    }
  }
  if (!has_flow) return refuse("this card's driver has no VK_NV_optical_flow");
  if (!has_memory) return refuse("this card's driver has no VK_KHR_external_memory_win32");
  if (!has_semaphore) return refuse("this card's driver has no VK_KHR_external_semaphore_win32");
  rep.push_back(strf("the device %s, Vulkan %s, VK_NV_optical_flow revision %u", props.deviceName,
                     version_text(props.apiVersion).c_str(), flow_revision));

  // ---- the queue, of the first family with the optical flow unit that also copies and times
  {
    uint32_t nf = 0;
    vk.vkGetPhysicalDeviceQueueFamilyProperties(m.phys, &nf, nullptr);
    std::vector<VkQueueFamilyProperties> families(nf);
    vk.vkGetPhysicalDeviceQueueFamilyProperties(m.phys, &nf, families.data());
    int chosen = -1;
    for (uint32_t i = 0; i < nf; ++i) {
      const VkQueueFamilyProperties& f = families[i];
      if (chosen < 0 && (f.queueFlags & VK_QUEUE_OPTICAL_FLOW_BIT_NV) && (f.queueFlags & VK_QUEUE_TRANSFER_BIT) &&
          f.timestampValidBits > 0) {
        chosen = (int)i;
      }
    }
    if (chosen < 0) return refuse("this card's driver has no queue for the optical flow unit");
    m.family = (uint32_t)chosen;
    m.ts_bits = families[(size_t)chosen].timestampValidBits;
    rep.push_back(strf("the queue family %u, %s, %u queue%s, timestamp bits %u", m.family,
                       queue_text(families[(size_t)chosen].queueFlags).c_str(), families[(size_t)chosen].queueCount,
                       families[(size_t)chosen].queueCount == 1 ? "" : "s", m.ts_bits));
  }
  m.ts_period_ns = props.limits.timestampPeriod;

  // ---- the features
  {
    VkPhysicalDeviceOpticalFlowFeaturesNV off{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_OPTICAL_FLOW_FEATURES_NV};
    VkPhysicalDeviceVulkan13Features f13{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_3_FEATURES};
    f13.pNext = &off;
    VkPhysicalDeviceVulkan12Features f12{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_2_FEATURES};
    f12.pNext = &f13;
    VkPhysicalDeviceFeatures2 f2{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FEATURES_2};
    f2.pNext = &f12;
    vk.vkGetPhysicalDeviceFeatures2(m.phys, &f2);
    if (!off.opticalFlow) return refuse("this card's driver lacks the feature opticalFlow");
    if (!f13.synchronization2) return refuse("this card's driver lacks the feature synchronization2");
    if (!f12.timelineSemaphore) return refuse("this card's driver lacks the feature timelineSemaphore");
    if (!f12.hostQueryReset) return refuse("this card's driver lacks the feature hostQueryReset");
  }

  // ---- the unit's own properties, formats and uses
  {
    VkPhysicalDeviceOpticalFlowPropertiesNV of{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_OPTICAL_FLOW_PROPERTIES_NV};
    VkPhysicalDeviceProperties2 p2{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2};
    p2.pNext = &of;
    vk.vkGetPhysicalDeviceProperties2(m.phys, &p2);
    rep.push_back(strf("the unit's grids 0x%x, sizes %ux%u to %ux%u, cost %u, both directions %u",
                       of.supportedOutputGridSizes, of.minWidth, of.minHeight, of.maxWidth, of.maxHeight,
                       of.costSupported, of.bidirectionalFlowSupported));
    if (!(of.supportedOutputGridSizes & VK_OPTICAL_FLOW_GRID_SIZE_4X4_BIT_NV))
      return refuse("the optical flow unit has no 4x4 grid");
    if (pad_w < of.minWidth || pad_h < of.minHeight || pad_w > of.maxWidth || pad_h > of.maxHeight)
      return refuse(strf("the optical flow unit takes no picture of %ux%u, only %ux%u to %ux%u", pad_w, pad_h,
                         of.minWidth, of.minHeight, of.maxWidth, of.maxHeight));
  }
  const auto offers = [&](VkOpticalFlowUsageFlagsNV usage, VkFormat want, VkResult& res) -> bool {
    VkOpticalFlowImageFormatInfoNV info{VK_STRUCTURE_TYPE_OPTICAL_FLOW_IMAGE_FORMAT_INFO_NV};
    info.usage = usage;
    uint32_t nfmt = 0;
    res = vk.vkGetPhysicalDeviceOpticalFlowImageFormatsNV(m.phys, &info, &nfmt, nullptr);
    if (res != VK_SUCCESS) return false;
    VkOpticalFlowImageFormatPropertiesNV blank{VK_STRUCTURE_TYPE_OPTICAL_FLOW_IMAGE_FORMAT_PROPERTIES_NV};
    std::vector<VkOpticalFlowImageFormatPropertiesNV> formats(nfmt, blank);
    res = vk.vkGetPhysicalDeviceOpticalFlowImageFormatsNV(m.phys, &info, &nfmt, formats.data());
    if (res != VK_SUCCESS && res != VK_INCOMPLETE) return false;
    for (uint32_t i = 0; i < nfmt && i < formats.size(); ++i) {
      if (formats[i].format == want) return true;
    }
    return false;
  };
  VkResult fr = VK_SUCCESS;
  if (!offers(VK_OPTICAL_FLOW_USAGE_INPUT_BIT_NV, VK_FORMAT_R8_UNORM, fr))
    return refuse("the optical flow unit takes no R8_UNORM pictures (" + std::string(vk_name(fr)) + ")");
  if (!offers(VK_OPTICAL_FLOW_USAGE_OUTPUT_BIT_NV, VK_FORMAT_R16G16_SFIXED5_NV, fr))
    return refuse("the optical flow unit gives no R16G16_SFIXED5_NV flow (" + std::string(vk_name(fr)) + ")");
  const auto features = [&](VkFormat f) -> VkFormatFeatureFlags2 {
    VkFormatProperties3 p3{VK_STRUCTURE_TYPE_FORMAT_PROPERTIES_3};
    VkFormatProperties2 p2{VK_STRUCTURE_TYPE_FORMAT_PROPERTIES_2};
    p2.pNext = &p3;
    vk.vkGetPhysicalDeviceFormatProperties2(m.phys, f, &p2);
    return p3.optimalTilingFeatures;
  };
  if (!(features(VK_FORMAT_R8_UNORM) & VK_FORMAT_FEATURE_2_OPTICAL_FLOW_IMAGE_BIT_NV))
    return refuse("the optical flow unit cannot read R8_UNORM images");
  if (!(features(VK_FORMAT_R16G16_SFIXED5_NV) & VK_FORMAT_FEATURE_2_OPTICAL_FLOW_VECTOR_BIT_NV))
    return refuse("the optical flow unit cannot write R16G16_SFIXED5_NV images");
  const auto accepts = [&](VkFormat f, VkImageUsageFlags usage, VkOpticalFlowUsageFlagsNV of_usage) -> bool {
    VkOpticalFlowImageFormatInfoNV ofi{VK_STRUCTURE_TYPE_OPTICAL_FLOW_IMAGE_FORMAT_INFO_NV};
    ofi.usage = of_usage;
    VkPhysicalDeviceImageFormatInfo2 info{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_IMAGE_FORMAT_INFO_2};
    info.pNext = &ofi;
    info.format = f;
    info.type = VK_IMAGE_TYPE_2D;
    info.tiling = VK_IMAGE_TILING_OPTIMAL;
    info.usage = usage;
    VkImageFormatProperties2 out{VK_STRUCTURE_TYPE_IMAGE_FORMAT_PROPERTIES_2};
    return vk.vkGetPhysicalDeviceImageFormatProperties2(m.phys, &info, &out) == VK_SUCCESS;
  };
  m.usage_input = VK_IMAGE_USAGE_TRANSFER_DST_BIT | VK_IMAGE_USAGE_SAMPLED_BIT;
  m.usage_flow = VK_IMAGE_USAGE_TRANSFER_SRC_BIT | VK_IMAGE_USAGE_STORAGE_BIT;
  if (!accepts(VK_FORMAT_R8_UNORM, m.usage_input, VK_OPTICAL_FLOW_USAGE_INPUT_BIT_NV))
    return refuse("the optical flow unit's input images cannot be copied into");
  if (!accepts(VK_FORMAT_R16G16_SFIXED5_NV, m.usage_flow, VK_OPTICAL_FLOW_USAGE_OUTPUT_BIT_NV))
    return refuse("the optical flow unit's flow images cannot be copied from");
  rep.push_back("the formats R8_UNORM in and R16G16_SFIXED5_NV out, with their uses");

  // ---- the answers about sharing with D3D12
  {
    const auto buffer_answer = [&](VkBufferUsageFlags usage) -> VkExternalMemoryFeatureFlags {
      VkPhysicalDeviceExternalBufferInfo info{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_EXTERNAL_BUFFER_INFO};
      info.usage = usage;
      info.handleType = VK_EXTERNAL_MEMORY_HANDLE_TYPE_D3D12_RESOURCE_BIT;
      VkExternalBufferProperties p{VK_STRUCTURE_TYPE_EXTERNAL_BUFFER_PROPERTIES};
      vk.vkGetPhysicalDeviceExternalBufferProperties(m.phys, &info, &p);
      return p.externalMemoryProperties.externalMemoryFeatures;
    };
    const VkExternalMemoryFeatureFlags luma_answer = buffer_answer(VK_BUFFER_USAGE_TRANSFER_SRC_BIT);
    const VkExternalMemoryFeatureFlags flow_answer = buffer_answer(VK_BUFFER_USAGE_TRANSFER_DST_BIT);
    VkSemaphoreTypeCreateInfo tci{VK_STRUCTURE_TYPE_SEMAPHORE_TYPE_CREATE_INFO};
    tci.semaphoreType = VK_SEMAPHORE_TYPE_TIMELINE;
    VkPhysicalDeviceExternalSemaphoreInfo si{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_EXTERNAL_SEMAPHORE_INFO};
    si.pNext = &tci;
    si.handleType = VK_EXTERNAL_SEMAPHORE_HANDLE_TYPE_D3D12_FENCE_BIT;
    VkExternalSemaphoreProperties sp{VK_STRUCTURE_TYPE_EXTERNAL_SEMAPHORE_PROPERTIES};
    vk.vkGetPhysicalDeviceExternalSemaphoreProperties(m.phys, &si, &sp);
    const bool fence_ok = (sp.externalSemaphoreFeatures & VK_EXTERNAL_SEMAPHORE_FEATURE_IMPORTABLE_BIT) != 0;
    rep.push_back(strf("sharing with D3D12, a resource as the luma buffer %s, as the flow buffer %s, a fence as a "
                       "timeline semaphore %s",
                       memory_features_text(luma_answer).c_str(), memory_features_text(flow_answer).c_str(),
                       fence_ok ? "IMPORTABLE" : "not importable"));
    if (!(luma_answer & VK_EXTERNAL_MEMORY_FEATURE_IMPORTABLE_BIT))
      return refuse("the D3D12 buffers or fences cannot be shared with Vulkan (the luma buffer)");
    if (!(flow_answer & VK_EXTERNAL_MEMORY_FEATURE_IMPORTABLE_BIT))
      return refuse("the D3D12 buffers or fences cannot be shared with Vulkan (the flow buffer)");
    if (!fence_ok) return refuse("the D3D12 buffers or fences cannot be shared with Vulkan (the fences)");
  }

  // ---- the device: one queue of the family, the three extensions, the four features
  {
    const float priority = 1.0f;
    VkDeviceQueueCreateInfo qci{VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO};
    qci.queueFamilyIndex = m.family;
    qci.queueCount = 1;
    qci.pQueuePriorities = &priority;
    VkPhysicalDeviceOpticalFlowFeaturesNV eof{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_OPTICAL_FLOW_FEATURES_NV};
    eof.opticalFlow = VK_TRUE;
    VkPhysicalDeviceVulkan13Features e13{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_3_FEATURES};
    e13.synchronization2 = VK_TRUE;
    e13.pNext = &eof;
    VkPhysicalDeviceVulkan12Features e12{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_2_FEATURES};
    e12.timelineSemaphore = VK_TRUE;
    e12.hostQueryReset = VK_TRUE;
    e12.pNext = &e13;
    const char* extensions[] = {VK_NV_OPTICAL_FLOW_EXTENSION_NAME, VK_KHR_EXTERNAL_MEMORY_WIN32_EXTENSION_NAME,
                                VK_KHR_EXTERNAL_SEMAPHORE_WIN32_EXTENSION_NAME};
    VkDeviceCreateInfo dci{VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO};
    dci.pNext = &e12;
    dci.queueCreateInfoCount = 1;
    dci.pQueueCreateInfos = &qci;
    dci.enabledExtensionCount = 3;
    dci.ppEnabledExtensionNames = extensions;
    r = vk.vkCreateDevice(m.phys, &dci, nullptr, &m.device);
    if (r != VK_SUCCESS) return refuse("the Vulkan device was refused (" + std::string(vk_name(r)) + ")");
  }
#define FLOW_LOAD_DEVICE(name)                                                     \
  vk.name = reinterpret_cast<PFN_##name>(vk.vkGetDeviceProcAddr(m.device, #name)); \
  if (!vk.name) return refuse("the Vulkan device gives no " #name);
  FLOW_DEVICE_FUNCS(FLOW_LOAD_DEVICE)
#undef FLOW_LOAD_DEVICE

  // ---- the modules the loader, the instance and the device brought in, each under the
  // Windows folder
  {
    const std::wstring folder = windows_folder();
    const std::vector<std::wstring> added = modules_between(m.mods_before, module_paths());
    rep.push_back(strf("modules the Vulkan setup added %zu, each of which must lie under %s", added.size(),
                       narrow(folder).c_str()));
    std::wstring outside;
    for (const auto& p : added) {
      const bool inside = under(p, folder);
      rep.push_back(strf("  %s %s", inside ? "module" : "OUTSIDE", narrow(p).c_str()));
      if (!inside && outside.empty()) outside = p;
    }
    if (!outside.empty()) return refuse("a Vulkan layer came into the engine (" + narrow(outside) + ")");
  }

  // ---- the queue, the commands, the timestamps
  vk.vkGetDeviceQueue(m.device, m.family, 0, &m.queue);
  vk.vkGetPhysicalDeviceMemoryProperties(m.phys, &m.mem);
  {
    VkCommandPoolCreateInfo pci{VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO};
    pci.flags = VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT;
    pci.queueFamilyIndex = m.family;
    r = vk.vkCreateCommandPool(m.device, &pci, nullptr, &m.pool);
    VkCommandBufferAllocateInfo cai{VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO};
    cai.commandPool = m.pool;
    cai.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY;
    cai.commandBufferCount = 2;
    if (r == VK_SUCCESS) r = vk.vkAllocateCommandBuffers(m.device, &cai, m.cb);
    cai.commandBufferCount = 1;
    if (r == VK_SUCCESS) r = vk.vkAllocateCommandBuffers(m.device, &cai, &m.once);
    VkFenceCreateInfo fci{VK_STRUCTURE_TYPE_FENCE_CREATE_INFO};
    if (r == VK_SUCCESS) r = vk.vkCreateFence(m.device, &fci, nullptr, &m.fence);
    VkQueryPoolCreateInfo qpi{VK_STRUCTURE_TYPE_QUERY_POOL_CREATE_INFO};
    qpi.queryType = VK_QUERY_TYPE_TIMESTAMP;
    qpi.queryCount = 8;
    if (r == VK_SUCCESS) r = vk.vkCreateQueryPool(m.device, &qpi, nullptr, &m.queries);
    if (r != VK_SUCCESS)
      return refuse("the optical flow unit's commands could not be made (" + std::string(vk_name(r)) + ")");
    vk.vkResetQueryPool(m.device, m.queries, 0, 8);
  }

  // ---- the session and its images, in GENERAL for life after one barrier
  {
    const VkOpticalFlowSessionCreateInfoNV si = m.session_info(pad_w, pad_h);
    r = vk.vkCreateOpticalFlowSessionNV(m.device, &si, nullptr, &m.session);
    if (r != VK_SUCCESS) return refuse("the optical flow session was refused (" + std::string(vk_name(r)) + ")");
    std::string e;
    for (int i = 0; i < 2; ++i) {
      if (!m.make_image(m.in[i], VK_FORMAT_R8_UNORM, pad_w, pad_h, m.usage_input, VK_OPTICAL_FLOW_USAGE_INPUT_BIT_NV,
                        e))
        return refuse("the optical flow unit's images could not be made (" + e + ")");
    }
    if (!m.make_image(m.flow, VK_FORMAT_R16G16_SFIXED5_NV, cells_w, cells_h, m.usage_flow,
                      VK_OPTICAL_FLOW_USAGE_OUTPUT_BIT_NV, e))
      return refuse("the optical flow unit's images could not be made (" + e + ")");
    VkImageMemoryBarrier2 b[3];
    const Impl::Image* images[3] = {&m.in[0], &m.in[1], &m.flow};
    for (int i = 0; i < 3; ++i) {
      b[i] = Impl::image_barrier(images[i]->image, VK_PIPELINE_STAGE_2_NONE, 0, VK_PIPELINE_STAGE_2_ALL_COMMANDS_BIT,
                                 VK_ACCESS_2_MEMORY_READ_BIT | VK_ACCESS_2_MEMORY_WRITE_BIT, VK_IMAGE_LAYOUT_UNDEFINED,
                                 VK_IMAGE_LAYOUT_GENERAL);
    }
    VkCommandBufferBeginInfo bi{VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};
    bi.flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT;
    r = vk.vkBeginCommandBuffer(m.once, &bi);
    if (r == VK_SUCCESS) {
      m.barrier(m.once, b, 3, nullptr, 0);
      r = vk.vkEndCommandBuffer(m.once);
    }
    VkCommandBufferSubmitInfo cbi{VK_STRUCTURE_TYPE_COMMAND_BUFFER_SUBMIT_INFO};
    cbi.commandBuffer = m.once;
    VkSubmitInfo2 sub{VK_STRUCTURE_TYPE_SUBMIT_INFO_2};
    sub.commandBufferInfoCount = 1;
    sub.pCommandBufferInfos = &cbi;
    if (r == VK_SUCCESS) r = vk.vkQueueSubmit2(m.queue, 1, &sub, m.fence);
    if (r == VK_SUCCESS) r = vk.vkWaitForFences(m.device, 1, &m.fence, VK_TRUE, (uint64_t)kWaitMs * 1000000ull);
    if (r == VK_SUCCESS) r = vk.vkResetFences(m.device, 1, &m.fence);
    if (r != VK_SUCCESS)
      return refuse("the optical flow unit's images could not be readied (" + std::string(vk_name(r)) + ")");
    rep.push_back(strf("the session %ux%u for a picture of %ux%u, grid 4x4, medium, forward only, no cost map, the "
                       "flow %ux%u, %ux%u cells over the picture",
                       pad_w, pad_h, me_w, me_h, cells_w, cells_h, crop_w, crop_h));
  }

  // ---- the sharing, two buffers and two fences of D3D12's imported into Vulkan
  {
    std::string note_text, e;
    if (!m.share_buffer((UINT64)pad_w * pad_h, D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS,
                        VK_BUFFER_USAGE_TRANSFER_SRC_BIT, L"flow luma", m.luma, m.vluma, m.mluma, note_text, e))
      return refuse("the D3D12 buffers or fences cannot be shared with Vulkan (the luma buffer, " + e + ")");
    if (!m.share_buffer((UINT64)cells_w * cells_h * 4, D3D12_RESOURCE_FLAG_NONE, VK_BUFFER_USAGE_TRANSFER_DST_BIT,
                        L"flow vectors", m.flowbuf, m.vflow, m.mflow, note_text, e))
      return refuse("the D3D12 buffers or fences cannot be shared with Vulkan (the flow buffer, " + e + ")");
    if (!m.share_fence(L"flow F1", m.f1, m.s1, e))
      return refuse("the D3D12 buffers or fences cannot be shared with Vulkan (F1, " + e + ")");
    if (!m.share_fence(L"flow F2", m.f2, m.s2, e))
      return refuse("the D3D12 buffers or fences cannot be shared with Vulkan (F2, " + e + ")");
    m.f2_event = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    if (!m.f2_event) return refuse("the optical flow unit's event could not be made");
    rep.push_back("shared, the luma and the flow buffers (" + note_text + ") and the fences F1 and F2");
  }

  // ---- the luma pass: the tie table, the weights, the shader
  {
    uint32_t ties = 0, other = 0;
    const double t0 = now_s();
    const std::vector<uint32_t> keys = tie_table(ties, other);
    m.tie_count = (UINT)keys.size();
    rep.push_back(strf("the luma's tie table %u keys of %u colours on a half, %u other differences, in %.1f ms",
                       m.tie_count, ties, other, (now_s() - t0) * 1000.0));
    std::vector<float> table;
    area_weights(frame_w, me_w, m.taps_x, table);
    area_weights(frame_h, me_h, m.taps_y, table);
    std::string e;
    if (!g.make_buffer(table.size() * 4, D3D12_HEAP_TYPE_UPLOAD, D3D12_RESOURCE_STATE_GENERIC_READ,
                       D3D12_RESOURCE_FLAG_NONE, L"flow luma weights", m.weights, e) ||
        !g.make_buffer(std::max<size_t>(1, keys.size()) * 4, D3D12_HEAP_TYPE_UPLOAD, D3D12_RESOURCE_STATE_GENERIC_READ,
                       D3D12_RESOURCE_FLAG_NONE, L"flow luma ties", m.ties, e))
      return refuse("the luma pass could not be made (" + e + ")");
    void* p = nullptr;
    const D3D12_RANGE none = {0, 0};
    if (FAILED(m.weights->Map(0, &none, &p)) || !p) return refuse("the luma pass could not be made (weights)");
    memcpy(p, table.data(), table.size() * 4);
    m.weights->Unmap(0, nullptr);
    p = nullptr;
    if (FAILED(m.ties->Map(0, &none, &p)) || !p) return refuse("the luma pass could not be made (ties)");
    if (!keys.empty()) memcpy(p, keys.data(), keys.size() * 4);
    m.ties->Unmap(0, nullptr);

    D3D12_DESCRIPTOR_RANGE frame_range = {D3D12_DESCRIPTOR_RANGE_TYPE_SRV, 1, 0, 0, 0};
    D3D12_DESCRIPTOR_RANGE table_range = {D3D12_DESCRIPTOR_RANGE_TYPE_SRV, 2, 1, 0, 0};
    D3D12_DESCRIPTOR_RANGE luma_range = {D3D12_DESCRIPTOR_RANGE_TYPE_UAV, 1, 0, 0, 0};
    D3D12_ROOT_PARAMETER params[4] = {};
    params[0].ParameterType = D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS;
    params[0].Constants.ShaderRegister = 0;
    params[0].Constants.Num32BitValues = kConstants;
    const D3D12_DESCRIPTOR_RANGE* ranges[3] = {&frame_range, &table_range, &luma_range};
    for (int i = 0; i < 3; ++i) {
      params[i + 1].ParameterType = D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
      params[i + 1].DescriptorTable.NumDescriptorRanges = 1;
      params[i + 1].DescriptorTable.pDescriptorRanges = ranges[i];
    }
    D3D12_ROOT_SIGNATURE_DESC rd = {};
    rd.NumParameters = 4;
    rd.pParameters = params;
    ComPtr<ID3DBlob> blob, problem;
    HRESULT hr = D3D12SerializeRootSignature(&rd, D3D_ROOT_SIGNATURE_VERSION_1, &blob, &problem);
    if (SUCCEEDED(hr) && blob)
      hr = g.device->CreateRootSignature(0, blob->GetBufferPointer(), blob->GetBufferSize(), IID_PPV_ARGS(&m.root));
    if (FAILED(hr) || !m.root) return refuse("the luma pass's root signature failed " + hr_text(hr));
    D3D12_COMPUTE_PIPELINE_STATE_DESC cd = {};
    cd.pRootSignature = m.root.Get();
    cd.CS = {g_flowluma_cs, sizeof(g_flowluma_cs)};
    hr = g.device->CreateComputePipelineState(&cd, IID_PPV_ARGS(&m.pso));
    if (FAILED(hr)) return refuse("the luma pass's pipeline state failed " + hr_text(hr));
    D3D12_DESCRIPTOR_HEAP_DESC hd = {};
    hd.Type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;
    hd.NumDescriptors = kSlots;
    hd.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
    hr = g.device->CreateDescriptorHeap(&hd, IID_PPV_ARGS(&m.heap));
    if (FAILED(hr)) return refuse("the luma pass's descriptor heap failed " + hr_text(hr));
    m.heap_step = g.device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
    const auto slot = [&](UINT i) {
      D3D12_CPU_DESCRIPTOR_HANDLE at = m.heap->GetCPUDescriptorHandleForHeapStart();
      at.ptr += (SIZE_T)i * m.heap_step;
      return at;
    };
    D3D12_SHADER_RESOURCE_VIEW_DESC sd = {};
    sd.Format = DXGI_FORMAT_R32_FLOAT;
    sd.ViewDimension = D3D12_SRV_DIMENSION_BUFFER;
    sd.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
    sd.Buffer.NumElements = (UINT)table.size();
    g.device->CreateShaderResourceView(m.weights.Get(), &sd, slot(kSlotWeights));
    D3D12_SHADER_RESOURCE_VIEW_DESC td = {};
    td.Format = DXGI_FORMAT_UNKNOWN;
    td.ViewDimension = D3D12_SRV_DIMENSION_BUFFER;
    td.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
    td.Buffer.NumElements = std::max<UINT>(1, m.tie_count);
    td.Buffer.StructureByteStride = 4;
    g.device->CreateShaderResourceView(m.ties.Get(), &td, slot(kSlotTies));
    D3D12_UNORDERED_ACCESS_VIEW_DESC ud = {};
    ud.Format = DXGI_FORMAT_R32_TYPELESS;
    ud.ViewDimension = D3D12_UAV_DIMENSION_BUFFER;
    ud.Buffer.NumElements = (UINT)((UINT64)pad_w * pad_h / 4);
    ud.Buffer.Flags = D3D12_BUFFER_UAV_FLAG_RAW;
    g.device->CreateUnorderedAccessView(m.luma.Get(), nullptr, &ud, slot(kSlotLuma));
    if (!g.make_list(m.allocator, m.list, L"flow luma", e)) return refuse("the luma pass's list failed, " + e);
    if (!m.timer.init(g, 2, e)) {
      note("flow: no GPU timer for the luma pass, %s", e.c_str());
      m.timer.shutdown();
    }
  }
  return true;
}

bool Flow::stop(std::string& err) {
  stopped_ = true;
  executed_ = false;
  if (impl_ && impl_->f2 && impl_->f2->GetCompletedValue() < impl_->v) impl_->f2->Signal(impl_->v);
  err = "the optical flow unit stopped (" + err + ")";
  return false;
}

bool Flow::submit(ID3D12Resource* frame, const uint8_t* luma, UINT64& read_value, std::string& err) {
  read_value = 0;
  executed_ = false;
  if (!impl_) {
    err = "the optical flow unit is not made";
    return false;
  }
  if (stopped_) {
    err = "the optical flow unit has stopped";
    return false;
  }
  Impl& m = *impl_;
  Gpu& g = *m.gpu;
  bool fp16 = false;
  DXGI_FORMAT format = DXGI_FORMAT_UNKNOWN;
  if (!luma) {
    const D3D12_RESOURCE_DESC fd = frame ? frame->GetDesc() : D3D12_RESOURCE_DESC{};
    format = fd.Format;
    fp16 = format == DXGI_FORMAT_R16G16B16A16_FLOAT;
    if (!frame || fd.Width != frame_w || fd.Height != frame_h || (format != DXGI_FORMAT_B8G8R8A8_UNORM && !fp16)) {
      err = strf("the optical flow unit was made for %ux%u frames in B8G8R8A8_UNORM or R16G16B16A16_FLOAT", frame_w,
                 frame_h);
      return false;
    }
  }
  const uint64_t value = m.v + 1;
  // The unit has finished frame value - 1, so the session's images may be bound again and the
  // luma buffer written, and so has the last luma list
  if (!m.wait_f2(value - 1, err)) return stop(err);
  if (!g.wait(m.list_value, kWaitMs, err)) return stop(err);
  if (FAILED(m.allocator->Reset()) || FAILED(m.list->Reset(m.allocator.Get(), nullptr))) {
    err = "resetting the luma list failed";
    return stop(err);
  }
  ID3D12GraphicsCommandList* l = m.list.Get();
  const UINT64 luma_bytes = (UINT64)pad_w * pad_h;
  if (luma) {
    // the test's luma in place of the pass, through an upload buffer of the unit's own
    if (!m.upload && !g.make_buffer(luma_bytes, D3D12_HEAP_TYPE_UPLOAD, D3D12_RESOURCE_STATE_GENERIC_READ,
                                    D3D12_RESOURCE_FLAG_NONE, L"flow luma upload", m.upload, err))
      return stop(err);
    void* p = nullptr;
    const D3D12_RANGE none = {0, 0};
    if (FAILED(m.upload->Map(0, &none, &p)) || !p) {
      err = "mapping the luma upload failed";
      return stop(err);
    }
    memcpy(p, luma, (size_t)luma_bytes);
    m.upload->Unmap(0, nullptr);
    transition(l, m.luma.Get(), D3D12_RESOURCE_STATE_COMMON, D3D12_RESOURCE_STATE_COPY_DEST);
    l->CopyBufferRegion(m.luma.Get(), 0, m.upload.Get(), 0, luma_bytes);
    transition(l, m.luma.Get(), D3D12_RESOURCE_STATE_COPY_DEST, D3D12_RESOURCE_STATE_COMMON);
    m.luma_timed = false;
  } else {
    // the frame's view, written now that the list before has finished
    D3D12_SHADER_RESOURCE_VIEW_DESC sd = {};
    sd.Format = format;
    sd.ViewDimension = D3D12_SRV_DIMENSION_TEXTURE2D;
    sd.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
    sd.Texture2D.MipLevels = 1;
    D3D12_CPU_DESCRIPTOR_HANDLE at = m.heap->GetCPUDescriptorHandleForHeapStart();
    at.ptr += (SIZE_T)kSlotFrame * m.heap_step;
    g.device->CreateShaderResourceView(frame, &sd, at);
    const auto table = [&](UINT i) {
      D3D12_GPU_DESCRIPTOR_HANDLE h = m.heap->GetGPUDescriptorHandleForHeapStart();
      h.ptr += (UINT64)i * m.heap_step;
      return h;
    };
    m.timer.mark(l, 0);
    ID3D12DescriptorHeap* heaps[] = {m.heap.Get()};
    l->SetDescriptorHeaps(1, heaps);
    l->SetComputeRootSignature(m.root.Get());
    l->SetPipelineState(m.pso.Get());
    const float white = sdr_white;
    UINT constants[kConstants] = {frame_w, frame_h, me_w, me_h, pad_w, pad_h, m.taps_x, m.taps_y, fp16 ? 1u : 0u,
                                  0u, m.tie_count};
    memcpy(&constants[9], &white, 4);
    l->SetComputeRoot32BitConstants(0, kConstants, constants, 0);
    l->SetComputeRootDescriptorTable(1, table(kSlotFrame));
    l->SetComputeRootDescriptorTable(2, table(kSlotWeights));
    l->SetComputeRootDescriptorTable(3, table(kSlotLuma));
    transition(l, frame, D3D12_RESOURCE_STATE_COMMON, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
    transition(l, m.luma.Get(), D3D12_RESOURCE_STATE_COMMON, D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
    l->Dispatch((pad_w / 4 + 7) / 8, (pad_h + 7) / 8, 1);
    transition(l, m.luma.Get(), D3D12_RESOURCE_STATE_UNORDERED_ACCESS, D3D12_RESOURCE_STATE_COMMON);
    transition(l, frame, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE, D3D12_RESOURCE_STATE_COMMON);
    m.timer.mark(l, 1);
    m.timer.resolve(l, 0, 2);
    m.luma_timed = m.timer.heap != nullptr;
  }
  if (!g.execute(l, m.list_value, err)) return stop(err);
  if (!luma) read_value = m.list_value;
  const HRESULT hr = g.queue->Signal(m.f1.Get(), value);
  if (FAILED(hr)) {
    err = "the queue's signal of F1 failed " + hr_text(hr);
    return stop(err);
  }
  m.v = value;
  const bool execute = frames_ > 0;
  if (!m.frame(value, (int)(frames_ % 2), execute, pad_w, pad_h, cells_w, cells_h, err)) return stop(err);
  ++frames_;
  executed_ = execute;
  return true;
}

UINT64 Flow::value() const { return impl_ ? impl_->v : 0; }

bool Flow::wait_on_queue(std::string& err) {
  if (!impl_ || impl_->v == 0) return true;
  const HRESULT hr = impl_->gpu->queue->Wait(impl_->f2.Get(), impl_->v);
  if (FAILED(hr)) {
    err = "the queue's wait for the flow failed " + hr_text(hr);
    return false;
  }
  return true;
}

namespace {

// One of the shared buffers read back through gpu.queue, behind the unit's last frame.
bool read_shared(Gpu& g, ID3D12Fence* f2, UINT64 value, ID3D12Resource* src, UINT64 bytes,
                 ComPtr<ID3D12Resource>& readback, ComPtr<ID3D12CommandAllocator>& allocator,
                 ComPtr<ID3D12GraphicsCommandList>& list, const wchar_t* name, std::vector<uint8_t>& out,
                 std::string& err) {
  if (!readback && !g.make_buffer(bytes, D3D12_HEAP_TYPE_READBACK, D3D12_RESOURCE_STATE_COPY_DEST,
                                  D3D12_RESOURCE_FLAG_NONE, name, readback, err))
    return false;
  if (!list && !g.make_list(allocator, list, L"flow readback", err)) return false;
  if (FAILED(allocator->Reset()) || FAILED(list->Reset(allocator.Get(), nullptr))) {
    err = "resetting the readback list failed";
    return false;
  }
  if (value > 0) {
    const HRESULT hr = g.queue->Wait(f2, value);
    if (FAILED(hr)) {
      err = "the queue's wait for the flow failed " + hr_text(hr);
      return false;
    }
  }
  ID3D12GraphicsCommandList* l = list.Get();
  transition(l, src, D3D12_RESOURCE_STATE_COMMON, D3D12_RESOURCE_STATE_COPY_SOURCE);
  l->CopyBufferRegion(readback.Get(), 0, src, 0, bytes);
  transition(l, src, D3D12_RESOURCE_STATE_COPY_SOURCE, D3D12_RESOURCE_STATE_COMMON);
  UINT64 done = 0;
  if (!g.execute(l, done, err) || !g.wait(done, kWaitMs, err)) return false;
  void* p = nullptr;
  const D3D12_RANGE whole = {0, (SIZE_T)bytes};
  if (FAILED(readback->Map(0, &whole, &p)) || !p) {
    err = "mapping a readback failed";
    return false;
  }
  out.assign((const uint8_t*)p, (const uint8_t*)p + bytes);
  const D3D12_RANGE none = {0, 0};
  readback->Unmap(0, &none);
  return true;
}

}  // namespace

bool Flow::read_flow(std::vector<uint8_t>& raw, std::string& err) {
  if (!impl_ || !executed_) {
    err = "there is no flow to read";
    return false;
  }
  Impl& m = *impl_;
  return read_shared(*m.gpu, m.f2.Get(), m.v, m.flowbuf.Get(), (UINT64)cells_w * cells_h * 4, m.rb_flow,
                     m.rb_allocator, m.rb_list, L"flow vectors readback", raw, err);
}

bool Flow::read_luma(std::vector<uint8_t>& raw, std::string& err) {
  if (!impl_ || impl_->v == 0) {
    err = "there is no luma to read";
    return false;
  }
  Impl& m = *impl_;
  return read_shared(*m.gpu, m.f2.Get(), m.v, m.luma.Get(), (UINT64)pad_w * pad_h, m.rb_luma, m.rb_allocator,
                     m.rb_list, L"flow luma readback", raw, err);
}

FlowTimes Flow::times() const {
  FlowTimes t;
  if (!impl_ || impl_->v == 0) return t;
  const Impl& m = *impl_;
  if (m.luma_timed && m.gpu->fence && m.gpu->fence->GetCompletedValue() >= m.list_value) {
    t.luma_valid = true;
    t.luma_ms = m.timer.ms(*m.gpu, 0, 1);
  }
  if (!stopped_ && m.f2->GetCompletedValue() >= m.v) {
    uint64_t ts[4] = {};
    const uint32_t set = (uint32_t)(m.v % 2);
    if (m.vk.vkGetQueryPoolResults(m.device, m.queries, set * 4, 4, sizeof ts, ts, sizeof(uint64_t),
                                   VK_QUERY_RESULT_64_BIT) == VK_SUCCESS) {
      const auto ms = [&](uint64_t a, uint64_t b) {
        uint64_t d = b - a;
        if (m.ts_bits < 64) d &= (1ull << m.ts_bits) - 1ull;
        return (double)d * m.ts_period_ns / 1.0e6;
      };
      t.unit_valid = true;
      t.copy_in_ms = ms(ts[0], ts[1]);
      t.execute_ms = ms(ts[1], ts[2]);
      t.copy_out_ms = ms(ts[2], ts[3]);
    }
  }
  return t;
}

bool Flow::try_session(UINT width, UINT height, std::string& result) {
  if (!impl_ || !impl_->device) {
    result = "no unit";
    return false;
  }
  Impl& m = *impl_;
  const VkOpticalFlowSessionCreateInfoNV si = m.session_info(pad8(width), pad8(height));
  VkOpticalFlowSessionNV s = VK_NULL_HANDLE;
  const VkResult r = m.vk.vkCreateOpticalFlowSessionNV(m.device, &si, nullptr, &s);
  if (r == VK_SUCCESS && s) m.vk.vkDestroyOpticalFlowSessionNV(m.device, s, nullptr);
  result = r == VK_SUCCESS ? "accepted" : "refused, " + vk_text(r);
  return r == VK_SUCCESS;
}

std::vector<std::string> Flow::modules_added() const {
  std::vector<std::string> out;
  if (!impl_) return out;
  for (const auto& p : modules_between(impl_->mods_before, module_paths())) out.push_back(narrow(p));
  return out;
}

ID3D12Resource* Flow::flow_buffer() const { return impl_ ? impl_->flowbuf.Get() : nullptr; }

void Flow::shutdown() {
  if (!impl_) return;
  Impl& m = *impl_;
  VkFns& vk = m.vk;
  bool idle = true;
  if (m.gpu && m.list_value) {
    // the last luma list reads what is released below
    std::string e;
    if (!m.gpu->wait(m.list_value, kWaitMs, e)) note("flow: the luma pass did not finish, %s", e.c_str());
  }
  if (m.device) {
    // the unit's queue waits on F1 for each frame, so where the D3D12 side never reached the last
    // value the CPU gives it, and the queue can come to rest
    if (m.f1 && m.v > 0 && m.f1->GetCompletedValue() < m.v) m.f1->Signal(m.v);
    if (m.s2 && m.v > 0 && vk.vkWaitSemaphores) {
      VkSemaphoreWaitInfo wi{VK_STRUCTURE_TYPE_SEMAPHORE_WAIT_INFO};
      wi.semaphoreCount = 1;
      wi.pSemaphores = &m.s2;
      wi.pValues = &m.v;
      idle = vk.vkWaitSemaphores(m.device, &wi, (uint64_t)kWaitMs * 1000000ull) == VK_SUCCESS;
    }
    if (!idle) {
      // no D3D12 queue may wait for ever on a flow that will not come, and nothing is released
      // under a queue that may still run, so the process gives it back as it ends
      if (m.f2 && m.f2->GetCompletedValue() < m.v) m.f2->Signal(m.v);
      note("flow: the optical flow unit did not come to rest, its Vulkan objects stay until the process ends");
      impl_.release();
      frames_ = 0;
      executed_ = false;
      return;
    }
    if (vk.vkDeviceWaitIdle) vk.vkDeviceWaitIdle(m.device);
    if (m.session) vk.vkDestroyOpticalFlowSessionNV(m.device, m.session, nullptr);
    m.free_image(m.in[0]);
    m.free_image(m.in[1]);
    m.free_image(m.flow);
    if (m.vluma) vk.vkDestroyBuffer(m.device, m.vluma, nullptr);
    if (m.vflow) vk.vkDestroyBuffer(m.device, m.vflow, nullptr);
    if (m.mluma) vk.vkFreeMemory(m.device, m.mluma, nullptr);
    if (m.mflow) vk.vkFreeMemory(m.device, m.mflow, nullptr);
    if (m.s1) vk.vkDestroySemaphore(m.device, m.s1, nullptr);
    if (m.s2) vk.vkDestroySemaphore(m.device, m.s2, nullptr);
    if (m.queries) vk.vkDestroyQueryPool(m.device, m.queries, nullptr);
    if (m.fence) vk.vkDestroyFence(m.device, m.fence, nullptr);
    if (m.pool) vk.vkDestroyCommandPool(m.device, m.pool, nullptr);
    if (vk.vkDestroyDevice) vk.vkDestroyDevice(m.device, nullptr);
  }
  if (m.instance && vk.vkDestroyInstance) vk.vkDestroyInstance(m.instance, nullptr);
  if (m.lib) FreeLibrary(m.lib);
  if (m.f2_event) CloseHandle(m.f2_event);
  m.timer.shutdown();
  impl_.reset();
  frames_ = 0;
  executed_ = false;
}

// ---------------------------------------------------------------- --flow-info

int run_flow_info(const Options& o) {
  std::string err;
  const HMONITOR monitor = o.have_at && o.have_size ? monitor_under(o.x, o.y, o.width, o.height)
                                                    : MonitorFromPoint(POINT{0, 0}, MONITOR_DEFAULTTOPRIMARY);
  MONITORINFO mi = {};
  mi.cbSize = sizeof(mi);
  if (!monitor || !GetMonitorInfoW(monitor, &mi)) {
    fail("the monitor could not be read");
    return exit_code::failed;
  }
  const UINT w = o.have_size ? (UINT)o.width : (UINT)(mi.rcMonitor.right - mi.rcMonitor.left);
  const UINT h = o.have_size ? (UINT)o.height : (UINT)(mi.rcMonitor.bottom - mi.rcMonitor.top);
  Gpu gpu;
  if (!gpu.init(monitor, err)) {
    fail("%s", err.c_str());
    return exit_code::failed;
  }
  UINT me_w = 0, me_h = 0;
  estimator_size(w, h, me_w, me_h);
  say("flow-info the engine's adapter %s, LUID %s, for a picture of %ux%u, the motion estimator's picture %ux%u",
      gpu.name.c_str(), luid_text(&gpu.luid).c_str(), w, h, me_w, me_h);
  Flow flow;
  const bool made = flow.init(gpu, w, h, me_w, me_h, err);
  for (const std::string& line : flow.report()) say("flow-info %s", line.c_str());
  int code = exit_code::ok;
  if (!made) {
    say("edges unavailable %s", err.c_str());
    code = exit_code::usage;
  } else {
    // one pair of blank frames through the unit, the luma pass, the sharing and the copies included
    Microsoft::WRL::ComPtr<ID3D12Resource> blank;
    bool ran = gpu.make_texture(DXGI_FORMAT_B8G8R8A8_UNORM, w, h, D3D12_RESOURCE_FLAG_NONE,
                                D3D12_RESOURCE_STATE_COMMON, L"flow-info frame", blank, err);
    UINT64 read_value = 0;
    for (int i = 0; ran && i < 2; ++i) ran = flow.submit(blank.Get(), nullptr, read_value, err);
    std::vector<uint8_t> raw;
    if (ran) ran = flow.read_flow(raw, err) && gpu.flush(kWaitMs, err);
    if (ran) {
      // the vectors as the unit gives them, in 32nds of a texel: how many cells hold one other
      // than 0 0, how many vectors there are, and the one most cells hold
      size_t moved = 0;
      std::vector<uint32_t> keys;
      const int16_t* pairs = (const int16_t*)raw.data();
      for (size_t i = 0; i + 1 < raw.size() / 2; i += 2) {
        moved += (pairs[i] || pairs[i + 1]) ? 1 : 0;
        keys.push_back(((uint32_t)(uint16_t)pairs[i] << 16) | (uint16_t)pairs[i + 1]);
      }
      std::sort(keys.begin(), keys.end());
      uint32_t most = 0;
      size_t most_n = 0, distinct = 0;
      for (size_t i = 0; i < keys.size();) {
        size_t j = i;
        while (j < keys.size() && keys[j] == keys[i]) ++j;
        ++distinct;
        if (j - i > most_n) {
          most_n = j - i;
          most = keys[i];
        }
        i = j;
      }
      const FlowTimes t = flow.times();
      say("flow-info two blank frames through the unit, %zu of %u cells with a vector other than 0 0, %zu vectors "
          "in all, the most common %d %d in 32nds of a texel in %zu cells, the luma pass %.3f ms, the copy in %.3f "
          "ms, the unit %.3f ms, the copy out %.3f ms",
          moved, flow.cells_w * flow.cells_h, distinct, (int)(int16_t)(most >> 16), (int)(int16_t)(most & 0xFFFF),
          most_n, t.luma_ms, t.copy_in_ms, t.execute_ms, t.copy_out_ms);
    } else {
      say("flow-info two blank frames through the unit failed, %s", err.c_str());
      say("edges unavailable %s", err.c_str());
      code = exit_code::usage;
    }
    const UINT sizes[2][2] = {{2560, 1440}, {3072, 1280}};
    for (const auto& s : sizes) {
      std::string result;
      flow.try_session(s[0], s[1], result);
      say("flow-info a session at %ux%u %s", s[0], s[1], result.c_str());
    }
    const std::wstring folder = windows_folder();
    const std::vector<std::string> added = flow.modules_added();
    // the setup's own list is in the report, a module a line, and any other came in during the work
    std::vector<std::wstring> setup;
    for (const std::string& line : flow.report()) {
      if (line.compare(0, 9, "  module ") == 0) setup.push_back(lower(widen(line.substr(9))));
    }
    std::string outside;
    for (const std::string& p : added) {
      if (!under(widen(p), folder) && outside.empty()) outside = p;
      if (std::find(setup.begin(), setup.end(), lower(widen(p))) == setup.end())
        say("flow-info   module since the setup %s", p.c_str());
    }
    say("flow-info modules the unit added in all, its work included, %zu, %s", added.size(),
        outside.empty() ? "each of them under the Windows folder" : ("one outside it, " + outside).c_str());
    if (!outside.empty()) {
      say("edges unavailable a Vulkan layer came into the engine (%s)", outside.c_str());
      code = exit_code::usage;
    }
    if (code == exit_code::ok) say("flow-info the unit is available");
  }
  gpu.flush(kWaitMs, err);
  flow.shutdown();
  gpu.shutdown();
  return code;
}
