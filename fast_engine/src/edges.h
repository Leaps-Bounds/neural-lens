// edges.h, the edge detector of the cut at moving edges (Edges cut, NRMotionSource 2, see
// look_settings.h and flow.h).
//
// The card's motion estimate holds one vector for each block of 8 by 8 texels, which is the
// motion of a moving thing or that of its background and not both, so along the edge of a
// thing that moves against its background the network reads its last picture from the wrong
// place. This module finds those edges in the optical flow unit's flow of the same two frames
// and makes the zone, the work texels near them, at the size the network works at. Three
// compute passes, recorded on a list the pipeline hands it, see Pipeline::detect_edges.
//   mark     shaders\edge_mark_cs.hlsl. A flow cell is marked where its vector differs from
//            the vector of one of its four neighbours by more than 2 texels of the motion
//            estimator's picture across or down. Each work texel takes the cell under its
//            centre, and the marked work texels inside the interior I are counted. I is the
//            work picture less its outer 16 texels at each side
//   across   shaders\edge_grow_cs.hlsl. The largest mark within 16 texels across
//   down     the same, down, which gives every texel within 16 texels of a marked texel in a
//            square of 33 by 33. Kept inside I, this is the zone. On a frame where the marked
//            texels inside I are more than 4 percent of I, the guard empties the zone
// A fourth pass, the cut, runs in the render list the pipeline hands it, see record_cut().
//   cut      shaders\edge_cut_cs.hlsl. Right after the card's estimate has been resolved into
//            the network's field, every texel of the field inside the zone is written as the
//            vector (0, 0), a constant, so its bits are those of +0.0. The texels outside the
//            zone keep the resolve's bits
//
// The detector reproduces the one the cut was measured with, which ran in floats on the
// optical flow probe's files, bit for bit. The flow's raw pairs are 32nds of a texel, so the
// step of 2 texels is |a - b| > 64 in whole numbers, which is exactly the test in floats, as
// a / 32, b / 32 and their difference are exact there. The cell under a work texel is taken
// in whole numbers as mvec_cs.hlsl takes its block. The square is grown one direction at a
// time, which gives the same texels, and texels outside the picture take no part, as in the
// measurement. The guard is a test in whole numbers too. With C the marked texels inside I,
// C > |I| / 25 in whole numbers (the limit computed on the CPU in 64 bits) is the same as
// 100 C / |I| > 4, the share in percent above 4, for every C and every |I| above 0.
//
// The zone is R8_UINT at the work size, 1 inside and 0 elsewhere, one of the work set's
// textures in the pipeline. Two uints a detect count the marked texels inside I and the zone's
// texels, cleared at the start of its list and read back at its end, see counts().
//
// Threads. The main thread only. Everything is recorded on the pipeline's lists and runs on
// gpu.queue. Nothing waits here.
#pragma once

#include "common.h"
#include "gpu.h"

// The optical flow the detector reads, the unit's flow buffer, see Flow::flow_buffer().
struct EdgeFlow {
  ID3D12Resource* flow = nullptr;  // R16G16_SINT pairs, rows of cells_w, cells_h rows, in COMMON,
                                   // returned to COMMON. 32nds of a texel of the me_w x me_h picture
  UINT cells_w = 0, cells_h = 0;   // the buffer's grid, the padded picture over 4
  UINT crop_w = 0, crop_h = 0;     // the cells over the picture itself, the only ones read
  UINT me_w = 0, me_h = 0;         // the picture the flow was taken of, the motion estimator's
};

// What one detect found, once the GPU has finished its list.
struct EdgeCounts {
  UINT interior = 0;     // |I|, the texels of the interior
  UINT limit = 0;        // the guard's limit, |I| / 25
  UINT marked = 0;       // the marked texels inside I
  bool guarded = false;  // marked > limit, so the zone is empty
  UINT zoned = 0;        // the zone's texels
  UINT w = 0, h = 0;     // the work size it ran at
  double ms = 0.0;       // the three passes on the card's clock
};

