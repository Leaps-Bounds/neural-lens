// common.h: what every part of the fast engine shares.
//
// The fast engine, lens-fast.exe, is the lens's presenter for a fullscreen lens. It captures
// the monitor on the GPU, runs Neural Rendering on a downscaled copy by calling the stack's
// runtime directly, and presents the original plus what the network changed through a flip
// model swapchain. It speaks lens_presenter.py's protocol on stdin and stdout, so the lens
// drives either presenter the same way. Why it exists: at 6144x2526 the Vulkan presenter with
// ReShade and the two add-ons reaches 62 pictures a second on 330 W, and the network alone,
// called directly at 2560x1053, takes 3.35 ms a picture.
//
// "The probe", which comments in these sources name, is a test program written before the
// engine and not part of this repository. It called the network directly on one still
// picture and did the downscale and the composite on the CPU, which proved the call
// sequence and the arithmetic the engine now does on the GPU. Its measurements are quoted
// where they explain a choice, and the self test compares the engine's pictures with the
// probe's where those are at hand.
//
// Rules every module keeps:
//   - No exception crosses a module boundary. A function that can fail returns bool and puts
//     a short reason in std::string& err: plain ASCII, no full stop, no newline. The caller
//     decides whether it is fatal.
//   - Nothing but the engine's one window may ever appear on screen: no message box, no
//     console. set_quiet_failures() is the first call of every program.
//   - stdout belongs to the protocol. Only say() and fail() write to it, and only the lines
//     the protocol names, because the lens parses every line. Anything a person might want
//     to read goes to stderr through note(), which the lens appends to presenter-stderr.log.
//     Start a note with the module's name, as in "capture: 6144x2560 frames". note() puts
//     the local time in front of it.
//   - One thread touches the GPU through D3D12: the main thread. The capture has its own
//     D3D11 device and its own thread, and meets the rest only through capture.h.
//   - Sizes and positions are physical pixels. The process is per monitor DPI aware,
//     version 2, as the lens is.
#pragma once

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>

#include <cstdint>
#include <string>
#include <vector>

// Named in the ready line, so a log says which presenter ran.
#define LENS_FAST_VERSION "0.6.1-fast"

// What the process returns. The lens only looks at whether it is still running, the numbers
// are for a person reading a log.
namespace exit_code {
constexpr int ok = 0;        // quit, the end of stdin, the window closed, --lifetime, --help
constexpr int failed = 1;    // "engine failed REASON" was printed
constexpr int usage = 2;     // a bad command line, or a part that is not built yet
constexpr int watchdog = 5;  // the main loop did not turn for 5 s, or the start-up stood
                             // still for 30 (main.cpp)
constexpr int crashed = 6;   // an unhandled exception, abort or a C runtime error (set_quiet_failures)
}

// ---------------------------------------------------------------- lines out
//
// Any thread may call these. Each call writes one whole line with a single WriteFile on the
// process's own handle, so lines from two threads never mix, and nothing is buffered: a line
// is on the pipe when the call returns. Line breaks inside the text become spaces, so one
// call is always one line. With no stdout or stderr at all (started by hand, not by the
// lens) the calls do nothing. A broken pipe is ignored: the lens going away is noticed as
// the end of stdin, not here.
//
// stdout and stderr have separate locks, so note() never waits behind a say() that is
// stuck on a full pipe. The watchdog depends on that.

// One protocol line on stdout. Bytes outside ASCII become '?': the lens reads this pipe in
// the ANSI code page, where some bytes do not decode at all and would end its reader thread.
void say(const char* fmt, ...);

// One line on stderr, for people. UTF-8 as given, with the local time in front as
// HH:MM:SS.mmm and a space, as in "21:07:45.123 capture: 6144x2560 frames". Every line the
// engine writes to stderr starts so, and no line on stdout does.
void note(const char* fmt, ...);

// "engine failed REASON" on stderr with the time in front, as note() writes it, and then on
// stdout as it is. It only prints: leaving is the caller's business.
void fail(const char* fmt, ...);

// printf into a string, for err texts.
std::string strf(const char* fmt, ...);

// An HRESULT as "0x887A0005".
std::string hr_text(HRESULT hr);

