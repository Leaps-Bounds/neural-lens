// common.cpp: lines out, the clock, the command line, the settings in ReShade.ini, the
// quality steps and their work sizes, and the settings that keep every failure silent on
// screen. See common.h.
#include "common.h"

#include "work_table.h"

#include <crtdbg.h>

#include <algorithm>
#include <cerrno>
#include <cmath>
#include <csignal>
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <exception>
#include <filesystem>
#include <mutex>

namespace {

// ---------------------------------------------------------------- lines out

// One lock for each stream, so a note() never waits behind a say() stuck on a full pipe.
std::mutex g_stdout_lock;
std::mutex g_stderr_lock;

std::string vformat(const char* fmt, va_list args) {
  char fixed[1024];
  va_list again;
  va_copy(again, args);
  int n = vsnprintf(fixed, sizeof(fixed), fmt, again);
  va_end(again);
  if (n < 0) return std::string();
  if ((size_t)n < sizeof(fixed)) return std::string(fixed, (size_t)n);
  std::string big((size_t)n + 1, '\0');
  vsnprintf(big.data(), big.size(), fmt, args);
  big.resize((size_t)n);
  return big;
}

// The bytes straight to the process's own handle: no C runtime stream in between, so there
// is nothing to flush and nothing that depends on how the runtime set its streams up in a
// windowed program. Errors are ignored: a reader that has gone away is not this side's
// problem.
void write_unlocked(DWORD which, const char* data, size_t size) {
  HANDLE h = GetStdHandle(which);
  if (h == nullptr || h == INVALID_HANDLE_VALUE) return;
  while (size > 0) {
    DWORD done = 0;
    DWORD ask = size > 0x40000000u ? 0x40000000u : (DWORD)size;
    if (!WriteFile(h, data, ask, &done, nullptr) || done == 0) return;
    data += done;
    size -= done;
  }
}

// Every line on stderr starts with the local time as HH:MM:SS.mmm and a space, as each line
// of the lens's own log does, so the two can be read side by side. It is the precise system
// time, because GetLocalTime moves only with the timer tick, which can be 15.6 ms. None of
// these calls takes a lock or allocates, so die() uses it too. kStampSize characters are
// written and no terminating zero.
constexpr size_t kStampSize = 13;

void put_digits(char* at, unsigned value, int count) {
  for (int k = count - 1; k >= 0; --k, value /= 10) at[k] = (char)('0' + value % 10);
}

void time_stamp(char* out) {
  FILETIME utc, local;
  SYSTEMTIME t;
  GetSystemTimePreciseAsFileTime(&utc);
  if (!FileTimeToLocalFileTime(&utc, &local) || !FileTimeToSystemTime(&local, &t)) GetLocalTime(&t);
  put_digits(out, t.wHour, 2);
  out[2] = ':';
  put_digits(out + 3, t.wMinute, 2);
  out[5] = ':';
  put_digits(out + 6, t.wSecond, 2);
  out[8] = '.';
  put_digits(out + 9, t.wMilliseconds, 3);
  out[12] = ' ';
}

// A line on stderr gets the time in front and a line on stdout never does, since the lens
// parses stdout. The time is read under the lock, so these lines reach stderr in time order.
void write_line(DWORD which, std::mutex& lock, std::string text, bool ascii_only) {
  for (char& c : text) {
    if (c == '\n' || c == '\r') c = ' ';
    else if (ascii_only && (unsigned char)c >= 0x80) c = '?';
  }
  text.push_back('\n');
  const bool stamped = which == STD_ERROR_HANDLE;
  if (stamped) text.insert(0, kStampSize, ' ');
  std::lock_guard<std::mutex> hold(lock);
  if (stamped) time_stamp(text.data());
  write_unlocked(which, text.data(), text.size());
}

// ---------------------------------------------------------------- dying quietly

char g_last_words[256];
char g_last_line[kStampSize + sizeof(g_last_words)];  // the time and then the words, for stderr

DWORD WINAPI last_words_to_stdout(void*) {
  write_unlocked(STD_OUTPUT_HANDLE, g_last_words, strlen(g_last_words));
  return 0;
}

// Says why on both streams and ends the process at once. It takes no lock and allocates
// nothing, since it runs when something is already wrong. stderr is a file and cannot
// block. stdout is a pipe that can be full when the lens has stopped reading, so that
// write gets its own thread and half a second: a process that hangs while dying would
// leave a dead topmost window over the whole screen. The line on stderr has the time in
// front, as every line there has, and the one on stdout is the protocol line alone.
[[noreturn]] void die(const char* reason) {
  snprintf(g_last_words, sizeof(g_last_words), "engine failed %s\n", reason);
  const size_t said = strlen(g_last_words);
  time_stamp(g_last_line);
  memcpy(g_last_line + kStampSize, g_last_words, said);
  write_unlocked(STD_ERROR_HANDLE, g_last_line, kStampSize + said);
  HANDLE t = CreateThread(nullptr, 0, last_words_to_stdout, nullptr, 0, nullptr);
  if (t) WaitForSingleObject(t, 500);
  TerminateProcess(GetCurrentProcess(), (UINT)exit_code::crashed);
  for (;;) Sleep(1000);
}

LONG WINAPI on_unhandled(EXCEPTION_POINTERS* info) {
  char why[128];
  DWORD code = 0;
  void* at = nullptr;
  if (info && info->ExceptionRecord) {
    code = info->ExceptionRecord->ExceptionCode;
    at = info->ExceptionRecord->ExceptionAddress;
  }
  if (code == 0xE06D7363u) snprintf(why, sizeof(why), "a C++ exception was not caught");
  else snprintf(why, sizeof(why), "unhandled exception 0x%08lX at %p", (unsigned long)code, at);
  die(why);
}

void on_invalid_parameter(const wchar_t*, const wchar_t*, const wchar_t*, unsigned int, uintptr_t) {
  die("invalid parameter in a C runtime call");
}

void on_pure_call() { die("pure virtual call"); }

void on_terminate() { die("terminate was called, an exception was not caught"); }

void on_abort(int) { die("abort was called"); }

// ---------------------------------------------------------------- the command line

bool to_int(const std::wstring& s, int& out) {
  if (s.empty()) return false;
  wchar_t* end = nullptr;
  errno = 0;
  long v = wcstol(s.c_str(), &end, 10);
  if (end == s.c_str() || *end != 0 || errno == ERANGE) return false;
  out = (int)v;
  return true;
}

bool to_number(const std::wstring& s, double& out) {
  if (s.empty()) return false;
  wchar_t* end = nullptr;
  errno = 0;
  double v = wcstod(s.c_str(), &end);
  if (end == s.c_str() || *end != 0 || errno == ERANGE || !std::isfinite(v)) return false;
  out = v;
  return true;
}

// Two dashes and a name. A lone value such as -3072 is not an option.
bool is_option(const wchar_t* a) { return a && a[0] == L'-' && a[1] == L'-' && a[2] != 0; }

std::wstring absolute(const std::wstring& path) {
  if (path.empty()) return path;
  DWORD need = GetFullPathNameW(path.c_str(), 0, nullptr, nullptr);
  if (need == 0) return path;
  std::wstring full((size_t)need, L'\0');
  DWORD got = GetFullPathNameW(path.c_str(), need, full.data(), nullptr);
  if (got == 0 || got >= need) return path;
  full.resize(got);
  // no trailing backslash, except on a root such as C:\ where it is part of the name
  while (full.size() > 3 && (full.back() == L'\\' || full.back() == L'/')) full.pop_back();
  return full;
}

const char kUsage[] =
    "lens-fast " LENS_FAST_VERSION " is the lens's presenter for a fullscreen lens.\n"
    "\n"
    "It captures the monitor on the GPU, runs Neural Rendering on a downscaled copy\n"
    "through the stack's runtime, and presents the original plus what the network\n"
    "changed. It speaks lens_presenter.py's protocol on stdin and stdout.\n"
    "\n"
    "  lens-fast.exe --source monitor:<index> --at X Y --size W H --stack DIR\n"
    "                [--crop X Y] [--title T] [--exclude] [--ready] [--max-fps N]\n"
    "                [--data DIR] [--passes N] [--quality N] [--present hwnd|dcomp]\n"
    "                [--no-settle] [--lifetime S]\n"
    "                [--work-size W H | --work-scale S | --work-max W H]\n"
    "  lens-fast.exe --stack DIR --selftest IMAGE OUTDIR [--passes N] [--quality N]\n"
    "                [--work-size W H | --work-scale S | --work-max W H] [--data DIR]\n"
    "                [--switches LIST] [--switch-frames N] [--switch-rest S]\n"
    "  lens-fast.exe --at X Y --size W H --capturetest SECONDS [--crop X Y] [--max-fps N]\n"
    "  lens-fast.exe --steps W H\n"
    "  lens-fast.exe --help\n"
    "\n"
    "  --source monitor:<n>  monitor capture. n counts from 1 and is only repeated in\n"
    "                        the ready line. The monitor captured is the one under the\n"
    "                        middle of the --at / --size rectangle\n"
    "  --at X Y              where the window goes, in physical pixels\n"
    "  --size W H            the window's and the picture's size, in physical pixels\n"
    "  --crop X Y            where in the monitor the shown region starts (0 0)\n"
    "  --title T             the window's title (LensPresenter)\n"
    "  --exclude             keep the window out of screen captures, its own included\n"
    "  --ready               keep presenting thirty times a second while nothing changes\n"
    "  --max-fps N           at most N new pictures a second, 0 for no limit (0)\n"
    "  --stack DIR           the folder with nvngx_dlssnr.dll and ReShade.ini\n"
    "  --data DIR            a writable folder for the runtime's logs (%TEMP%\\lens-fast)\n"
    "  --passes N            neural passes, 1 to 8 (1)\n"
    "  --quality N           the quality step, 0 to 4. The network works on a copy of\n"
    "                        the picture, and a lower step makes that copy smaller, which\n"
    "                        costs less power and gives up some of the fine detail the\n"
    "                        network adds. 4 Quality, 3 Balanced, 2 Performance, 1 Low\n"
    "                        power, 0 Lowest power. Not given, it is 4 for a picture that\n"
    "                        fits 2560x1440 and 3 for a larger one, where no loss was seen\n"
    "  --work-size W H       for tests, the size the network works at in place of a step\n"
    "  --work-scale S        for tests, that size as a share of the picture, 0 to 1\n"
    "  --work-max W H        for tests, that size as the picture fitted into W x H\n"
    "  --present hwnd|dcomp  make the swapchain for the window (the default) or for\n"
    "                        DirectComposition\n"
    "  --no-settle           do not run the network again on a picture that has come to\n"
    "                        rest (it runs up to 4 more times, see settle below)\n"
    "  --lifetime S          leave after S seconds whatever happens, for tests\n"
    "  --selftest IMAGE OUTDIR\n"
    "                        run IMAGE through the pipeline with no window and no\n"
    "                        capture, time it and write the pictures into OUTDIR\n"
    "  --switches LIST       with --selftest, at the end switch through these quality\n"
    "                        steps in order, as in 4,3,2,1,0,4, and keep a picture of each\n"
    "  --switch-frames N     frames drawn at each of them (421). Under 100 no picture is\n"
    "                        kept, and such a run is for the video memory alone\n"
    "  --switch-rest S       after the last of them, S seconds with no frame and then\n"
    "                        frames again, with the video memory in use at each point\n"
    "  --capturetest SECONDS capture for that long and report, with no window and no network\n"
    "  --steps W H           print the five steps' work sizes for a W x H picture and\n"
    "                        leave. It may be given several times\n"
    "  --help                this text\n"
    "An option it does not know is ignored with a note on stderr.\n"
    "\n"
    "Lines on stdin, as lens_presenter.py reads them:\n"
    "  crop X Y | shot BASE | probe N | pause | resume | live 1|0 | wake [SECONDS]\n"
    "  cap N | ready 1|0 | clip 1|0 | stop-capture | quit\n"
    "and four of its own:\n"
    "  nr 1|0       the network on or off. Off shows the capture unchanged\n"
    "  reload       read the settings in ReShade.ini again\n"
    "  settle 1|0   on by default. When a picture that changed over 1/32 of its area or\n"
    "               more has stood still for 150 ms, the network runs on it up to 4\n"
    "               more times, so a still picture reaches the network's settled state.\n"
    "               Never while the picture changes, and under a limit no faster than\n"
    "               the limit\n"
    "  quality N    switch to that quality step, 0 to 4. The network for the new size is\n"
    "               made beside the one in use while the pictures go on, about 130 ms.\n"
    "               Then the next picture is the first at the new size, and the network\n"
    "               starts on it without its history. A picture at rest then goes through\n"
    "               the network 64 times, and once more 14 s later, which is when the\n"
    "               old network's video memory comes back\n"
    "The end of stdin means quit.\n"
    "\n"
    "Lines on stdout:\n"
    "  presenter ready ...   once the first picture is on screen. It ends with the work\n"
    "                        size, the passes and the quality step in use\n"
    "  engine quality N work WxH\n"
    "                        the answer to a quality line, once that step is in use\n"
    "  stats new=N arrived=N repeated=N dropped=N skipped=N meter=MS delay=MS\n"
    "                        once a second. meter is the time in ms from a captured\n"
    "                        frame's timestamp to the present call, negative because the\n"
    "                        timestamp is a refresh still to come. delay is the time in\n"
    "                        ms from that timestamp to the refresh that showed the\n"
    "                        picture, nan when none was learned. With\n"
    "                        LENS_PRESENTER_PROFILE=1 more pairs follow\n"
    "  paused | resumed | shot done ... | shot failed REASON\n"
    "  probe n=N median=M max=X | capture lost REASON | engine failed REASON\n";

}  // namespace

