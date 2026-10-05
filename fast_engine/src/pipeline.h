// pipeline.h: the GPU work for one captured frame.
//
//   ingest   compute: the crop is area-downscaled to the work size into the network's
//            input, and compared with the frame before it, every texel. The call waits
//            for the GPU and says whether anything changed.
//   render   the network (one feature a pass, chained), then the residual composite drawn
//            as one full-screen triangle straight into the target:
//                out = native + (bilinear(network output) - bilinear(network input))
//            which keeps the original's detail, because only what the network changed is
//            scaled up. With the network off it is a plain copy of native. It submits and
//            does not wait.
//   repaint  the composite again from what the last render left, without the network.
//   joined   ingest and render in one command list that is submitted and not waited for,
//            for a source whose frames keep changing: the answer of the comparison comes
//            back later, see render_joined() and take_flag().
//
// The work size has its own scale across and its own down. The downscale's footprints and
// weights and the composite's sample positions are computed for each axis by itself, so a
// work size squeezed in height, as 2560x896 for a 6144x2526 picture, needs nothing special.
// The work size can change while the pipeline runs, see prepare_work().
//
// Why the comparison is here and exact: the engine's window is excluded from capture, so
// every present of its own comes back from the capture as a frame identical to the last.
// Such a frame must cost as little as possible and must never run the network, or the
// engine would feed itself at the display's rate for ever over a still screen.
//
// Why the composite is drawn and not computed: swapchain back buffers cannot be unordered
// access views, and drawing into them saves copying a whole frame, 62 MB at 6144x2526.
//
// The pipeline keeps no copy of the native picture. It remembers WHICH texture holds it:
// the one last given to render(), and after an ingest() that found no change the new one,
// which holds the same picture. That is what lets the capture hand its slots round (see
// capture.h: a slot stays valid until the acquire after the next). So:
//   - after ingest() says changed, call render() with that frame before any repaint() and
//     before the next Capture::acquire(). Until then repaint() would mix the new input
//     with the old output.
//   - a texture given to ingest() or render() must stay valid and unchanged until the
//     pipeline has been given a newer one and the GPU has finished with the older: the
//     capture's rule gives exactly that, since every ingest() waits for the GPU. A
//     render_joined() waits for nothing, so its caller waits for the draw before it takes
//     the next frame, and tells the capture which lists read which slot (note_read).
//
// Frames in 16-bit floats, which the capture delivers for a monitor with Windows HDR on
// (capture.h, fp16): ingest() first turns such a frame into an 8-bit one, with the
// conversion shader (shaders\convert_cs.hlsl: scaled by the SDR white level, clipped,
// sRGB-encoded), into one of two textures of the pipeline's own, and everything after
// works on that: the downscale, the composite and the shot's "before". The comparison
// alone reads the two 16-bit frames themselves, bit for bit, since the conversions are
// clipped at the SDR white level and a change in a highlight above it would not show in
// them, while the picture drawn carries it. Two textures are enough: the one the previous
// ingest() converted is the frame before, and the one from two ingests back is free, since
// every draw from it was submitted before the previous ingest() waited for the GPU. An
// 8-bit frame goes the way it always did, untouched. The pipeline tells the two apart by
// the frame's own format, so a caller passes frames as the capture hands them.
//
// A target in 16-bit floats (Target::format R16G16B16A16_FLOAT, the swapchain of a monitor
// with Windows HDR on, in scRGB): the composite is then drawn by a second shader
// (shaders\composite_hdr_ps.hlsl) in linear light, the 16-bit frame behind the converted
// one plus the network's change taken back to linear and scaled by the SDR white level, so
// the picture is shown in HDR as the desktop is, highlights kept. The 16-bit frame is read
// at draw time, so the capture's slot rule covers it as it covers the frame itself. The
// shot's "after" and the probe then read the 16-bit target back and render it to 8 bits as
// Windows shows standard range content, scaled by the SDR white level and clipped, and
// read_target_raw() gives the 16-bit picture itself. An 8-bit target is drawn as it always
// was, by the same shader on the same textures.
//
// Threads: the main thread only. Everything runs on gpu.queue.
#pragma once

