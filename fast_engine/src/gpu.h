// gpu.h: the engine's one D3D12 device and its one command queue.
//
// Everything the engine does on the GPU goes through this queue: the pipeline's compute and
// draw work, Neural Rendering, and the swapchain's presents (a D3D12 swapchain is made on a
// queue and flips in that queue's order). One queue means one order: a later list always
// sees what an earlier one wrote, and a present always follows the draw before it, with no
// synchronisation between queues to get wrong. The only other GPU client in the process is
// the capture's D3D11 device, which meets this one through shared textures and one shared
// fence (capture.h).
//
// Threads: the main thread only, for everything in this file. D3D12 itself would allow
// more, but the engine has exactly one thread that touches it and nothing here locks.
//
// Failure: bool and std::string& err, as everywhere. No function here throws. After a
// failure that names the device as removed nothing can be saved: the caller prints
// "engine failed REASON" and leaves, and the lens starts a presenter again.
#pragma once

#include "common.h"

#include <d3d12.h>
#include <dxgi1_6.h>
#include <wrl/client.h>

struct Gpu {
  // Open for every module to use. They are set by init() and stay the same objects until
  // shutdown(). Do not Release, replace or rename them.
  Microsoft::WRL::ComPtr<IDXGIFactory6> factory;      // the swapchain is made from it (window.cpp)
  Microsoft::WRL::ComPtr<IDXGIAdapter3> adapter;
  Microsoft::WRL::ComPtr<ID3D12Device> device;        // feature level 12_0
  Microsoft::WRL::ComPtr<ID3D12CommandQueue> queue;   // the one direct queue
  Microsoft::WRL::ComPtr<ID3D12Fence> fence;          // this queue's own fence, see execute()
  HANDLE fence_event = nullptr;                       // used inside wait()
  UINT64 fence_value = 0;                             // the last value signalled on the queue

  LUID luid = {};            // the adapter's, which the capture makes its D3D11 device on
  UINT vendor_id = 0;        // 0x10DE is NVIDIA. Neural Rendering needs it, see nr.h
  std::string name;          // the adapter's description in ASCII, for the ready line
  UINT64 timestamp_hz = 0;   // ticks a second of the queue's timestamp queries

  // Creates the factory, the device, the queue and the fence. The adapter is the one whose
  // output shows the monitor when that is an NVIDIA card, so the capture, the network and
  // the present all happen on the card that draws that screen and no picture crosses to
  // another card. When another maker's card draws the monitor and the computer has an
  // NVIDIA card as well, that one is taken, the first in the system's high performance
  // order, since the network runs nowhere else, and Windows carries the pictures across.
  // When no adapter lists the monitor, or monitor is null (the self test), it is the first
  // hardware adapter in the high performance order. Software adapters are never taken.
  // The debug layer is not enabled.
  // false with err, for example "no hardware adapter" or "D3D12CreateDevice failed 0x...".
  bool init(HMONITOR monitor, std::string& err);

  // Releases everything. The caller has waited for the queue (flush) and has destroyed
  // whatever it made on the device. Safe to call twice and without init.
  void shutdown();

  // A direct command allocator and a command list for it, the list closed, both named for
  // debugging. The caller resets them for each use (allocator->Reset, list->Reset) and may
  // only reset an allocator when the GPU has finished the list recorded from it: wait for
  // the value execute() gave.
  bool make_list(Microsoft::WRL::ComPtr<ID3D12CommandAllocator>& allocator,
                 Microsoft::WRL::ComPtr<ID3D12GraphicsCommandList>& list, const wchar_t* name,
                 std::string& err);

  // Closes the list, runs it on the queue and signals the fence after it. value is what the
  // fence reaches once the GPU has finished this list and everything submitted before it.
  // It does not wait. false with err when Close fails, which means the list was recorded
  // wrongly, or when the device is removed.
  bool execute(ID3D12GraphicsCommandList* list, UINT64& value, std::string& err);