// ---------------------------------------------------------------- lines out

void say(const char* fmt, ...) {
  va_list args;
  va_start(args, fmt);
  std::string text = vformat(fmt, args);
  va_end(args);
  write_line(STD_OUTPUT_HANDLE, g_stdout_lock, std::move(text), true);
}

void note(const char* fmt, ...) {
  va_list args;
  va_start(args, fmt);
  std::string text = vformat(fmt, args);
  va_end(args);
  write_line(STD_ERROR_HANDLE, g_stderr_lock, std::move(text), false);
}

void fail(const char* fmt, ...) {
  va_list args;
  va_start(args, fmt);
  std::string text = "engine failed " + vformat(fmt, args);
  va_end(args);
  // stderr first: it is a file and always takes the line, whatever the pipe is doing
  write_line(STD_ERROR_HANDLE, g_stderr_lock, text, false);
  write_line(STD_OUTPUT_HANDLE, g_stdout_lock, std::move(text), true);
}

std::string strf(const char* fmt, ...) {
  va_list args;
  va_start(args, fmt);
  std::string text = vformat(fmt, args);
  va_end(args);
  return text;
}

std::string hr_text(HRESULT hr) { return strf("0x%08lX", (unsigned long)hr); }

std::string narrow(const std::wstring& text) {
  if (text.empty()) return std::string();
  int n = WideCharToMultiByte(CP_UTF8, 0, text.data(), (int)text.size(), nullptr, 0, nullptr, nullptr);
  if (n <= 0) return std::string();
  std::string out((size_t)n, '\0');
  WideCharToMultiByte(CP_UTF8, 0, text.data(), (int)text.size(), out.data(), n, nullptr, nullptr);
  return out;
}

