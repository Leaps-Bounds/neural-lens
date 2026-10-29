// flow.h, the card's optical flow unit, run through Vulkan in the engine's own process, for the
// cut at moving edges.
//
// The card's motion estimate (framegen.h) holds one vector for each block of 8 by 8 texels,
// which is the motion of a moving thing or that of its background and not both. NVIDIA's cards
// also carry an optical flow unit, which Vulkan reaches through the extension VK_NV_optical_flow
// and D3D12 does not reach. It gives one vector for each block of 4 by 4 pixels. This module
// runs it on every new frame beside the motion estimate, so that the edges of moving things can
// be found in its flow (Edges cut, NRMotionSource 2, see look_settings.h).
//
// The loader and the layers. Before anything of Vulkan the module sets the loader's layer
// filter in the engine's own environment, VK_LOADER_LAYERS_DISABLE=~all~, and clears
// VK_LOADER_LAYERS_ENABLE, VK_LOADER_LAYERS_ALLOW and VK_INSTANCE_LAYERS, each of which could
// let a layer back in. Overlays and capture programs register implicit layers that would
// otherwise load into every Vulkan program, this one included. It then loads vulkan-1.dll from
// the Windows system folder by its full path, takes vkGetInstanceProcAddr from it and every
// other function through that and vkGetDeviceProcAddr, so no import library is linked. A loader
// older than 1.3.234, the release that brought the filter, is refused. The modules of the
// process are listed before the loader is loaded and again once the device is made, and every
// module that came in must lie under the Windows folder, as the loader and the drivers do. Any
// other is a layer that got past the filter, so the unit is refused and gives back the device,
// the instance and the loader.
//
// The device. The Vulkan device is the one whose LUID is the D3D12 adapter's (Gpu::luid), so
// the unit runs on the card the network runs on. It must be NVIDIA's, at Vulkan 1.3 or later,
// with VK_NV_optical_flow, VK_KHR_external_memory_win32 and VK_KHR_external_semaphore_win32 and
// the features opticalFlow, synchronization2, timelineSemaphore and hostQueryReset. The unit
// takes one queue of the first family that has the optical flow unit, copies and timestamps.
//
// The session. The luma of each frame at the motion estimator's size, me_w x me_h, padded to
// multiples of 8 with the last column and row repeated, in R8_UNORM inputs, and the flow in
// R16G16_SFIXED5_NV, one vector for each 4 by 4 block in pixels of that size times 32, previous
// minus current. The grid is 4x4, the performance level medium, temporal hints are off, and the
// session runs forward only with no cost map. Frame k since the last forget() goes into input
// k % 2. Frame 0 is only copied, and from frame 1 on the unit compares input k % 2 with the
// other one, the frame before. The research's optical flow probe, a test program written
// before this module and not part of this repository, ran the unit on the frames the cut was
// measured on, with the cost map and both directions as well, and this session gives its
// forward flows back bit for bit.
//
// The luma. A compute pass of the module's own on gpu.queue, shaders\flowluma_cs.hlsl, brings
// the frame to the estimator's size by the exact area filter of the network's input and takes
// the BT.709 luma of each texel in whole numbers. A table holds the 769 colours whose luma the
// probe's double sum rounded down from a half, built at init() by the probe's own line, luma8
// below. So the unit is given the probe's luma byte for byte. The estimator's NV12 picture is
// not used, since its luma differs from the probe's on some colours.
//
// The sharing. Two D3D12 buffers on a shared heap, the luma (pad_w x pad_h bytes) and the flow
// (cells_w x cells_h int16 pairs), and two shared D3D12 fences, F1 (the luma of frame n is
// written) and F2 (the flow of frame n is in its buffer), are imported into Vulkan as buffers
// and timeline semaphores. The images the unit works on stay Vulkan's own. Each frame the
// unit's queue copies the luma buffer into an input, runs the unit and copies the flow out
// into the flow buffer, taking both buffers from VK_QUEUE_FAMILY_EXTERNAL and giving them back.
//
// The order in a frame. submit() comes after FrameGen::estimate(). It records the luma list on
// gpu.queue, has gpu.queue signal F1 after it, and submits the unit's work, which waits for F1
// and signals F2. Nothing waits on the CPU. A list that reads the flow has gpu.queue wait for
// F2 first, see wait_on_queue(). Before the luma list of frame n the CPU makes sure F2 has
// reached n - 1, since the session's images are bound by a host call and the unit reads the
// luma buffer until then. A new frame comes 8 ms or more after the last and the unit takes 1.4
// to 1.6 ms at the sizes measured, so that check passes at once nearly always. It waits 2000 ms
// at most.
//
// Threads. The main thread only, as FrameGen.
//
// Failure. bool and std::string& err, as everywhere. init() fails with the reason the engine
// prints as "edges unavailable REASON", after which the network is handed the card's estimate
// whole, as with Card. A failure after init(), a Vulkan error, a device lost or a wait that
// times out, signals F2 from the CPU so that no D3D12 queue waits for ever, and the unit stops
// for good, which stopped() says, and every later submit() fails at once.
//
// Sources. Vulkan's declarations come from The Khronos Group's headers, kept unchanged in
// third_party\vulkan. Nothing of NVIDIA's SDKs or samples is used.
#pragma once

#include "common.h"
#include "edges.h"
#include "gpu.h"

#include <memory>

// The unit's own time for one frame in ms, the luma pass on gpu.queue by its timestamps and, on
// the unit's queue, the copy of the luma in, the unit's run and the copy of the flow out.
struct FlowTimes {
  bool luma_valid = false;  // the luma pass's list has finished and was timed
  double luma_ms = 0.0;
  bool unit_valid = false;  // the unit's work for the frame has finished and was timed
  double copy_in_ms = 0.0, execute_ms = 0.0, copy_out_ms = 0.0;
};