#include "common.h"
#include "gpu.h"

// Somewhere to draw the finished picture: a swapchain back buffer (window.h) or, in the
// self test, a texture of the test's own.
struct Target {
  ID3D12Resource* texture = nullptr;     // B8G8R8A8_UNORM or R16G16B16A16_FLOAT, ALLOW_RENDER_TARGET
  D3D12_CPU_DESCRIPTOR_HANDLE rtv = {};  // a render target view of it, made by its owner
  UINT width = 0;                        // the same as the pipeline's, see PipelineDesc
  UINT height = 0;
  DXGI_FORMAT format = DXGI_FORMAT_B8G8R8A8_UNORM;  // the texture's, one of the two above
};

// What the HDR composite does with the network's change where the original is above SDR
// white, where the network saw a clipped input. Fade is the engine's choice, the other two
// are for tests, see composite_hdr_ps.hlsl.
enum class HdrAbove { Pass = 0, Fade = 1, Clip = 2 };

struct PipelineDesc {
  UINT width = 0;    // the picture: the crop's size and the target's, --size
  UINT height = 0;
  UINT work_w = 0;   // the size the network works at, from work_plan(). No side larger than
  UINT work_h = 0;   // the picture's
  int passes = 1;    // 1 to 8
  std::wstring stack_dir;  // handed to Nr::init
  std::wstring data_dir;
  NrPasses settings;       // each pass's own, see common.h
  bool nr_on = true;       // the state "nr 1|0" switches later
  // false: the runtime is never loaded and every picture is the plain copy. For tests of
  // the capture, the window and the loop on their own. set_nr(true) then does nothing.
  bool load_network = true;
};

// GPU milliseconds of one frame the GPU has finished, from timestamp queries, for the
// profile on the stats line. 0 for a stage that did not run in that frame.
struct StageTimes {
  double ingest_ms = 0.0;     // downscale and comparison, without the conversion of a
                              // 16-bit frame, which last_convert_ms() gives for an
                              // ingest() and convert_ms below for a joined draw
  double nr_ms = 0.0;         // all passes
  double composite_ms = 0.0;  // the draw into the target, and the readback copies if any
  double convert_ms = 0.0;    // of a joined draw, the conversion of a 16-bit frame
  bool joined = false;        // the frame was a render_joined(): ingest_ms and convert_ms
                              // are its own list's, which no last_ingest_ms() reported
  bool ran_network = false;   // the network ran in it, so nr_ms is a run's time
  UINT64 sequence = 0;        // the draw's number, 1 up, as last_draw_sequence() gave it at
                              // its submission, for the trace
  UINT64 ticks[5] = {};       // the draw's five timestamps as the card's clock counts them:
                              // the list's start, after the conversion, the draw's start,
                              // after the network, the end. For the trace, with the queue's
                              // clock calibration (Gpu::clock_pair)
};

class Pipeline {
 public:
  // The picture is cut into 16 by 16 tiles for the comparison's answer, see
  // add_changed_tiles() and take_flag().
  static constexpr int kTilesAcross = 16;
  static constexpr int kTiles = kTilesAcross * kTilesAcross;

  Pipeline();
  ~Pipeline();  // calls shutdown()
  Pipeline(const Pipeline&) = delete;
  Pipeline& operator=(const Pipeline&) = delete;

  // Creates the shaders' pipeline states, the work size textures and, unless
  // desc.load_network is false, the network (Nr::init: it blocks for the feature creation,
  // 257 ms a pass in the probe). gpu must outlive the pipeline.
  // false with err: the step and the reason, Nr's own reason when it is the network.
  bool init(Gpu& gpu, const PipelineDesc& desc, std::string& err);