std::wstring widen(const std::string& text) {
  if (text.empty()) return std::wstring();
  int n = MultiByteToWideChar(CP_UTF8, 0, text.data(), (int)text.size(), nullptr, 0);
  if (n <= 0) return std::wstring();
  std::wstring out((size_t)n, L'\0');
  MultiByteToWideChar(CP_UTF8, 0, text.data(), (int)text.size(), out.data(), n);
  return out;
}

std::string ascii(const std::wstring& text) {
  std::string out;
  out.reserve(text.size());
  for (wchar_t c : text) out.push_back(c >= 0x20 && c < 0x7F ? (char)c : '?');
  return out;
}

// ---------------------------------------------------------------- the clock

double now_s() {
  static const double seconds_per_tick = [] {
    LARGE_INTEGER f;
    QueryPerformanceFrequency(&f);
    return 1.0 / (double)f.QuadPart;
  }();
  LARGE_INTEGER t;
  QueryPerformanceCounter(&t);
  return (double)t.QuadPart * seconds_per_tick;
}

// ---------------------------------------------------------------- Neural Rendering's settings

namespace {

// One number from [RenoDX.DLSS5]. ReShade writes them with a full stop whatever the
// system's locale, and this program never changes the C locale, so wcstod reads them right.
float ini_number(const std::wstring& ini, const wchar_t* key, float fallback) {
  wchar_t text[64] = {};
  GetPrivateProfileStringW(L"RenoDX.DLSS5", key, L"", text, 64, ini.c_str());
  if (!text[0]) return fallback;
  wchar_t* end = nullptr;
  double v = wcstod(text, &end);
  if (end == text || !std::isfinite(v)) return fallback;
  return (float)v;
}

}  // namespace

