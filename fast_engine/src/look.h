// look.h: the Look stage, the engine's own versions of the add-on's reshaping of the
// network's change, see _harnesses\wip-060\research\look-stage-spec.md for the ideas. It
// runs at the work size on the network's input and the last pass's output, after the
// passes and the strength, before the composite, so the composite adds the reshaped change
// to the frame in standard range and in HDR alike, and a stage that changes nothing leaves
// the output byte for byte.
//
// The change is measured per channel in linear light as stops, e = log2(n / p), and the
// output rewritten as n' = n * 2^(t (e' - e)), with t fading to 0 near black where the ratio
// is noise. What it does, in order (look_cs.hlsl):
//   bands      a guided filter of the luma change on the input's log luminance, at half the
//              work size (look_band_cs.hlsl), splits it into a broad band and a fine one:
//              Large-scale tone and Fine detail scale them, and halo suppression takes back
//              fine darkening where a texel is 1 to 3 stops darker than the brightest input
//              near it, its twin on the brighter side of dark things
//   filter     the stabiliser: the change blended over frames with the history read where
//              this texel's content was in the frame before, in place or along the motion
//              estimate, held inside the 3x3 range of the current frame and dropped where
//              the input's luminance moved; Stabilize is time-based (10 to 250 ms), Detail
//              stability a fixed 0.15 a network run
//   limits     soft knees, M tanh(x / M), on brightening, darkening and the colour's size
// Every setting is read from the add-on's section (look_settings.h), so the fullscreen
// picture follows the same values as the windowed one, and profiles carry them.
//
// The history runs on the network's clock: a frame that does not run the network advances
// nothing. It starts afresh when the network's own history does (reset), when the filter's
// kind changes, after a gap of more than a quarter of a second for the stabiliser, and at
// a new work size.
//
// Threads: the main thread only. Everything records on the pipeline's own list and runs on
// gpu.queue; nothing waits here.
#pragma once

#include "common.h"
#include "gpu.h"
#include "look_settings.h"

class Look {
 public:
  Look() = default;
  ~Look() { shutdown(); }
  Look(const Look&) = delete;
  Look& operator=(const Look&) = delete;

  // The shaders, their root signatures and the descriptor heap. gpu outlives the object.
  bool init(Gpu& gpu, std::string& err);

  // The textures for a work size: the half-size band textures, the history pair and a copy
  // of the output. Called with the GPU idle (the pipeline's commit of a work size), and at
  // the first record for a size. The history starts afresh.
  bool resize(UINT w, UINT h, std::string& err);

  // The history starts afresh at the next record.
  void forget();

  // The motion estimate for the next record, or null for none: the vectors as the estimator
  // made them (R16G16_SINT, one a cell, in COMMON, returned to COMMON), the grid, how many
  // work texels one cell covers, and how many work texels one unit of a vector is.
  void set_motion(ID3D12Resource* vectors, UINT vec_w, UINT vec_h, float cell_work_texels, float unit_work_texels);

  // Records the stage on the list for the frame the network has just run on: in is the
  // network's input (NON_PIXEL_SHADER_RESOURCE, kept) and out the last pass's output
  // (UNORDERED_ACCESS, kept, rewritten in place). reset says the network's history restarted
  // this frame. now is now_s(), the stabiliser's clock. With look.active() false nothing is
  // recorded and the history is dropped. The textures of a new work size are made here when
  // needed. false with err when a texture cannot be made.
  bool record(ID3D12GraphicsCommandList* l, ID3D12Resource* in, ID3D12Resource* out, UINT w, UINT h,
              const NrLook& look, bool reset, double now, std::string& err);

  // Whether the last record ran the stage, and the band split with it, for the log.
  bool ran() const { return ran_; }
  bool ran_bands() const { return ran_bands_; }

  void shutdown();

 private:
  bool make_textures(std::string& err);
  void srv(ID3D12Resource* r, DXGI_FORMAT format, UINT slot);
  void uav(ID3D12Resource* r, DXGI_FORMAT format, UINT slot);
  D3D12_GPU_DESCRIPTOR_HANDLE gpu_slot(UINT slot) const;

  Gpu* gpu_ = nullptr;
  UINT w_ = 0, h_ = 0, hw_ = 0, hh_ = 0;
  Microsoft::WRL::ComPtr<ID3D12RootSignature> band_root_, compose_root_;
  Microsoft::WRL::ComPtr<ID3D12PipelineState> band_pso_, compose_pso_;
  Microsoft::WRL::ComPtr<ID3D12DescriptorHeap> heap_;
  UINT heap_step_ = 0;
  // the textures of the work size
  Microsoft::WRL::ComPtr<ID3D12Resource> mom_[2], ext_[2], coef_[2];  // half size, in UNORDERED_ACCESS for life
  Microsoft::WRL::ComPtr<ID3D12Resource> hist_a_[2], hist_b_[2];      // the history pair, states tracked
  D3D12_RESOURCE_STATES hist_state_[2] = {};
  Microsoft::WRL::ComPtr<ID3D12Resource> src_;                        // the output as the network left it
  int ping_ = 0;              // which history pair holds the frame before
  bool history_ = false;      // it holds something to read
  int history_kind_ = 0;      // 1 the stabiliser, 2 detail stability
  double last_now_ = 0.0;     // when the stage last ran
  bool ran_ = false, ran_bands_ = false;
  // the motion for the next record
  ID3D12Resource* vectors_ = nullptr;
  UINT vec_w_ = 0, vec_h_ = 0;
  float vec_cell_ = 1.0f, vec_unit_ = 0.0f;
};