  // Blocks the calling thread until the fence has reached value, or timeout_ms has passed.
  // false with err "the GPU did not finish in N ms" or "device removed 0x...". There is
  // always a timeout, a few seconds at most: this process holds a topmost window over the
  // whole screen, and one that waits for ever looks like a frozen computer.
  bool wait(UINT64 value, DWORD timeout_ms, std::string& err);

  // Signals the fence and waits for it: everything submitted so far is done when it returns
  // true. Before destroying anything the GPU may still be using, and at shutdown.
  bool flush(DWORD timeout_ms, std::string& err);

  // Whether the device still works. false with err "device removed 0x..." (the reason from
  // GetDeviceRemovedReason) once it does not.
  bool alive(std::string& err) const;

  // A committed 2D texture with one mip in a default heap, named for debugging. state is
  // the state it is created in and the one the creator then keeps track of: D3D12 does not
  // remember states for the caller. clear, when not null, is the optimised clear value for
  // a render target.
  // false with err naming the size, the format and the HRESULT.
  bool make_texture(DXGI_FORMAT format, UINT width, UINT height, D3D12_RESOURCE_FLAGS flags,
                    D3D12_RESOURCE_STATES state, const wchar_t* name,
                    Microsoft::WRL::ComPtr<ID3D12Resource>& out, std::string& err,
                    const D3D12_CLEAR_VALUE* clear = nullptr);

  // A committed buffer. heap is D3D12_HEAP_TYPE_UPLOAD (created in GENERIC_READ),
  // D3D12_HEAP_TYPE_READBACK (created in COPY_DEST) or D3D12_HEAP_TYPE_DEFAULT (created in
  // state). Upload and readback buffers keep their one state for life and may stay mapped.
  bool make_buffer(UINT64 bytes, D3D12_HEAP_TYPE heap, D3D12_RESOURCE_STATES state,
                   D3D12_RESOURCE_FLAGS flags, const wchar_t* name,
                   Microsoft::WRL::ComPtr<ID3D12Resource>& out, std::string& err);

  // Bytes of this process's video memory in use on the adapter (the local segment), 0 when
  // it cannot be read. The probe counted 690 MiB with the network loaded at 2560x1053.
  UINT64 vram_bytes() const;
};

// Records one transition barrier for the whole resource. Nothing is recorded when the two
// states are the same.
void transition(ID3D12GraphicsCommandList* list, ID3D12Resource* resource,
                D3D12_RESOURCE_STATES before, D3D12_RESOURCE_STATES after);

// GPU timestamps for the per stage timings: a query heap of count timestamps and the buffer
// they are read back through. Typical use, with slots 0 to 3:
//   mark(list, 0); ...stage A...; mark(list, 1); ...stage B...; mark(list, 2);
//   resolve(list, 0, 3);            // last, on the same list
//   ...execute, and once that list has finished on the GPU:
//   double a = ms(gpu, 0, 1), b = ms(gpu, 1, 2);
// The numbers are the GPU's own clock between the marks, so they do not include the wait
// for the queue or the time the CPU takes to notice. The probe's 3.35 ms was measured so.
struct GpuTimer {
  Microsoft::WRL::ComPtr<ID3D12QueryHeap> heap;
  Microsoft::WRL::ComPtr<ID3D12Resource> readback;  // count * 8 bytes, mapped for life
  const UINT64* ticks = nullptr;                    // the mapped buffer, one value a slot
  UINT count = 0;

  bool init(Gpu& gpu, UINT count, std::string& err);
  void shutdown();

  // Records the timestamp into slot. A slot may be marked once in a list.
  void mark(ID3D12GraphicsCommandList* list, UINT slot);

  // Records the copy of slots first to first + n - 1 into the readback buffer. After the
  // last mark of the list.
  void resolve(ID3D12GraphicsCommandList* list, UINT first, UINT n);

  // Milliseconds from slot a to slot b. Only meaningful once the GPU has finished the list
  // that resolved them: before that it reads the list before. 0 when the timer is not set
  // up or the slots were never resolved.
  double ms(const Gpu& gpu, UINT a, UINT b) const;
};