// UTF-16 to UTF-8 and back. Bad input gives replacement characters, never an exception.
std::string narrow(const std::wstring& text);
std::wstring widen(const std::string& text);

// UTF-16 to plain ASCII, anything else as '?'. For names that go into protocol lines,
// such as the adapter's.
std::string ascii(const std::wstring& text);

// ---------------------------------------------------------------- the clock

// QueryPerformanceCounter in seconds. Any thread. It is the clock Windows Graphics Capture
// stamps its frames with: a frame's SystemRelativeTime counts 100 ns units of it, so that
// value divided by 1e7 compares directly with now_s(), and the difference at the Present
// call is the meter in the stats line.
double now_s();

// ---------------------------------------------------------------- Neural Rendering's settings

// The most passes an engine runs, and so the most sets of settings and features it holds.
constexpr int kNrMaxPasses = 8;

// The six settings the engine takes from the lens. They live in <stack>\ReShade.ini, section
// [RenoDX.DLSS5], where the lens and the add-on's overlay write them. The defaults are the
// runtime's own, used for any key that is missing. NRGlobalTone is not here on purpose: the
// runtime never reads DLSSNR.GlobalToneStrength (it is not among the names it asked for).
struct NrSettings {
  unsigned style = 0;            // NRStyle: 0 Default, 1 Natural, 2 Cinematic
  float intensity = 1.0f;        // NRIntensity
  float local_tone = 1.0f;       // NRLocalTone
  float local_structure = 1.0f;  // NRLocalStructure
  float skin_structure = -1.0f;  // NRSkinStructure, -1 lets the model decide
  int auto_mask = 0;             // NRAutoMask, 0 or 1
};

// Reads the six settings of the first pass from <stack_dir>\ReShade.ini. Any thread. The
// file is read afresh on every call, which is what the "reload" command is for. Returns
// false with err when the file is not there, leaving out at its defaults: the engine can
// still run. A missing key keeps its default and is not an error.
bool read_nr_settings(const std::wstring& stack_dir, NrSettings& out, std::string& err);

// Whether two sets are the same, value for value.
bool same_settings(const NrSettings& a, const NrSettings& b);

// The passes whose intensity the add-on keeps a key of its own for, NRPass2Intensity to
// NRPass4Intensity, from the second on.
constexpr int kAddonPassIntensities = 4;

// The settings of every pass. pass[0] is the base, the six keys above. Each pass after it
// starts from the base and takes its own values where the file holds them:
//   - the lens's own section [NeuralLens.Passes], keys Pass<n>Style, Pass<n>LocalTone,
//     Pass<n>LocalStructure, Pass<n>SkinStructure and Pass<n>AutoMask, n from 2, which the
//     add-on never reads, so it never sees keys it does not know
//   - the intensity of passes 2 to 4 from the add-on's own NRPass2Intensity, NRPass3Intensity
//     and NRPass4Intensity in [RenoDX.DLSS5], which the lens writes for those passes and this
//     engine runs them at. Their names suggest that the add-on runs those passes at them too,
//     and that its overlay can change them, which was not measured, see docs\NOTES.md, What
//     is not measured. Where the lens's section holds Pass<n>IntensityTied, the pass is
//     ticked Same as pass 1 and runs at the base's intensity, whatever the add-on's key says.
//     The lens keeps that key at the base for such a pass, for the add-on, and the value of
//     Pass<n>IntensityTied is the one it last wrote there, so it can tell a value given to
//     the pass as its own from a base the overlay moved
//   - the intensity of a pass from the fifth on, which the add-on has no key for, and of a
//     pass 2 to 4 where the add-on's key is missing, from the lens's Pass<n>Intensity
// A pass with no key of its own for a value runs at the base's. NRPass4Color, which the
// add-on also keeps in its section, is left alone: the lens never set it, and it belongs to
// the add-on's own colour stage, which this engine does not have.
struct NrPasses {
  NrSettings pass[kNrMaxPasses];
  NrPasses() = default;
  // every pass at the same values, which is how one set of settings was used before
  explicit NrPasses(const NrSettings& all) {
    for (NrSettings& p : pass) p = all;
  }
  const NrSettings& base() const { return pass[0]; }
};