bool read_nr_settings(const std::wstring& stack_dir, NrSettings& out, std::string& err) {
  out = NrSettings();
  // The path has to be a full one: given a bare name, the profile functions look in the
  // Windows folder instead.
  const std::wstring ini = path_join(absolute(stack_dir), L"ReShade.ini");
  if (!file_exists(ini)) {
    err = "no ReShade.ini in the stack folder " + narrow(stack_dir);
    return false;
  }
  const NrSettings d;
  const float style = ini_number(ini, L"NRStyle", (float)d.style);
  out.style = style > 0.0f ? (unsigned)style : 0u;
  out.intensity = ini_number(ini, L"NRIntensity", d.intensity);
  out.local_tone = ini_number(ini, L"NRLocalTone", d.local_tone);
  out.local_structure = ini_number(ini, L"NRLocalStructure", d.local_structure);
  out.skin_structure = ini_number(ini, L"NRSkinStructure", d.skin_structure);
  out.auto_mask = (int)ini_number(ini, L"NRAutoMask", (float)d.auto_mask) != 0 ? 1 : 0;
  return true;
}

bool same_settings(const NrSettings& a, const NrSettings& b) {
  return a.style == b.style && a.intensity == b.intensity && a.local_tone == b.local_tone &&
         a.local_structure == b.local_structure && a.skin_structure == b.skin_structure &&
         a.auto_mask == b.auto_mask;
}

// ---------------------------------------------------------------- the command line

