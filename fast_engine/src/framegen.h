// framegen.h: pictures made between the frames the capture delivers, for a source slower
// than the display. A game at 60 frames a second on a 120 Hz screen leaves every other
// refresh showing the same picture again, and frame generation fills that refresh with a
// picture moved along the motion the card's own motion estimator finds between the last two
// frames.
//
// The estimator is D3D12's, ID3D12VideoMotionEstimator on the video encode queue. It runs on
// the card's video engine beside the shader cores the network uses, and needs no SDK of
// NVIDIA's. It takes NV12 pictures up to 4096x4096 on an RTX 5090, so a capture larger than
// that is estimated at half size, and gives one vector a block of 8x8 texels, in quarter
// texels. Measured in the probe (_harnesses\wip-060\research\flow, 2026-10-15): 2.0 ms a
// frame at 3072x1280, 0.03 ms for the warp, and a pure move of a picture given back exactly.
//
// Two ways to use the motion, chosen by the lens (Options::framegen, "framegen" on stdin):
//   ahead    the last picture carried half a frame on along its motion, shown between the
//            frames the capture delivers. Nothing is delayed: each frame's own picture is
//            shown as it always was, and the made one follows it half a frame later. What
//            the motion uncovers is a guess, the nearest content stretched over it.
//   between  a picture halfway between the last two frames, shown first, and the last
//            frame's own picture half a frame after it. Each frame's picture is thereby
//            shown half a frame later than it was, plus the estimate's time, which is the
//            delay frame generation is known for. The made picture draws on both frames, so
//            nothing is guessed, and the edges of a moving thing are blended.
// Either way one picture is made for each frame, so the rate shown is twice the source's,
// up to the display's. The stats line counts them as generated=N.
//
// How it sits in the loop (main.cpp): before the render of a new frame, estimate() converts
// the frame to NV12 and has the encode queue estimate the motion from the frame before, on
// the GPU and without waiting, since the Look stage's filter and the network's motion vectors
// read the estimate in that render. After the composite is submitted and before its present,
// keep() copies the finished picture into one of two textures of its own. For "between"
// draw_made() then draws the made picture into the back buffer in place of the frame's own,
// and the frame's own is presented half a frame later by a repaint. For "ahead" the loop
// presents draw_made()'s picture half a frame after the frame's own, from a list that waits
// on the GPU for the estimate. A frame that arrives before the made picture is due takes its
// place, and the made one is dropped.
//
// Threads: the main thread only. The estimate runs on the encode queue, held to gpu.queue
// by fences, never waited for on the CPU.
#pragma once

#include "common.h"
#include "gpu.h"
#include "pipeline.h"  // Target

#include <d3d12video.h>

struct FrameGen {
  FrameGen() = default;
  ~FrameGen() { shutdown(); }
  FrameGen(const FrameGen&) = delete;
  FrameGen& operator=(const FrameGen&) = delete;

  // Makes the estimator for width x height pictures, its queue, the shaders and the
  // textures. The two copies of the pictures, in format (the target's: Window::kFormat or
  // kHdrFormat), are made at the first keep(), since the estimate alone serves the Look
  // stage's filter and the network's motion vectors as well. false with err when the card
  // has no motion estimator for NV12 or the picture is outside its sizes, and the loop then
  // keeps the option off. gpu outlives the object.
  bool init(Gpu& gpu, UINT width, UINT height, DXGI_FORMAT format, std::string& err);

  // The pictures are drawn in another format from now on (Window::set_hdr): the copies go,
  // to be made again in it at the next keep(), and the frames seen are forgotten. keep()
  // calls it by itself when the target's format differs from the copies'.
  bool retarget(DXGI_FORMAT format, std::string& err);

  // Forgets the frames seen: the next after_fresh() has nothing to estimate from, so no
  // picture is made for its frame. After a pause, a jump of the crop, a capture started
  // again, a switch of the network's state, anything after which the last two pictures no
  // longer follow one another.
  void forget();

  // A new frame's picture has been drawn into target (submitted, not waited for). Copies
  // the picture, converts the frame to NV12 and, when a frame came before, has the encode
  // queue estimate the motion from it. frame is the captured frame (B8G8R8A8_UNORM, or
  // R16G16B16A16_FLOAT in scRGB), in COMMON and returned to COMMON; target as render() left
  // it, in PRESENT, returned to PRESENT. ready says whether a picture can be made from this
  // frame (there was one before), and read_value is the gpu.queue fence value after which
  // the list that reads the frame is done, for Capture::note_read. Submits and returns.
  bool after_fresh(ID3D12Resource* frame, const Target& target, bool& ready, UINT64& read_value,
                   std::string& err);