// Reads the base and the own values of the first count passes, see NrPasses. Every pass
// beyond count is the base, and at one pass the lens's section is not read at all. Any
// thread, the file read afresh each time, each section in one call. Returns false with err
// when the file is not there, out at the defaults.
bool read_nr_passes(const std::wstring& stack_dir, NrPasses& out, std::string& err, int count = kNrMaxPasses);

// Whether the first count passes of two sets are the same, value for value.
bool same_passes(const NrPasses& a, const NrPasses& b, int count);

// Which of a pass's six values differ from the base, as words for a note: "intensity 0.94,
// style 2", or an empty string where none does.
std::string own_values_text(const NrSettings& base, const NrSettings& pass);

// ---------------------------------------------------------------- the command line

// How the swapchain is made (window.h). Which one works under the window's styles is
// decided on screen, so both exist.
enum class PresentPath {
  Hwnd,   // CreateSwapChainForHwnd, the default
  Dcomp,  // CreateSwapChainForComposition on a DirectComposition visual
};

struct Options {
  // ---- the presenter's own, as lens_presenter.py takes them
  std::string source;        // --source as given, "monitor:2". Repeated in the ready line
  int monitor_index = 0;     // the number in it, from 1. Only repeated: the monitor captured
                             // is the one under the middle of the --at / --size rectangle
  bool have_at = false;
  int x = 0, y = 0;          // --at X Y: where the window goes
  bool have_size = false;
  int width = 0, height = 0; // --size W H: the window's and the picture's size
  int crop_x = 0, crop_y = 0; // --crop X Y: where in the monitor the shown region starts
  std::wstring title = L"LensPresenter";  // --title T
  bool exclude = false;      // --exclude: WDA_EXCLUDEFROMCAPTURE on the window
  bool ready = false;        // --ready: thirty presents a second while nothing changes
  double max_fps = 0.0;      // --max-fps N: at most N new pictures a second, 0 no limit

  // ---- the engine's
  std::wstring stack_dir;    // --stack DIR, absolute: nvngx_dlssnr.dll and ReShade.ini
  std::wstring data_dir;     // --data DIR, absolute: the runtime's logs. %TEMP%\lens-fast
  int passes = 1;            // --passes N, 1 to 8
  int quality = -1;          // --quality N, 0 to 4. -1 when not given, and the step is then
                             // the default for the picture's size, see work_plan()
  // The next three are for tests. Each gives the work size itself, and no step is used.
  int work_w = 0, work_h = 0;  // --work-size W H: the work size as given, 0 when not given
  double work_scale = 0.0;   // --work-scale S in (0, 1], 0 when not given
  bool work_max_given = false;
  int work_max_w = 2560;     // --work-max W H: the picture fitted into W x H
  int work_max_h = 1440;
  PresentPath present = PresentPath::Hwnd;  // --present hwnd|dcomp
  bool settle = true;        // false with --no-settle: a picture that has come to rest is
                             // not put through the network again, see main.cpp
  double lifetime_s = 0.0;   // --lifetime S: leave after S seconds whatever happens, 0 never

  // ---- other ways to run
  bool help = false;         // --help
  bool selftest = false;     // --selftest IMAGE OUTDIR
  std::wstring selftest_image, selftest_outdir;  // absolute
  std::vector<int> switches; // --switches LIST, with --selftest. The quality steps the test
                             // switches through at its end, in order, as in 4,3,2,1,0,4
  int switch_frames = 0;     // --switch-frames N, the frames drawn at each of them. 0 when
                             // not given, and it is then as many as the test draws before
                             // it keeps its pictures
  double switch_rest_s = 0.0;  // --switch-rest S, seconds with no frame after the last of
                             // them, then frames again, to see when the video memory of the
                             // network that was replaced comes back
  bool capturetest = false;  // --capturetest SECONDS
  double capturetest_seconds = 0.0;
  std::vector<int> steps_for;  // --steps W H, once for each picture size: W, H, W, H, ...

  // ---- from the environment, as lens_presenter.py reads them
  bool profile = false;      // LENS_PRESENTER_PROFILE=1: per stage ms on the stats line
  double heartbeat_s = 0.0;  // LENS_PRESENTER_HEARTBEAT: seconds between presents at rest.
                             // 0 when not given, and the loop keeps its own rate, see main.cpp
};