  // A new frame has arrived: downscale it and find out whether it differs from the last.
  //
  //   cur    the new frame: B8G8R8A8_UNORM, width x height, in COMMON. Returned to COMMON.
  //          Or R16G16B16A16_FLOAT in scRGB, see the top of the file: it is converted
  //          first, and the frame before must then be the one the previous ingest()
  //          converted, or null.
  //   prev   the frame before it, same kind, in COMMON, returned to COMMON. Null means
  //          there is none (the first frame, or the caller wants this one drawn whatever
  //          it holds): changed is then true and nothing is compared.
  //   shared_fence, value
  //          the queue waits for this fence to reach value before it reads cur: that is
  //          the capture's copy into the slot finishing on its own device. Null fence:
  //          nothing to wait for (the self test's own textures).
  //   changed  true when any texel of cur differs from prev in any channel.
  //
  // The call BLOCKS until the GPU has run the work and the answer is read, a few
  // milliseconds at most, and gives up after 2 s with err. Since the queue runs in order,
  // everything submitted before, a render() included, is finished too when it returns.
  //
  // After changed == false: the pipeline now draws repaints from cur, the caller counts
  // the frame as skipped and does nothing more. After changed == true: the network's
  // input holds the downscaled cur, and render(cur, ...) must follow.
  //
  // false with err: the wait timed out or the device is removed. changed is then unset.
  bool ingest(ID3D12Resource* cur, ID3D12Resource* prev, ID3D12Fence* shared_fence, UINT64 value,
              bool& changed, std::string& err);

  // Draws the new picture: the network on the input ingest() prepared, then the composite
  // into the target. It submits to the queue and RETURNS WITHOUT WAITING, so the caller
  // can present at once: the present is queued behind the draw.
  //
  //   cur     the frame ingest() was just given and reported as changed. COMMON before and
  //           after. The pipeline keeps drawing repaints from it.
  //   target  in PRESENT (the same as COMMON), which is how a back buffer is between
  //           frames. Returned to PRESENT. Every texel is written, nothing is cleared.
  //   reset   the network drops its history for this picture. The pipeline also resets by
  //           itself on the first render after init, after set_nr(true) and after a
  //           set_settings() that changed something, so the caller passes true only for
  //           what the pipeline cannot know: the first picture after a pause, or after
  //           the crop jumped.
  //   keep_copy  also copy the native frame and the finished target into readback
  //           buffers, for read_native() and read_target(). A shot or a probe asks for
  //           it. The buffers are created at the first use, 62 MB each at 6144x2526.
  //
  // It may block for a moment when the frame before it is still on the GPU, never longer
  // than Gpu::wait's timeout.
  // false with err: the network refused (Nr's reason), or the device is removed. The
  // target then holds nothing to present.
  bool render(ID3D12Resource* cur, const Target& target, bool reset, bool keep_copy,
              std::string& err);

  // Draws the last picture again into the target, from the native frame and the network's
  // input and output as the last render() left them. The network does not run: a repeated
  // present costs one draw. Used for the heartbeat, for the first presents after a resume,
  // for a shot or probe over a still, and for the second back buffer.
  // target and keep_copy as in render(). Submits and returns without waiting.
  // false with err "nothing rendered yet" before the first render(), or as render().
  bool repaint(const Target& target, bool keep_copy, std::string& err);

  // The ingest and the render of a new frame in ONE command list, submitted at once and not
  // waited for: the conversion of a 16-bit frame, the comparison and the downscale, the
  // network and the composite into the target, in that order, behind the queue's wait for
  // the capture's copy. The arguments are ingest()'s and render()'s. The frame is drawn
  // whether or not it differs from the one before: whether it did is learned afterwards,
  // from take_flag(), with the tiles that changed. An unchanged frame drawn this way has
  // cost a run of the network, which is what the caller takes it for only while frames keep
  // changing, see main.cpp.
  //
  // Why: under a game that keeps the card busy every list submitted waits for a gap in the
  // game's work. ingest() and render() are two such lists with a wait on the CPU between
  // them, and this is one. Under a window of a test's own that kept the card busy from the
  // foreground the one list took as long to get through the card as the two, or longer, so
  // the loop uses it only when LENS_FAST_JOIN asks, see kJoinAfter in main.cpp.
  //
  // The two frames stay valid and unchanged until the GPU has finished this list, as for
  // ingest(): the caller tells the capture the fence value (Capture::note_read), and it
  // waits for the draw (wait_drawn) before it takes the next frame.
  // false with err as ingest() and render() give it. The pipeline's state is then as before
  // the call, and the target holds nothing to present.
  bool render_joined(ID3D12Resource* cur, ID3D12Resource* prev, ID3D12Fence* shared_fence, UINT64 value,
                     const Target& target, bool reset, bool keep_copy, std::string& err);

