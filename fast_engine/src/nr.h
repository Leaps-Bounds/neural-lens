// nr.h: Neural Rendering (NGX feature 18), called directly through the stack's DLL.
//
// The stack's nvngx_dlssnr.dll is loaded by its full path. In the lens's stack that file is
// the Cost Scaler proxy (MIT), which loads NVIDIA's runtime, nvngx_dlssnr_real.dll, from its
// own folder and answers the runtime's caller check itself, so this engine patches and hooks
// nothing. The runtime is then driven with the engine's own parameter object: no NGX core
// library is loaded. The probe measured this way of calling it on an RTX 5090 at 2560x1053:
// evaluate 3.35 ms on the GPU (median of 300), create 257 ms on the CPU, about 690 MiB of
// video memory.
//
// The proxy must be a plain pass-through here, because the engine scales the picture itself.
// It reads nvngx_dlssnr.ini next to the EXE first and next to its own DLL second, and with
// no ini at all it defaults to rescaling at 0.75 with its hotkeys on. So init() keeps the
// engine's own ini next to lens-fast.exe, see there.
//
// Threads: the main thread, with one exception. prepare() may be called from another
// thread, as long as no other call into this object runs at the same moment, so that two
// calls into the runtime never run at once. There is one Nr in a process, since the runtime
// is initialised once for the device and is not known to take a second initialisation. A
// new work size therefore never starts the runtime again. Its features are created beside
// the ones in use and then take their place, see prepare().
//
// Every call into the DLL is wrapped in a structured exception handler, so a crash inside
// it comes back as a failure with a reason, not as the end of the process.
#pragma once

#include "common.h"
#include "gpu.h"

// The format of the textures handed to evaluate(), input and output alike. It is what the
// probe's reference picture was made with. R16G16B16A16_FLOAT also ran there, no faster
// (3.36 ms against 3.35) and on more memory (712 MiB against 690).
constexpr DXGI_FORMAT kNrFormat = DXGI_FORMAT_R8G8B8A8_UNORM;

// The most passes, and so features, one Nr holds, is kNrMaxPasses in common.h.

class Nr {
 public:
  Nr();
  ~Nr();  // calls shutdown()
  Nr(const Nr&) = delete;
  Nr& operator=(const Nr&) = delete;

  // Loads the runtime, initialises it for gpu's device and creates one feature for each
  // pass, all at work_w x work_h. It blocks while the features are created (257 ms for one
  // in the probe) and waits for the GPU before it returns.
  //
  //   stack_dir  where nvngx_dlssnr.dll is, with nvngx_dlssnr_real.dll beside it. Absolute.
  //   data_dir   a writable folder for the runtime's logs. It is created when missing.
  //   passes     1 to kNrMaxPasses. Each pass has its own feature, so each keeps its own
  //              history, and the passes are chained by the caller: the output of one is
  //              the input of the next. With settings.shared, and two passes or more,
  //              only the first pass's feature is made and every pass evaluates it, each
  //              with its own values, so one history serves them all, see NrPasses.
  //   settings   each pass's own, used from the first evaluate on: pass p evaluates with
  //              settings.pass[p]. settings.preset is the model preset the features are
  //              created with (DLSSNR.Hint.Render.Preset).
  //
  // The private proxy ini: before the DLL is loaded, init makes sure that
  // <folder of this exe>\nvngx_dlssnr.ini exists and holds EnableProxy = 0 and
  // EnableHotkeys = 0 in [DLSSNR_Proxy]. It is written only when missing or different, from
  // the stack's ini as the base so the other keys stay as the lens set them. The stack's
  // own ini is never written. When this exe sits in the stack folder itself the two are the
  // same file and init leaves it alone: there the lens sets EnableProxy before it starts
  // the engine. Hotkeys off matters as much as the proxy off: with them on, Ctrl+Alt+Space
  // switches the proxy on and writes that into the ini.
  //
  // Zero motion vectors and zero depth are part of this object. They are two textures of
  // one texel each (R16G16_FLOAT and R32_FLOAT), cleared once, which every evaluate hands
  // over with their subrects set to that one texel and the motion scale set to the work
  // size. The network's output is the same, byte for byte, as with two zero textures of the
  // work size, which the self test's reference pictures were made with, and the two of one
  // texel serve every work size.
  //
  // false with err, which says which step failed and the runtime's result where there is
  // one: "nvngx_dlssnr.dll not found in ...", "the adapter is not an NVIDIA card",
  // "Init_Ext failed 0xBAD00002 platform error", "CreateFeature raised an exception".
  // After a failure the object is as after shutdown().
  bool init(Gpu& gpu, const std::wstring& stack_dir, const std::wstring& data_dir, UINT work_w,
            UINT work_h, int passes, const NrPasses& settings, std::string& err);