// Parses the whole command line. Any thread, once. argv[0] is skipped.
//   - An option it does not know is skipped with its values, with a note on stderr: the
//     lens may pass --fifo. The values of an unknown option are the arguments up to the
//     next one that starts with two dashes.
//   - Values may be negative: --at -3072 0 is a monitor to the left of the main one.
//   - --help wins over everything, and nothing else is checked. --steps comes next, and
//     with it nothing is required and nothing is started.
//   - --selftest needs --stack. --capturetest needs --at and --size. Otherwise --source,
//     --at, --size and --stack are all required, and the source must be monitor:<n>:
//     window capture and the pattern source are not in this engine.
//   - --passes outside 1 to 8, --quality outside 0 to 4 and --work-scale outside (0, 1] are
//     clamped with a note.
//   - Folders are made absolute. None of them is created or checked here.
// Returns false with err, a reason fit for "engine failed REASON".
bool parse_options(int argc, wchar_t** argv, Options& out, std::string& err);

// The --help text: several lines, ASCII, ending in a newline.
const char* usage_text();

// Writes usage_text() to stdout as it is. Any thread.
void print_usage();

// ---------------------------------------------------------------- the quality steps
//
// The network runs on a copy of the picture at the work size, and a quality step is a work
// size. There are five, from 4 down to 0: Quality, Balanced, Performance, Low power and
// Lowest power. Quality is the largest size that costs the picture nothing. Balanced
// squeezes the height, with no loss seen in the test pictures. The three below it give up
// more of the fine detail the network adds for less GPU time. The original's own detail is
// kept at every step, since only the network's change is scaled up (pipeline.h).
//
// The sizes are measured ones. For a picture size in work_table.h they come from that
// table, which also holds the network's time at each and how much of its change a test
// picture kept. For any other picture size they come from the rule the table was made by
// (common.cpp, quality_rule), which lands on multiples of 128 texels. A work size is never
// a plain share of the picture. Measured at 6144x2526, a height one row past a multiple of
// 128 cost 0.03 to 0.28 ms more than the multiple itself, and at some sizes the network's
// change fell to 0.63 of what the multiple gave.
// At 6144x2526 the five work sizes are 2560x1024, 2560x896, 2176x896, 2560x640 and
// 1536x640, and the network takes 3.27, 3.03, 2.84, 2.70 and 2.37 ms there on an RTX 5090,
// against 3.36 ms at 2560x1053, the picture fitted into 2560x1440.

constexpr int kQualityMost = 4;  // the steps are 0 to 4

// "Lowest power", "Low power", "Performance", "Balanced" and "Quality" for 0 to 4, and an
// empty text for anything else.
const char* quality_name(int step);

// The step in use when none is asked for. It is 4 for a picture that fits 2560x1440. The
// network runs at the picture's own size there, and any smaller size takes away about 60
// percent of the one-texel texture it adds. It is 3 for a larger picture, which is downscaled
// at every step and showed no loss at Balanced, on text, thin lines, an interface and the
// Blender picture.
int default_quality(int W, int H);

// The work size of a step for a W x H picture. A step outside 0 to 4 is held at the nearer
// end. measured, when not null, is set to whether the picture size is in the table, so the
// five sizes were measured on a picture of that size. Otherwise they are the rule's.
void quality_work_size(int W, int H, int step, int& work_w, int& work_h, bool* measured = nullptr);

// The table's figures for a step of a picture size that is in it: the network's GPU
// milliseconds on an RTX 5090, and the share of the network's change that the Blender test
// picture kept against the picture fitted into 2560x1440. false when the size is not in the
// table.
bool quality_figures(int W, int H, int step, double& ms, double& kept);

// "steps 6144x2526: 4 Quality 2560x1024, 3 Balanced 2560x896, 2 Performance 2176x896,
// 1 Low power 2560x640, 0 Lowest power 1536x640, default 3, measured", or "by the rule" at
// the end for a picture size that is not in the table. What --steps W H prints.
std::string steps_text(int W, int H);

// The work size the engine starts with, and what decided it.
struct WorkPlan {
  int w = 0, h = 0;       // the work size
  int quality = -1;       // the step in use, or -1 when an option gave the size itself
  bool chosen = false;    // --quality named the step. False when it is the size's default
  bool measured = false;  // as quality_work_size() says
  const char* given_by = "";  // the option that gave the size, as in "--work-size", or empty
};