bool parse_options(int argc, wchar_t** argv, Options& out, std::string& err) {
  out = Options();
  err.clear();
  Options& o = out;

  o.profile = env_text(L"LENS_PRESENTER_PROFILE") == L"1";
  {
    double hb = 0.0;
    if (to_number(env_text(L"LENS_PRESENTER_HEARTBEAT"), hb) && hb > 0.0) o.heartbeat_s = hb;
  }

  // --help wins over everything, a mistake before it included
  for (int k = 1; k < argc; ++k) {
    const std::wstring a = argv[k];
    if (a == L"--help" || a == L"-h" || a == L"/?") {
      o.help = true;
      return true;
    }
  }

  int i = 1;
  std::vector<std::wstring> v;
  // The next n arguments as the values of the option at i. A value may start with one dash,
  // it is then a negative number, but not with two: that is the next option.
  auto values = [&](int n) -> bool {
    const std::string name = narrow(argv[i]);
    v.clear();
    for (int k = 0; k < n; ++k) {
      if (i + 1 >= argc || is_option(argv[i + 1])) {
        err = strf("%s needs %d value%s", name.c_str(), n, n == 1 ? "" : "s");
        return false;
      }
      v.push_back(argv[++i]);
    }
    return true;
  };

  for (; i < argc; ++i) {
    const std::wstring a = argv[i];
    if (a == L"--source") {
      if (!values(1)) return false;
      o.source = ascii(v[0]);
    } else if (a == L"--at") {
      if (!values(2)) return false;
      if (!to_int(v[0], o.x) || !to_int(v[1], o.y)) {
        err = "--at needs two whole numbers";
        return false;
      }
      o.have_at = true;
    } else if (a == L"--size") {
      if (!values(2)) return false;
      // 16384 is the largest texture side D3D12 has
      if (!to_int(v[0], o.width) || !to_int(v[1], o.height) || o.width < 1 || o.height < 1 ||
          o.width > 16384 || o.height > 16384) {
        err = "--size needs a width and a height from 1 to 16384";
        return false;
      }
      o.have_size = true;
    } else if (a == L"--crop") {
      if (!values(2)) return false;
      if (!to_int(v[0], o.crop_x) || !to_int(v[1], o.crop_y)) {
        err = "--crop needs two whole numbers";
        return false;
      }
    } else if (a == L"--title") {
      if (!values(1)) return false;
      o.title = v[0];
    } else if (a == L"--exclude") {
      o.exclude = true;
    } else if (a == L"--ready") {
      o.ready = true;
    } else if (a == L"--max-fps") {
      if (!values(1)) return false;
      if (!to_number(v[0], o.max_fps)) {
        err = "--max-fps needs a number";
        return false;
      }
      if (o.max_fps < 0.0) o.max_fps = 0.0;
    } else if (a == L"--stack") {
      if (!values(1)) return false;
      o.stack_dir = absolute(v[0]);
    } else if (a == L"--data") {
      if (!values(1)) return false;
      o.data_dir = absolute(v[0]);
    } else if (a == L"--passes") {
      if (!values(1)) return false;
      if (!to_int(v[0], o.passes)) {
        err = "--passes needs a whole number from 1 to 8";
        return false;
      }
      if (o.passes < 1 || o.passes > 8) {
        const int asked = o.passes;
        o.passes = asked < 1 ? 1 : 8;
        note("options: --passes %d is outside 1 to 8, using %d", asked, o.passes);
      }
    } else if (a == L"--quality") {
      if (!values(1)) return false;
      if (!to_int(v[0], o.quality)) {
        err = "--quality needs a whole number from 0 to 4";
        return false;
      }
      if (o.quality < 0 || o.quality > kQualityMost) {
        const int asked = o.quality;
        o.quality = asked < 0 ? 0 : kQualityMost;
        note("options: --quality %d is outside 0 to 4, using %d", asked, o.quality);
      }
    } else if (a == L"--work-size") {
      if (!values(2)) return false;
      if (!to_int(v[0], o.work_w) || !to_int(v[1], o.work_h) || o.work_w < 1 || o.work_h < 1 ||
          o.work_w > 16384 || o.work_h > 16384) {
        err = "--work-size needs a width and a height from 1 to 16384";
        return false;
      }
    } else if (a == L"--work-max") {
      if (!values(2)) return false;
      if (!to_int(v[0], o.work_max_w) || !to_int(v[1], o.work_max_h) || o.work_max_w < 16 ||
          o.work_max_h < 16 || o.work_max_w > 16384 || o.work_max_h > 16384) {
        err = "--work-max needs a width and a height from 16 to 16384";
        return false;
      }
      o.work_max_given = true;
    } else if (a == L"--switches") {
      if (!values(1)) return false;
      // whole numbers from 0 to 4 with commas between, as in 4,3,2,1,0,4
      o.switches.clear();
      bool good = !v[0].empty();
      for (size_t at = 0; good && at <= v[0].size();) {
        const size_t comma = std::min(v[0].find(L',', at), v[0].size());
        int step = -1;
        good = to_int(v[0].substr(at, comma - at), step) && step >= 0 && step <= kQualityMost;
        if (good) o.switches.push_back(step);
        at = comma + 1;
      }
      if (!good) {
        err = "--switches needs quality steps from 0 to 4 with commas between, as in 4,3,2,1,0,4";
        return false;
      }
    } else if (a == L"--switch-frames") {
      if (!values(1)) return false;
      if (!to_int(v[0], o.switch_frames) || o.switch_frames < 1 || o.switch_frames > 100000) {
        err = "--switch-frames needs a whole number from 1 to 100000";
        return false;
      }
    } else if (a == L"--switch-rest") {
      if (!values(1)) return false;
      if (!to_number(v[0], o.switch_rest_s) || o.switch_rest_s < 0.0 || o.switch_rest_s > 120.0) {
        err = "--switch-rest needs a number of seconds from 0 to 120";
        return false;
      }
    } else if (a == L"--steps") {
      if (!values(2)) return false;
      int w = 0, h = 0;
      if (!to_int(v[0], w) || !to_int(v[1], h) || w < 1 || h < 1 || w > 16384 || h > 16384) {
        err = "--steps needs a width and a height from 1 to 16384";
        return false;
      }
      o.steps_for.push_back(w);
      o.steps_for.push_back(h);
    } else if (a == L"--work-scale") {
      if (!values(1)) return false;
      if (!to_number(v[0], o.work_scale)) {
        err = "--work-scale needs a number above 0 and up to 1";
        return false;
      }
      if (o.work_scale <= 0.0) {
        note("options: --work-scale %g is not above 0, fitting --work-max instead", o.work_scale);
        o.work_scale = 0.0;
      } else if (o.work_scale > 1.0) {
        note("options: --work-scale %g is above 1, using 1", o.work_scale);
        o.work_scale = 1.0;
      }
    } else if (a == L"--present") {
      if (!values(1)) return false;
      if (_wcsicmp(v[0].c_str(), L"hwnd") == 0) o.present = PresentPath::Hwnd;
      else if (_wcsicmp(v[0].c_str(), L"dcomp") == 0) o.present = PresentPath::Dcomp;
      else {
        err = "--present needs hwnd or dcomp";
        return false;
      }
    } else if (a == L"--no-settle") {
      o.settle = false;
    } else if (a == L"--lifetime") {
      if (!values(1)) return false;
      if (!to_number(v[0], o.lifetime_s)) {
        err = "--lifetime needs a number of seconds";
        return false;
      }
      if (o.lifetime_s < 0.0) o.lifetime_s = 0.0;
    } else if (a == L"--selftest") {
      if (!values(2)) return false;
      o.selftest = true;
      o.selftest_image = absolute(v[0]);
      o.selftest_outdir = absolute(v[1]);
    } else if (a == L"--capturetest") {
      if (!values(1)) return false;
      if (!to_number(v[0], o.capturetest_seconds) || o.capturetest_seconds <= 0.0) {
        err = "--capturetest needs a number of seconds above 0";
        return false;
      }
      o.capturetest = true;
    } else if (is_option(a.c_str())) {
      // not ours, --fifo for one: skip it and whatever values follow it
      int skipped = 0;
      while (i + 1 < argc && !is_option(argv[i + 1])) {
        ++i;
        ++skipped;
      }
      note("options: ignoring %s, which this engine does not have%s", narrow(a).c_str(),
           skipped ? ", and its values" : "");
    } else {
      note("options: ignoring the stray argument %s", narrow(a).c_str());
    }
  }

  // --steps only prints, and nothing else is required or checked
  if (!o.steps_for.empty()) return true;

  if (o.data_dir.empty()) {
    wchar_t temp[MAX_PATH + 2] = {};
    DWORD n = GetTempPathW(MAX_PATH + 1, temp);
    o.data_dir = absolute(path_join(n ? std::wstring(temp, n) : std::wstring(L"."), L"lens-fast"));
  }

  // the source, when one was given: monitor:<n> is the only kind this engine has
  if (!o.source.empty()) {
    const size_t colon = o.source.find(':');
    const std::string kind = o.source.substr(0, colon);
    const std::string ref = colon == std::string::npos ? std::string() : o.source.substr(colon + 1);
    if (kind == "monitor") {
      if (!to_int(widen(ref), o.monitor_index) || o.monitor_index < 1) {
        err = "--source monitor needs a number from 1, as in monitor:1";
        return false;
      }
    } else if (!o.selftest) {
      if (kind == "window") err = "window capture is not in the fast engine, only monitor capture";
      else if (kind == "pattern") err = "the pattern source is not in the fast engine";
      else err = "unknown source " + o.source;
      return false;
    }
  }

  if (o.selftest) {
    if (o.stack_dir.empty()) {
      err = "--selftest needs --stack DIR";
      return false;
    }
    return true;
  }
  if (o.capturetest) {
    if (!o.have_at || !o.have_size) {
      err = "--capturetest needs --at X Y and --size W H";
      return false;
    }
    return true;
  }

  std::string missing;
  auto lacks = [&](bool have, const char* name) {
    if (have) return;
    if (!missing.empty()) missing += ", ";
    missing += name;
  };
  lacks(!o.source.empty(), "--source");
  lacks(o.have_at, "--at");
  lacks(o.have_size, "--size");
  lacks(!o.stack_dir.empty(), "--stack");
  if (!missing.empty()) {
    err = "the command line lacks " + missing + " (--help lists the options)";
    return false;
  }
  return true;
}

