// main.cpp: start-up, the loop, the stats line and the way out.
//
// The loop is lens_presenter.py's (its lines 593 to 827) carried over to this engine's frame
// flow. One turn:
//
//   mark the watchdog, answer the window's messages, take every command from the lens
//   a frame is waiting:
//       the last draw is waited for, so the frame taken is the newest, see take_frame()
//       Capture::acquire, then Pipeline::ingest, which says whether it differs from the last
//       unchanged: counted as skipped, nothing more
//       changed:   Pipeline::render straight into the back buffer, Window::present: "new"
//       with LENS_FAST_JOIN set, while the frames keep changing the ingest and the render
//       go to the card as one list and the picture is presented at once, see
//       Pipeline::render_joined and kJoinAfter below: the answer of the comparison is read
//       back a turn later
//   nothing new:
//       the picture at rest through the network once more while it is still to settle
//       Pipeline::repaint and a present when the heartbeat is due, or at the display's rate
//       while live, wake, a screenshot or a probe is on: "repeated"
//   once a second the stats line, the monitor's colour state (the capture starts again when
//       Windows HDR went on or off for it, see watch_colour()), and once the reason when
//       the capture counts as lost
//   wait for a frame, a command, a window message or the moment the next thing is due
//
// The wait comes last in a turn, so whatever ends it is acted on at once by the turn that
// follows: the messages, then the commands, then the frame.
//
// The frame rate limit is not in this loop. The capture keeps it, by the rule in capture.h,
// because it acts when a frame arrives. A frame is taken or left out there and then, a frame
// left out is never copied, and no frame waits for a turn. So every frame that reaches this
// loop is drawn at once. The loop's part is three calls. It tells the capture the limit. It
// gives a turn back when the frame that took it showed nothing new. And when the source
// stops it asks for the last frame, which the limit had kept back, once that frame is due.
//
// The loop itself leaves a frame out in one case. Over a source that changes at every
// refresh the pictures can come to be shown a refresh later than they could be, and stay so.
// After a quarter of a second of that, the frame that waits in the capture is left there for
// the next one to replace, which puts the pictures back in step, see kLateAfter.
//
// Where it differs from the Python loop, and why:
//   - A repeated picture is a repaint. The network runs for a frame that changed, and up to
//     four more times on a picture that has come to rest after a large change (the settle,
//     see kSettleRuns). There are no warm-up presents.
//   - Frames are compared on the GPU by the loop (Pipeline::ingest), not in the capture's
//     callback, so the loop wakes for every frame the capture delivers, and counts the
//     unchanged ones as skipped itself.
//   - The window stays hidden until the first picture has been presented, and the ready line
//     is printed then. The stats line and the lost reasons run from the start all the same,
//     so a capture that never delivers is reported and not waited for in silence.
//   - Commands are acted on in the order they came. The Python loop kept a flag for each
//     and acted on pause before resume whatever their order.
//   - After a resume there is no three second wake: that was for the add-on's stale history.
//     The next picture resets the network's history instead.
//   - A screenshot's files are written by a thread of their own, and both pictures are of
//     the same present. A request that comes while one is being written is refused.
//   - A probe over a still reads repaints of one picture and so reports 0.000: the output
//     over a still really is that steady here, once the settle's runs are over. In the
//     Vulkan presenter every present ran the network, and a probe over a still measured the
//     network's own flicker.
//   - Waits end on time (a high resolution timer) and last until the next thing is due,
//     where the Python loop waited a whole period again after every wake.
//
// The quality step. The network works at a size the step chooses (common.h), and "quality N"
// changes the step while the loop runs. The network for the new size is made beside the one
// in use, on a thread of the pipeline's, and the loop goes on drawing meanwhile. Then the
// two change places between two pictures, and the picture on screen is drawn again at the
// new size at once, the network starting on it without its history. Over a still picture
// the settle then runs again. See switch_quality().
//
// Switches for tests, all from the environment:
//   LENS_PRESENTER_PROFILE=1      adds the per stage milliseconds and the test figures to
//                                 the stats line
//   LENS_FAST_NO_NETWORK=1        runs without loading the runtime at all, every picture a
//                                 plain copy, to try the capture, the window and this loop
//                                 on their own
//   LENS_FAST_LIVE_INTERVAL=0     a new limit starts the capture again, as it does where the
//                                 running session will not take a new interval
//   LENS_FAST_CAPTURE_INTERVAL=N  the capture's interval is N ms whatever the limit, 0 for
//                                 every composition
//   LENS_FAST_HEARTBEAT=F,R       presents a second while nothing changes: F in the ten
//                                 seconds after a new picture, R after that, 0 for none.
//                                 The rates are kept as given, with no burst, see watch_path()
//   LENS_FAST_BURST=S             a burst lasts S seconds at most (4)
//   LENS_FAST_QUIET_CHECK=S       a capture that has delivered nothing for S seconds is
//                                 started again to see whether it still works (3), 0 never
//   LENS_FAST_TRACE=FILE          with the profile on, every present, every answer of the
//                                 display's statistics and every compositor frame as a line
//                                 of text, see Trace
//   LENS_FAST_STATS_NOTE=1        every stats line goes to stderr as a note too, so a lens's
//                                 presenter-stderr.log keeps the profile's figures, which the
//                                 lens itself does not log
//   LENS_FAST_SWITCH_SYNC=1       the network of a new quality step is made on the loop's own
//                                 thread, which stands still meanwhile, see switch_quality()
//   LENS_FAST_LEAVE_OUT=0         no frame is ever left out for pictures that are shown late,
//                                 see kLateAfter
//   LENS_FAST_LEAVE_OUT=always    every new picture counts as late, so frames are left out
//                                 that cannot help, to try how seldom that then happens
//   LENS_FAST_STALL=MS,S          every S seconds the loop stands still for MS milliseconds
//                                 between a new frame's ingest and its render, which is what
//                                 makes the pictures late, to try what follows
//   LENS_FAST_SPLIT_WAIT=1        the ingest first waits on the CPU for the capture's copy, with
//                                 the profile or without it. With the profile on, the stats
//                                 line's cwait= tells that wait from the queue's own turn, see
//                                 Pipeline::ingest
//   LENS_FAST_QUEUE_PRIORITY=P    the queue at high or realtime priority, see Gpu::init
//   LENS_FAST_GPU_CLASS=C         this process's class with the card's scheduler, above, high
//                                 or realtime, read back and noted, see gpu_class() in gpu.cpp.
//                                 Both priority switches first take the right to raise
//                                 priorities, which only a process run as administrator holds
//   LENS_FAST_SHOT_RAW=1          a screenshot over a monitor with Windows HDR on also writes
//                                 BASE-raw.npy, the captured frame in 16-bit floats as it came,
//                                 before the conversion to 8 bits, see Pipeline::keep_raw, and
//                                 BASE-out.npy, the picture as drawn into the 16-bit swapchain
//   LENS_FAST_HDR_ABOVE=pass|fade|clip
//                                 what the HDR composite does with the network's change where
//                                 the original is brighter than SDR white, see
//                                 composite_hdr_ps.hlsl. The default is fade
//   LENS_FAST_JOIN=N              the ingest and the render of a new frame go to the card as
//                                 one list once N frames in a row were found changed, see
//                                 kJoinAfter. Unset or 0, every frame goes the way of an
//                                 ingest that is waited for and a render after it
//   LENS_FAST_COPY_QUEUE=1        the capture copies the crop out of each frame with a D3D12
//                                 copy queue, on the card's copy engine, instead of on its
//                                 D3D11 context, whose copy waits for the 3D engine behind a
//                                 game in the foreground. See capture.cpp, copy_on_queue()
#include "capture.h"
#include "capturetest.h"
#include "common.h"
#include "gpu.h"
#include "pipeline.h"
#include "proto.h"
#include "selftest.h"
#include "window.h"

#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <new>
#include <string>
#include <vector>