  // The answer of a render_joined() the GPU has finished, oldest first and each once: true
  // with changed as ingest() would have said it, and tiles[i] set to 1 for every tile that
  // holds a texel that differs, as add_changed_tiles() sets them, the others left as they
  // are. false when every finished joined draw's answer has been taken. Cheap: a read of the
  // fence and of memory already written.
  bool take_flag(bool& changed, uint8_t tiles[kTiles]);

  // The GPU times of the draws the GPU has finished, oldest first and each once: true with t
  // filled in for one of them, false when every finished draw's times have been taken. A
  // draw is a render(), a repaint() or a render_joined(). For a render, ingest_ms is the
  // ingest() that led to it, which last_ingest_ms() reported when it returned. For a joined
  // draw it is the list's own ingest, and t.joined says so. For a repaint it is 0, as nr_ms
  // is. Cheap, as take_flag().
  bool take_times(StageTimes& t);

  // Whether take_times() will be called. Off, the GPU times of finished draws are not
  // queued, since nothing would take them. Off until set. On, the queue keeps the times of
  // the last kTimesKept finished draws at most, so a caller that stops taking them for a
  // while loses the oldest and nothing grows.
  void keep_times(bool on);
  static constexpr int kTimesKept = 12;

  // For the trace: the number of the draw submitted last (1 up, 0 before any), which its
  // StageTimes carry as sequence, and the three timestamps of the last ingest() as the card's
  // clock counts them (its start, after the conversion, its end), valid once ingest() has
  // returned, since it waits for its list.
  UINT64 last_draw_sequence() const;
  void last_ingest_ticks(UINT64 out[3]) const;

  // BLOCKS until the GPU has finished the last render(), repaint() or render_joined(), and
  // returns at once when it has. The loop calls it before it takes the next frame from the capture: the
  // frame taken is then the newest one there is at the moment the card can start on it,
  // where a frame taken while the last draw still runs waits behind that draw in ingest()
  // and is older by as long as the draw took. Gives up after Gpu::wait's timeout with err,
  // as ingest() does.
  bool wait_drawn(std::string& err);

  // Makes the two readback buffers a draw with keep_copy needs, when they are not there
  // yet, the target's for a target of that format. The caller asks before such a draw:
  // false with err means they cannot be made, 62 MB each at 6144x2526 and twice that for a
  // 16-bit target's, and the draw then goes without keep_copy, so a screenshot fails and
  // the picture goes on. After true, keep_copy cannot fail a draw for want of them.
  bool prepare_copies(DXGI_FORMAT target_format, std::string& err);

  // The pictures kept by the last render() or repaint() with keep_copy, as tight RGB8:
  // width * height * 3 bytes, top row first, no padding. read_native() is the capture as
  // it came (the shot's "before"), or for a 16-bit frame the 8-bit frame made of it, and
  // read_target() what was drawn (its "after"). A 16-bit target is rendered to 8 bits as
  // Windows shows standard range content on that monitor: scaled by the SDR white level,
  // clipped, sRGB-encoded.
  // They BLOCK until the GPU has finished that frame. At 6144x2526 each is 46.5 MB.
  // false with err "no copy was kept" when the last frame was drawn without keep_copy.
  bool read_native(std::vector<uint8_t>& rgb, std::string& err);
  bool read_target(std::vector<uint8_t>& rgb, std::string& err);

  // For tests of the conversion. With keep_raw(true) a draw with keep_copy also copies the
  // frame as the capture handed it when that is a 16-bit frame, into a third readback
  // buffer, 8 bytes a texel, made at the first use. read_raw() gives it as tight
  // R16G16B16A16_FLOAT: width * height * 4 halves, top row first. false with err "no raw
  // frame was kept" after a draw without keep_copy, without keep_raw, or of an 8-bit frame.
  void keep_raw(bool on);
  bool read_raw(std::vector<uint16_t>& rgba, std::string& err);