const char* usage_text() { return kUsage; }

void print_usage() {
  std::lock_guard<std::mutex> hold(g_stdout_lock);
  write_unlocked(STD_OUTPUT_HANDLE, kUsage, sizeof(kUsage) - 1);
}

// ---------------------------------------------------------------- the quality steps

namespace {

struct Size {
  int w = 0, h = 0;
};

// The picture fitted into most_w x most_h, each side rounded to nearest. The scale is the
// smallest of 1, most_w / W and most_h / H, kept as a fraction num / den so that the
// rounding is exact: in floating point 2526 * (2560 / 6144) can land on either side of
// 1052.5. A half rounds up. 6144x2526 into 2560x1440 gives 2560x1053.
constexpr Size fitted(int W, int H, int most_w, int most_h) {
  long long num = 1, den = 1;
  if ((long long)most_w * den < num * W) {
    num = most_w;
    den = W;
  }
  if ((long long)most_h * den < num * H) {
    num = most_h;
    den = H;
  }
  Size s;
  s.w = (int)((2LL * W * num + den) / (2 * den));
  s.h = (int)((2LL * H * num + den) / (2 * den));
  if (s.w > W) s.w = W;
  if (s.h > H) s.h = H;
  return s;
}

// The kinds of picture the rule tells apart, numbered as work_table.h numbers them.
constexpr int kNative = 0;      // the picture fits 2560x1440
constexpr int kDownscaled = 1;  // larger, and 900 rows or more are left when it is fitted
constexpr int kShort = 2;       // larger, and fewer rows are left, as for a 32:9 screen

// The largest multiple of 128 not above x, 128 at least.
constexpr int floor128(int x) {
  const int v = (x / 128) * 128;
  return v < 128 ? 128 : v;
}

// The multiple of 128 nearest to that many percent of x, a half going up, 128 at least.
constexpr int near128(int x, int percent) {
  const int v = (int)(((long long)percent * x + 6400) / 12800) * 128;
  return v < 128 ? 128 : v;
}

// h, and at least 128 under `above`, and 128 at least.
constexpr int below(int h, int above) {
  const int v = h < above - 128 ? h : above - 128;
  return v < 128 ? 128 : v;
}

struct Ruled {
  int kind = kNative;
  Size step[5];  // by step, 0 to 4
};

// The rule gives the five work sizes of a picture size that is not in the table. It is the
// recipe the table's sizes were chosen by, and it gives every entry of the table, which is
// checked below when this file is compiled. tools\make_work_table.py holds the same rule in
// Python.
//
// R is the reference size, the picture fitted into 2560x1440. f is floor128, r is near128.
//   native      R is the picture itself. Any resampling takes away the network's finest
//               texture, and a narrower width takes it away both ways, so the width stays
//               and only the height steps down:
//               4 R, 3 (Rw, r(82% Rh)), 2 (Rw, r(70% Rh)), 1 (Rw, r(60% Rh)),
//               0 (r(60% Rw), height of 1)
//   downscaled  4 (f(Rw), f(Rh)), 3 (f(Rw), r(82% Rh)), 2 (r(85% Rw), height of 3),
//               1 (f(Rw), r(60% Rh)), 0 (r(60% Rw), height of 1)
//   short       the height has little room left, so the width steps down first:
//               4 (f(Rw), f(Rh)), 3 (r(85% Rw), height of 4), 2 (width of 3, height of 4 - 128),
//               1 (r(60% Rw), height of 2), 0 (width of 1, height of 2 - 128)
//               With 768 rows or more in R, step 3 is (f(Rw), f(Rh) - 128) instead. Measured
//               on 3840x1200, 2560x640 took 2.692 ms where 2176x768 took 2.688, and was
//               nearer the reference on all four test pictures.
// A step's height is at least 128 rows under the height above it where both have the same
// width. A native picture of 128 rows or fewer has no such height. Its steps 3 to 1 are the
// picture itself, since one row fewer would resample every row and save nothing.
// A downscaled step 0 that lands on 1280 wide takes 1408. 1280 was a weak width, the
// network's change there about a tenth under its neighbours'.
// At the end no side is larger than the picture's and no step is larger than the one above
// it, which only matters for pictures of a few hundred texels.
constexpr Ruled quality_rule(int W, int H) {
  if (W < 1) W = 1;
  if (H < 1) H = 1;
  const Size ref = fitted(W, H, 2560, 1440);
  const int rw = ref.w, rh = ref.h;
  Ruled r;
  if (rw == W && rh == H) {
    r.kind = kNative;
    int h3 = below(near128(rh, 82), floor128(rh) + (rh % 128 ? 128 : 0));
    if (h3 >= rh) h3 = rh;  // with 128 rows or fewer there is no multiple of 128 under the picture
    const int h2 = below(near128(rh, 70), h3);
    const int h1 = below(near128(rh, 60), h2);
    const int w0 = near128(rw, 60) < rw ? near128(rw, 60) : rw;
    r.step[4] = {rw, rh};
    r.step[3] = {rw, h3};
    r.step[2] = {rw, h2};
    r.step[1] = {rw, h1};
    r.step[0] = {w0, h1};
  } else if (rh >= 900) {
    r.kind = kDownscaled;
    const int w4 = floor128(rw), h4 = floor128(rh);
    const int h3 = near128(rh, 82) < h4 ? below(near128(rh, 82), h4 + 128) : h4 - 128;
    const int w2 = near128(rw, 85) < w4 - 128 ? near128(rw, 85) : w4 - 128;
    const int h1 = below(near128(rh, 60), h3);
    int w0 = near128(rw, 60) < w4 ? near128(rw, 60) : w4;
    if (w0 == 1280 && w2 - 128 >= 1408) w0 = 1408;
    r.step[4] = {w4, h4};
    r.step[3] = {w4, h3};
    r.step[2] = {w2, h3};
    r.step[1] = {w4, h1};
    r.step[0] = {w0, h1};
  } else {
    r.kind = kShort;
    const int w4 = floor128(rw), h4 = floor128(rh);
    const int w3 = near128(rw, 85) < w4 - 128 ? near128(rw, 85) : w4 - 128;
    const int h2 = below(h4 - 128, h4);
    const int w1 = near128(rw, 60) < w3 - 128 ? near128(rw, 60) : w3 - 128;
    const int h0 = below(h2 - 128, h2);
    r.step[4] = {w4, h4};
    r.step[3] = {w3, h4};
    r.step[2] = {w3, h2};
    r.step[1] = {w1, h2};
    r.step[0] = {w1, h0};
    if (rh >= 768) r.step[3] = {w4, h4 - 128};
  }
  for (int k = 4; k >= 0; --k) {
    Size s = r.step[k];
    if (s.w > W) s.w = W;
    if (s.h > H) s.h = H;
    if (s.w < 1) s.w = 1;
    if (s.h < 1) s.h = 1;
    if (k < 4 && (long long)s.w * s.h > (long long)r.step[k + 1].w * r.step[k + 1].h) s = r.step[k + 1];
    r.step[k] = s;
  }
  return r;
}

constexpr bool rule_gives(int W, int H, int kind, Size s4, Size s3, Size s2, Size s1, Size s0) {
  const Ruled r = quality_rule(W, H);
  const Size want[5] = {s0, s1, s2, s3, s4};
  for (int k = 0; k < 5; ++k) {
    if (r.step[k].w != want[k].w || r.step[k].h != want[k].h) return false;
  }
  return r.kind == kind;
}

// Every entry of the table that the tool marked as the rule's is what this rule gives, and
// every other entry is not.
constexpr bool rule_gives_table() {
  for (const work_table::Entry& e : work_table::kEntries) {
    const Ruled r = quality_rule(e.width, e.height);
    bool same = r.kind == e.kind;
    for (int k = 0; k < 5; ++k) same = same && r.step[k].w == e.step[k].w && r.step[k].h == e.step[k].h;
    if (same != e.by_rule) return false;
  }
  return true;
}
static_assert(rule_gives_table(), "quality_rule() and work_table.h disagree, see tools\\make_work_table.py");

// Sizes that are not in the table: a fullscreen lens on four common screens, which is the
// screen less the 34 rows of the lens's title bar, and two pictures too small for the grid.
static_assert(rule_gives(3840, 2126, kDownscaled, {2560, 1408}, {2560, 1152}, {2176, 1152}, {2560, 896}, {1536, 896}));
static_assert(rule_gives(3440, 1406, kDownscaled, {2560, 1024}, {2560, 896}, {2176, 896}, {2560, 640}, {1536, 640}));
static_assert(rule_gives(5120, 1406, kShort, {2560, 640}, {2176, 640}, {2176, 512}, {1536, 512}, {1536, 384}));
static_assert(rule_gives(3840, 1166, kShort, {2560, 768}, {2560, 640}, {2176, 640}, {1536, 640}, {1536, 512}));
static_assert(rule_gives(2560, 1406, kNative, {2560, 1406}, {2560, 1152}, {2560, 1024}, {2560, 896}, {1536, 896}));
static_assert(rule_gives(1920, 1046, kNative, {1920, 1046}, {1920, 896}, {1920, 768}, {1920, 640}, {1152, 640}));
static_assert(rule_gives(640, 360, kNative, {640, 360}, {640, 256}, {640, 128}, {640, 128}, {384, 128}));
static_assert(rule_gives(100, 80, kNative, {100, 80}, {100, 80}, {100, 80}, {100, 80}, {100, 80}));
static_assert(rule_gives(240, 86, kNative, {240, 86}, {240, 86}, {240, 86}, {240, 86}, {128, 86}));
static_assert(rule_gives(128, 128, kNative, {128, 128}, {128, 128}, {128, 128}, {128, 128}, {128, 128}));
static_assert(rule_gives(240, 129, kNative, {240, 129}, {240, 128}, {240, 128}, {240, 128}, {128, 128}));

const work_table::Entry* table_entry(int W, int H) {
  for (const work_table::Entry& e : work_table::kEntries) {
    if (e.width == W && e.height == H) return &e;
  }
  return nullptr;
}

int held_step(int step) { return step < 0 ? 0 : (step > kQualityMost ? kQualityMost : step); }

}  // namespace