// What the command line asks for, for a W x H picture. --work-size, --work-scale and
// --work-max each give the size themselves, and the first of them in that order wins. They
// are for tests, and a size given so is used as it is, measured or not: --work-size as
// written, --work-scale as that share of each side rounded to nearest, --work-max as the
// picture fitted into it, in whole numbers, so a half rounds up on every machine. The self
// test's reference pictures were made at 2560x1053, which is 6144x2526 fitted into
// 2560x1440. No side is ever larger than the picture's. With none of the three it is the
// step: --quality, or the default for the size.
WorkPlan work_plan(int W, int H, const Options& o);

// ---------------------------------------------------------------- rates

// The capture's minimum update interval in ms for a frame rate limit, 0 for none. Windows
// rounds the interval up to whole refreshes, measured at 120 Hz: 11 ms gave 60 frames a
// second and 23 ms gave 40. So the interval is half a refresh below the most whole refreshes
// between frames that still deliver at least the limit, and the loop's own pacing takes out
// any extra. Where one refresh is already that, as 60 on a 100 Hz screen, it is 0.
// The same formula as lens_presenter.py's capture_interval.
int capture_interval_ms(double max_fps, double refresh_hz);

// ---------------------------------------------------------------- the process

// Makes sure no dialog box can ever appear, whatever goes wrong: system error boxes off,
// C runtime reports, assert and abort to stderr, and an unhandled exception, a pure call,
// an invalid parameter or std::terminate print "engine failed REASON" and end the process
// with exit_code::crashed without the system's crash dialog. Call it first in wmain.
// This window is topmost and click-through over the whole screen: a dialog behind it could
// not even be clicked.
void set_quiet_failures();

// Ends the process at once with this exit code. Any thread. It is TerminateProcess, not
// ExitProcess, on purpose: ExitProcess runs every DLL's unload code with the other threads
// already gone, and the Neural Rendering runtime's unload is not known to survive that. The
// probe left this way after its Shutdown1 call and so does the engine, on every path out:
// quit, the watchdog, --lifetime. Print what there is to print first, nothing is flushed
// here because say() and note() hold nothing back.
[[noreturn]] void leave_now(int code);

// Per monitor DPI aware, version 2, so --at and --size are physical pixels on whichever
// monitor they name. Before any window or monitor call. Main thread.
void set_dpi_aware();

// The monitor under the middle of the rectangle, the nearest one when it is off screen.
// This is the monitor the engine captures, picks its adapter by and reads its refresh rate
// from. Call set_dpi_aware() first.
HMONITOR monitor_under(int x, int y, int w, int h);

// How Windows composes for a monitor: in standard range, or with Windows HDR on for it.
// With HDR on the desktop is composed in scRGB and shown at the SDR white level, and an
// 8-bit capture of it comes out clipped at 80 nits, 1.0 in scRGB, and sRGB-encoded.
struct MonitorColour {
  bool known = false;           // the monitor was found among the active display paths
  bool hdr = false;             // Windows HDR is on for it
  double sdr_white_nits = 0.0;  // the SDR white level Windows uses for it, 0 when unknown
  int bits = 0;                 // bits per colour channel on the link, 0 when unknown
};

// Reads a monitor's colour state from DisplayConfig: the active path whose source device
// is the monitor's, its advanced colour information (GET_ADVANCED_COLOR_INFO_2 from Windows
// 11 24H2 on, which tells HDR from Auto Colour Management, and GET_ADVANCED_COLOR_INFO before
// that) and its SDR white level. A few hundred microseconds. Main thread.
MonitorColour monitor_colour(HMONITOR monitor);

// ---------------------------------------------------------------- small helpers

// The folder lens-fast.exe itself is in, without a trailing backslash.
std::wstring exe_dir();

// a\b, with exactly one backslash between.
std::wstring path_join(const std::wstring& a, const std::wstring& b);

bool file_exists(const std::wstring& path);  // a file, not a folder
bool dir_exists(const std::wstring& path);

// Creates the folder and its parents. True when it exists afterwards.
bool make_dirs(const std::wstring& path);

// An environment variable, empty when unset.
std::wstring env_text(const wchar_t* name);
