// capture.h: Windows Graphics Capture of one monitor, kept on the GPU.
//
// The capture has its own D3D11 device, on the same adapter as the engine's D3D12 device,
// and its own thread: the system calls it for every frame. In that call the crop under the
// lens is copied, GPU to GPU, into a "slot": a texture both devices can use. A fence both
// devices share says when the copy is done. The engine then reads the slot from D3D12.
// Nothing comes back to the CPU: the Vulkan presenter's path through the CPU (the frame
// read back, compared and uploaded again) is what this replaces.
//
// Slots, which is the contract that matters:
//   - acquire() hands out the newest complete frame. A frame that arrived and was replaced
//     by a newer one before anyone took it counts as dropped.
//   - The slot handed out by one acquire() stays valid and unchanged through the next
//     acquire() and is given back to the capture by the one after that. So the caller
//     always has two it can rely on, the newest and the one before, which is what the
//     pipeline compares, and it may keep drawing from the older while the newer is new.
//   - A slot's content is complete once the shared fence has reached the value that came
//     with it. acquire() does not wait for that: the reader makes its queue wait
//     (ID3D12CommandQueue::Wait(fence(), value), which Pipeline::ingest does).
//   - Slots are created by the first start() and live until destroy(). stop() and a later
//     start() leave them alone: what was handed out before a pause is still valid and
//     unchanged after it, and the loop repaints from it on resume.
//
// The frame rate limit is kept here, because it acts at the moment a frame arrives, in the
// capture's own thread, see set_limit(). A frame is taken or left out there and then, and
// one that is left out is not copied.
//
// Threads: every function here is called from the main thread. The capture's own thread
// never calls out, it only sets the event. No function throws: the C++/WinRT calls are
// wrapped in try and catch inside capture.cpp, on both threads.
//
// The capture's D3D11 device is its own business. Nothing else in the engine uses D3D11.
#pragma once

#include "common.h"

#include <d3d12.h>

// One captured frame, as the D3D12 device sees it.
struct CaptureFrame {
  ID3D12Resource* texture = nullptr;  // B8G8R8A8_UNORM, W x H: the crop under the lens. In
                                      // COMMON whenever the engine is not using it, and to
                                      // be left in COMMON. Owned by the capture: no Release
  UINT64 fence_value = 0;             // the copy is done when the shared fence reaches this
  double timestamp_s = 0.0;           // the frame's SystemRelativeTime in seconds, which is
                                      // on now_s()'s clock: the composition it belongs to
  double arrived_s = 0.0;             // now_s() when the system delivered it
};

// What happened since the last take_counters(), for the stats line and the lost reasons.
struct CaptureCounters {
  unsigned arrived = 0;   // frames the system delivered that cover the lens, dropped ones
                          // included. A frame equal to the last counts: the capture cannot
                          // know, the pipeline finds out. It shows the capture is alive.
                          // A frame whose copy into its slot failed is not counted
  unsigned dropped = 0;   // of those, never handed out: replaced by a newer one before
                          // acquire() took them, or left out by the frame rate limit
  unsigned copies = 0;    // crops copied into a slot. Without a limit every arrived frame
                          // is one, with a limit only the frames it takes
  unsigned unfit = 0;     // frames too small to cover the lens, which are not copied
  int unfit_w = 0;        // the size of the last such frame
  int unfit_h = 0;
  double callback_ms = 0.0;  // CPU milliseconds spent in the frame callback, summed
  unsigned callbacks = 0;    // how many calls that was: callback_ms / callbacks is the
                             // "capture=" figure of the profile
};