namespace {

// ---------------------------------------------------------------- the loop's numbers

// The heartbeat: seconds between presents while nothing changes. What it is for was
// measured at 6144x2526 on a 120 Hz screen over a still picture, an RTX 5090, two monitors
// connected. A present can reach the screen in two ways.
//   - Shown directly. It is on screen at the next refresh, 4.7 ms after the call on average.
//     The compositor presents nothing of its own, and no frame comes back from the capture.
//   - Composed. It is on screen 13 to 22 ms after the call, and it comes back from the
//     capture as a frame equal to the last, 1 to 10 ms after the call, which is copied and
//     compared for nothing.
// Which of the two it is follows from how the presents came before.
//   - After two seconds with no present every present was composed, in 20 of 20 trials.
//   - Presents at the display's rate put the swapchain on the direct path. In those 20
//     trials, which began from fifteen composed repeats a second, the first 74 to 77 were
//     composed and the ones after them were shown directly. From no repeats at all it took
//     104. With 63 at that rate it took 10 to 14 more at fifteen a second. Twelve at that
//     rate did not do it, nor did thirty a second for a second, and fifteen a second stayed
//     composed for as long as it ran, 375 presents.
//   - Once there, twelve to thirty presents a second held it, for as long as each run
//     lasted. With eight, four and none the next present was composed again.
//   - A window just made was on the direct path after five presents in most runs. In the
//     others it was composed. 120 presents at the display's rate in its first two seconds
//     did not change that in one run, and 1.77 s of them did in another.
// The first new picture after twelve seconds of rest was shown one refresh before its
// frame's own or at it (delay -8.3 or 0.0 ms) on the direct path, and one refresh after it
// (8.3 ms) when composed, which is 8 to 17 ms later.
// Direct presents cost little, composed ones more than none. Over the still picture the
// card drew 44.7 W with no repeats, 45.3 W with fifteen direct ones a second, 47.4 W with
// thirty direct, 46.3 W with four composed, 50.0 W with fifteen composed. Over a caret that
// blinks it drew 47 to 49 W whatever the repeats.
// So the heartbeat is fifteen a second at all times, which holds the direct path with room
// to spare and replaces thirty a second for ten seconds and four after. watch_path() gets
// the swapchain onto that path when the repeats show it is not there. On a display faster
// than 120 Hz a repeat comes every eight refreshes, which is what fifteen a second is at
// 120 Hz, in case the compositor counts refreshes and not time. That was not measured.
// "ready" keeps thirty a second. LENS_PRESENTER_HEARTBEAT, as lens_presenter.py reads it,
// sets the seconds between presents once ten seconds have passed since a new picture.
constexpr double kBeat = 1.0 / 15.0;
constexpr double kBeatRefreshes = 8.0;
constexpr double kReadyBeat = 1.0 / 30.0;
constexpr double kCooldown = 10.0;
// For watch_path(). kEchoes is how many repeats in a row must come back from the capture
// before the path may be composed, and the next kEchoesEarly repeats are then made early
// and must come back too. A frame that follows the repeat wherever it is put is the
// repeat's own, and one that keeps its own time belongs to something else that changes
// about as often as the heartbeat beats. A burst of repeats at the display's rate lasts until
// they stop coming back, which is when no such frame has come for kBurstQuiet refreshes.
// That took 0.6 to 0.9 s after a pause and 1.77 s in a window just made. It lasts
// kBurstSeconds at most, or kBurstRefreshes on a slower display, since it was not measured
// whether presents count there or time. After a burst that did not help the next is tried
// kBurstEvery later, and twice as long after each further one, kBurstMost at most.
constexpr int kEchoes = 4;
constexpr int kEchoesEarly = 2;
constexpr double kBurstSeconds = 4.0;
constexpr double kBurstRefreshes = 480.0;
constexpr double kBurstQuiet = 8.0;
constexpr double kBurstEvery = 5.0;
constexpr double kBurstMost = 300.0;
// New pictures that follow one another at the display's rate for this long count as a
// burst, and the repeats after them are asked afresh which path they take.
constexpr double kRunSeconds = 1.0;

// A repeated picture is due this long before its moment. A wait ends a little after its time
// and never before, and the half millisecond is the Python loop's own.
constexpr double kSlack = 0.0005;

// The settle. The network carries its own history from one run to the next, so its first
// run on a picture that has just stopped moving is not yet what it makes of that picture
// once it has seen it a few times. A picture that has come to rest is therefore put through
// the network again, kSettleRuns times, and the still picture a person then looks at is
// nearer the settled one. Measured in the self test, on a picture that scrolled 8 texels a
// frame for ten frames and stopped, the first still picture was 0.447 of 255 from the
// network's settled picture on average, and 0.339, 0.263, 0.215 and 0.178 after one to four
// more runs. On screen at 6144x2526 the four runs moved the picture by 1.42 of 255.
//   - At rest means no new picture for kSettleAfter, and under a frame rate limit for a
//     period and a half of the limit, so it never runs while the picture changes.
//   - The runs are a refresh apart, and under a limit no closer than the limit's period.
//   - It runs only after a large change. The tiles that changed since the last rest must
//     number kSettleTiles of the picture's 256 or more. A caret that blinks changes one tile
//     every half second. Settling after each blink would run the network five times where
//     it runs once, for a picture whose every other part is settled already.
// "settle 0" and --no-settle switch it off.
constexpr double kSettleAfter = 0.150;
constexpr int kSettleRuns = 4;
constexpr int kSettleTiles = Pipeline::kTiles / 32;

// The video memory of a network that a switch of the quality step has replaced comes back
// in two stages, measured in the self test at 6144x2526 on an RTX 5090.
//   - The stack keeps the old network until the new one has run a number of times. With 64
//     runs after the switch it was given up, with 32 it was not.
//   - About ten seconds after that, the runtime returns its memory from inside the next run.
//     With frames running the memory was back 10.0 to 10.4 s after the switch. With 15 s of
//     repaints alone it was not, 1196 MiB where 814 belong, and the first frame after them
//     brought it back.
// A picture that moves makes those runs by itself. A picture at rest after a switch gets
// kSwitchRuns runs in all where a settle gives four, a refresh apart, half a second at 120
// Hz, and kMemoryNoteAfter seconds after the switch it goes through the network once more.
// A second later the memory in use is noted, see note_memory(). With "settle 0" the picture
// at rest is left alone, and the memory stays until the picture has moved again.
constexpr int kSwitchRuns = 64;
constexpr double kMemoryNoteAfter = 14.0;

// Pictures that are shown late, and the one frame left out to end it.
//
// The swapchain has two buffers. After a present the next back buffer is the one on screen,
// and it stays on screen until the display takes the picture just presented, at the next
// refresh. A render into it waits in the GPU's queue until then, and the loop, which waits
// for that render before it takes the next frame (take_frame), waits behind it. While each
// picture is finished before the first refresh after its frame arrived, the buffer is free when the
// next frame comes and nothing waits. Once one picture is finished after that refresh, the
// render of the next waits for the buffer and ends a refresh late as well, and so does every
// one after it, for as long as a frame comes at every refresh. A second slip makes it two
// refreshes. The pictures still come one to a refresh, so nothing shows it but the delay.
// One refresh without a render ends it. So when the pictures have been late for kLateAfter,
// the loop leaves one frame out. The frame that waits in the capture stays there until the
// next one takes its place, and counts as dropped. It is taken after all when none comes
// within a refresh and a half, since it is then the last picture of a source that stopped.
//
// Which pictures are late. The display's statistics name the refresh that showed each new
// picture. Counted from the first refresh after its frame arrived, that is 0 for a picture
// shown as early as can be, 1 for one a refresh later, and so on.
//   - 2 or more is late. A frame left out takes one off, and the pictures keep the whole
//     refresh they had for their work.
//   - 1 is late only when the picture's work, begun as its frame arrives, would be done
//     kLateRoom of a refresh before that first refresh. Where it would not, as over a source
//     that loads the GPU itself, the pictures are a refresh later whatever the loop does, and
//     a frame left out would only be missed. The loop's own clock says which it is. In such
//     a chain a picture's work begins at the refresh before, and its present call comes that
//     work less the time from that refresh to the frame's arrival after the arrival. Begun at
//     the arrival, the work ends as long after it as the present call came, and a refresh
//     less the time to the first refresh on top.
// Only a run of pictures whose frames came at every refresh counts. A frame the source or a
// limit left out has already ended whatever chain there was.
//
// A frame left out may not help, as when the compositor composes the pictures, or not for
// long, where the work fits by too little or the computer stutters. So after each frame
// left out the next one waits twice as long, kLateMost at the most, which is then one frame
// a minute. Pictures that are less late than before the last frame left out are on their way
// down and do not wait longer. Once no picture has been late for kLateSoon, the wait is
// kLateAfter again.
//
// Measured at 6144x2526 on a 120 Hz screen with two monitors connected, over a picture that
// scrolled as a whole at every refresh, 120 frames a second. Its frames arrived 14.2 ms
// before their timestamp, 5.9 ms before the first refresh after them, and the network's
// work did not fit before that refresh. In step, the present call came 3.3 ms after the
// arrival and the pictures were shown one refresh after that first one, at their frame's
// own. Once late, the present call came 10.3 ms after the arrival and they were shown two
// after it. With no frame left out for it, that lasted 10 to 40 seconds on end, until a
// frame happened to be missed.
//   - With the loop made to stand still for 9 ms every 7 s, 45 s each way. With no frame
//     left out, 3029 of 5394 pictures were shown those two refreshes after, in 25 of the 45
//     seconds. With it, 132 of 5387, in runs of 238 to 246 ms, each ended by a frame left
//     out, 5 in all, and every second read the usual delay.
//   - The same with the network not loaded, where the work is short and fits. With no frame
//     left out 5241 of 5398 pictures were shown one refresh after the first they could have
//     made. With it 227 of 5387, with 7 frames left out, one of them for pictures three
//     refreshes after, one for two and five for one.
//   - With the network and no such stops, one frame was left out in the run's first second,
//     and every picture of the 41 seconds after it was shown at its usual refresh. None was
//     left out for the one refresh the pictures are after the first there, in any run.
constexpr double kLateAfter = 0.25;
constexpr double kLateRoom = 0.2;
constexpr double kLateSoon = 2.0;
constexpr double kLateMost = 64.0;

// One list per picture while the source is live, see Pipeline::render_joined.
//
// A new frame costs the card two lists: the ingest, which the loop waits for to learn
// whether the frame differs from the last, and then the render. Over a game that keeps the
// card busy each list waits for a gap in the game's work, measured at 23 ms for the ingest's
// own turn and 41 ms from the render's submission to the screen, see docs\NOTES.md. So with
// LENS_FAST_JOIN=N, once N frames in a row were found changed the two go as one list behind
// the capture's fence and the present follows at once, without the answer: the frame is
// drawn whatever it holds. The answer comes back a turn later (Pipeline::take_flag) for the
// books: a frame that differed counts as a new picture then, with the tiles that changed,
// and a frame that was the same as the last counts as a repeat and a skipped frame, as the
// careful way counts it, and the run starts again from nothing, see resolve_joined(). That
// frame cost a run of the network for nothing, which same= counts in the profile.
//
// Off unless the switch is set (kJoinAfter 0). Measured on a test computer with an RTX 5090
// under a window of a test's own that held the foreground and kept the card busy: the
// ingest's wait went from 1 to 22 ms to under a millisecond and the present call came 3 to
// 13 ms sooner, but the one list took as long to get through the card as the two had, or
// longer, so the delay to the screen was the same at 85 percent of the card and at 60 or 30
// fps with gaps, and 2 to 10 ms longer under free running frames of 12 to 50 ms, where the
// network's span inside the one list ran up to twice the span it had in a list of its own.
// The picture is the same byte for byte either way. The switch stays for a measurement over
// a game, which may share the card differently.
//
// Why the run must start again: the engine's window is excluded from capture, so while the
// compositor composes its presents each present comes back as a frame equal to the last
// (see the heartbeat above). Drawn as a new picture, that frame would come back once more,
// and the engine would feed itself at the display's rate for ever over a still screen. With
// the run at nothing after one such frame the next goes the careful way, is found the same
// and is not presented, which ends it: one run of the network and one present for each time
// a live source goes still on that path, none while the presents are shown directly. A
// source that changes every other refresh on that path (a game at 60 fps on a 120 Hz
// display) has an echo between every two of its frames, never reaches a run of two, and
// keeps the careful way with N of 2 or more, which is right for it: joined, every echo
// would cost a run, which N of 1 does to it.
constexpr int kJoinAfter = 0;

// How long the main loop may stand still before the watchdog ends the process.
constexpr double kWatchdogSeconds = 5.0;

// How long the start-up may stand still, from the options to the loop's first turn. The
// lens waits twenty seconds for the window and then ends the engine itself, and takes up to
// three more to see it gone. This is longer than both together, so it acts only on a start
// that hangs when no lens is left to end it.
constexpr double kStartSeconds = 30.0;

// With no first frame this long after the start, a note says so. In practice Windows
// Graphics Capture delivers a frame when a session starts, over a still screen too, so this
// is not expected: it is here so that a hidden window that waits for ever leaves a trace.
// A second later the stats line's check reports the capture as lost, see report().
constexpr double kFirstFrameNote = 2.0;

// ---------------------------------------------------------------- the watchdog and --lifetime
//
// The window is topmost and click-through over the whole screen. A loop that hangs would
// leave its last picture there, over a desktop that goes on working unseen underneath, which
// looks like a frozen computer. So a second thread ends the process when the loop has not
// turned for five seconds. A pause is watched like the rest: paused, the loop still turns at
// least once a second, see paused_turn(), and the call that stops the capture for a pause
// is one that could hang with the window still up. The start-up is watched too, with an
// allowance of its own, so a start that hangs does not outlive a lens that is gone.

std::atomic<double> g_turn{0.0};      // now_s() when the main thread last began a turn
std::atomic<double> g_allow_s{kStartSeconds};  // how long it may stand still: the start-up's
                                               // allowance, then the loop's, see start()
std::atomic<bool> g_shot_busy{false}; // a screenshot is being written by its thread
double g_lifetime_s = 0.0;            // --lifetime, set before its thread starts
double g_born = 0.0;                  // now_s() when wmain began, for the start-up's timing
// The call the loop is in, named by the watchdog when it gives up: a hang inside a driver or
// the runtime leaves no other trace, since the process is ended from outside the call.
std::atomic<const char*> g_step{"start"};

void mark_turn() { g_turn.store(now_s()); }
void step(const char* what) { g_step.store(what, std::memory_order_relaxed); }

// Both must hold before it gives up on the loop: the allowance by the clock since the last
// turn, five seconds once the loop runs, and as many checks of its own in a row that found
// the loop where it was, twenty for five seconds. The clock alone is not enough, because it
// may run on while the computer sleeps: the first check after waking would find a turn hours
// old in a loop that is perfectly well.
DWORD WINAPI watchdog_thread(void*) {
  double seen = g_turn.load();
  int still = 0;
  for (;;) {
    Sleep(250);
    const double turn = g_turn.load();
    if (turn != seen) {
      seen = turn;
      still = 0;
      continue;
    }
    ++still;
    const double allow = g_allow_s.load();
    const double quiet = now_s() - turn;
    if (still >= (int)(allow * 4.0) && quiet >= allow) {
      // stderr only: it is a file and cannot block, where stdout is a pipe that may be the
      // very thing the loop is stuck on
      const char* where = g_step.load(std::memory_order_relaxed);
      note("watchdog: the main thread has stood still for %.1f s, stuck in %s%s%s, leaving", quiet,
           where, strcmp(where, "messages") == 0 ? ": " : "",
           strcmp(where, "messages") == 0 ? Window::pump_state().c_str() : "");
      leave_now(exit_code::watchdog);
    }
  }
}

// --lifetime: the end after that many seconds whatever the rest of the program is doing,
// so a test never leaves an engine behind. It does not ask the loop, which may be the part
// that hangs.
DWORD WINAPI lifetime_thread(void*) {
  const double end = now_s() + g_lifetime_s;
  for (;;) {
    const double left = end - now_s();
    if (left <= 0.0) break;
    Sleep(left > 1.0 ? 1000 : (DWORD)(left * 1000.0) + 1);
  }
  note("lifetime: %g s are over, leaving", g_lifetime_s);
  leave_now(exit_code::ok);
}

bool start_thread(LPTHREAD_START_ROUTINE entry, void* arg, HANDLE* keep = nullptr) {
  HANDLE thread = CreateThread(nullptr, 0, entry, arg, 0, nullptr);
  if (!thread) return false;
  if (keep) *keep = thread;
  else CloseHandle(thread);
  return true;
}

// ---------------------------------------------------------------- the state

// How a picture comes to be drawn.
enum class Draw {
  New,      // the frame just taken, which differs from the one before: the network runs
  Joined,   // the frame just taken, not compared yet: its ingest and the network in one
            // list, see kJoinAfter
  Again,    // the frame on screen through the network once more: after "nr" and "reload"
  Settle,   // the same for a picture that has come to rest, the network's next run on it
  Repaint,  // the last picture as it is, from what the last render left: no network
};

// The per stage figures of LENS_PRESENTER_PROFILE=1, summed over a second.
struct Profile {
  double ingest_ms = 0.0;
  int ingests = 0;
  double nr_ms = 0.0;
  int nr_runs = 0;
  double composite_ms = 0.0;
  int draws = 0;
  double present_ms = 0.0;  // CPU time inside Present
  int presents = 0;
  double wake_ms = 0.0;       // from a frame's arrival to the loop starting its ingest
  double wall_ms = 0.0;       // the ingest call as the clock on the wall has it, waits included,
                              // or for a joined frame the recording and submission of its list
  double cwait_ms = 0.0;      // of that, the wait for the capture's copy, LENS_FAST_SPLIT_WAIT=1
  int timed = 0;
  double dwait_ms = 0.0;      // the wait for the last draw before a frame is taken, see take_frame()
  int dwaits = 0;
  double conv_ms = 0.0;       // GPU time of the conversion of 16-bit frames, over the ingests
  int joined = 0;             // new pictures drawn by one list, see kJoinAfter
  int same = 0;               // of the frames drawn so, the ones found the same as the last
};

// Every present is followed to the screen. DXGI's frame statistics say which refresh showed
// it. Against the captured frame's timestamp that is the delay of the stats line, the time
// from the refresh the source picture belongs to, to the refresh that shows the lens's
// picture of it. With LENS_PRESENTER_PROFILE=1 the rest is reported too.
struct Trace {
  struct Made {            // one present whose showing is still to be learned
    UINT id = 0;           // Window::present_id(), 0 once the statistics have named it
    double called = 0.0;   // when Present returned
    double stamp = 0.0;    // the captured frame's timestamp, 0 for a repeated picture
    double arrived = 0.0;  // when the capture delivered that frame, 0 for a repeated picture
  };
  static constexpr int kMade = 32;
  Made made[kMade];
  int next = 0;
  UINT seen = 0;           // the last present the statistics named
  double period = 0.0;     // one refresh as the statistics count it, 0 until measured
  UINT base_refresh = 0;   // a sample of the statistics some refreshes back, to measure it from
  double base_s = 0.0;
  double t_ask = 0.0;      // when to ask again for a present not named yet, 0 with none open

  // this second
  int composed = 0;            // compositor frames presented to this window's display
  int shown = 0;               // presents the statistics named
  int behind[5] = {};          // new pictures shown 0, 1, 2, 3 and 4 or more refreshes after
                               // their frame's timestamp
  std::vector<double> delay;   // ms from the frame's timestamp to the refresh showing its picture
  double echo_ms = 0.0;        // the longest a frame equal to the last took after a lone repeat
  std::vector<double> flip;    // ms from the present call to that refresh
  std::vector<double> ahead;   // ms the timestamp lay ahead of the frame's arrival
  std::vector<double> grid;    // ms from the timestamp to the nearest refresh of the display
  std::vector<double> stamps;  // timestamps not yet held against the compositor's frames
  std::vector<CompositorFrame> frames;  // the compositor's frames of the last seconds
  bool frames_known = false;   // the system keeps such statistics

  // LENS_FAST_TRACE=FILE: every present, every answer of the statistics, every compositor
  // frame and every draw's moments on the card as a line of text, for a test to work through
  // afterwards.
  //   P id called stamp arrived              a present, stamp and arrived 0 for a repeat
  //   S id refresh sync_refresh sync_s now   the statistics when they changed
  //   C id start target period n, then for each display: source present shown refresh vblank
  //   G seq kind stamp arrived submitted i0 i1 i2 d0 d1 d2 d3 d4
  //                                          a draw the card has finished: its number, kind
  //                                          (new, joined, again, settle or repaint), the
  //                                          frame's stamp and arrival (0 unless new or
  //                                          joined), when its list was submitted, the
  //                                          ingest's three timestamps (start, after the
  //                                          conversion, end, or 0 for a settle and a repaint,
  //                                          and for a joined draw the list's own, which d0
  //                                          to d2 repeat) and the draw's five (the
  //                                          list's start, after the conversion, the draw's
  //                                          start, after the network, the end), the card's
  //                                          clock put on now_s()'s by the queue's calibration
  // All moments in seconds on now_s()'s clock.
  FILE* file = nullptr;
  UINT file_refresh = 0;
  struct DrawNote {  // a draw submitted, until its times come back
    UINT64 sequence = 0;
    const char* kind = "";
    double stamp = 0.0;
    double arrived = 0.0;
    double submitted = 0.0;
    UINT64 ingest[3] = {};
  };
  static constexpr int kDrawNotes = 16;
  DrawNote draws[kDrawNotes];
  UINT64 cal_gpu = 0;      // the queue's clock calibration, taken afresh each second
  double cal_cpu_s = 0.0;
  double cal_at = 0.0;
};

struct State {
  Options o;

  // ---- the parts
  Gpu gpu;
  Window window;
  Pipeline pipeline;
  Capture capture;
  CommandReader reader;
  HMONITOR monitor = nullptr;
  MonitorColour colour;          // the monitor's colour state, read whenever the capture starts
  HANDLE frame_event = nullptr;  // the capture sets it for every complete frame. Auto-reset
  HANDLE timer = nullptr;        // ends a wait on time, see wait_turn(). Null: plain timeouts
  int work_w = 0;                // the size the network works at
  int work_h = 0;
  int quality = -1;              // the quality step in use, 0 to 4. -1 while an option gave
                                 // the work size itself, until a "quality N" comes
  bool network = true;           // false with LENS_FAST_NO_NETWORK=1

  // ---- what the lens has asked for
  bool quit = false;
  bool paused = false;
  bool live = false;             // "live 1": the display's rate whether or not anything changed
  bool ready = false;            // "ready 1" and --ready: thirty presents a second at rest
  bool clip = false;             // "clip 1": a screenshot also goes to the clipboard
  bool settle = true;            // "settle 1|0" and --no-settle
  double wake_until = 0.0;       // "wake": the display's rate until this moment
  double limit_fps = 0.0;        // "cap N" and --max-fps: new pictures a second, 0 no limit
  bool want_recapture = false;   // the limit changed: the capture starts again
  int want_quality = -1;         // the step a "quality N" line asked for, -1 for none
  bool switching = false;        // the network for another step is being made, see switch_quality()
  int switch_to = -1;            // that step, and its work size
  int switch_w = 0;
  int switch_h = 0;
  bool switch_sync = false;      // with LENS_FAST_SWITCH_SYNC=1 it is made on the loop's thread
  bool switched = false;         // the switch has landed and its first picture is still to come
  double t_asked = 0.0;          // when the switch began
  double t_stood = 0.0;          // when the last picture before the landing was presented
  int held = 0;                  // pictures drawn while it was being made, with the network's
                                 // change as it stood
  double gap_most = 0.0;         // the longest time between two presents since the switch began
  double t_landed = 0.0;         // when the last switch landed
  double t_memory = 0.0;         // when the video memory is looked at after a switch, see
                                 // note_memory(), 0 for never
  double memory_before = 0.0;    // MiB in use before the first switch of those it follows
  bool memory_asked = false;     // the picture was at rest then, and one more run of the
                                 // network was asked for
  bool memory_run = false;       // that run is still to be drawn
  int runs_since_switch = kSwitchRuns;  // runs of the network since the last switch landed,
                                 // counted up to kSwitchRuns, where nothing is owed any more
  bool shot_wanted = false;      // "shot BASE": the next present is read back and saved
  std::wstring shot_base;
  ProbeRun probe;                // "probe N": probe.left pictures are still to be read back
  int crop_x = 0;                // "crop X Y"
  int crop_y = 0;
  NrPasses settings;             // each pass's own, as last read from ReShade.ini

  // ---- the picture
  CaptureFrame cur;              // the newest frame taken from the capture
  bool have_cur = false;
  bool have = false;             // a picture has been rendered, so there is one to repaint
  bool shown = false;            // the window is visible and the ready line is out
  bool redraw = false;           // the frame on screen has to go through render again
  bool reset_next = false;       // the next render drops the network's history
  bool repaint_once = false;     // after a resume the picture is presented again at the next
                                 // turn, whatever the heartbeat

  // ---- one list per picture, see kJoinAfter
  int join_after = kJoinAfter;   // changed frames in a row before the joined way is taken, 0
                                 // never, which it is unless LENS_FAST_JOIN=N says otherwise
  int changed_run = 0;           // frames in a row found changed, by the answers read back
  ID3D12Resource* joined_prev = nullptr;  // the frame before the one draw(Joined) draws
  struct Joined {                // a joined draw whose answer is still to be read
    CaptureFrame frame;
    double meter = 0.0;          // its entry in the meter, made once the answer says it was new
    bool late = false;           // and whether it counts as late then, see cur_was_held
  };
  std::vector<Joined> joined;    // oldest first

  // ---- the settle
  bool at_rest = true;           // the picture has been judged since it last changed
  bool rest_owed = false;        // it was large enough a change to settle, and "settle" was off
  int settle_left = 0;           // runs of the network the picture at rest is still to get
  uint8_t moved[Pipeline::kTiles] = {};  // the tiles that changed since the last rest
  double t_changed = 0.0;        // when a picture that differs was last drawn (new or again)