  // The target as drawn when it is a 16-bit one, the same layout as read_raw(): the
  // picture in scRGB before any rendering to 8 bits. false with err "no copy was kept"
  // after a draw without keep_copy, and "the target is not a 16-bit one" for an 8-bit one.
  bool read_target_raw(std::vector<uint16_t>& rgba, std::string& err);

  // The SDR white level the conversion of a 16-bit frame scales by, in units of 80 nits:
  // 3.0 for 240 nits. Values below 1 count as 1. From the next ingest(). Until the first
  // call it is 1. The HDR composite and the rendering of a 16-bit target to 8 bits use it
  // from the next draw.
  void set_sdr_white(double units);

  // What the HDR composite does with the network's change above SDR white, from the next
  // draw. Fade until set, see composite_hdr_ps.hlsl for why.
  void set_hdr_above(HdrAbove above);

  // Forgets every frame it was given: the native picture, the converted frames and the
  // kept copies. For the caller that starts its capture again with the other format, whose
  // old slots go, see Capture::start(): it has waited for the GPU (Gpu::flush) first.
  // Afterwards repaint() fails with "nothing rendered yet" until the next render(), and the
  // converted textures are made again at the next 16-bit frame. The network's state is
  // left alone, and the next render() resets its history as after a pause.
  void drop_frames();

  // The targets drawn into from now on have another format than before (Window::set_hdr):
  // the kept copies go, and the target's readback buffer is made again at the next draw
  // with keep_copy, in the new layout. The caller has waited for the GPU (Gpu::flush)
  // first. A draw into a target of the other format without this call fails with err.
  void drop_target_copies();

  // The same picture as read_target(), every 4th texel each way starting at the top left:
  // w = (width + 3) / 4, h = (height + 3) / 4, tight RGB8. For the probe, which compares
  // consecutive pictures and reads a sixteenth of the bytes this way.
  bool read_target_sparse(std::vector<uint8_t>& rgb, UINT& w, UINT& h, std::string& err);

  // The network on or off, from the next render(). Off: render() draws the native frame
  // unchanged and the network does not run. On again: the next render() resets its history.
  // A repaint() right after the switch still shows the picture as it was last rendered:
  // the caller follows the switch with a render of the current frame (ingest with prev
  // null) to show the change at once.
  void set_nr(bool on);
  bool nr_on() const;

  // New settings for the network, each pass's own, from the next render(). When they differ
  // from the current ones, over the passes in use, the next render() resets the history.
  void set_settings(const NrPasses& settings);
  // The same values for every pass.
  void set_settings(const NrSettings& settings);

  // Whether a render() runs the network: it is loaded, it is switched on, the strength of
  // one of its passes at least, NRIntensity or a pass's own, is above 0, and no other work
  // size is being made (begin_work). At a strength of 0 the network gives back its input and
  // still takes its full time, 3.35 ms at 2560x1053, so with every pass at 0 the pipeline
  // draws the native frame as it does with the network off, which is the same picture byte
  // for byte. A pass at 0 among others that are not still runs, and gives its input on.
  bool network_runs() const;

  // For the self test. With true the network runs at a strength of 0 as well, which is how
  // the test shows that it gives its input back there.
  void set_run_at_zero(bool run);