class Edges {
 public:
  static constexpr UINT kStep = 64;          // a step of 2 texels, in the flow's 32nds
  static constexpr UINT kWidth = 16;         // the zone reaches this many work texels from a mark,
                                             // edge_grow_cs.hlsl's kRadius
  static constexpr UINT kBorder = 16;        // I leaves this many texels out at each side
  static constexpr UINT kGuardPercent = 4;   // the guard, a share of I in percent
  static constexpr int kContexts = 2;        // the detect lists that can be on the card at once
  static constexpr int kCutContexts = 3;     // the render lists that can be on the card at once,
                                             // the pipeline's draw contexts

  Edges() = default;
  ~Edges() { shutdown(); }
  Edges(const Edges&) = delete;
  Edges& operator=(const Edges&) = delete;

  // The shaders, their root signature, the descriptor heap, the counts' buffers and the
  // timestamps. gpu outlives the object.
  bool init(Gpu& gpu, std::string& err);

  // |I| and the guard's limit for a work size, in 64 bits. Both 0 where I is empty.
  static void interior_of(UINT w, UINT h, UINT& interior, UINT& limit);

  // Records the three passes on the list for detect context index (0 to kContexts - 1), whose
  // descriptors, counts and timestamps are its own: the counts cleared, the mark, the largest
  // across, the largest down with I and the guard, and the counts copied out for counts().
  // mark, across and zone are the work size's R8_UINT textures with unordered access, in
  // NON_PIXEL_SHADER_RESOURCE, returned there. The flow buffer is read from COMMON and
  // returned to COMMON. The caller has had the queue wait for the flow.
  void record(ID3D12GraphicsCommandList* l, int index, const EdgeFlow& flow, ID3D12Resource* mark,
              ID3D12Resource* across, ID3D12Resource* zone, UINT w, UINT h);

  // What the last list recorded for detect context index found. Only meaningful once the GPU
  // has finished that list.
  EdgeCounts counts(int index) const;

  // Records the cut on the render list of draw context index (0 to kCutContexts - 1), whose
  // descriptors and timestamps are its own, right after the resolve of the network's field.
  // Every texel of field inside zone is written as (0, 0). zone is the work size's R8_UINT zone,
  // field the network's R16G16_FLOAT field with unordered access, the same size, both in
  // NON_PIXEL_SHADER_RESOURCE, returned there, which also makes the cut's stores visible to
  // the network's reads that follow.
  void record_cut(ID3D12GraphicsCommandList* l, int index, ID3D12Resource* zone, ID3D12Resource* field, UINT w,
                  UINT h);

  // The cut's time on the card's clock, of the last list recorded for draw context index. Only
  // meaningful once the GPU has finished that list, 0 before the first.
  double cut_ms(int index) const;

  void shutdown();

 private:
  void srv_texture(ID3D12Resource* r, UINT slot);
  void uav_texture(ID3D12Resource* r, UINT slot);
  void uav_counts(UINT slot);
  D3D12_CPU_DESCRIPTOR_HANDLE cpu_slot(UINT slot) const;
  D3D12_GPU_DESCRIPTOR_HANDLE gpu_slot(UINT slot) const;

  Gpu* gpu_ = nullptr;
  Microsoft::WRL::ComPtr<ID3D12RootSignature> root_;
  Microsoft::WRL::ComPtr<ID3D12PipelineState> mark_pso_, grow_pso_, cut_pso_;
  Microsoft::WRL::ComPtr<ID3D12DescriptorHeap> heap_;
  UINT heap_step_ = 0;
  Microsoft::WRL::ComPtr<ID3D12Resource> counts_;  // two uints for each context, 256 bytes apart,
                                                   // in COMMON between lists
  Microsoft::WRL::ComPtr<ID3D12Resource> zeros_;   // an upload buffer of zeros they are cleared from
  Microsoft::WRL::ComPtr<ID3D12Resource> back_;    // where they are copied for the CPU, mapped for life
  const uint8_t* back_bytes_ = nullptr;
  GpuTimer timer_;
  GpuTimer cut_timer_;          // two timestamps for each draw context, round the cut
  EdgeCounts last_[kContexts];  // what each context's last record set up, its counts read later
};