// ---------------------------------------------------------------- the frame rate limit's rule
//
// With a limit a frame is taken or left out at the moment it arrives. It is never kept
// waiting for its turn. A loop that held the newest frame until its turn came presented it
// late by up to a period. Measured on a 120 Hz screen, its present call came 4.5 ms later
// at a limit of 80 than that of a frame taken as it arrives (the meter read -10.4 ms
// against -14.9) and 9.7 ms later at a limit of 60 (-5.0 against -14.7). Every frame a
// newer one replaced while it waited had also been copied at full size for nothing, 37 a
// second at a limit of 80.
//
// The beat runs on the frames' own timestamps. Each is the refresh the compositor made the
// frame for, and lies on the display's refresh grid to 0.002 ms (measured), where the
// moments the callback runs at wander by a millisecond or more. So the same frames are
// taken whatever else the computer is doing.
//
//   turn    the moment the limit last gave a frame its turn
//   early   how far before the next turn a frame is still taken. A quarter of a refresh,
//           for a rate that Windows reports as 119 or 120
//
// A frame is taken when its timestamp has reached turn + period - early. The turn then
// moves on by exactly one period, whatever the frame's own moment, so the beat keeps its
// phase and the frames taken come to the limit exactly. Of frames 1/120 s apart a limit of
// 80 takes two of every three and a limit of 100 five of every six. Two periods or more
// after the last turn, after a still or at the first frame of all, the beat starts again
// from this frame.
constexpr bool limit_takes(double turn, double stamp, double period, double early) {
  return stamp >= turn + period - early;
}

constexpr double limit_next_turn(double turn, double stamp, double period) {
  return stamp - turn >= 2.0 * period ? stamp : turn + period;
}

// Two allowances, in refreshes of the display. kLimitEarly is how far before its turn a
// frame is still taken. kLimitNewer is how much longer than the time between two delivered
// frames a frame before its turn is kept for a newer one to come in its place, see
// Capture::set_limit(). That one is 4 ms at least, since a callback can run a few
// milliseconds late whatever the display's rate.
constexpr double kLimitEarly = 0.25;
constexpr double kLimitNewer = 0.5;
constexpr double kLimitNewerLeast = 0.004;

// How many of the frames of ten seconds the limit takes, when the display runs at hz, the
// frames change at every refresh and the capture's interval is the one the loop asks for.
// Under a limit of half the display's rate or less the system itself delivers only every
// second, third or fourth composition, see capture_interval_ms().
constexpr int limit_taken_in_ten_seconds(double hz, double limit) {
  const int skip = (int)(hz / limit + 0.05);
  const double spacing = (skip < 2 ? 1 : skip) / hz;
  double turn = 0.0;
  int taken = 0;
  for (int i = 0; i * spacing < 10.0; ++i) {
    const double stamp = 5000.0 + i * spacing;
    if (!limit_takes(turn, stamp, 1.0 / limit, kLimitEarly / hz)) continue;
    turn = limit_next_turn(turn, stamp, 1.0 / limit);
    ++taken;
  }
  return taken;
}
// The limit comes out exactly at every pairing of rate and limit, where the frames a second
// that arrive are at least the limit. With the turn moved to half a period before a late
// frame instead, as the loop that held frames did, 50 at 120 Hz gave 480 and 60 at 144 Hz
// gave 576.
static_assert(limit_taken_in_ten_seconds(120.0, 30.0) == 300);
static_assert(limit_taken_in_ten_seconds(120.0, 40.0) == 400);
static_assert(limit_taken_in_ten_seconds(120.0, 50.0) == 500);
static_assert(limit_taken_in_ten_seconds(120.0, 60.0) == 600);
static_assert(limit_taken_in_ten_seconds(120.0, 80.0) == 800);
static_assert(limit_taken_in_ten_seconds(120.0, 100.0) == 1000);
static_assert(limit_taken_in_ten_seconds(119.977, 60.0) == 600);  // the rate this display measures at
static_assert(limit_taken_in_ten_seconds(119.977, 80.0) == 800);
static_assert(limit_taken_in_ten_seconds(60.0, 30.0) == 300);
static_assert(limit_taken_in_ten_seconds(60.0, 40.0) == 400);
static_assert(limit_taken_in_ten_seconds(60.0, 50.0) == 500);
static_assert(limit_taken_in_ten_seconds(100.0, 30.0) == 300);
static_assert(limit_taken_in_ten_seconds(100.0, 60.0) == 600);
static_assert(limit_taken_in_ten_seconds(100.0, 80.0) == 800);
static_assert(limit_taken_in_ten_seconds(144.0, 30.0) == 300);
static_assert(limit_taken_in_ten_seconds(144.0, 60.0) == 600);
static_assert(limit_taken_in_ten_seconds(144.0, 80.0) == 800);
static_assert(limit_taken_in_ten_seconds(144.0, 100.0) == 1000);
static_assert(limit_taken_in_ten_seconds(240.0, 100.0) == 1000);
// The same in numbers a double holds exactly, a period of 3/8 s and an allowance of 1/16.
static_assert(limit_takes(8.0, 8.375, 0.375, 0.0625) && limit_next_turn(8.0, 8.375, 0.375) == 8.375);
static_assert(!limit_takes(8.375, 8.5, 0.375, 0.0625));                  // a quarter early, left out
static_assert(limit_takes(8.375, 8.75, 0.375, 0.0625));                  // on the beat
static_assert(limit_next_turn(8.375, 8.875, 0.375) == 8.75);             // late, the beat goes on
static_assert(limit_next_turn(8.375, 9.125, 0.375) == 9.125);            // two periods on, afresh
static_assert(limit_takes(0.0, 5000.0, 0.375, 0.0625) && limit_next_turn(0.0, 5000.0, 0.375) == 5000.0);