  // Whether init succeeded and shutdown has not been called.
  bool ready() const;

  // Records one pass on the caller's list. Nothing runs until the caller executes the list.
  //
  //   list    open, a direct list of gpu's device, to be run on gpu's queue.
  //   pass    0 to passes - 1: which feature, and which pass's values. In the shared mode
  //           the features in use were made with, every pass runs the first feature.
  //   input   work_w x work_h, kNrFormat, in NON_PIXEL_SHADER_RESOURCE. Left in that state.
  //   output  work_w x work_h, kNrFormat, created with ALLOW_UNORDERED_ACCESS, in
  //           UNORDERED_ACCESS. Left in that state. It must not be the input.
  //   reset   true tells the network to drop its history: the first picture, after a pause,
  //           and whenever the new picture does not follow from the last one.
  //
  // AFTER THIS CALL THE LIST'S DESCRIPTOR HEAPS, ROOT SIGNATURES AND PIPELINE STATE ARE
  // UNDEFINED: the runtime sets its own and does not put the caller's back. Set every one
  // of them again before recording anything else that needs them. Resource states other
  // than the two named above are not touched.
  //
  // false with err when the runtime refuses or raises. The list may then hold part of the
  // runtime's commands: do not execute it, reset it.
  bool evaluate(ID3D12GraphicsCommandList* list, int pass, ID3D12Resource* input,
                ID3D12Resource* output, bool reset, std::string& err);

  // New settings, each pass's own, used from the next evaluate on. Nothing is created
  // again: the values a pass is steered by are read by the runtime at every evaluate. It
  // does not reset the history itself, the caller passes reset when it wants a clean
  // start. The preset and the shared state are taken when features are next made, by
  // prepare(): until then the features in use run as they were made, so a caller that
  // changes either follows with a prepare() at the work size in use and use_prepared().
  // needs_remake() says whether the features in use differ from the settings in that.
  void set_settings(const NrPasses& settings);
  bool needs_remake() const;

  // The state the features in use were made with: whether every pass runs the first
  // pass's feature, and the model preset. false and 0 before init.
  bool shared() const;
  unsigned preset() const;

  // Another work size, in two steps, so that the features in use go on working until the
  // new ones are there. The same size as the one in use is allowed: that makes the
  // features again with the settings' preset and shared state.
  //
  // prepare() creates one feature for each pass at work_w x work_h, or the first pass's
  // alone in the shared mode, beside the ones in use. It blocks for the creation, on an
  // RTX 5090 once a process has made its first 118 to 135 ms a pass at a work size up to
  // 2560x1440, 143 to 154 ms a pass at Full at 6144x2560, and once 226 ms a pass for
  // Balanced right after Full there, and waits for the GPU through a fence of its own, so
  // it may run on a thread that is not the drawing one.
  // Until it returns the caller makes no other call into this object. The features in use
  // are not touched, and evaluate() keeps using them afterwards. A second prepare() before
  // use_prepared() releases what the first one made.
  // false with err, as init. The features in use then stay as they are and nothing is
  // prepared.
  bool prepare(UINT work_w, UINT work_h, std::string& err);

  // The prepared features become the ones evaluate() uses, and the ones used until now are
  // released. The caller has waited for the GPU first (Gpu::flush), since no list that
  // evaluates the old ones may still be running. Every pass's next evaluate must be given
  // reset, since a new feature has no history. Nothing happens when nothing is prepared.
  void use_prepared();

  // Releases what prepare() made without using it.
  void drop_prepared();

  // The work size evaluate() runs at, and the passes init was given.
  UINT work_width() const;
  UINT work_height() const;
  int passes() const;

  // CPU milliseconds the feature creation took, all passes together, for the log. create_ms
  // is init's and prepare_ms the last prepare()'s.
  double create_ms() const;
  double prepare_ms() const;

  // Releases the features and shuts the runtime down for the device. The caller has waited
  // for the GPU first (Gpu::flush): no list that evaluates may still be running. The DLLs
  // stay loaded on purpose and the process is expected to leave through leave_now(), since
  // the runtime's unload code is not known to be safe. Safe to call twice and without init.
  void shutdown();

 private:
  struct Impl;
  Impl* impl_ = nullptr;
};