class Flow {
 public:
  Flow();
  ~Flow();
  Flow(const Flow&) = delete;
  Flow& operator=(const Flow&) = delete;

  // Makes the unit for frames of frame_w x frame_h, whose luma it takes at me_w x me_h, the
  // motion estimator's picture (FrameGen::me_width and me_height). gpu outlives the object.
  // false with err, the reason after "edges unavailable", such as "no Vulkan loader
  // (vulkan-1.dll)", "the Vulkan loader is older than 1.3.234", "no Vulkan device on the
  // engine's adapter", "this card's driver has no VK_NV_optical_flow", "the optical flow
  // session was refused (VK_...)", "the D3D12 buffers or fences cannot be shared with Vulkan
  // (WHAT)" or "a Vulkan layer came into the engine (PATH)". Whatever was made is given back
  // then, the loader included.
  bool init(Gpu& gpu, UINT frame_w, UINT frame_h, UINT me_w, UINT me_h, std::string& err);

  // What init() found, a line each, in order: the layer filter, the loader, the devices, the
  // queue, the unit's properties, the answers about sharing, the modules the setup brought in.
  // Kept after a refusal too, for --flow-info and the log.
  const std::vector<std::string>& report() const { return report_; }

  // A new frame. frame is the captured frame at frame_w x frame_h, B8G8R8A8_UNORM or
  // R16G16B16A16_FLOAT in linear scRGB at sdr_white, in COMMON and returned to COMMON. With
  // luma, which holds pad_w x pad_h bytes, those bytes go into the luma buffer in place of the
  // luma pass, and frame is not read (--flow-luma-file, a test). read_value is the gpu.queue
  // fence value after which the list that reads the frame is done, for Capture::note_read.
  // Submits and returns. false with err on a failure, after which stopped() is true where the
  // unit had begun the frame.
  bool submit(ID3D12Resource* frame, const uint8_t* luma, UINT64& read_value, std::string& err);

  // Whether the last submit() had the unit compare the frame with the one before, so the flow
  // buffer holds the flow from the frame before to that frame once F2 has reached value().
  bool ready() const { return executed_; }

  // F2's value for the last submit(), 0 before the first.
  UINT64 value() const;

  // Has gpu.queue wait for the last flow before whatever it runs next. true at once before the
  // first submit().
  bool wait_on_queue(std::string& err);

  // Forgets the frames seen, as FrameGen::forget() does, so the next frame is only copied in.
  void forget() { frames_ = 0; executed_ = false; }

  // For the sequence mode's dumps, with the GPU waited for. read_flow() gives the flow of the
  // last frame, int16 pairs, cells_w x cells_h, rows tight, only where ready(). read_luma()
  // gives the luma the unit was given for it, pad_w x pad_h bytes.
  bool read_flow(std::vector<uint8_t>& raw, std::string& err);
  bool read_luma(std::vector<uint8_t>& raw, std::string& err);

  // The times of the last frame, each part valid once that part has finished.
  FlowTimes times() const;

  // The unit stopped after a failure in the middle of a run, see the head of this file.
  bool stopped() const { return stopped_; }

  // For --flow-info, makes a session of the engine's settings at width x height and destroys
  // it. false with the reason in result, which otherwise says it was accepted.
  bool try_session(UINT width, UINT height, std::string& result);

  // The modules the process holds now that it did not hold before the loader was loaded, each
  // with its full path.
  std::vector<std::string> modules_added() const;

  // Waits for the unit's queue and gives everything back. The caller has waited for gpu.queue
  // first. Safe without init and twice.
  void shutdown();

  // The flow buffer, R16G16_SINT pairs as a typed buffer view reads them, cells_w x cells_h,
  // in COMMON. Null without the unit.
  ID3D12Resource* flow_buffer() const;

  UINT frame_w = 0, frame_h = 0;  // the frames
  UINT me_w = 0, me_h = 0;        // the luma, the estimator's picture
  UINT pad_w = 0, pad_h = 0;      // the session's picture, me_w and me_h up to multiples of 8
  UINT cells_w = 0, cells_h = 0;  // the flow, pad_w / 4 x pad_h / 4
  UINT crop_w = 0, crop_h = 0;    // the cells over the picture itself, ceil(me_w / 4) x ceil(me_h / 4)
  float sdr_white = 1.0f;         // a 16-bit frame's SDR white in units of 80 nits, set by the caller

 private:
  struct Impl;
  // A failure in the middle of a frame. F2 is signalled from the CPU to the last value, the unit
  // stops, and err becomes "the optical flow unit stopped (REASON)". Returns false.
  bool stop(std::string& err);

  std::unique_ptr<Impl> impl_;
  std::vector<std::string> report_;
  unsigned long long frames_ = 0;  // frames since the last forget()
  bool executed_ = false;
  bool stopped_ = false;
};

// The unit's last flow as the edge detector reads it, see edges.h.
inline EdgeFlow edge_flow_of(const Flow& flow) {
  EdgeFlow f;
  f.flow = flow.flow_buffer();
  f.cells_w = flow.cells_w;
  f.cells_h = flow.cells_h;
  f.crop_w = flow.crop_w;
  f.crop_h = flow.crop_h;
  f.me_w = flow.me_w;
  f.me_h = flow.me_h;
  return f;
}

// --flow-info prints what the engine finds of the optical flow unit on the monitor under --at
// and --size, or on the primary monitor, a line each on stdout, see common.cpp's usage. Returns
// 0 when the unit can be used and 2 when it is refused.
int run_flow_info(const Options& o);