  // ---- pictures shown late, see kLateAfter
  bool leave_allowed = true;     // false with LENS_FAST_LEAVE_OUT=0, and no frame is ever left out
  bool late_always = false;      // true with LENS_FAST_LEAVE_OUT=always, for a test, and every
                                 // new picture counts as late
  double last_stamp = 0.0;       // the timestamp of the frame the last new picture was made of
  double late_from = 0.0;        // pictures of frames stamped before this are not judged. They
                                 // belong to a chain that a frame left out has ended
  int late_run = 0;              // new pictures in a row that were late
  int late_steps = 0;            // how many refreshes late the last of them was
  double t_late = 0.0;           // when the first of the run was presented
  double t_last_late = 0.0;      // when the last late picture of all was presented
  double late_need_s = kLateAfter;  // how long a run must last before a frame is left out
  bool leave_out = false;        // the next frame to wait in the capture is left out,
  double leave_by = 0.0;         // if it waits there before this moment
  bool leaving = false;          // a frame is being left out, and waits for a newer one
  double left_arrived = 0.0;     // when that frame came, which tells it from the newer one
  double leave_until = 0.0;      // when it is taken after all, since no newer one came
  int left_before = 0;           // how many refreshes late the pictures were before the last
                                 // frame left out
  int left_steps = -1;           // the same, until the first picture after it has been looked
                                 // at, and -1 from then on
  int left = 0;                  // frames left out this second, for the profile
  double stall_ms = 0.0;         // LENS_FAST_STALL=MS,S for a test, where the loop stands still
  double stall_every = 0.0;      // for MS milliseconds every S seconds
  double t_stall = 0.0;          // when next

  // ---- the capture's health
  bool live_interval = true;     // a new limit changes the running session's interval. False
                                 // with LENS_FAST_LIVE_INTERVAL=0, and the capture starts again
  int interval_forced = -1;      // LENS_FAST_CAPTURE_INTERVAL=N, a test's own interval in ms
                                 // whatever the limit, -1 when not given
  bool capturing = false;        // a capture was started and has not been paused away
  bool stopped = false;          // "stop-capture" ended it: reported as closed
  bool lost_said = false;        // "capture lost ..." is said once for each loss
  std::string said_colour;       // the last "hdr: ..." note, said again only when it changes
  double t_fit = 0.0;            // when a frame that covers the lens was last taken
  double t_recapture = 0.0;      // when a new limit last reached the capture, until the first
                                 // frame after it has been noted
  double quiet_after_s = 3.0;    // a capture quiet for this long is started again to see
                                 // whether it still delivers. LENS_FAST_QUIET_CHECK=S for a
                                 // test, 0 for never
  double t_check = 0.0;          // when a quiet capture was last started again to see whether
                                 // it still delivers, 0 when none is being checked
  double t_quiet = 0.0;          // the last frame before that check

  // ---- the beat
  bool beat_given = false;       // LENS_PRESENTER_HEARTBEAT or a test set the heartbeat's
                                 // rates, and the two below are used
  double beat_fast_s = kBeat;    // seconds between presents while nothing changes, in the ten
                                 // seconds after a new picture, 0 for none
  double beat_rest_s = kBeat;    // and after those ten seconds, 0 for none
  int echoes = 0;                // repeats in a row that each came back from the capture as a
                                 // frame equal to the last, with no other such frame between
                                 // them, which says the compositor composes them, see
                                 // watch_path()
  bool repeat_open = false;      // a repeat has been presented, well after the present before
                                 // it, and no frame has come since
  double t_repeat = 0.0;         // when that repeat was presented
  double t_run = 0.0;            // since when the presents have followed one another at the
                                 // display's rate
  bool composed = false;         // presents at the display's rate did not get the swapchain
                                 // shown directly, so no repeats until burst_again
  bool said_composed = false;    // and the note about it has been written
  double burst_until = 0.0;      // a burst is on, repeats at the display's rate until this
                                 // moment or until they stop coming back
  double t_burst = 0.0;          // when that burst began
  bool burst_said = false;       // its beginning was noted, so its end is too
  double t_back = 0.0;           // when a frame equal to the last last came from the capture
  double burst_again = 0.0;      // no burst before this moment
  double burst_gap = kBurstEvery;  // from a burst that did not help to the next, doubling
  double burst_test_s = -1.0;    // LENS_FAST_BURST=S for a test, a burst then lasts S seconds
                                 // at most. A tenth of a second does not help, and what
                                 // follows is seen
  double refresh_hz = 60.0;      // of the window's monitor, read again every second
  double t_started = 0.0;        // when the loop began
  bool said_waiting = false;     // the note about a first frame that does not come
  double t_new = 0.0;            // when a new picture was last presented
  double t_present = 0.0;        // when anything was last presented
  double t_report = 0.0;         // when the stats line last went out
  bool progress = false;         // this turn took a frame or presented a picture

  // ---- this second, for the stats line
  int fresh = 0;                 // new: pictures presented for the first time
  int repeated = 0;              // presents of a picture already shown
  int skipped = 0;               // frames the same as the one before
  int late = 0;                  // of the new pictures, frames the limit had kept back and
                                 // handed on when no newer one came
  int settled = 0;               // of the repeated ones, the settle's runs of the network
  bool cur_was_held = false;     // the frame being taken is such a one
  std::vector<double> meter;     // ms from each new picture's capture to its present
  Profile profile;
  Trace trace;
  bool stats_note = false;       // LENS_FAST_STATS_NOTE=1: every stats line on stderr too

  // ---- the screenshot's writer
  HANDLE shot_thread = nullptr;  // the last one started, kept so the way out can wait for it
  std::vector<uint8_t> sparse;   // the probe's picture, kept so it is not allocated each time
  bool shot_raw = false;         // LENS_FAST_SHOT_RAW=1: a screenshot keeps the 16-bit frame too