  // Another work size while the pipeline runs, in two steps: made, then put in use.
  //
  // What the new size needs is made beside what is in use: the network's input and output
  // textures, the downscale's weights and the network's features (Nr::prepare). The
  // features take long, 118 to 135 ms a pass on an RTX 5090, and there are two ways to make
  // them. No side of the work size may be larger than the picture's.
  //
  // begin_work() makes the textures and the weights at once and the features on a thread of
  // its own, and returns. Until they are made the pipeline goes on drawing, but makes no
  // call into the runtime, since two calls into it must never run at once. ingest() only
  // compares, and render() draws the new native frame with the network's change as the last
  // render before begin_work() left it. Over a picture that moves, that change is a few
  // frames old where it is shown, for as long as the features take. network_runs() is false
  // meanwhile. work_state() says how far it is, and work_event() is set when it is done.
  //   work_state: 0 nothing is being made, 1 the features are still being made, 2 they are
  //   made and commit_work() is due, 3 they could not be made (err says why, once. The
  //   pipeline is then as before begin_work(), and the next call returns 0).
  // false with err from begin_work means nothing has changed and nothing is being made.
  //
  // prepare_work() does the same on the calling thread and BLOCKS until the features are
  // made. After true, commit_work() is due. false with err means nothing has changed.
  //
  // commit_work() puts the size that was made in use. It waits for the GPU to finish
  // everything submitted so far, then releases the old features and textures. From here on:
  //   - ingest() downscales to the new size, and the next render() resets the network's
  //     history, since the new features have none
  //   - the network's textures hold nothing yet, so a repaint() before that render draws
  //     the native frame alone. The caller follows the commit with a render of the current
  //     frame (ingest with prev null), as after set_nr().
  // false with err when nothing was made, the wait timed out or the device is removed.
  //
  // The runtime gives the video memory of the features that were replaced back about ten
  // seconds after the switch, from inside the first call made to it after that time, so a
  // render() that runs the network has to come. Measured without a window, with frames
  // running: 847 MiB in use at 2560x896, up to 1371 MiB while switching between 2560x1024
  // and 1536x640 every third of a second, and 847 MiB again 10.1 s after the last switch.
  // With repaints alone for 15 s after a switch it stayed at 1196 MiB, and the first frame
  // then brought it to 814, the level of the size in use.
  bool begin_work(UINT work_w, UINT work_h, std::string& err);
  int work_state(std::string& err);
  HANDLE work_event() const;
  bool prepare_work(UINT work_w, UINT work_h, std::string& err);
  bool commit_work(std::string& err);

  // The work size in use.
  UINT work_width() const;
  UINT work_height() const;

  // CPU milliseconds the feature creation took in the last prepare_work(), all passes
  // together, 0 without a network.
  double prepare_ms() const;

  // GPU times of the last finished frame. Cheap: it reads numbers already resolved.
  // A frame is a render() or a repaint(). For a render, ingest_ms is the ingest() that led
  // to it. For a repaint, ingest_ms and nr_ms are 0.
  StageTimes times() const;

  // GPU milliseconds of the most recent ingest(), which has always finished when it
  // returns. Also of one that found no change: times() never shows those, since no frame
  // follows them, and they are the ones that come back after every present.
  double last_ingest_ms() const;
  // Of that ingest, the GPU milliseconds of the conversion of a 16-bit frame, 0 for an
  // 8-bit frame. Not part of last_ingest_ms().
  double last_convert_ms() const;
  // Under LENS_FAST_SPLIT_WAIT=1, how long the most recent ingest() waited on the CPU for the
  // capture's copy before it went on to the queue, 0 otherwise.
  double last_copy_wait_ms() const;

  // Where the most recent ingest() found the frame changed: the picture is cut into 16 by
  // 16 tiles, and tiles[i] is set to 1 for every tile that holds a texel that differs, row
  // by row from the top left. The others are left as they are, so the caller can gather
  // several frames in one array. Every tile is set when nothing was compared (prev null).
  // It tells a caret that blinks, one tile, from a page that scrolled. kTiles is declared at
  // the top of the class.
  void add_changed_tiles(uint8_t tiles[kTiles]) const;

  // CPU milliseconds the creation of the network's features took in init(), all passes
  // together, 0 without a network. For the log and the self test.
  double network_create_ms() const;

  // The network's input (output false) or what its last pass made of it (output true), as
  // tight RGB8, w x h being the work size. For the self test, which saves both as pictures.
  // It BLOCKS until the GPU has finished everything submitted so far.
  // false with err "there is no network" when none was loaded.
  bool read_work(bool output, std::vector<uint8_t>& rgb, UINT& w, UINT& h, std::string& err);

  // Releases everything, the network included. The caller has waited for the GPU first
  // (Gpu::flush). Safe to call twice and without init.
  void shutdown();

 private:
  struct Impl;
  Impl* impl_ = nullptr;
};