const char* quality_name(int step) {
  static const char* const names[kQualityMost + 1] = {"Lowest power", "Low power", "Performance", "Balanced",
                                                      "Quality"};
  return step >= 0 && step <= kQualityMost ? names[step] : "";
}

int default_quality(int W, int H) {
  const work_table::Entry* e = table_entry(W, H);
  return work_table::kDefaultStep[e ? e->kind : quality_rule(W, H).kind];
}

void quality_work_size(int W, int H, int step, int& work_w, int& work_h, bool* measured) {
  step = held_step(step);
  const work_table::Entry* e = table_entry(W, H);
  if (measured) *measured = e != nullptr;
  if (e) {
    work_w = e->step[step].w;
    work_h = e->step[step].h;
    return;
  }
  const Ruled r = quality_rule(W, H);
  work_w = r.step[step].w;
  work_h = r.step[step].h;
}

bool quality_figures(int W, int H, int step, double& ms, double& kept) {
  const work_table::Entry* e = table_entry(W, H);
  if (!e || step < 0 || step > kQualityMost) return false;
  ms = e->step[step].ms;
  kept = e->step[step].kept;
  return true;
}

std::string steps_text(int W, int H) {
  std::string text = strf("steps %dx%d:", W, H);
  bool measured = false;
  for (int step = kQualityMost; step >= 0; --step) {
    int w = 0, h = 0;
    quality_work_size(W, H, step, w, h, &measured);
    text += strf(" %d %s %dx%d,", step, quality_name(step), w, h);
  }
  return text + strf(" default %d, %s", default_quality(W, H), measured ? "measured" : "by the rule");
}