class Capture {
 public:
  Capture();
  ~Capture();  // calls destroy()
  Capture(const Capture&) = delete;
  Capture& operator=(const Capture&) = delete;

  // Starts capturing the monitor. May be called again after stop(): a pause and resume, or
  // a new interval where set_interval() could not change the running session. It returns
  // once the session has started; the first frame comes later, through the event.
  //
  //   device, adapter   the engine's D3D12 device and its adapter's LUID. The capture's
  //                     D3D11 device is made on that adapter, and the slots and the fence
  //                     are shared with that device. Created on the first call and reused
  //                     after: the device and W, H must be the same on every call.
  //   monitor           the monitor to capture, from monitor_under().
  //   W, H              the lens: the size of the crop and of every slot.
  //   crop_x, crop_y    where in the monitor's picture the crop starts. As in the Vulkan
  //                     presenter it is pushed back inside when it would reach over the
  //                     frame's edge, and only a frame smaller than W x H is unfit.
  //   min_interval_ms   the least time between frames the system should deliver, from
  //                     capture_interval_ms(). 0: every composition.
  //   frame_event       an event of the caller's. The capture sets it whenever a new
  //                     complete frame is waiting for acquire(), and whenever the limit
  //                     has kept a frame back, so the caller can ask held_due_s().
  //                     Auto-reset works: the caller calls acquire() after every wake.
  //
  // The cursor is not captured and no border is drawn, as in the Vulkan presenter. Both
  // are switched off on the session before it starts: left on, Windows draws a yellow
  // frame round the whole monitor for as long as the capture runs.
  //
  // false with err: "Windows Graphics Capture is not available", "no D3D11 device on the
  // adapter 0x...", "the monitor cannot be captured 0x...", "sharing the slots failed
  // 0x...". After a failure the capture is stopped, and start may be tried again.
  bool start(ID3D12Device* device, LUID adapter, HMONITOR monitor, int W, int H, int crop_x,
             int crop_y, int min_interval_ms, HANDLE frame_event, std::string& err);

  // Moves the crop, from the next frame the system delivers. Cheap, call it on every "crop"
  // command.
  void set_crop(int crop_x, int crop_y);

  // The least time between frames, changed on the running session, so a new frame rate
  // limit needs no new session. Windows 11 build 26200 takes it both ways. Measured at 120
  // Hz, a session that went from 1 ms to 29 ms delivered 30 frames a second from then on,
  // and set back to 1 ms it delivered every composition again. The call took 0.13 ms and
  // the next frame came 4.6 to 6.1 ms later, where stopping the session and starting
  // another took 20 to 21.5 ms and its first frame came 27 ms after the change. 0 asks for
  // every composition.
  // false when no session runs, when Windows refuses, or when the session does not read
  // back what was asked. The caller then stops the capture and starts it with the interval.
  bool set_interval(int min_interval_ms);

  // The interval the running session has taken, in ms. That is what start() or
  // set_interval() asked for when Windows took it, and 1 when every composition is
  // delivered. 0 when Windows took none (before Windows 11 24H2 the session has no such
  // setting, and every composition is delivered whatever was asked) or when no session runs.
  int interval_ms() const;