  // ---- the output in HDR
  bool hdr_out = true;           // the swapchain takes scRGB, so with Windows HDR on for the
                                 // monitor the picture is drawn in 16-bit floats, see
                                 // switch_output(). false once the swapchain refused it
};

// A failure nothing can be done about: the window goes first, so no dead picture stays on
// the screen while the lens is told, then the reason, then the process. Nothing is torn
// down in order: with a device that is removed or a network that raised, an orderly
// shutdown is one more thing that can hang.
[[noreturn]] void die(State& s, const std::string& reason) {
  if (HWND hwnd = s.window.hwnd()) ShowWindow(hwnd, SW_HIDE);
  fail("%s", reason.c_str());
  leave_now(exit_code::failed);
}

bool busy(const State& s, double now) {
  return s.live || now < s.wake_until || now < s.burst_until || s.shot_wanted || s.probe.left > 0;
}

void resolve_joined(State& s);  // the answers of the joined draws, with take_frame() below

// The engine's own heartbeat, no further apart than eight refreshes, see kBeat.
double own_beat(const State& s) { return std::min(kBeat, kBeatRefreshes / s.refresh_hz); }

// How long a burst lasts at most, see kBurstSeconds.
double burst_s(const State& s) {
  if (s.burst_test_s >= 0.0) return s.burst_test_s;
  return std::max(kBurstSeconds, kBurstRefreshes / s.refresh_hz);
}

// How long after a repeat its own frame can come back from the capture. Over 224 composed
// repeats at 120 Hz it came 1 to 10 ms after the present call, a refresh and a fifth.
double echo_within(const State& s) { return 2.5 / s.refresh_hz; }

// Whether the frame rate limit asks for fewer presents than the heartbeat makes. In the
// Vulkan presenter a repeated present ran the neural pass as a new one does, so with a
// limit the heartbeat was never faster than the limit. A repeat is one draw here, but the
// rule stays, since whoever sets a limit asks for fewer presents.
bool limit_below(const State& s, double beat) {
  return s.limit_fps > 0.0 && 1.0 / s.limit_fps >= beat;
}

// Seconds from one present to the next while nothing changes, a very long time when there
// is to be none.
double heartbeat_s(const State& s, double now) {
  double hb = own_beat(s);
  bool early = false;
  if (s.beat_given) {
    // the rates the environment gave, one for the ten seconds after a new picture and one
    // for after them
    hb = now - s.t_new < kCooldown ? s.beat_fast_s : s.beat_rest_s;
  } else if ((s.composed && now < s.burst_again) || limit_below(s, hb)) {
    // No repeats where they would not keep the swapchain on the direct path, since composed
    // ones cost more than none and buy nothing (see kBeat). That is while a burst has not
    // helped, until the next is tried, and under a limit that allows fewer than hold it.
    hb = 0.0;
  } else if (s.echoes >= kEchoes) {
    early = true;
  }
  if (s.ready && (hb <= 0.0 || hb > kReadyBeat)) hb = kReadyBeat;
  if (hb <= 0.0) return 1e9;
  // Under such a limit a repeat that is asked for all the same, by "ready" or a test, comes
  // a period and a half of the limit after the last present, so that it does not fall on
  // the moment the next new picture is due and make that picture wait for it.
  if (limit_below(s, hb)) return 1.5 / s.limit_fps;
  // The repeats seem to come back. The next ones are made early, out of step with whatever
  // else may be changing the screen, see kEchoes. Not so early that the frame of the
  // present before could still be on its way.
  if (early) hb = std::max(1.05 * echo_within(s), hb - 1.2 * echo_within(s));
  return hb;
}

// Keeps the swapchain on the direct path over a still screen, see kBeat. The engine can tell
// which path its repeats take. A repeat the compositor composes comes back from the capture
// as a frame equal to the last, and a repeat shown directly brings none. draw() and
// take_frame() count them. A frame equal to the last that follows no repeat is something
// else making the compositor compose, and the count starts again, since the repeats' own
// frames cannot be told from those. When kEchoes repeats in a row have each come back, and
// the kEchoesEarly after them that are made early as well, the repeats go to the display's
// rate for a burst, which is what puts the swapchain on the direct path. The burst ends
// when its repeats stop coming back, and the heartbeat holds the path afterwards. Should
// the repeats still come back after a whole burst, the direct path is not to be had for
// now. There are then no repeats at all, which is the cheapest when composed, until the
// next burst is tried, kBurstEvery later and twice as long after each further one that did
// not help. New pictures at the display's rate do what a burst does, and the repeats after
// kRunSeconds of them are judged afresh.
void watch_path(State& s, double now) {
  if (s.beat_given || !s.o.exclude) return;  // a test's own rates, or a window that sees itself
  if (now < s.burst_until) {
    s.echoes = 0;  // judged by the repeats after it
    if (now - std::max(s.t_back, s.t_burst) >= kBurstQuiet / s.refresh_hz) {
      // its repeats no longer come back, so they are shown directly and the burst is over
      s.burst_until = now;
      if (s.burst_said) {
        note("loop: the repeats are shown directly after %.0f ms at the display's rate",
             (now - s.t_burst) * 1000.0 - kBurstQuiet * 1000.0 / s.refresh_hz);
      }
    }
    return;
  }
  // under a limit the repeats are too far apart to hold the direct path, and no burst lasts
  if (heartbeat_s(s, now) > own_beat(s) + 1e-9) return;
  if (now < s.wake_until) {
    s.echoes = 0;  // the lens's own wake, judged by the repeats after it
    return;
  }
  if (s.echoes < kEchoes + kEchoesEarly) return;
  s.echoes = 0;
  if (now < s.burst_again) {
    s.composed = true;
    if (!s.said_composed) {
      s.said_composed = true;
      note("loop: the repeats are still composed, so there are none until the display's rate is "
           "tried again, in %.0f s at the latest",
           s.burst_again - now);
    }
    return;
  }
  s.burst_said = !s.said_composed;
  if (s.burst_said) {
    note("loop: the repeats come back from the capture, so they are composed. The display's "
         "rate until they no longer do, %.1f s at most",
         burst_s(s));
  }
  s.composed = false;  // judged again by the repeats after the burst
  s.t_burst = now;
  s.burst_until = now + burst_s(s);
  s.burst_again = now + s.burst_gap;
  s.burst_gap = std::min(s.burst_gap * 2.0, kBurstMost);
}

// The last repeat brought no frame back in that time, so it was shown directly.
void repeat_was_direct(State& s) {
  s.echoes = 0;
  s.burst_gap = kBurstEvery;
  s.composed = false;
  if (s.said_composed) {
    s.said_composed = false;
    note("loop: the repeats are shown directly again");
  }
}

// How long after the last picture that differed the picture counts as at rest.
double rest_after(const State& s) {
  return s.limit_fps > 0.0 ? std::max(kSettleAfter, 1.5 / s.limit_fps) : kSettleAfter;
}

// How far apart the settle's runs are. A refresh, and under a limit its period at least.
double settle_apart(const State& s) {
  const double refresh = 1.0 / s.refresh_hz;
  return s.limit_fps > 0.0 ? std::max(refresh, 1.0 / s.limit_fps) : refresh;
}

// Whether the picture at rest is to go through the network once more now. The first call
// after the picture has come to rest judges it. How many tiles changed since the last rest
// decides whether it is settled at all, see kSettleTiles.
bool settle_due(State& s, double now) {
  if (!s.at_rest) {
    // a frame the limit has kept back means the source has not stopped yet
    if (now - s.t_changed < rest_after(s) || s.capture.held_due_s() > 0.0) return false;
    s.at_rest = true;
    int tiles = 0;
    for (uint8_t& tile : s.moved) {
      tiles += tile;
      tile = 0;
    }
    // After a pause or a jump of the crop the next picture starts the network afresh
    // (reset_next). The one on screen is from before, and is not settled. Nor is one the
    // network does not run on, which it does not when it is off or its strength is 0.
    const bool large = tiles >= kSettleTiles && s.pipeline.network_runs() && !s.reset_next;
    s.settle_left = large && s.settle ? kSettleRuns : 0;
    s.rest_owed = large && !s.settle;
    // The first rest after a switch of the quality step: as many runs as are still short
    // of kSwitchRuns since the switch, so that the stack gives the old network up.
    if (s.settle_left > 0 && s.runs_since_switch < kSwitchRuns) {
      s.settle_left = std::max(s.settle_left, kSwitchRuns - s.runs_since_switch);
    }
  }
  if (s.settle_left <= 0) return false;
  if (!s.settle || !s.pipeline.network_runs() || s.reset_next) {
    s.settle_left = 0;
    return false;
  }
  return now - s.t_present >= settle_apart(s) - kSlack;
}

// Whether the last picture is to be presented again now, with nothing new to show.
bool repeat_due(const State& s, double now) {
  if (s.shot_wanted) return true;  // a screenshot does not wait for a beat
  if (s.repaint_once) return true; // nor does the picture after a resume
  const double since = now - s.t_present;
  if (busy(s, now)) return since >= 1.0 / s.refresh_hz - kSlack;  // the display's rate
  return since >= heartbeat_s(s, now) - kSlack;
}

// ---------------------------------------------------------------- waiting

#ifndef CREATE_WAITABLE_TIMER_HIGH_RESOLUTION
#define CREATE_WAITABLE_TIMER_HIGH_RESOLUTION 0x00000002  // Windows 10 1803 and later
#endif

// Waits until a frame is there, a command has come, the window has a message, or `seconds`
// have passed, whichever is first. The loop never waits in any other way, and never
// without an end.
//
// Messages are part of the wait because the lens moves, clips, hides and shows this window
// from its own process and those calls are answered by this thread: measured with the
// Vulkan presenter, a loop asleep on something else made each move of the lens wait 267 ms.
// It is the plain MsgWaitForMultipleObjects on purpose, which returns for input that is new
// since the queue was last looked at: Window::pump() has emptied the queue earlier in the
// turn, so nothing that came since is missed, and a message nobody removes cannot make the
// loop spin.
//
// The end of the wait is a high resolution timer where Windows has one. A plain timeout
// ends on the system's timer tick, which for a program that has not asked for a finer one
// is 15.6 ms apart. A heartbeat's 33 ms wait would then end at 47, and the last frame before
// a stop, which the limit hands on 12 ms after it came, would come a tick late. The timeout
// stays behind the timer as the end that cannot fail.
void wait_turn(State& s, double seconds) {
  if (seconds <= 0.0) return;
  if (seconds > 1.0) seconds = 1.0;  // nothing in the loop is due later than the stats line
  HANDLE handles[4];
  DWORD count = 0;
  if (s.frame_event) handles[count++] = s.frame_event;
  if (HANDLE commands = s.reader.event()) handles[count++] = commands;
  // the network for another quality step is being made, and the wait ends when it is there
  if (s.switching) {
    if (HANDLE made = s.pipeline.work_event()) handles[count++] = made;
  }
  DWORD timeout = (DWORD)std::ceil(seconds * 1000.0);
  if (timeout < 1) timeout = 1;
  if (s.timer) {
    LARGE_INTEGER due;
    due.QuadPart = -(LONGLONG)(seconds * 1e7);  // relative, in units of 100 ns
    if (due.QuadPart > -1) due.QuadPart = -1;
    if (SetWaitableTimer(s.timer, &due, 0, nullptr, nullptr, FALSE)) {
      handles[count++] = s.timer;
      timeout += 2;
    }
  }
  // Which of them ended the wait does not matter: the turn that follows looks at them all.
  if (MsgWaitForMultipleObjects(count, handles, FALSE, timeout, QS_ALLINPUT) == WAIT_FAILED) {
    Sleep(1);  // whatever is wrong with the handles, the loop must not spin on it
  }
}

// ---------------------------------------------------------------- the capture

// The interval the capture is asked for under the limit as it stands. With a limit of half
// the display's rate or less the system itself delivers fewer frames, see
// capture_interval_ms().
int wanted_interval(const State& s) {
  if (s.interval_forced >= 0) return s.interval_forced;
  return capture_interval_ms(s.limit_fps, s.refresh_hz);
}

// Tells the capture the frame rate limit, which is three numbers: its period, how far before
// its turn a frame is still taken, and how long a frame before its turn is kept for a newer
// one. That last is the time between two frames the system delivers and half a refresh.
// The system delivers a frame every refresh, or every second, third or fourth one when the
// session runs with an interval, which Windows rounds up to whole refreshes.
void apply_limit(State& s) {
  if (s.limit_fps <= 0.0) {
    s.capture.set_limit(0.0, 0.0, 0.0);
    return;
  }
  const double refresh = 1.0 / s.refresh_hz;
  const int interval = s.capture.running() ? s.capture.interval_ms() : wanted_interval(s);
  int apart = interval > 1 ? (int)std::ceil(interval / 1000.0 * s.refresh_hz - 0.01) : 1;
  if (apart < 1) apart = 1;
  s.capture.set_limit(1.0 / s.limit_fps, kLimitEarly * refresh,
                      apart * refresh + std::max(kLimitNewer * refresh, kLimitNewerLeast));
}

// The monitor's colour state, read whenever the capture starts. With Windows HDR on for the
// monitor an 8-bit capture would be the desktop clipped at 80 nits, 1.0 in scRGB, so the
// capture then takes 16-bit floats, the pipeline scales them by the SDR white level into
// the 8-bit frames the network works on, and the picture is drawn in 16-bit floats again,
// the original with the network's change on it (pipeline.h). The ready line repeats the
// state as ", hdr off" or ", hdr on".
void read_colour(State& s) { s.colour = monitor_colour(s.monitor); }

// The state as a note, "hdr: off" or "hdr: on, sdr white 240 nits, ...", said once the
// swapchain has followed it, when the capture first starts and whenever the sentence changes.
// The quiet restarts over a still screen say nothing, as the capture's own session line is
// said once for them, and a change while the capture runs has its own note, see
// watch_colour().
void say_colour(State& s) {
  std::string said;
  if (!s.colour.known) {
    said = "hdr: unknown, the monitor's colour state could not be read";
  } else if (s.colour.hdr) {
    said = strf("hdr: on, sdr white %.0f nits, the capture takes 16-bit floats, the network sees them scaled to "
                "that white, and the picture is %s",
                s.colour.sdr_white_nits,
                s.window.hdr() ? "drawn in 16-bit floats"
                               : "shown in standard range at that white, since the swapchain does not take scRGB");
  } else {
    said = "hdr: off";
  }
  if (said == s.said_colour) return;
  note("%s", said.c_str());
  s.said_colour = std::move(said);
}

// Whether the capture takes 16-bit frames, from the colour state as last read. The white
// level is what Windows says, or 80 nits when it could not be read.
bool wants_fp16(const State& s) { return s.colour.known && s.colour.hdr; }

double sdr_white_units(const State& s) {
  return s.colour.sdr_white_nits > 0.0 ? s.colour.sdr_white_nits / 80.0 : 1.0;
}

// The capture is about to start with the other format, and its slots go: every frame the
// loop was handed goes with them. The GPU finishes what it was drawing from them first, the
// pipeline forgets them, and the loop is as before its first frame: the window stays as it
// is, showing the last picture, until the new capture's first frame is drawn, which comes
// at once with a new session. The note of a missing first frame is not for this.
void drop_frames(State& s) {
  note("loop: the capture changes to %s, the frames on hand go and the next one is drawn afresh",
       wants_fp16(s) ? "16-bit floats" : "8 bits a channel");
  std::string err;
  if (!s.gpu.flush(3000, err)) die(s, "wait for the GPU: " + err);
  resolve_joined(s);  // every joined draw is done now, and its answer is about frames that go
  s.pipeline.drop_frames();
  s.have = false;
  s.have_cur = false;
  s.changed_run = 0;
  s.repaint_once = false;
  s.redraw = false;
  s.at_rest = true;
  s.settle_left = 0;
  s.memory_run = false;
  s.reset_next = true;
  s.said_waiting = true;
}

// The swapchain is about to change its format, with the monitor's HDR state: the GPU
// finishes what it draws into its buffers, the pipeline lets go of the copies it kept of a
// target, and the window makes the buffers again. What the window shows then stays until
// the next present, so a picture is presented at the next turn: the last one again when
// the frames on hand are still good, the new capture's first frame otherwise.
void switch_output(State& s, bool hdr) {
  std::string err;
  if (!s.gpu.flush(3000, err)) die(s, "wait for the GPU: " + err);
  s.pipeline.drop_target_copies();
  if (!s.window.set_hdr(hdr, err)) die(s, "window: " + err);
  // a swapchain that does not take scRGB stays in 8 bits, and is not asked again
  if (hdr && !s.window.hdr()) s.hdr_out = false;
  s.repaint_once = s.have;
}

// Starts the capture, at the start, after a pause, and for a new limit where the running
// session would not take the new interval. The monitor's colour state is read afresh each
// time, so a capture started again after Windows HDR went on or off for the monitor takes
// the format for it, the swapchain follows (16-bit floats in scRGB with HDR on, see
// window.h), the SDR white level follows, and the note says the state once the swapchain
// has followed it, when it is new. A new white level while the capture runs waits for its
// next start.
bool start_capture(State& s, std::string& err) {
  s.refresh_hz = s.window.refresh_hz();
  read_colour(s);
  if (s.capture.slots_made() && s.capture.slots_fp16() != wants_fp16(s)) drop_frames(s);
  const bool hdr_out = wants_fp16(s) && s.hdr_out;
  if (s.window.hdr() != hdr_out) switch_output(s, hdr_out);
  say_colour(s);
  s.pipeline.set_sdr_white(sdr_white_units(s));
  apply_limit(s);
  if (!s.capture.start(s.gpu.device.Get(), s.gpu.luid, s.monitor, s.o.width, s.o.height, wants_fp16(s),
                       s.crop_x, s.crop_y, wanted_interval(s), s.frame_event, err)) {
    s.capturing = false;
    return false;
  }
  // again, now that the session says which interval it took
  apply_limit(s);
  s.capturing = true;
  s.stopped = false;
  s.lost_said = false;  // a new session is watched again, see report()
  s.t_fit = now_s();
  s.t_check = 0.0;  // a session of its own: whatever was being checked was the old one's
  return true;
}

// Windows HDR switched on or off for the monitor while the capture runs. Switched on, the
// session went on delivering frames in the format it was started with (measured on a test
// computer with an RTX 5090, no "capture lost" came after the switch, and the 8-bit frames
// of the HDR desktop were clipped at 80 nits, 1.0 in scRGB, 45 of 255 from the right
// picture on average). HDR switched off while the capture ran was not measured. So the
// state is read once a second, from report(), and the capture started again when it
// changed, which takes the new format and the swapchain with it, see start_capture(). A
// few hundred microseconds a second. A new SDR white level alone is taken without a
// restart. The next frame is converted and drawn to it, and the picture on screen is drawn
// again at once.
void watch_colour(State& s) {
  if (!s.capturing || s.paused) return;
  const MonitorColour now = monitor_colour(s.monitor);
  if (!now.known) return;
  if (now.hdr != s.colour.hdr || !s.colour.known) {
    note("hdr: Windows HDR went %s for the monitor while the capture ran, so the capture starts again",
         now.hdr ? "on" : "off");
    s.capture.stop();
    std::string err;
    if (!start_capture(s, err)) {
      say("capture lost could not start again: %s", err.c_str());
      s.lost_said = true;
    }
    return;
  }
  if (now.hdr && now.sdr_white_nits > 0.0 && now.sdr_white_nits != s.colour.sdr_white_nits) {
    note("hdr: the SDR white level is now %.0f nits", now.sdr_white_nits);
    s.colour = now;
    s.pipeline.set_sdr_white(sdr_white_units(s));
    if (s.have && s.have_cur) s.redraw = true;
  }
}

// "pause": the capture ends and nothing is presented, so nothing runs on the GPU until
// "resume". The lens hides the window meanwhile. The watchdog watches the stop as it
// watches any other call, since the window may still be up while it runs.
void do_pause(State& s) {
  if (s.paused) return;
  s.paused = true;
  step("pause");
  s.capture.stop();
  step("commands");
  s.capturing = false;
  say("paused");
}

// "resume": the capture starts afresh. The last picture is presented again first, at the
// next turn. The slots handed out before the pause are still valid and the pipeline repaints
// from them. Whatever the capture brings next does not follow from that picture, so the
// network starts it without its history.
void do_resume(State& s) {
  if (!s.paused) return;
  s.paused = false;
  s.repaint_once = s.have;
  s.changed_run = 0;  // what comes next does not follow from the picture before
  mark_turn();
  s.lost_said = false;
  std::string err;
  if (!start_capture(s, err)) {
    say("capture lost could not start again: %s", err.c_str());
    s.lost_said = true;
  }
  s.reset_next = true;
  say("resumed");
}

// A new limit, or a new refresh rate under the old one. The running session takes the new
// interval as it is. Where it does not, the capture starts again asking for it, and the old
// one stops first, so the two never both deliver.
void recapture(State& s) {
  s.want_recapture = false;
  if (s.paused || !s.capturing) return;  // "resume" starts it with the limit as it is then
  s.refresh_hz = s.window.refresh_hz();
  const double t0 = now_s();
  s.t_recapture = t0;
  if (s.live_interval && !s.stopped && s.capture.set_interval(wanted_interval(s))) {
    apply_limit(s);
    note("loop: limit %g, the capture runs on with an interval of %d ms, set in %.2f ms", s.limit_fps,
         s.capture.interval_ms(), (now_s() - t0) * 1000.0);
    return;
  }
  s.capture.stop();
  std::string err;
  if (!start_capture(s, err)) {
    say("capture lost could not start again: %s", err.c_str());
    s.lost_said = true;
    return;
  }
  note("loop: limit %g, the capture started again with an interval of %d ms, in %.1f ms", s.limit_fps,
       s.capture.interval_ms(), (now_s() - t0) * 1000.0);
}

// "stop-capture", for tests: the capture ends as it does when Windows closes it because
// the displays changed. The loop goes on showing its last picture and reports the loss.
void stop_capture(State& s) {
  if (!s.capturing) return;
  s.capture.stop();
  s.stopped = true;
}

// ---------------------------------------------------------------- commands

// "crop X Y": the lens has moved. A step under a drag follows from the picture before it,
// as a scrolling page does. A jump does not: when the crop moves by more than a quarter of
// the lens the two pictures share too little, and the network starts the next one without
// its history.
void move_crop(State& s, int x, int y) {
  const long long dx = std::llabs((long long)x - s.crop_x);
  const long long dy = std::llabs((long long)y - s.crop_y);
  if (dx * 4 > s.o.width || dy * 4 > s.o.height) s.reset_next = true;
  s.crop_x = x;
  s.crop_y = y;
  s.capture.set_crop(x, y);
}

// "shot BASE": the next present is read back. One screenshot at a time: while the files
// of one are being written a second request is refused, since its pictures, 93 MB at
// 6144x2526, would have to be held until the writer is free.
void want_shot(State& s, const std::wstring& base) {
  if (base.empty()) return;
  if (g_shot_busy.load()) {
    say("shot failed busy");
    return;
  }
  s.shot_base = base;
  s.shot_wanted = true;
}

// "nr 1|0". A repaint would still show the picture as it was last rendered, so the frame on
// screen goes through render once more and the change shows at once, over a still too.
void switch_network(State& s, bool on) {
  if (!s.network) return;  // LENS_FAST_NO_NETWORK=1: there is none to switch
  if (on == s.pipeline.nr_on()) return;
  s.pipeline.set_nr(on);
  s.redraw = true;
  note("loop: the network is %s", s.pipeline.nr_on() ? "on" : "off");
}

// "settle 1|0". Switched on over a picture at rest that was owed its runs, they follow now.
// Switched off in the middle of them, the rest of them is owed.
void switch_settle(State& s, bool on) {
  if (on == s.settle) return;
  s.settle = on;
  if (on && s.at_rest && s.rest_owed) {
    s.settle_left = kSettleRuns;
    s.rest_owed = false;
  } else if (!on && s.settle_left > 0) {
    s.settle_left = 0;
    s.rest_owed = true;
  }
  note("loop: the settle is %s", on ? "on" : "off");
}

// "reload": the lens has written new settings into ReShade.ini, the base in the add-on's
// section and each pass's own values, see NrPasses. Only the passes in use are read. The note
// names the base and, for each pass that has values of its own, those values.
void reload_settings(State& s) {
  NrPasses fresh;
  std::string err;
  if (!read_nr_passes(s.o.stack_dir, fresh, err, s.o.passes)) {
    note("loop: reload: %s, the settings stay as they are", err.c_str());
    return;
  }
  if (same_passes(fresh, s.settings, s.o.passes)) return;
  s.settings = fresh;
  s.pipeline.set_settings(fresh);
  s.redraw = true;
  const NrSettings& base = fresh.base();
  std::string own;
  bool all_zero = base.intensity <= 0.0f;
  for (int p = 1; p < s.o.passes && p < kNrMaxPasses; ++p) {
    const std::string text = own_values_text(base, fresh.pass[p]);
    if (!text.empty()) own += strf(", pass %d: %s", p + 1, text.c_str());
    if (fresh.pass[p].intensity > 0.0f) all_zero = false;
  }
  note("loop: settings: style %u, intensity %.2f, local tone %.2f, local structure %.2f, "
       "skin structure %.2f, auto mask %d%s%s",
       base.style, base.intensity, base.local_tone, base.local_structure, base.skin_structure, base.auto_mask,
       own.c_str(), s.network && all_zero ? ". At an intensity of 0 the network does not run" : "");
}

// "quality N": the network works at another size, and the loop does not stand still for it.
//
// The network for the new size takes 118 to 135 ms a pass to make on an RTX 5090. Made on
// this thread, that held the loop. Measured over a moving picture at 120 Hz, the picture
// before the first one at the new size stood for 112 to 157 ms, 13 to 19 refreshes. So it is
// made on a thread of the pipeline's own (Pipeline::begin_work), beside the network in use.
// Two calls into the runtime must never run at once, so while that thread works this one
// makes none. The pictures go on, each the new captured frame with the network's change as
// it stood when the switch began. A picture that moves shows that change a few frames old
// for as long as the making takes. A still picture shows no difference at all. Measured the
// same way over twelve switches, 11 to 17 pictures were drawn while the network was made,
// and the longest any picture stood was 9.6 to 24.8 ms, one to three refreshes.
//
// When the new network is made, the two change places between two pictures
// (Pipeline::commit_work), which waits for the GPU to finish the picture before, and the old
// network and its textures are released. The frame on screen goes through render once more,
// as after "nr", so the change shows at once over a still as well. To the new network the
// whole picture is new. It starts without its history, and at rest the picture settles
// again.
//
// The line is answered on stdout with the step and the work size in use from then on. That
// is said when the step is in use, also when it was in use already, and when the new network
// could not be made and the old one stays. Two steps of a picture size may share a work size,
// and nothing is made then. A line that comes while a switch is under way waits for it to
// land. LENS_FAST_SWITCH_SYNC=1, for tests, makes the network on this thread as before.
void answer_quality(const State& s) {
  if (s.quality >= 0) say("engine quality %d work %dx%d", s.quality, s.work_w, s.work_h);
  else say("engine quality none work %dx%d", s.work_w, s.work_h);
}

// The switch could not be made. The old network stays, and the picture is drawn afresh.
void switch_failed(State& s, const std::string& err) {
  std::string alive;
  if (!s.gpu.alive(alive)) die(s, "quality: " + err);
  note("loop: quality %d, the network for %dx%d could not be made, %s. The work size stays %dx%d", s.switch_to,
       s.switch_w, s.switch_h, err.c_str(), s.work_w, s.work_h);
  s.switching = false;
  s.redraw = true;
  answer_quality(s);
}

// The new network is made. It takes the old one's place, and the next picture is its first.
void land_switch(State& s) {
  std::string err;
  const int state = s.pipeline.work_state(err);
  if (state == 1) return;  // still being made
  if (state != 2) {
    switch_failed(s, state == 3 ? err : std::string("nothing was being made"));
    return;
  }
  step("quality");
  const double t1 = now_s();
  if (!s.pipeline.commit_work(err)) die(s, "quality: " + err);
  const double t2 = now_s();
  step("commands");
  note("loop: quality %d %s, the network works at %dx%d, it was %dx%d. Made in %.0f ms beside the old one "
       "(%.0f ms of it the creation on the CPU), put in use in %.1f ms, %.0f MiB of video memory in use",
       s.switch_to, quality_name(s.switch_to), s.switch_w, s.switch_h, s.work_w, s.work_h,
       (t1 - s.t_asked) * 1000.0, s.pipeline.prepare_ms(), (t2 - t1) * 1000.0,
       (double)s.gpu.vram_bytes() / 1048576.0);
  s.switching = false;
  s.quality = s.switch_to;
  s.work_w = s.switch_w;
  s.work_h = s.switch_h;
  s.redraw = true;
  s.switched = true;
  s.t_stood = s.t_present;
  s.t_landed = t2;
  s.t_memory = t2 + kMemoryNoteAfter;
  s.memory_asked = false;
  s.memory_run = false;
  s.runs_since_switch = 0;
  answer_quality(s);
}

// The memory of the network that a switch replaced comes back only from inside a run of the
// network made some ten seconds after the switch, see kSwitchRuns. Over a still screen the
// loop makes no such run by itself, so kMemoryNoteAfter seconds after a switch a picture at
// rest goes through the network once more, as a settle's run does. A second later the memory
// in use is noted, beside the level before the first switch and the budget the system
// gives this process, for whoever reads the log.
void note_memory(State& s) {
  const double now = now_s();
  // With the settle off a picture at rest is left alone, also here.
  if (!s.memory_asked && s.settle && s.have && !s.paused && s.pipeline.network_runs() &&
      now - s.t_changed > 1.0) {
    s.memory_asked = true;
    s.memory_run = true;
    s.t_memory = now + 1.0;
    return;
  }
  s.t_memory = 0.0;
  note("loop: %.0f MiB of video memory in use %.0f s after the last switch of the quality step, %.0f MiB before "
       "the first, the budget %.0f MiB%s",
       (double)s.gpu.vram_bytes() / 1048576.0, now - s.t_landed, s.memory_before,
       (double)s.gpu.vram_budget_bytes() / 1048576.0,
       s.memory_asked ? ". The picture was at rest and went through the network once more for it" : "");
  s.memory_asked = false;
}

void switch_quality(State& s) {
  const int quality = s.want_quality;
  s.want_quality = -1;
  int w = 0, h = 0;
  quality_work_size(s.o.width, s.o.height, quality, w, h);
  if (w == s.work_w && h == s.work_h) {
    s.quality = quality;
    answer_quality(s);
    return;
  }
  step("quality");
  s.switch_to = quality;
  s.switch_w = w;
  s.switch_h = h;
  s.t_asked = now_s();
  s.held = 0;
  s.gap_most = 0.0;
  if (s.t_memory <= 0.0) s.memory_before = (double)s.gpu.vram_bytes() / 1048576.0;
  std::string err;
  if (s.switch_sync) {
    // on this thread, and the loop stands still until the network is made
    if (!s.pipeline.prepare_work((UINT)w, (UINT)h, err)) {
      switch_failed(s, err);
      mark_turn();
      return;
    }
    mark_turn();  // a long turn, and not a hang
    s.switching = true;
    land_switch(s);
    return;
  }
  if (!s.pipeline.begin_work((UINT)w, (UINT)h, err)) {
    switch_failed(s, err);
    return;
  }
  s.switching = true;
  step("commands");
}

// Every command that has come since the last turn, in the order it came.
void take_commands(State& s) {
  Command c;
  while (!s.quit && s.reader.next(c)) {
    switch (c.kind) {
      case Command::Quit:
        s.quit = true;
        break;
      case Command::Crop:
        move_crop(s, c.x, c.y);
        break;
      case Command::Shot:
        want_shot(s, c.text);
        break;
      case Command::Probe:
        s.probe.begin(c.n);
        break;
      case Command::Pause:
        do_pause(s);
        break;
      case Command::Resume:
        do_resume(s);
        break;
      case Command::Live:
        s.live = c.on;
        break;
      case Command::Wake:
        s.wake_until = now_s() + c.value;
        break;
      case Command::Cap: {
        const double fps = c.value > 0.0 ? c.value : 0.0;
        if (fps != s.limit_fps) {
          s.limit_fps = fps;
          s.want_recapture = true;  // once a turn, however many "cap" lines came
        }
        break;
      }
      case Command::Ready:
        s.ready = c.on;
        break;
      case Command::Clip:
        s.clip = c.on;
        break;
      case Command::StopCapture:
        stop_capture(s);
        break;
      case Command::Nr:
        switch_network(s, c.on);
        break;
      case Command::Reload:
        reload_settings(s);
        break;
      case Command::Settle:
        switch_settle(s, c.on);
        break;
      case Command::Quality:
        s.want_quality = c.n;  // once a turn, the last of them, however many lines came
        break;
    }
  }
}

// ---------------------------------------------------------------- the profile

// Pipeline::take_times() gives the GPU times of every draw the GPU has finished, each once,
// so they are gathered wherever the loop passes: after an ingest, which waits for the queue
// and with it for the draw submitted before, after a read back, before a draw, at the top of
// a turn and before the stats line. A joined draw brings its own ingest's time with it. An
// ingest that was waited for is counted as soon as it returns, the ones that find no change
// too: those are the ones that come back after every present.
void trace_draw_done(State& s, const StageTimes& t);

void read_stage_times(State& s, bool after_ingest) {
  if (!s.o.profile) return;
  Profile& p = s.profile;
  if (after_ingest) {
    p.ingest_ms += s.pipeline.last_ingest_ms();
    p.conv_ms += s.pipeline.last_convert_ms();
    ++p.ingests;
  }
  StageTimes t;
  while (s.pipeline.take_times(t)) {
    p.composite_ms += t.composite_ms;
    ++p.draws;
    if (t.ran_network) {
      p.nr_ms += t.nr_ms;
      ++p.nr_runs;
    }
    if (t.joined) {
      p.ingest_ms += t.ingest_ms;
      p.conv_ms += t.convert_ms;
      ++p.ingests;
    }
    if (s.trace.file) trace_draw_done(s, t);
  }
}

// A draw was submitted: noted by its number for the G line once its times come back. The
// ingest's timestamps are the last ingest()'s, which led to a new or an again draw.
void trace_draw_noted(State& s, const char* kind, bool with_frame, double submitted, bool own_ingest) {
  Trace& t = s.trace;
  if (!t.file) return;
  Trace::DrawNote& n = t.draws[s.pipeline.last_draw_sequence() % Trace::kDrawNotes];
  n.sequence = s.pipeline.last_draw_sequence();
  n.kind = kind;
  n.stamp = with_frame ? s.cur.timestamp_s : 0.0;
  n.arrived = with_frame ? s.cur.arrived_s : 0.0;
  n.submitted = submitted;
  if (own_ingest) {
    s.pipeline.last_ingest_ticks(n.ingest);
  } else {
    n.ingest[0] = n.ingest[1] = n.ingest[2] = 0;
  }
}

// The G line of a draw the card has finished, its ticks put on now_s()'s clock.
void trace_draw_done(State& s, const StageTimes& t) {
  Trace& tr = s.trace;
  if (t.sequence == 0) return;
  const Trace::DrawNote& n = tr.draws[t.sequence % Trace::kDrawNotes];
  if (n.sequence != t.sequence) return;
  const double now = now_s();
  if (tr.cal_at == 0.0 || now - tr.cal_at > 1.0) {
    if (s.gpu.clock_pair(tr.cal_gpu, tr.cal_cpu_s)) tr.cal_at = now;
  }
  if (tr.cal_at == 0.0 || s.gpu.timestamp_hz == 0) return;
  const auto moment = [&](UINT64 tick) {
    return tick == 0 ? 0.0 : tr.cal_cpu_s + ((double)tick - (double)tr.cal_gpu) / (double)s.gpu.timestamp_hz;
  };
  const UINT64* ingest = t.joined ? t.ticks : n.ingest;
  fprintf(tr.file, "G %llu %s %.6f %.6f %.6f %.6f %.6f %.6f %.6f %.6f %.6f %.6f %.6f\n",
          (unsigned long long)t.sequence, n.kind, n.stamp, n.arrived, n.submitted, moment(ingest[0]),
          moment(ingest[1]), moment(ingest[2]), moment(t.ticks[0]), moment(t.ticks[1]), moment(t.ticks[2]),
          moment(t.ticks[3]), moment(t.ticks[4]));
}

// ---------------------------------------------------------------- where a present went

// The median of the values, the upper one of an even count, NaN of none. It sorts them.
double median_of(std::vector<double>& values) {
  if (values.empty()) return std::nan("");
  std::sort(values.begin(), values.end());
  return values[values.size() / 2];
}

// A number for the stats line, "nan" spelled out as for the meter.
std::string number_text(double value, const char* format = "%.1f") {
  return std::isnan(value) ? std::string("nan") : strf(format, value);
}

// A present has just been made. It is noted with its number, so the statistics can name it
// once the display has shown it.
void trace_present(State& s, bool fresh, double called) {
  Trace& t = s.trace;
  Trace::Made& m = t.made[t.next];
  t.next = (t.next + 1) % Trace::kMade;
  m.id = s.window.present_id();
  m.called = called;
  m.stamp = fresh ? s.cur.timestamp_s : 0.0;
  m.arrived = fresh ? s.cur.arrived_s : 0.0;
  if (fresh && s.o.profile) {
    t.ahead.push_back((s.cur.timestamp_s - s.cur.arrived_s) * 1000.0);
    t.stamps.push_back(s.cur.timestamp_s);
  }
  if (t.file) {
    fprintf(t.file, "P %u %.6f %.6f %.6f\n", m.id, called, m.stamp, fresh ? s.cur.arrived_s : 0.0);
  }
  // A present is on screen within two refreshes. The loop usually turns before that and
  // asks then. After a lone new picture over a still screen this is what makes it ask, and
  // with the profile on after a repeated one too.
  if (fresh || s.o.profile) t.t_ask = called + 3.0 / s.refresh_hz;
}

// With the profile on, the compositor's frames are gathered as they complete, for the
// stats line's account of where the frames' timestamps lie, see trace_text().
void trace_compositor(State& s) {
  Trace& t = s.trace;
  const size_t had = t.frames.size();
  t.frames_known = Window::compositor_frames(t.frames);
  // Frames the compositor itself presented to this window's display, which is the one whose
  // refreshes are as far apart as the swapchain's. Where the engine's picture covers all
  // that changes and is shown directly, the compositor has nothing to present. It presented 8
  // of 3188 frames over the full-size test, where a composed window makes it present each.
  const double period = t.period > 0.0 ? t.period : 1.0 / s.refresh_hz;
  for (size_t i = had; i < t.frames.size(); ++i) {
    const CompositorFrame& f = t.frames[i];
    const CompositorFrame::Target* ours = nullptr;
    for (int k = 0; k < f.targets; ++k) {
      const CompositorFrame::Target& d = f.target[k];
      if (!ours || std::fabs(d.vblank_s - period) < std::fabs(ours->vblank_s - period)) ours = &d;
    }
    if (ours && ours->present_s > 0.0) ++t.composed;
  }
  if (t.file) {
    for (size_t i = had; i < t.frames.size(); ++i) {
      const CompositorFrame& f = t.frames[i];
      fprintf(t.file, "C %llu %.6f %.6f %.6f %d", (unsigned long long)f.id, f.start_s, f.target_s,
              f.period_s, f.targets);
      for (int k = 0; k < f.targets; ++k) {
        const CompositorFrame::Target& d = f.target[k];
        fprintf(t.file, " %u %.6f %.6f %u %.6f", d.source, d.present_s, d.shown_s, d.refresh,
                d.vblank_s);
      }
      fprintf(t.file, "\n");
    }
  }
  if (t.frames.size() > 1024) t.frames.erase(t.frames.begin(), t.frames.end() - 512);
}

// The display has shown a new picture at the moment `at`. Whether it was late, and when
// enough of them were, the order to leave one frame out, see kLateAfter. period is one
// refresh.
void judge_late(State& s, const Trace::Made& m, double at, double period) {
  if (!s.leave_allowed || m.arrived <= 0.0 || m.stamp < s.late_from) return;
  // a timestamp half a second from the clock is not a refresh, whatever it is, see capture.cpp
  if (std::fabs(m.stamp - m.arrived) > 0.5) return;
  // The first refresh after the frame arrived. The frame's timestamp is a refresh, so that
  // one lies a whole number of refreshes from it.
  const double first = m.stamp - std::floor((m.stamp - m.arrived) / period) * period;
  const int steps = (int)std::floor((at - first) / period + 0.5);
  const double waited = m.called - m.arrived;
  const double room = first - m.arrived;
  const bool late =
      s.late_always || steps >= 2 || (steps == 1 && waited < 2.0 * room - (1.0 + kLateRoom) * period);
  if (s.left_steps >= 0) {
    // the first picture since a frame was left out
    if (steps < s.left_steps) {
      note("loop: since that frame was left out the pictures are shown %d refresh%s sooner", s.left_steps - steps,
           s.left_steps - steps == 1 ? "" : "es");
    } else {
      note("loop: the frame left out did not help, the pictures are shown as late as before");
    }
    s.left_steps = -1;
  }
  if (!late) {
    s.late_run = 0;
    return;
  }
  // No picture was late for kLateSoon, so whatever frame was left out before did help, and
  // the wait is the first one again.
  if (s.t_last_late > 0.0 && m.called - s.t_last_late > kLateSoon) s.late_need_s = kLateAfter;
  s.t_last_late = m.called;
  if (s.late_run == 0) s.t_late = m.called;
  ++s.late_run;
  s.late_steps = steps;
  // How long the run must last. Pictures that are less late than they were before the last
  // frame left out are on their way down, and wait no longer than the first time.
  const double wait = steps < s.left_before ? kLateAfter : s.late_need_s;
  if (s.leave_out || s.leaving || s.late_run < std::max(8, (int)(wait * s.refresh_hz + 0.5))) return;
  note("loop: the pictures of the last %.0f ms were shown %d refresh%s after the first one their frames could have "
       "made (a present call %.1f ms after its frame's arrival, that refresh %.1f ms after it). One frame is left out",
       (m.called - s.t_late) * 1000.0, steps, steps == 1 ? "" : "es", waited * 1000.0, room * 1000.0);
  // The next one waits twice as long, until the pictures have been on time for a while. A
  // frame left out on the way down does not shorten a wait that was longer already.
  s.late_need_s = std::max(s.late_need_s, std::min(2.0 * wait, kLateMost));
  s.leave_out = true;
  s.leave_by = now_s() + 2.0 / s.refresh_hz;
  s.late_run = 0;
  // what was presented up to now belongs to the chain this ends, whenever it is shown
  s.late_from = s.last_stamp + 0.5 * period;
}

// Asks the statistics which present the display showed last, and when. They answer for one
// present at a time, the newest shown, so this runs every turn. A present they never name
// was replaced by a newer one before a refresh came, or shown and gone between two turns.
void trace_look(State& s, double now) {
  Trace& t = s.trace;
  if (t.t_ask > 0.0 && now >= t.t_ask) {
    // once more two refreshes on, while a present of the last 150 ms is still unnamed
    bool open = false;
    for (const Trace::Made& m : t.made) open = open || (m.id != 0 && now - m.called < 0.15);
    t.t_ask = open ? now + 2.0 / s.refresh_hz : 0.0;
  }
  if (s.o.profile) trace_compositor(s);
  PresentShown shown;
  if (!s.window.shown(shown)) return;
  if (t.file && (shown.id != t.seen || shown.sync_refresh != t.file_refresh)) {
    t.file_refresh = shown.sync_refresh;
    fprintf(t.file, "S %u %u %u %.6f %.6f\n", shown.id, shown.refresh, shown.sync_refresh,
            shown.sync_s, now);
  }

  // One refresh as the statistics count it, measured over a second or so of refreshes. The
  // mode's rate is a whole number, and the display's own period was 8.3338 ms (119.994 Hz)
  // where the mode said 120.
  if (t.base_s <= 0.0 || shown.sync_refresh < t.base_refresh) {
    t.base_refresh = shown.sync_refresh;
    t.base_s = shown.sync_s;
  } else if (shown.sync_refresh - t.base_refresh >= 100) {
    const double period = (shown.sync_s - t.base_s) / (double)(shown.sync_refresh - t.base_refresh);
    if (period > 0.001 && period < 0.1) {
      if (t.period <= 0.0 && s.o.profile) {
        note("loop: one refresh is %.4f ms by the display's statistics, the mode says %.0f Hz",
             period * 1000.0, s.refresh_hz);
      }
      t.period = period;
    }
    t.base_refresh = shown.sync_refresh;
    t.base_s = shown.sync_s;
  }
  if (shown.id == t.seen) return;
  t.seen = shown.id;

  const double period = t.period > 0.0 ? t.period : 1.0 / s.refresh_hz;
  for (Trace::Made& m : t.made) {
    if (m.id != shown.id) continue;
    // the refresh that showed it lies so many refreshes before the statistics' sample
    const double at = shown.sync_s + (double)(int)(shown.refresh - shown.sync_refresh) * period;
    ++t.shown;
    t.flip.push_back((at - m.called) * 1000.0);
    if (m.stamp > 0.0) {
      const double after = at - m.stamp;
      t.delay.push_back(after * 1000.0);
      // counted from one refresh before the frame's own, which is where a picture shown
      // directly lands when the compositor works two refreshes ahead
      const int refreshes = (int)std::floor(after / period + 0.5);
      ++t.behind[std::clamp(refreshes + 1, 0, 4)];
      const double off = (m.stamp - shown.sync_s) / period;
      t.grid.push_back(std::fabs(off - std::floor(off + 0.5)) * period * 1000.0);
      judge_late(s, m, at, period);
    }
    m.id = 0;
    break;
  }
}

// The profile's account of the second, as pairs for the stats line. Keys only ever get added
// at the end of this.
//   shown    presents the display's statistics named
//   behind   five counts of new pictures by the refresh that showed them: one refresh before
//            their frame's own timestamp or earlier, at it, one after, two after, three or
//            more after
//   flip     ms from the present call to the refresh that showed it
//   ahead    ms a frame's timestamp lay ahead of the moment the capture delivered it
//   grid     ms from the timestamp to the nearest refresh of the display
//   target   ms from the timestamp to the nearest refresh a compositor frame was made for
//   lead     ms the compositor began that frame before the refresh it was made for
//   settled  of the repeated pictures, the settle's runs of the network
//   composed compositor frames that the compositor itself presented to this display
//   echo     ms, the longest a frame equal to the last took to come after a repeat that
//            stood alone, which is a composed repeat's own frame, see watch_path()
//   left     frames the loop left out because the pictures were shown late, see kLateAfter.
//            They are among the dropped ones
std::string trace_text(State& s) {
  Trace& t = s.trace;
  std::vector<double> target, lead;
  if (t.frames_known) {
    const double period = t.period > 0.0 ? t.period : 1.0 / s.refresh_hz;
    std::vector<double> waiting;
    for (const double stamp : t.stamps) {
      const CompositorFrame* best = nullptr;
      for (const CompositorFrame& f : t.frames) {
        if (!best || std::fabs(f.target_s - stamp) < std::fabs(best->target_s - stamp)) best = &f;
      }
      if (!best || std::fabs(best->target_s - stamp) > 0.5 * period) {
        // Its compositor frame is not complete yet. It is looked at again next second,
        // unless it is older than every frame known by then.
        if (!t.frames.empty() && stamp > t.frames.back().target_s) waiting.push_back(stamp);
        continue;
      }
      target.push_back((stamp - best->target_s) * 1000.0);
      lead.push_back((best->target_s - best->start_s) * 1000.0);
    }
    t.stamps.swap(waiting);
  } else {
    t.stamps.clear();
  }
  std::string text = strf(" shown=%d behind=%d,%d,%d,%d,%d", t.shown, t.behind[0], t.behind[1],
                          t.behind[2], t.behind[3], t.behind[4]);
  text += " flip=" + number_text(median_of(t.flip));
  text += " ahead=" + number_text(median_of(t.ahead));
  text += " grid=" + number_text(median_of(t.grid), "%.2f");
  text += " target=" + number_text(median_of(target), "%.2f");
  text += " lead=" + number_text(median_of(lead));
  text += strf(" settled=%d composed=%d", s.settled, t.composed);
  text += " echo=" + number_text(t.echo_ms > 0.0 ? t.echo_ms : NAN);
  text += strf(" left=%d", s.left);
  if (t.file) fflush(t.file);
  return text;
}

// The second's figures start again.
void trace_reset(Trace& t) {
  t.echo_ms = 0.0;
  t.composed = 0;
  t.shown = 0;
  for (int& n : t.behind) n = 0;
  t.delay.clear();
  t.flip.clear();
  t.ahead.clear();
  t.grid.clear();
}

// ---------------------------------------------------------------- the screenshot and the probe

// Writes one screenshot's files and says the reply. Its own thread, because encoding three
// PNGs of a fullscreen picture takes long enough to hold up the window's messages and to
// look like a hang to the watchdog. It touches no GPU and none of the loop's state.
DWORD WINAPI shot_thread(void* arg) {
  Shot* shot = static_cast<Shot*>(arg);
  const std::string reply = save_shot(*shot);
  delete shot;
  // free for the next request before the lens hears of this one, so a request that
  // follows the reply at once is not told "busy"
  g_shot_busy.store(false);
  say("%s", reply.c_str());
  return 0;
}

// The present just made was drawn with keep_copy for a screenshot: the captured frame and
// what was drawn from it are read back, both from this one present, and handed to the
// writer. The two reads block until the GPU has finished the frame and turn 62 MB each into
// tight RGB at 6144x2526, on this thread: the pipeline belongs to it.
void take_shot(State& s) {
  s.shot_wanted = false;
  Shot* shot = new (std::nothrow) Shot;
  if (!shot) {
    say("shot failed out of memory");
    return;
  }
  shot->base = s.shot_base;
  shot->width = s.o.width;
  shot->height = s.o.height;
  shot->clipboard = s.clip;
  std::string err;
  if (!s.pipeline.read_native(shot->before, err)) {
    say("shot failed %s", err.c_str());
    delete shot;
    return;
  }
  if (!s.pipeline.read_target(shot->after, err)) {
    // the captured frame alone is still worth saving, as the Python loop saved it
    note("loop: the screenshot has no after picture: %s", err.c_str());
    shot->after.clear();
  }
  // LENS_FAST_SHOT_RAW=1: the 16-bit frame as it came, when there is one
  if (s.shot_raw && !s.pipeline.read_raw(shot->raw, err)) shot->raw.clear();
  if (s.shot_raw && !s.pipeline.read_target_raw(shot->out, err)) shot->out.clear();
  g_shot_busy.store(true);
  HANDLE thread = nullptr;
  if (!start_thread(shot_thread, shot, &thread)) {
    g_shot_busy.store(false);
    delete shot;
    say("shot failed the writer could not be started");
    return;
  }
  if (s.shot_thread) CloseHandle(s.shot_thread);
  s.shot_thread = thread;
}

// The present just made was drawn with keep_copy for a probe: every 4th texel each way is
// read back and compared with the picture before it. Over a still these are repaints of one
// picture and the differences are 0: a repeat does not run the network, so nothing flickers.
void feed_probe(State& s) {
  std::string err;
  UINT w = 0, h = 0;
  if (!s.pipeline.read_target_sparse(s.sparse, w, h, err)) {
    // the reply in the protocol's own shape, so whoever waits for it is answered
    note("loop: the probe could not read the picture back: %s", err.c_str());
    s.probe.begin(0);
    say("probe n=0 median=nan max=nan");
    return;
  }
  std::string reply;
  if (s.probe.add(s.sparse, reply)) {
    s.probe.begin(0);  // over, whatever add() left behind: a probe that never ends would
                       // keep the loop at the display's rate for good
    say("%s", reply.c_str());
  }
}

// ---------------------------------------------------------------- one picture

// The first picture has been presented while the window was hidden: now it may be seen.
// Whether a picture presented while hidden is on screen at the moment of showing is not
// something to rely on, so it is presented once more, which also gives the second back
// buffer its picture. Then the lens is told. It finds the window by its class as soon as it
// is visible.
void first_picture(State& s) {
  step("show");
  s.window.show();
  std::string err;
  Target target;
  step("back buffer");
  if (!s.window.back_buffer(target, err)) die(s, "back buffer: " + err);
  step("repaint");
  if (!s.pipeline.repaint(target, false, err)) die(s, "repaint: " + err);
  step("present");
  if (!s.window.present(err)) die(s, "present: " + err);
  s.t_present = now_s();
  trace_present(s, false, s.t_present);
  ++s.repeated;
  s.shown = true;
  // The quality step in use is one part of the line, which the lens takes by its name. It is
  // "quality N" with nothing after the number. Where an option gave the work size itself
  // there is no step, and the part says that. The last part is the monitor's colour state,
  // "hdr off" or "hdr on", see read_colour(). The format is the swapchain's: 87
  // (B8G8R8A8_UNORM), or 10 (R16G16B16A16_FLOAT) with Windows HDR on for the monitor.
  const std::string quality =
      s.quality >= 0 ? strf("quality %d", s.quality) : std::string("quality none, the work size was given");
  say("presenter ready %dx%d at (%d,%d) on %s, format %d, present mode flip-discard, %u images, "
      "readback yes, source %s, version " LENS_FAST_VERSION ", engine fast, work %dx%d, passes %d, %s, hdr %s",
      s.o.width, s.o.height, s.o.x, s.o.y, s.gpu.name.c_str(), (int)s.window.format(),
      Window::kBuffers, s.o.source.c_str(), s.work_w, s.work_h, s.network ? s.o.passes : 0,
      quality.c_str(), s.colour.hdr ? "on" : "off");
  note("loop: the first picture is on screen %.0f ms after the process began",
       (s.t_present - g_born) * 1000.0);
}

// Draws one picture into the back buffer and presents it. The pipeline submits and does not
// wait, and the present is queued behind the draw, so the call returns while the GPU works.
void draw(State& s, Draw how) {
  std::string err;
  Target target;
  step("back buffer");
  if (!s.window.back_buffer(target, err)) die(s, "back buffer: " + err);

  // A screenshot or a probe reads this picture back: the copies are made on the GPU as
  // part of the draw, before the present. The buffers they go into are made at the first
  // use. When there is no memory for them it is the screenshot or the probe that fails, and
  // the picture is drawn all the same.
  bool keep = s.shot_wanted || s.probe.left > 0;
  if (keep && !s.pipeline.prepare_copies(target.format, err)) {
    note("loop: the picture cannot be read back: %s", err.c_str());
    if (s.shot_wanted) {
      s.shot_wanted = false;
      say("shot failed out of memory");
    }
    if (s.probe.left > 0) {
      s.probe.begin(0);
      say("probe n=0 median=nan max=nan");
    }
    keep = false;
  }
  double t_sub = now_s();
  // whatever draw before this one the GPU has finished is read now, before this one takes
  // its context
  read_stage_times(s, false);
  bool ran_network = false;
  if (how == Draw::Repaint) {
    step("repaint");
    if (!s.pipeline.repaint(target, keep, err)) die(s, "repaint: " + err);
    trace_draw_noted(s, "repaint", false, now_s(), false);
  } else if (how == Draw::Joined) {
    // The frame just taken, not compared: its ingest, the network and the composite in one
    // list, submitted and not waited for, see kJoinAfter. The picture the network starts
    // without its history is new to it as a whole, as below.
    if (s.reset_next) {
      for (uint8_t& tile : s.moved) tile = 1;
    }
    step("joined");
    if (!s.pipeline.render_joined(s.cur.texture, s.joined_prev, s.capture.fence(), s.cur.fence_value, target,
                                  s.reset_next, keep, err)) {
      die(s, "joined: " + err);
    }
    const double t_done = now_s();
    trace_draw_noted(s, "joined", true, t_done, false);
    if (s.o.profile && s.cur.arrived_s > 0.0) {
      s.profile.wake_ms += (t_sub - s.cur.arrived_s) * 1000.0;
      s.profile.wall_ms += (t_done - t_sub) * 1000.0;
      s.profile.cwait_ms += s.pipeline.last_copy_wait_ms();
      ++s.profile.timed;
    }
    ++s.profile.joined;
    // the list reads both frames: their slots are not written before it is done
    s.capture.note_read(s.cur, s.gpu.fence_value);
    if (s.joined_prev) {
      CaptureFrame before;
      before.texture = s.joined_prev;
      s.capture.note_read(before, s.gpu.fence_value);
    }
    s.joined.push_back({s.cur, 0.0});
    if (t_done - t_sub > 0.25) note("loop: a joined draw call took %.0f ms", (t_done - t_sub) * 1000.0);
    s.reset_next = false;
    s.redraw = false;
    s.have = true;
    ran_network = s.pipeline.network_runs();
    if (ran_network && s.runs_since_switch < kSwitchRuns) ++s.runs_since_switch;
  } else {
    if (how == Draw::Again) {
      // With no frame to compare it with, ingest prepares the frame on screen as if it
      // were new, and render may follow.
      bool changed = false;
      step("ingest again");
      if (!s.pipeline.ingest(s.cur.texture, nullptr, s.capture.fence(), s.cur.fence_value, changed,
                             err)) {
        die(s, "ingest: " + err);
      }
      read_stage_times(s, true);
      t_sub = now_s();
      // to the network the whole picture is new, so it settles again once at rest
      s.pipeline.add_changed_tiles(s.moved);
      s.at_rest = false;
      s.settle_left = 0;
    }
    // New and Again follow an ingest of this frame. Settle needs none. The network's input
    // still holds this frame, downscaled, since an ingest that found no change wrote the
    // same texels again.
    // A picture the network starts without its history, after a pause or a jump of the crop,
    // is new to it as a whole, however little of the frame differs. So it settles once at rest.
    if (s.reset_next) {
      for (uint8_t& tile : s.moved) tile = 1;
    }
    step("render");
    if (!s.pipeline.render(s.cur.texture, target, s.reset_next, keep, err)) {
      die(s, "render: " + err);
    }
    trace_draw_noted(s, how == Draw::New ? "new" : how == Draw::Again ? "again" : "settle", how == Draw::New,
                     now_s(), how != Draw::Settle);
    // the composite reads the frame: its slot is not written before the list is done
    s.capture.note_read(s.cur, s.gpu.fence_value);
    // A slow call says so: the first network run at a new size is the suspect, and the
    // watchdog only sees the loop stand still.
    const double took = (now_s() - t_sub) * 1000.0;
    if (took > 250.0) note("loop: a render call took %.0f ms", took);
    s.reset_next = false;
    s.redraw = false;
    s.have = true;
    ran_network = s.pipeline.network_runs();
    if (ran_network && s.runs_since_switch < kSwitchRuns) ++s.runs_since_switch;
  }

  const double t0 = now_s();
  step("present");
  if (!s.window.present(err)) die(s, "present: " + err);
  const double t1 = now_s();
  if (t1 - t0 > 0.25) note("loop: a present call took %.0f ms", (t1 - t0) * 1000.0);
  // Presents that follow one another within two refreshes are a run at the display's rate.
  // A run of kRunSeconds puts the swapchain on the direct path as a burst does, new
  // pictures as well as repeats, so the repeats that follow are judged afresh, see
  // watch_path().
  const bool alone = t1 - s.t_present >= echo_within(s);
  if (t1 - s.t_present > 2.5 / s.refresh_hz) s.t_run = t1;
  else if (t1 - s.t_run >= kRunSeconds) s.composed = false;
  // A switch of the quality step, from its line to the first picture at the new work size:
  // how many pictures were drawn meanwhile, and the longest any of them stood on screen.
  const bool fresh = how == Draw::New || how == Draw::Joined;
  if (s.switching || s.switched) {
    s.gap_most = std::max(s.gap_most, t1 - s.t_present);
    if (s.switching && how != Draw::Repaint) ++s.held;
  }
  if (s.switched && how != Draw::Repaint) {
    s.switched = false;
    note("loop: quality %d, the first picture at %dx%d was presented %.0f ms after the line was taken up. %d "
         "pictures were drawn meanwhile with the network's change as it stood. The picture before the first had "
         "stood for %.1f ms, and the longest any picture stood in that time was %.1f ms",
         s.quality, s.work_w, s.work_h, (t1 - s.t_asked) * 1000.0, s.held, (t1 - s.t_stood) * 1000.0,
         s.gap_most * 1000.0);
  }
  s.t_present = t1;
  s.progress = true;
  s.repaint_once = false;
  trace_present(s, fresh, t1);
  s.profile.present_ms += (t1 - t0) * 1000.0;
  ++s.profile.presents;

  if (fresh) {
    // The meter: the present call against the capture's own timestamp, which names the
    // composition the frame belongs to. Both are on now_s()'s clock. A joined picture's
    // entry, and its count as new and as late, wait for its answer, see resolve_joined():
    // they then fall in the line of the second the answer came in, a turn later at most,
    // and never have to be taken out of a line that has gone out.
    if (how == Draw::Joined && !s.joined.empty()) {
      s.joined.back().meter = (t1 - s.cur.timestamp_s) * 1000.0;
      s.joined.back().late = s.cur_was_held;
    } else {
      s.meter.push_back((t1 - s.cur.timestamp_s) * 1000.0);
      ++s.fresh;
      if (s.cur_was_held) ++s.late;
    }
    s.t_new = t1;
    s.t_changed = t1;
    s.echoes = 0;
    s.repeat_open = false;
    // A frame that does not follow the last one at the next refresh has ended whatever run
    // of late pictures there was, since a refresh went by without a render, see kLateAfter.
    // The pictures from before it are no longer judged.
    const double refresh = s.trace.period > 0.0 ? s.trace.period : 1.0 / s.refresh_hz;
    if (s.cur.timestamp_s - s.last_stamp > 1.5 * refresh) {
      s.late_run = 0;
      s.late_from = s.cur.timestamp_s - 0.5 * refresh;
    }
    s.last_stamp = s.cur.timestamp_s;
  } else {
    ++s.repeated;
    if (how == Draw::Again) s.t_changed = t1;
    if (how == Draw::Settle) {
      if (s.settle_left > 0) --s.settle_left;
      ++s.settled;
    }
    // Which path the repeats take, see watch_path(). The repeat before this one brought no
    // frame back from the capture, so it was shown directly. Only a repeat that stands alone
    // is asked, one that comes after the present before it could have had its frame back.
    // The settle's runs and a burst's repeats come a refresh apart, and which of them a
    // frame belongs to cannot be told.
    if (s.repeat_open && t1 - s.t_repeat >= echo_within(s)) repeat_was_direct(s);
    s.repeat_open = alone;
    s.t_repeat = t1;
  }

  // The reads come before anything else is drawn: a draw without keep_copy forgets the
  // copies of this one.
  if (keep) {
    step("read back");
    if (s.shot_wanted) take_shot(s);
    if (s.probe.left > 0) feed_probe(s);
    read_stage_times(s, false);
  }
  if (!s.shown) first_picture(s);
}

// Takes the newest frame from the capture and finds out whether it shows anything new.
// Returns true when it did, and the new picture has then been presented. While the frames
// keep changing it is drawn before that is known, see kJoinAfter, and true then means it
// was presented.
//
// Every frame taken goes through ingest, changed or not. The pipeline keeps no copy of the
// captured picture: it draws repaints from the newest frame it was given, and the capture
// takes the one before back at the next acquire. A frame acquired and not ingested would
// leave the pipeline drawing from a slot the capture is about to write.
//
// The last draw is waited for before the frame is taken. The ingest waits for the card in
// any case, and the queue runs in order, so a frame taken while the draw before it still
// runs waits behind that draw, and the picture made of it is older by as long as the draw
// took. Over a game that keeps the card busy a draw can take a few refreshes, and frames
// that arrived meanwhile would then wait their turn behind an older one. Waited for first,
// the frame taken is the newest one the capture has at the moment the card can start on it,
// and the ones before it count as dropped. While a draw ends within a refresh, as it does
// over a free card, the wait finds it done and costs a read of the fence. The limit's rule,
// the frame it keeps back, the settle and the repeats are as they were: the capture judges
// frames as they arrive, and this only moves the moment the loop takes one.
// The answers of the joined draws the GPU has finished, see kJoinAfter: a frame that
// differed counts as a new picture now, in the meter and the line, with its tiles kept for
// the settle, and a frame that was the same as the last is counted as the careful way
// counts it, as a repeat of the picture and a skipped frame, with its turn given back (the
// frame's own, or the one before it when the echo of its present has taken a turn since,
// see Capture::turn_back) and the capture's echo bookkeeping of take_frame(). Every turn
// passes here, so an answer waits a turn at most.
void resolve_joined(State& s) {
  bool changed = false;
  uint8_t tiles[Pipeline::kTiles];
  for (;;) {
    for (uint8_t& tile : tiles) tile = 0;
    if (!s.pipeline.take_flag(changed, tiles)) return;
    State::Joined done;
    const bool known = !s.joined.empty();
    if (known) {
      done = s.joined.front();
      s.joined.erase(s.joined.begin());
    }
    if (changed) {
      ++s.changed_run;
      for (int i = 0; i < Pipeline::kTiles; ++i) {
        if (tiles[i]) s.moved[i] = 1;
      }
      if (known) {
        s.meter.push_back(done.meter);
        ++s.fresh;
        if (done.late) ++s.late;
      }
      continue;
    }
    s.changed_run = 0;
    ++s.profile.same;
    ++s.skipped;
    ++s.repeated;
    s.capture.turn_back(done.frame);
    s.t_back = done.frame.arrived_s;
    s.echoes = 0;
    s.repeat_open = false;
  }
}

// Whether the frame just taken goes the joined way, see kJoinAfter: the frames before it
// were found changed often enough in a row, every answer is in, and there is a frame
// before it to compare with.
bool join_now(const State& s, ID3D12Resource* before) {
  return s.join_after > 0 && before != nullptr && s.changed_run >= s.join_after && s.joined.empty();
}

bool take_frame(State& s) {
  CaptureFrame frame;
  std::string err;
  step("wait draw");
  const double t_wait = now_s();
  if (!s.pipeline.wait_drawn(err)) die(s, "wait for the draw: " + err);
  if (s.o.profile) {
    s.profile.dwait_ms += (now_s() - t_wait) * 1000.0;
    ++s.profile.dwaits;
  }
  // the last draw is done, so the answer of a joined one is in
  resolve_joined(s);
  read_stage_times(s, false);
  step("acquire");
  if (!s.capture.acquire(frame)) return false;
  s.progress = true;
  s.t_fit = now_s();
  if (!s.have_cur) {
    note("loop: the first frame was taken %.0f ms after the process began", (s.t_fit - g_born) * 1000.0);
  }
  if (s.t_recapture > 0.0) {
    note("loop: the first frame under the new limit came %.1f ms after it", (s.t_fit - s.t_recapture) * 1000.0);
    s.t_recapture = 0.0;
  }

  // The frame handed out before this one stays valid and unchanged through this acquire,
  // so the two can be compared. Null for the first: it is drawn whatever it holds.
  ID3D12Resource* before = s.have_cur ? s.cur.texture : nullptr;
  if (join_now(s, before)) {
    // The joined way: drawn and presented at once, compared on the way, see kJoinAfter.
    // Whatever the settle still had to do for the picture before is over, and where this
    // frame differs is learned with the answer.
    s.cur = frame;
    s.have_cur = true;
    s.joined_prev = before;
    s.at_rest = false;
    s.settle_left = 0;
    if (s.stall_ms > 0.0 && now_s() >= s.t_stall) {
      // a test's own hiccup, see LENS_FAST_STALL
      Sleep((DWORD)s.stall_ms);
      s.t_stall = now_s() + s.stall_every;
    }
    draw(s, Draw::Joined);
    return true;
  }
  bool changed = false;
  step("ingest");
  const double t_in = now_s();
  if (!s.pipeline.ingest(frame.texture, before, s.capture.fence(), frame.fence_value, changed,
                         err)) {
    die(s, "ingest: " + err);
  }
  if (s.o.profile && frame.arrived_s > 0.0) {
    s.profile.wake_ms += (t_in - frame.arrived_s) * 1000.0;
    s.profile.wall_ms += (now_s() - t_in) * 1000.0;
    s.profile.cwait_ms += s.pipeline.last_copy_wait_ms();
    ++s.profile.timed;
  }
  s.cur = frame;
  s.have_cur = true;
  read_stage_times(s, true);

  // The same as the last: what every present of this window comes back as, since the
  // window is excluded from capture. Nothing runs for it, which is the point: over a still
  // screen the network rests. Under a limit it gives its turn back, so a picture that
  // repeats does not cost the next new one its turn.
  if (!changed) {
    s.changed_run = 0;
    ++s.skipped;
    s.capture.turn_back(frame);
    // A repeat that comes back like this, within a few refreshes, was composed. A frame like
    // this at any other time has another cause. Something else on the monitor changed, or
    // the pointer moved, which brings 120 such frames a second. The repeats' own frames
    // cannot be told from those, so the count starts again. See watch_path().
    const double after = frame.arrived_s - s.t_repeat;
    s.t_back = frame.arrived_s;
    if (s.repeat_open) s.trace.echo_ms = std::max(s.trace.echo_ms, after * 1000.0);
    if (s.repeat_open && after >= 0.0 && after <= echo_within(s)) {
      ++s.echoes;
    } else if (s.repeat_open && after > echo_within(s)) {
      repeat_was_direct(s);
    } else {
      s.echoes = 0;
    }
    s.repeat_open = false;
    return false;
  }
  // The picture is changing. Whatever the settle still had to do for the one before is
  // over, and where this frame differs is kept for when the picture next comes to rest.
  ++s.changed_run;
  s.pipeline.add_changed_tiles(s.moved);
  s.at_rest = false;
  s.settle_left = 0;
  if (s.stall_ms > 0.0 && now_s() >= s.t_stall) {
    // a test's own hiccup, see LENS_FAST_STALL
    Sleep((DWORD)s.stall_ms);
    s.t_stall = now_s() + s.stall_every;
  }
  draw(s, Draw::New);
  return true;
}

// ---------------------------------------------------------------- the stats line

// "stats new=N arrived=N repeated=N dropped=N skipped=N meter=MS delay=MS", once a second,
// and the counters start again. Then, once for each loss, the reason when the capture counts
// as lost. The loop goes on showing its last picture and the lens starts a new presenter,
// unless frames have come back by then.
//
// meter is the present call against the captured frame's timestamp, as lens_presenter.py
// reports it. It is negative here. The timestamp is the refresh the compositor made the
// frame for, which is still to come when the frame arrives, and how far ahead it lies
// depends on the displays connected. The compositor began a frame one refresh before that
// refresh with one monitor and two refreshes before it with a second monitor beside it, and
// the meter read -6.6 ms and -15.0 ms for the same work.
// delay is the figure for a person. It runs from that timestamp to the refresh that showed
// the picture made of the frame, by the display's own statistics, the median of the second.
// It is negative when the picture is on screen before the frame's own refresh, which it is
// with the second monitor connected. The engine's presents are shown directly, at the next
// refresh, where the compositor's own picture of the same frame takes two. Measured there
// over 4859 pictures, 4711 were shown one refresh before their frame's own (-8.3 ms), 142
// at it, and 6 later. "nan" when no new picture's showing was learned.
void report(State& s, double now) {
  const CaptureCounters c = s.capture.take_counters();
  // the answers and the times of what the GPU has finished go into this second's line
  resolve_joined(s);
  read_stage_times(s, false);

  // The median of the second, the upper one of an even count, as the Python loop took it.
  // "nan" is spelled out, since the lens reads the number with Python's float(), which does
  // not know the "-nan(ind)" this runtime prints for some of them.
  std::string meter = "nan";
  if (!s.meter.empty()) {
    std::sort(s.meter.begin(), s.meter.end());
    meter = strf("%.1f", s.meter[s.meter.size() / 2]);
  }
  // New keys only ever go at the end of the line, behind whatever was there before. The lens
  // takes the pairs it knows by name and skips the rest.
  const std::string delay = " delay=" + number_text(median_of(s.trace.delay));
  std::string extra;
  if (s.o.profile) {
    Profile& p = s.profile;
    extra = strf(" capture=%.2f ingest=%.2f nr=%.2f composite=%.2f present=%.2f",
                 c.callback_ms / (double)std::max(1u, c.callbacks),
                 p.ingest_ms / std::max(1, p.ingests), p.nr_ms / std::max(1, p.nr_runs),
                 p.composite_ms / std::max(1, p.draws), p.present_ms / std::max(1, p.presents));
    // copied counts the crops the capture copied into a slot, which under a limit is fewer
    // than arrived. late counts the new pictures from a frame the limit had kept back, the
    // last before a stop.
    extra += delay + strf(" copied=%u late=%d", c.copies, s.late) + trace_text(s);
    // wake and iwall: where the time from a frame's arrival to its ingest's end goes, the
    // loop's own latency and the ingest's waits for the card, which ingest= leaves out
    extra += strf(" wake=%.2f iwall=%.2f cwait=%.2f", p.wake_ms / std::max(1, p.timed),
                  p.wall_ms / std::max(1, p.timed), p.cwait_ms / std::max(1, p.timed));
    // dwait: the wait for the last draw before a frame is taken, see take_frame()
    extra += strf(" dwait=%.2f", p.dwait_ms / std::max(1, p.dwaits));
    // conv: the conversion of a 16-bit frame to 8 bits on the card, a mean over the ingests,
    // 0 for a monitor without Windows HDR. ingest= leaves it out
    extra += strf(" conv=%.2f", p.conv_ms / std::max(1, p.ingests));
    // joined: new pictures drawn by one list, see kJoinAfter. same: of the frames drawn so,
    // those found the same as the last afterwards, each a run of the network for nothing
    extra += strf(" joined=%d same=%d", p.joined, p.same);
    p = Profile();  // a draw still on the GPU is read in the next second
  } else {
    extra = delay;
  }
  const std::string line = strf("stats new=%d arrived=%u repeated=%d dropped=%u skipped=%d meter=%s%s", s.fresh,
                                c.arrived, s.repeated, c.dropped, s.skipped, meter.c_str(), extra.c_str());
  say("%s", line.c_str());
  if (s.stats_note) note("%s", line.c_str());
  s.meter.clear();
  trace_reset(s.trace);
  s.fresh = s.repeated = s.skipped = s.late = s.settled = s.left = 0;
  s.t_report = now;
  // It follows a change of the display's mode, and under a limit the capture's interval
  // and the limit's allowances follow with it.
  const double hz = s.window.refresh_hz();
  if (hz != s.refresh_hz) {
    s.refresh_hz = hz;
    if (s.limit_fps > 0.0) s.want_recapture = true;
  }

  if (!s.capturing) return;
  if (s.lost_said) {
    // Said, and the lens may have kept this presenter: it starts a new one only when no
    // frame has come back by then. A frame that covers the lens means the capture works
    // again, and the rules below watch it from here on, so a later loss is said as well.
    if (c.arrived == 0) return;
    s.lost_said = false;
    s.t_check = 0.0;
  }
  // Windows HDR on or off for the monitor since the capture started, see watch_colour()
  watch_colour(s);
  if (s.lost_said || !s.capturing) return;
  // Windows ends a monitor capture when the displays change. Otherwise it delivers a frame
  // only when what the monitor shows has changed, and the presents of this window do not
  // count when it is excluded from capture: over a still source the first runs on screen
  // got no frame at all for seconds on end under thirty presents a second. So a quiet
  // capture may only mean a still screen. A new session always delivers the screen as it is
  // at once (10 to 13 ms in the capture test), so a capture quiet for three seconds is
  // started again, and only one that brings nothing in the second after that is lost.
  // Before the first picture the same rule tells the lens that this presenter never got a
  // frame.
  std::string reason;
  if (s.capture.closed() || s.stopped) {
    reason = "closed";
  } else if (c.unfit > 0 && now - s.t_fit > 1.0) {
    reason = strf("frames of %dx%d no longer cover the lens", c.unfit_w, c.unfit_h);
  } else if (s.t_check > 0.0) {
    if (c.arrived > 0) {
      s.t_check = 0.0;  // it delivers: the screen was only still
    } else if (now - s.t_check >= 0.9) {
      reason = strf("no frame for %.0f s", now - s.t_quiet);
    }
  } else if (s.quiet_after_s > 0.0 && now - s.capture.last_arrival_s() > s.quiet_after_s) {
    s.t_quiet = s.capture.last_arrival_s();
    s.capture.stop();
    std::string err;
    if (start_capture(s, err)) {
      s.t_check = now_s();
    } else {
      reason = "could not start again: " + err;
    }
  }
  if (!reason.empty()) {
    say("capture lost %s", reason.c_str());
    s.lost_said = true;
  }
}

// Paused, the line still comes, with nothing in it.
void report_paused(State& s, double now) {
  (void)s.capture.take_counters();  // what came just before the pause is not carried into
                                    // the first second after it
  say("stats new=0 arrived=0 repeated=0 dropped=0 skipped=0 meter=nan delay=nan");
  s.meter.clear();
  trace_reset(s.trace);
  s.fresh = s.repeated = s.skipped = s.late = s.settled = s.left = 0;
  s.t_report = now;
}

// ---------------------------------------------------------------- the loop

// A frame waits in the capture. Whether it is the one frame that is left out because the
// pictures are shown late, see kLateAfter. It stays where it is, and the next frame to
// arrive takes its place there. Should none come within a refresh and a half of it, the
// source has stopped and this frame is its last picture, so it is taken after all.
bool leaves_frame(State& s, double now) {
  if (s.leave_out) {
    s.leave_out = false;
    if (now < s.leave_by) {
      s.leaving = true;
      s.left_arrived = s.capture.pending_arrived_s();
      s.leave_until = s.left_arrived + 1.5 / s.refresh_hz;
      s.left_before = s.left_steps = s.late_steps;
    }
  }
  if (!s.leaving) return false;
  const bool same = s.capture.pending_arrived_s() == s.left_arrived;
  if (same && now < s.leave_until) return true;
  s.leaving = false;
  if (!same) ++s.left;  // a newer frame has taken its place
  return false;
}

// How long the turn may wait: until the next thing is due, and no longer than that.
double next_wait(const State& s) {
  const double now = now_s();
  double wait;
  if (s.capture.pending() && !s.leaving) {
    wait = 0.0;  // a frame came in during the turn
  } else if (!s.have) {
    wait = 1.0;  // nothing to present yet: the first frame ends the wait
  } else if (busy(s, now)) {
    wait = s.t_present + 1.0 / s.refresh_hz - now;
  } else {
    wait = s.t_present + heartbeat_s(s, now) - now;
  }
  wait = std::min(wait, s.t_report + 1.0 - now);  // the stats line
  // a frame the limit has kept back, which is handed on when no newer one comes
  if (const double due = s.capture.held_due_s(); due > 0.0) wait = std::min(wait, due - now);
  // a present the display's statistics have not named yet, see trace_look()
  if (s.trace.t_ask > 0.0) wait = std::min(wait, s.trace.t_ask - now);
  // A frame that is being left out. The one that takes its place ends the wait as any frame
  // does, and this is the moment it is taken itself when none comes.
  if (s.leaving) wait = std::min(wait, s.leave_until - now);
  // The settle has two moments, the one from which the picture counts as at rest, then each
  // of its runs. While the limit keeps a frame back the picture is not at rest, and that
  // frame's own moment above ends the wait.
  if (s.have && !s.at_rest) {
    if (s.capture.held_due_s() <= 0.0) wait = std::min(wait, s.t_changed + rest_after(s) - now);
  } else if (s.settle_left > 0) {
    wait = std::min(wait, s.t_present + settle_apart(s) - now);
  }
  if (!s.have && !s.said_waiting) {
    wait = std::min(wait, s.t_started + kFirstFrameNote - now + 0.001);  // the note, see turn()
  }
  // A turn that neither took a frame nor presented anything has nothing left to do at
  // once, whatever the numbers say: it waits at least a millisecond, so the loop cannot spin.
  if (wait < 0.001 && !s.progress) wait = 0.001;
  return wait;
}

// One turn while paused: no capture and no present, only the window's messages, the
// commands and the stats line. The wait lasts until that line is due, since a command or a
// message ends it at once.
void paused_turn(State& s) {
  double now = now_s();
  if (now - s.t_report >= 1.0) {
    report_paused(s, now);
    now = now_s();
  }
  wait_turn(s, std::max(0.001, s.t_report + 1.0 - now));
}

// One turn of the running loop. Returns after its wait.
void turn(State& s) {
  s.progress = false;
  double now = now_s();
  bool is_new = false;
  trace_look(s, now);
  resolve_joined(s);  // the answer of a joined draw the GPU has finished, see kJoinAfter

  // Whatever frame the capture has ready is drawn at once. Under a limit the capture has
  // already judged it. Is none ready, the limit may have kept the last frame back, the one
  // that came before its turn and had no newer one after it. The source has stopped then,
  // and that frame is what the screen is left showing. Once it is due it is asked for and
  // drawn, late by a refresh or two, where every other frame is drawn as it comes.
  s.cur_was_held = false;
  if (!s.capture.pending()) {
    const double due = s.capture.held_due_s();
    if (due > 0.0 && now >= due) {
      step("release");
      s.cur_was_held = s.capture.release_held();
    }
  }
  if (!s.capture.pending()) {
    s.leaving = false;  // nothing waits there, so nothing is being left out
  } else if (!leaves_frame(s, now)) {
    is_new = take_frame(s);
  }

  // Nothing new under the lens, so the last picture again. It goes through the network when
  // a setting changed, or when the picture has come to rest and is still to settle. It is
  // repainted as it is while the lens wants pictures at the display's rate, and as the
  // heartbeat. Not while a frame is being left out, which is for one refresh to pass without
  // a render.
  if (is_new) s.memory_run = false;  // the network has just run, which is all that run was for
  if (!is_new && s.have && !s.leaving) {
    now = now_s();
    watch_path(s, now);
    if (s.redraw) {
      draw(s, Draw::Again);
    } else if (settle_due(s, now)) {
      draw(s, Draw::Settle);
    } else if (s.memory_run) {
      // once more through the network after a switch, see note_memory()
      s.memory_run = false;
      if (s.settle && s.pipeline.network_runs() && !s.reset_next) draw(s, Draw::Settle);
    } else if (repeat_due(s, now)) {
      draw(s, Draw::Repaint);
    }
  }

  now = now_s();
  if (!s.have && !s.said_waiting && now - s.t_started > kFirstFrameNote) {
    s.said_waiting = true;
    note("loop: no frame from the capture %.1f s after the start, the window stays hidden and "
         "the loop goes on waiting",
         now - s.t_started);
  }
  step("stats");
  if (now - s.t_report >= 1.0) report(s, now);
  step("wait");
  wait_turn(s, next_wait(s));
}

// The way out for quit, the end of stdin and a closed window. The window goes first, so
// nothing of the engine is on screen while the rest is taken down. Then the order the
// headers ask for: no more frames, the GPU at rest, and only then the things it was using.
// The watchdog watches this as it watched the loop: if any of it hangs, the process ends
// five seconds later all the same.
[[noreturn]] void leave(State& s, int code) {
  mark_turn();
  step("leaving");
  if (HWND hwnd = s.window.hwnd()) ShowWindow(hwnd, SW_HIDE);
  if (s.trace.file) fflush(s.trace.file);  // the process ends without the C runtime's own flush
  s.capture.stop();
  std::string err;
  if (s.gpu.flush(3000, err)) {
    s.pipeline.shutdown();
    s.capture.destroy();
    s.window.destroy();
  } else {
    // nothing may be released under a GPU that is still working: the process just ends
    note("loop: the GPU did not come to rest, leaving without the orderly shutdown: %s",
         err.c_str());
  }
  // A screenshot still being written gets the time to finish, ten seconds at most: its
  // files are no use half written.
  if (s.shot_thread) {
    for (int i = 0; i < 100 && WaitForSingleObject(s.shot_thread, 100) == WAIT_TIMEOUT; ++i) {
      mark_turn();
    }
  }
  leave_now(code);
}

[[noreturn]] void run(State& s) {
  s.t_started = s.t_report = now_s();
  const char* why = "quit";
  for (;;) {
    mark_turn();
    step("messages");
    if (!s.window.pump()) {
      why = "the window was closed";
      break;
    }
    step("commands");
    take_commands(s);
    if (s.quit) break;
    if (s.switching) land_switch(s);
    // The next switch begins once the one before has shown its first picture. Begun earlier,
    // it would hold the network before the new one had made anything to hold, and the
    // pictures drawn meanwhile would have no network's change at all. Paused, nothing is
    // drawn, and nothing has to be waited for.
    if (s.want_quality >= 0 && !s.switching && (!s.switched || s.paused)) switch_quality(s);
    if (s.t_memory > 0.0 && !s.switching && now_s() >= s.t_memory) note_memory(s);
    if (s.want_recapture) recapture(s);
    if (s.paused) paused_turn(s);
    else turn(s);
  }
  note("loop: leaving, %s", why);
  leave(s, exit_code::ok);
}

// ---------------------------------------------------------------- start-up

// In this order: the monitor under the lens, the GPU that draws it, the window (hidden),
// the pipeline with the network, the commands, the capture. Each failure says "engine
// failed REASON" and ends the process. The window comes before the pipeline because a
// swapchain the window refuses is found in milliseconds, and the network takes 257 ms a
// pass to create.
//
// The watchdog already runs, started by wmain with the start-up's allowance, and each part
// names itself for it first. At the end the allowance becomes the loop's.
//
// COM is not initialised here: nothing on this thread needs an apartment. The capture keeps
// a multithreaded one alive for itself, the PNG writer initialises its own thread.
void start(State& s) {
  const Options& o = s.o;
  std::string err;

  s.ready = o.ready;
  s.settle = o.settle;
  s.limit_fps = o.max_fps > 0.0 ? o.max_fps : 0.0;
  s.crop_x = o.crop_x;
  s.crop_y = o.crop_y;
  s.meter.reserve(256);
  if (o.heartbeat_s > 0.0) {
    s.beat_given = true;
    s.beat_rest_s = o.heartbeat_s;
  }
  if (const std::wstring beat = env_text(L"LENS_FAST_HEARTBEAT"); !beat.empty()) {
    double fast = 0.0, rest = 0.0;
    if (swscanf(beat.c_str(), L"%lf,%lf", &fast, &rest) == 2 && fast >= 0.0 && rest >= 0.0) {
      s.beat_given = true;
      s.beat_fast_s = fast > 0.0 ? 1.0 / fast : 0.0;
      s.beat_rest_s = rest > 0.0 ? 1.0 / rest : 0.0;
      note("loop: LENS_FAST_HEARTBEAT, %g presents a second for ten seconds after a new picture "
           "and %g after that",
           fast, rest);
    }
  }
  if (const std::wstring burst = env_text(L"LENS_FAST_BURST"); !burst.empty()) {
    s.burst_test_s = std::max(0.0, _wtof(burst.c_str()));
    note("loop: LENS_FAST_BURST, a burst lasts %g s at most", s.burst_test_s);
  }
  if (const std::wstring quiet = env_text(L"LENS_FAST_QUIET_CHECK"); !quiet.empty()) {
    s.quiet_after_s = std::max(0.0, _wtof(quiet.c_str()));
    note("loop: LENS_FAST_QUIET_CHECK, a quiet capture is started again after %g s (0: never)",
         s.quiet_after_s);
  }
  s.switch_sync = env_text(L"LENS_FAST_SWITCH_SYNC") == L"1";
  if (s.switch_sync) note("loop: LENS_FAST_SWITCH_SYNC=1, a new quality step's network is made on the loop's thread");
  s.leave_allowed = env_text(L"LENS_FAST_LEAVE_OUT") != L"0";
  if (!s.leave_allowed) note("loop: LENS_FAST_LEAVE_OUT=0, no frame is left out for pictures that are shown late");
  s.late_always = env_text(L"LENS_FAST_LEAVE_OUT") == L"always";
  if (s.late_always) note("loop: LENS_FAST_LEAVE_OUT=always, every new picture counts as late");
  if (const std::wstring stall = env_text(L"LENS_FAST_STALL"); !stall.empty()) {
    double ms = 0.0, every = 0.0;
    if (swscanf(stall.c_str(), L"%lf,%lf", &ms, &every) == 2 && ms > 0.0 && ms <= 1000.0 && every > 0.0) {
      s.stall_ms = ms;
      s.stall_every = every;
      s.t_stall = now_s() + every;
      note("loop: LENS_FAST_STALL, the loop stands still for %g ms every %g s before it draws a new picture", ms,
           every);
    }
  }
  if (const std::wstring join = env_text(L"LENS_FAST_JOIN"); !join.empty()) {
    s.join_after = std::clamp(_wtoi(join.c_str()), 0, 1000);
    if (s.join_after > 0) {
      note("loop: LENS_FAST_JOIN, the ingest and the render go as one list after %d changed frames in a row",
           s.join_after);
    } else {
      note("loop: LENS_FAST_JOIN=0, every new frame's ingest is waited for before its render");
    }
  }
  if (const std::wstring path = env_text(L"LENS_FAST_TRACE"); !path.empty()) {
    s.trace.file = _wfopen(path.c_str(), L"w");
    note("loop: LENS_FAST_TRACE, %s", s.trace.file ? "every present is written down" : "the file cannot be written");
  }
  s.stats_note = env_text(L"LENS_FAST_STATS_NOTE") == L"1";
  if (s.stats_note) note("loop: LENS_FAST_STATS_NOTE, every stats line goes to stderr too");
  s.shot_raw = env_text(L"LENS_FAST_SHOT_RAW") == L"1";
  if (s.shot_raw) note("loop: LENS_FAST_SHOT_RAW=1, a screenshot of a 16-bit capture writes the raw frame and the picture drawn too");
  HdrAbove above = HdrAbove::Fade;
  if (const std::wstring word = env_text(L"LENS_FAST_HDR_ABOVE"); !word.empty()) {
    if (word == L"pass") {
      above = HdrAbove::Pass;
    } else if (word == L"fade") {
      above = HdrAbove::Fade;
    } else if (word == L"clip") {
      above = HdrAbove::Clip;
    } else {
      note("loop: LENS_FAST_HDR_ABOVE is not pass, fade or clip, the change fades out above SDR white");
    }
    note("loop: LENS_FAST_HDR_ABOVE, above SDR white the network's change %s",
         above == HdrAbove::Pass ? "passes" : above == HdrAbove::Fade ? "fades out" : "is clipped");
  }

  step("gpu");
  s.monitor = monitor_under(o.x, o.y, o.width, o.height);
  if (!s.gpu.init(s.monitor, err)) die(s, "gpu: " + err);
  // the slots' guard: the capture never writes a slot a list of this queue still reads
  s.capture.set_reader_fence(s.gpu.fence.Get());

  step("window");
  WindowDesc wd;
  wd.x = o.x;
  wd.y = o.y;
  wd.width = o.width;
  wd.height = o.height;
  wd.title = o.title;
  wd.exclude = o.exclude;
  wd.path = o.present;
  // With Windows HDR on for the monitor the swapchain is made in 16-bit floats from the
  // start. The capture's start reads the state again, with the note, and keeps the two in
  // step from then on, see start_capture().
  const MonitorColour first = monitor_colour(s.monitor);
  wd.hdr = first.known && first.hdr;
  if (!s.window.create(s.gpu, wd, err)) die(s, "window: " + err);
  if (wd.hdr && !s.window.hdr()) s.hdr_out = false;
  s.refresh_hz = s.window.refresh_hz();

  step("pipeline");
  const WorkPlan plan = work_plan(o.width, o.height, o);
  s.work_w = plan.w;
  s.work_h = plan.h;
  s.quality = plan.quality;
  if (plan.quality >= 0) {
    note("loop: quality %d %s, %s, work %dx%d, %s for a picture of %dx%d", plan.quality,
         quality_name(plan.quality), plan.chosen ? "as asked" : "the default for this size", plan.w, plan.h,
         plan.measured ? "a measured size" : "by the rule", o.width, o.height);
  } else {
    note("loop: the work size %dx%d was given by %s, no quality step is in use", plan.w, plan.h, plan.given_by);
  }
  if (!read_nr_passes(o.stack_dir, s.settings, err, o.passes)) {
    note("loop: %s, the network runs on its own defaults", err.c_str());
  }
  s.network = env_text(L"LENS_FAST_NO_NETWORK") != L"1";
  if (!s.network) note("loop: LENS_FAST_NO_NETWORK=1, every picture is the plain copy");
  PipelineDesc pd;
  pd.width = (UINT)o.width;
  pd.height = (UINT)o.height;
  pd.work_w = (UINT)s.work_w;
  pd.work_h = (UINT)s.work_h;
  pd.passes = o.passes;
  pd.stack_dir = o.stack_dir;
  pd.data_dir = o.data_dir;
  pd.settings = s.settings;
  pd.nr_on = true;
  pd.load_network = s.network;
  if (!s.pipeline.init(s.gpu, pd, err)) die(s, "pipeline: " + err);
  // the draws' GPU times are taken by read_stage_times() with the profile on and by nothing else
  s.pipeline.keep_times(s.o.profile);
  s.pipeline.keep_raw(s.shot_raw);
  s.pipeline.set_hdr_above(above);

  step("commands");
  if (!s.reader.start(err)) die(s, "commands: " + err);
  if (!s.reader.attached() && o.lifetime_s <= 0.0) {
    // Started by hand with no stdin: nobody could ever tell this window to go away. The
    // window is still hidden and nothing has been drawn, so the process simply ends.
    fail("no stdin to take commands from: started without the lens it needs --lifetime S");
    leave_now(exit_code::usage);
  }

  s.frame_event = CreateEventW(nullptr, FALSE, FALSE, nullptr);
  if (!s.frame_event) die(s, strf("the frame event could not be made, error %lu", GetLastError()));
  // Null is fine: the waits then end on the system's tick, see wait_turn().
  s.timer = CreateWaitableTimerExW(nullptr, nullptr, CREATE_WAITABLE_TIMER_HIGH_RESOLUTION,
                                   TIMER_ALL_ACCESS);
  if (!s.timer) {
    note("loop: no high resolution timer, error %lu: waits end on the system's tick",
         GetLastError());
  }

  step("capture");
  s.live_interval = env_text(L"LENS_FAST_LIVE_INTERVAL") != L"0";
  if (!s.live_interval) note("loop: LENS_FAST_LIVE_INTERVAL=0, a new limit starts the capture again");
  if (const std::wstring forced = env_text(L"LENS_FAST_CAPTURE_INTERVAL"); !forced.empty()) {
    s.interval_forced = std::max(0, _wtoi(forced.c_str()));
    note("loop: LENS_FAST_CAPTURE_INTERVAL, the capture's interval is %d ms whatever the limit",
         s.interval_forced);
  }
  if (!start_capture(s, err)) die(s, "capture: " + err);

  const int passes = s.network ? o.passes : 0;
  note("loop: %dx%d at (%d,%d) on %s, %.0f Hz, work %dx%d, %d pass%s, limit %g, %.0f MiB of video "
       "memory in use of a budget of %.0f MiB, %.0f ms after the process began",
       o.width, o.height, o.x, o.y, s.gpu.name.c_str(), s.refresh_hz, s.work_w, s.work_h, passes,
       passes == 1 ? "" : "es", s.limit_fps, (double)s.gpu.vram_bytes() / 1048576.0,
       (double)s.gpu.vram_budget_bytes() / 1048576.0, (now_s() - g_born) * 1000.0);

  // from here the loop turns, and the watchdog holds it to its five seconds
  mark_turn();
  g_allow_s.store(kWatchdogSeconds);
}

}  // namespace