  // after_fresh() in two halves, for a loop that wants the estimate before the frame's render,
  // as the Look stage's filter does (look.h): estimate() converts the frame and has the encode
  // queue estimate the motion from the frame before, with ready and read_value as above;
  // keep() copies the finished picture after the render, before the present. The first keep
  // since init() or a new format makes the two copies, both or neither. Where the card cannot
  // make them it returns false with outs_failed set, and the loop gives the estimator up as
  // after a failed init().
  bool estimate(ID3D12Resource* frame, bool& ready, UINT64& read_value, std::string& err);
  bool keep(const Target& target, std::string& err);

  // Has gpu.queue wait for the last estimate before whatever it runs next: before the list that
  // reads the vectors is executed. true at once without an estimate.
  bool wait_estimate_on_queue(std::string& err);

  // The vectors for the Look stage, null without an estimate, and their measure for a work size:
  // one vector a cell of cell_texels(work_w) work texels, in units of unit_texels(work_w) of them.
  ID3D12Resource* vectors_texture() const { return have >= 2 ? vectors.Get() : nullptr; }
  float cell_texels(UINT work_w) const { return me_w ? 8.0f * (float)work_w / (float)me_w : 1.0f; }
  float unit_texels(UINT work_w) const { return me_w ? 0.25f * (float)work_w / (float)me_w : 0.0f; }

  // Draws the made picture into target: mode 1 ahead, the last picture carried on by part of
  // its motion; mode 0 between, part of the way from the picture before to the last. The
  // list waits on the GPU for the estimate; the call submits and returns. target in PRESENT,
  // returned to PRESENT. Only after after_fresh() said ready.
  bool draw_made(const Target& target, int mode, float part, std::string& err);

  // The estimator's picture and its grid of vectors, for the log.
  UINT me_width() const { return me_w; }
  UINT me_height() const { return me_h; }
  UINT vec_width() const { return vec_w; }
  UINT vec_height() const { return vec_h; }
  bool has_coarse() const { return level_count > 0; }
  int levels() const { return level_count; }
  // The coarser estimates' sizes for the log, as "1280x720, 640x360, 320x180"
  std::string level_text() const;

  // The GPU's own time of the last conversion (estimate()'s part on the engine's queue, the
  // NV12 pictures, the coarse ones too) and of the last draw_made(), once those lists have
  // finished on the GPU. The estimate itself runs on the encode queue, which takes no
  // timestamps: the sequence mode times it by the clock.
  double last_prep_ms() const { return gpu ? timer.ms(*gpu, 0, 1) : 0.0; }
  double last_draw_ms() const { return gpu ? timer.ms(*gpu, 2, 3) : 0.0; }
  // The estimates' own time on the encode queue, from timestamp queries there where the
  // queue takes them (probed at init), once the estimate has finished: the fine estimate
  // with its resolve, and the coarse one. 0 where it does not
  double last_estimate_ms() const;
  double last_coarse_estimate_ms() const;
  UINT coarse_width() const { return level_count > 0 ? levels_[0].me_w : 0; }
  UINT coarse_height() const { return level_count > 0 ? levels_[0].me_h : 0; }

  // Waits for the queues and releases everything. Safe without init and twice.
  void shutdown();

  // ---- the parts, open for the self test
  Gpu* gpu = nullptr;
  GpuTimer timer;                 // slots 0 and 1 round the conversion, 2 and 3 round the draw
  UINT w = 0, h = 0;              // the picture
  UINT me_w = 0, me_h = 0;        // the estimator's picture
  UINT vec_w = 0, vec_h = 0;      // the vectors, one a block
  DXGI_FORMAT format = DXGI_FORMAT_B8G8R8A8_UNORM;  // the pictures' and the copies'

  Microsoft::WRL::ComPtr<ID3D12VideoDevice1> video;
  Microsoft::WRL::ComPtr<ID3D12VideoMotionEstimator> estimator;
  Microsoft::WRL::ComPtr<ID3D12VideoMotionVectorHeap> mv_heap;
  Microsoft::WRL::ComPtr<ID3D12CommandQueue> encode_queue;
  Microsoft::WRL::ComPtr<ID3D12CommandAllocator> encode_allocator;
  Microsoft::WRL::ComPtr<ID3D12VideoEncodeCommandList> encode_list;
  Microsoft::WRL::ComPtr<ID3D12Fence> encode_fence;
  HANDLE encode_event = nullptr;
  UINT64 encode_value = 0;        // the last value signalled on the encode queue

  Microsoft::WRL::ComPtr<ID3D12CommandAllocator> prep_allocator, keep_allocator, draw_allocator;
  Microsoft::WRL::ComPtr<ID3D12GraphicsCommandList> prep_list, keep_list, draw_list;
  UINT64 prep_value = 0;          // gpu.queue's fence value after the last prepare list
  UINT64 keep_value = 0;          // after the last copy of a picture
  UINT64 draw_value = 0;          // and after the last draw