WorkPlan work_plan(int W, int H, const Options& o) {
  if (W < 1) W = 1;
  if (H < 1) H = 1;
  WorkPlan p;
  if (o.work_w > 0 && o.work_h > 0) {
    p.given_by = "--work-size";
    p.w = o.work_w;
    p.h = o.work_h;
  } else if (o.work_scale > 0.0) {
    p.given_by = "--work-scale";
    const double s = o.work_scale < 1.0 ? o.work_scale : 1.0;
    p.w = (int)std::llround((double)W * s);
    p.h = (int)std::llround((double)H * s);
  } else if (o.work_max_given) {
    p.given_by = "--work-max";
    const Size s = fitted(W, H, o.work_max_w, o.work_max_h);
    p.w = s.w;
    p.h = s.h;
  } else {
    p.chosen = o.quality >= 0;
    p.quality = p.chosen ? held_step(o.quality) : default_quality(W, H);
    quality_work_size(W, H, p.quality, p.w, p.h, &p.measured);
  }
  if (p.w < 1) p.w = 1;
  if (p.h < 1) p.h = 1;
  if (p.w > W) p.w = W;
  if (p.h > H) p.h = H;
  return p;
}

// ---------------------------------------------------------------- rates

int capture_interval_ms(double max_fps, double refresh_hz) {
  if (max_fps <= 0.0 || refresh_hz <= 0.0) return 0;
  const int per = (int)(refresh_hz / max_fps + 0.05);  // 119.88 Hz reports as 119 or 120
  if (per < 2) return 0;
  return (int)(((double)per - 0.5) * 1000.0 / refresh_hz);
}

// ---------------------------------------------------------------- the process

void set_quiet_failures() {
  // no "program has stopped working", no "there is no disk in the drive", no file open box
  SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX);
  // assert and the runtime's own error reports go to stderr, never into a message box,
  // whatever the program's subsystem
  _set_error_mode(_OUT_TO_STDERR);
  _set_abort_behavior(0, _WRITE_ABORT_MSG | _CALL_REPORTFAULT);
  _CrtSetReportMode(_CRT_WARN, _CRTDBG_MODE_FILE);
  _CrtSetReportFile(_CRT_WARN, _CRTDBG_FILE_STDERR);
  _CrtSetReportMode(_CRT_ERROR, _CRTDBG_MODE_FILE);
  _CrtSetReportFile(_CRT_ERROR, _CRTDBG_FILE_STDERR);
  _CrtSetReportMode(_CRT_ASSERT, _CRTDBG_MODE_FILE);
  _CrtSetReportFile(_CRT_ASSERT, _CRTDBG_FILE_STDERR);
  _set_invalid_parameter_handler(on_invalid_parameter);
  _set_purecall_handler(on_pure_call);
  std::set_terminate(on_terminate);
  signal(SIGABRT, on_abort);
  SetUnhandledExceptionFilter(on_unhandled);
}

void leave_now(int code) {
  TerminateProcess(GetCurrentProcess(), (UINT)code);
  for (;;) Sleep(1000);
}

void set_dpi_aware() {
  // It fails when the awareness is already set, which is as good.
  if (!SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)) {
    if (GetLastError() != ERROR_ACCESS_DENIED) SetProcessDPIAware();
  }
}

HMONITOR monitor_under(int x, int y, int w, int h) {
  POINT middle = {x + w / 2, y + h / 2};
  return MonitorFromPoint(middle, MONITOR_DEFAULTTONEAREST);
}

// ---------------------------------------------------------------- small helpers

std::wstring exe_dir() {
  std::wstring path(32768, L'\0');
  DWORD n = GetModuleFileNameW(nullptr, path.data(), (DWORD)path.size());
  path.resize(n);
  const size_t cut = path.find_last_of(L"\\/");
  return cut == std::wstring::npos ? std::wstring() : path.substr(0, cut);
}

std::wstring path_join(const std::wstring& a, const std::wstring& b) {
  if (a.empty()) return b;
  if (b.empty()) return a;
  size_t skip = 0;
  while (skip < b.size() && (b[skip] == L'\\' || b[skip] == L'/')) ++skip;
  if (a.back() == L'\\' || a.back() == L'/') return a + b.substr(skip);
  return a + L"\\" + b.substr(skip);
}

bool file_exists(const std::wstring& path) {
  const DWORD attr = GetFileAttributesW(path.c_str());
  return attr != INVALID_FILE_ATTRIBUTES && !(attr & FILE_ATTRIBUTE_DIRECTORY);
}

bool dir_exists(const std::wstring& path) {
  const DWORD attr = GetFileAttributesW(path.c_str());
  return attr != INVALID_FILE_ATTRIBUTES && (attr & FILE_ATTRIBUTE_DIRECTORY);
}

bool make_dirs(const std::wstring& path) {
  if (path.empty()) return false;
  std::error_code ec;
  std::filesystem::create_directories(std::filesystem::path(path), ec);
  return dir_exists(path);
}

std::wstring env_text(const wchar_t* name) {
  const DWORD need = GetEnvironmentVariableW(name, nullptr, 0);
  if (need == 0) return std::wstring();
  std::wstring value((size_t)need, L'\0');
  const DWORD got = GetEnvironmentVariableW(name, value.data(), need);
  if (got == 0 || got >= need) return std::wstring();
  value.resize(got);
  return value;
}