  // The frame rate limit, see the rule above. Any time, with or without a session.
  //   period_s        seconds between new pictures. 0 is no limit, every frame is taken
  //   early_s         how far before its turn a frame is still taken
  //   newer_within_s  how long a frame that came before its turn is kept for a newer one
  //                   to come in its place. The loop gives the time between two frames the
  //                   system delivers, and half a refresh on top
  // A frame that comes before its turn is not copied. The capture keeps hold of the
  // system's own frame, which costs nothing, until a newer one arrives. Then it is let go
  // and counts as dropped. When none arrives the source has stopped, and this frame is the
  // picture the screen is left showing, so it must still be shown. held_due_s() says when,
  // and release_held() copies it then. That is the only frame the limit ever delays.
  // A new limit starts the beat afresh, and a frame held at that moment is due at once.
  void set_limit(double period_s, double early_s, double newer_within_s);

  // now_s() from which release_held() will hand the held frame on, the later of its turn
  // and newer_within_s after it came. 0 when no frame is held. The loop puts it into its
  // wait.
  double held_due_s() const;

  // Copies the held frame into a slot when it is due, and uses the turn up. true when a
  // frame is now waiting for acquire(). It never waits for the GPU.
  bool release_held();

  // The frame handed out showed nothing new, Pipeline::ingest found it equal to the one
  // before. The turn it took is given back, so a picture that repeats does not cost the
  // next new one its turn. Nothing happens when a later frame has taken a turn since.
  void turn_back(const CaptureFrame& frame);

  // The newest complete frame not handed out yet. false when there is none, and out is
  // left alone. It never waits, not for a frame and not for the GPU.
  // The frame handed out by the call before this one stays valid, see the slots above;
  // the one before that is the capture's again from now.
  bool acquire(CaptureFrame& out);

  // Whether a complete frame is waiting for acquire(). Does not take it.
  bool pending() const;

  // now_s() when the frame that waits for acquire() was delivered, 0 when none waits. A frame
  // the loop leaves waiting is replaced by the next one to arrive and counts as dropped, and
  // this is how the loop tells the newer one from it.
  double pending_arrived_s() const;

  // The shared fence as the D3D12 device sees it, for ID3D12CommandQueue::Wait. Valid
  // from the first successful start() until destroy(). Null before.
  ID3D12Fence* fence() const;

  // The counts since the last call, which sets them back to nothing. Once a second.
  CaptureCounters take_counters();

  // Whether the system closed the capture, as it does when the displays change. It stays
  // true until the next start(). A stop() of the engine's own does not set it.
  bool closed() const;

  // now_s() at the last frame the system delivered, of any size, or at start() when none
  // has come yet. A frame whose copy into its slot failed does not count: a capture that
  // delivers frames it cannot hand on is as lost as one that delivers none, and the loop
  // finds it by the same rule. A monitor capture delivers a frame only when what the
  // monitor shows has changed (a still desktop gave 2 in 5 s in the capture test). The
  // presents of the engine's own window, which is excluded from capture, bring none while
  // they are shown directly, and one each when they come so seldom that the compositor
  // composes them, twelve a second or fewer in the measurement. So a quiet capture is not
  // by itself a lost one. A new session delivers its first frame at once, which is how the
  // loop tells the two apart.
  double last_arrival_s() const;

  // Whether a session is running: between a successful start() and stop().
  bool running() const;

  // Whether the session took the request to draw no border: IsBorderRequired(false) did
  // not throw and reads back false. Valid after a successful start(), false before. It is
  // what the session says, which is all a program can read: Windows documents that where
  // the user has denied borderless capture the setting succeeds and is ignored, and that
  // shows only on screen. The capture test reports it.
  bool borderless() const;

  // Ends the session: no more frames, no more callbacks once it returns. The slots stay.
  // Safe when not running.
  void stop();

  // stop(), then releases the slots, the fence and the D3D11 device. Before it, the caller
  // has waited for the GPU (Gpu::flush) and no longer uses any frame it was handed.
  void destroy();

 private:
  struct Impl;
  Impl* impl_ = nullptr;
};