int wmain(int argc, wchar_t** argv) {
  set_quiet_failures();
  g_born = now_s();
  // Before any window or monitor call, so --at and --size are physical pixels.
  set_dpi_aware();

  Options o;
  std::string err;
  if (!parse_options(argc, argv, o, err)) {
    fail("%s", err.c_str());
    return exit_code::usage;
  }
  if (o.help) {
    print_usage();
    return exit_code::ok;
  }
  if (!o.steps_for.empty()) {
    for (size_t i = 0; i + 1 < o.steps_for.size(); i += 2) {
      say("%s", steps_text(o.steps_for[i], o.steps_for[i + 1]).c_str());
    }
    return exit_code::ok;
  }
  // The two tests may have had the runtime or the capture loaded, so they leave the way the
  // engine does, see leave_now(). The streams are flushed first for whatever they wrote
  // through the C runtime.
  if (o.selftest || o.capturetest) {
    const int code = o.selftest ? run_selftest(o) : run_capturetest(o);
    fflush(nullptr);
    leave_now(code);
  }

  // From here on the process only ever ends through leave_now(): the runtime's unload code
  // is not known to survive an ordinary exit.
  if (o.lifetime_s > 0.0) {
    g_lifetime_s = o.lifetime_s;
    if (!start_thread(lifetime_thread, nullptr)) {
      fail("the --lifetime thread could not be started");
      return exit_code::failed;
    }
  }
  // The watchdog comes before the start-up, which it watches too: a driver or runtime call
  // in there that never returns would otherwise leave a hidden process behind for good once
  // the lens is gone.
  mark_turn();
  if (!start_thread(watchdog_thread, nullptr)) {
    fail("the watchdog thread could not be started");
    return exit_code::failed;
  }

  // Never destroyed: every way out is leave_now(), which runs no destructor.
  State* s = new (std::nothrow) State;
  if (!s) {
    fail("out of memory");
    return exit_code::failed;
  }
  s->o = o;
  start(*s);
  run(*s);
}