  Microsoft::WRL::ComPtr<ID3D12Resource> nv[2];         // NV12, me_w x me_h: the last two frames
  Microsoft::WRL::ComPtr<ID3D12Resource> luma, chroma;  // the conversion's planes, R8 and R8G8
  Microsoft::WRL::ComPtr<ID3D12Resource> planes;        // the buffer they go through into nv
  D3D12_PLACED_SUBRESOURCE_FOOTPRINT plane_fp[2] = {};
  Microsoft::WRL::ComPtr<ID3D12Resource> vectors;       // R16G16_SINT, vec_w x vec_h
  // The coarser estimates: the same again at half the estimator's size, then a quarter, then
  // an eighth, each one's vectors reaching twice as far as the one before and seeing past
  // finer texture, all candidates for the warp where the fine vector fails a texel
  // (gen_ps.hlsl). A level is made while it is 32 texels or more each way and within the
  // estimator's size range; where one cannot be made the finer ones go on alone. Measured
  // offline, see gen_ps.hlsl
  static constexpr int kLevels = 3;
  struct Level {
    UINT me_w = 0, me_h = 0, vec_w = 0, vec_h = 0;
    Microsoft::WRL::ComPtr<ID3D12VideoMotionEstimator> estimator;
    Microsoft::WRL::ComPtr<ID3D12VideoMotionVectorHeap> mv_heap;
    Microsoft::WRL::ComPtr<ID3D12Resource> nv[2], luma, chroma, planes, vectors;
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT plane_fp[2] = {};
  };
  Level levels_[kLevels];
  int level_count = 0;
  // A research switch, set before init() by the sequence mode (--sequence-lab): the most
  // coarser levels made, kLevels unless nocoarse (0), levels1 or levels2 say less, for the
  // cost and the gain of each. The plain warp and the search's dense window were research
  // forms of the shader, measured and gone (the figures are in the research), as a hint
  // from the estimate before (D3D12's pHintMotionVectorHeap), which changed nothing
  int lab_levels = kLevels;
  bool lab_fixed_gate = false;  // fixedgate: the gate at its six levels whatever the noise
  float sdr_white = 1.0f;     // set by the lens: the SDR white level in units of 80 nits, by which
                              // a 16-bit frame is scaled for the estimator (nv12_cs.hlsl)
  bool coarse_on = true;      // set by the lens each frame: frame generation is on, so the coarse
                              // estimate is wanted; the Look stage's filter alone takes the fine one
  bool have_coarse = false;   // the last estimate made the coarser levels' vectors
  void drop_levels(int from); // releases the coarser levels from that one on
  // the estimates' timestamps on the encode queue, 3 slots, see last_estimate_ms()
  Microsoft::WRL::ComPtr<ID3D12QueryHeap> encode_query_heap;
  Microsoft::WRL::ComPtr<ID3D12Resource> encode_stamps;   // readback, mapped for life
  const UINT64* encode_ticks = nullptr;
  UINT64 encode_hz = 0;
  Microsoft::WRL::ComPtr<ID3D12Resource> out[2];        // the last two pictures, in format
  bool outs_failed = false;       // the last keep() could not make the two, see make_outs()
  // the noise pass before the warp, gen_noise_cs.hlsl: its sum and count, and the zeros it
  // starts from each time
  Microsoft::WRL::ComPtr<ID3D12RootSignature> noise_root;
  Microsoft::WRL::ComPtr<ID3D12PipelineState> noise_pso_8, noise_pso_16;   // 8-bit and 16-bit pictures
  Microsoft::WRL::ComPtr<ID3D12Resource> noise_acc, noise_zero;
  int cur = 0;                    // which of nv and out holds the last frame
  int have = 0;                   // frames seen since forget(), 2 at most: 2 means an estimate exists

  Microsoft::WRL::ComPtr<ID3D12RootSignature> nv12_root, gen_root;
  Microsoft::WRL::ComPtr<ID3D12PipelineState> nv12_pso, gen_pso_8, gen_pso_16;
  Microsoft::WRL::ComPtr<ID3D12DescriptorHeap> heap;
  UINT heap_step = 0;

  // LENS_FAST_FRAMEGEN_SHOT=DIR, a test's aid: the first three made pictures are written to
  // DIR as made-N.png beside first-N.png and second-N.png, the pictures they were made
  // from, 8-bit pictures only. The loop stands still for the write.
  std::wstring shot_dir;
  int shots_left = 0;
  Microsoft::WRL::ComPtr<ID3D12Resource> shot_buffer[5];  // the three pictures, the luma, the vectors

 private:
  bool make_outs(std::string& err);
  bool wait_encode(std::string& err);
  void srv(ID3D12Resource* r, DXGI_FORMAT f, UINT slot);
  void shot(const Target& target, ID3D12Resource* first, ID3D12Resource* second);
  D3D12_GPU_DESCRIPTOR_HANDLE gpu_slot(UINT slot) const;
};
