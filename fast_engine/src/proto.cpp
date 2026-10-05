// proto.cpp: the commands on stdin, the screenshot's files and clipboard copy, and the
// probe's arithmetic. The contract is proto.h, the protocol is lens_presenter.py's.
//
// Nothing here touches the GPU or the window. The parts that are plain arithmetic on bytes
// and words are written so that the compiler can work them out, and the end of this file
// has it do so: what a line of stdin parses to, the order of the bytes in the PNG rows, in
// the side by side picture and in the clipboard's bitmap. No test program links this file
// by itself, so that is where its logic is proven. What needs Windows to run (the pipe, the
// Windows Imaging Component, the clipboard) has been compiled and read, not run.
#include "proto.h"

#include <objbase.h>
#include <wincodec.h>
#include <wrl/client.h>

#include <algorithm>
#include <climits>
#include <cmath>
#include <cstdlib>
#include <deque>
#include <memory>
#include <mutex>
#include <new>
#include <string_view>
#include <thread>

using Microsoft::WRL::ComPtr;

namespace {

// ---------------------------------------------------------------- words and numbers

// What Python's split() and strip() take for a blank in a line of ASCII.
constexpr bool is_blank(char c) {
  return c == ' ' || c == '\t' || c == '\r' || c == '\n' || c == '\v' || c == '\f';
}

constexpr bool is_digit(char c) { return c >= '0' && c <= '9'; }

constexpr std::string_view trimmed(std::string_view s) {
  while (!s.empty() && is_blank(s.front())) s.remove_prefix(1);
  while (!s.empty() && is_blank(s.back())) s.remove_suffix(1);
  return s;
}

// The words of a line. Four are kept: no command takes more than two values, and a fourth
// word only ever says "too many". count goes on counting past them.
struct Words {
  std::string_view word[4];
  int count = 0;
};

constexpr Words words_of(std::string_view s) {
  Words w;
  size_t i = 0;
  while (i < s.size()) {
    while (i < s.size() && is_blank(s[i])) ++i;
    if (i >= s.size()) break;
    const size_t start = i;
    while (i < s.size() && !is_blank(s[i])) ++i;
    if (w.count < 4) w.word[w.count] = s.substr(start, i - start);
    ++w.count;
  }
  return w;
}

// A whole number as the lens writes one with %d: a sign if any, then digits and nothing
// else. One beyond an int is held at the end of the range and not refused: Python's int
// takes any size, and the capture clamps a crop to the frame anyway.
constexpr bool whole(std::string_view s, int& out) {
  size_t i = 0;
  bool negative = false;
  if (i < s.size() && (s[i] == '+' || s[i] == '-')) negative = s[i++] == '-';
  if (i >= s.size()) return false;
  long long v = 0;
  for (; i < s.size(); ++i) {
    if (!is_digit(s[i])) return false;
    if (v <= INT_MAX) v = v * 10 + (s[i] - '0');  // past the range it no longer matters
  }
  if (negative) v = -v;
  out = v > INT_MAX ? INT_MAX : v < INT_MIN ? INT_MIN : (int)v;
  return true;
}

// Whether a word has the shape of a plain decimal number: a sign if any, digits with or
// without a point, an exponent if any. That leaves out what strtod would also take and a
// frame rate or a number of seconds never is: inf, nan and hexadecimal.
constexpr bool decimal_shape(std::string_view s) {
  size_t i = 0;
  if (i < s.size() && (s[i] == '+' || s[i] == '-')) ++i;
  size_t digits = 0;
  for (; i < s.size() && is_digit(s[i]); ++i) ++digits;
  if (i < s.size() && s[i] == '.') {
    ++i;
    for (; i < s.size() && is_digit(s[i]); ++i) ++digits;
  }
  if (digits == 0) return false;
  if (i < s.size() && (s[i] == 'e' || s[i] == 'E')) {
    ++i;
    if (i < s.size() && (s[i] == '+' || s[i] == '-')) ++i;
    size_t exponent = 0;
    for (; i < s.size() && is_digit(s[i]); ++i) ++exponent;
    if (exponent == 0) return false;
  }
  return i == s.size();
}

// "live 0", "live off" and "live no" switch off, anything else switches on, "OFF" too:
// the presenter compares as written.
constexpr bool is_off(std::string_view word) { return word == "0" || word == "off" || word == "no"; }

// ---------------------------------------------------------------- one line

// A line as far as it can be read without Windows or the C library: which command, its
// whole numbers, and the two things that still need converting, as they stand in the line.
struct Parsed {
  Command::Kind kind = Command::Quit;
  int x = 0;
  int y = 0;
  int n = 0;
  bool on = false;
  std::string_view number;  // the value of "cap" or "wake" as written. Empty when "wake"
                            // came without one, or with something that is not a number
  std::string_view text;    // the BASE of "shot", as bytes
};

// The rules of lens_presenter.py's commands(), one for one and in its order, then the four
// commands of this engine's own. False for a line there is nothing to do for.
constexpr bool parse_line(std::string_view line, Parsed& out) {
  out = Parsed();
  const std::string_view all = trimmed(line);
  const Words w = words_of(all);
  if (w.count == 0) return false;
  const std::string_view name = w.word[0];

  if (name == "quit") {
    out.kind = Command::Quit;
    return true;
  }
  if (name == "crop") {
    if (w.count != 3 || !whole(w.word[1], out.x) || !whole(w.word[2], out.y)) return false;
    out.kind = Command::Crop;
    return true;
  }
  if (name == "shot") {
    if (w.count < 2) return false;
    // everything after the command, so a path with spaces in it stays whole
    out.text = trimmed(all.substr(name.size()));
    out.kind = Command::Shot;
    return true;
  }
  if (name == "stop-capture") {
    out.kind = Command::StopCapture;
    return true;
  }
  if (name == "pause") {
    out.kind = Command::Pause;
    return true;
  }
  if (name == "resume") {
    out.kind = Command::Resume;
    return true;
  }
  if (name == "live" || name == "ready" || name == "clip" || name == "nr" || name == "settle") {
    if (w.count != 2) return false;
    out.on = !is_off(w.word[1]);
    out.kind = name == "live" ? Command::Live
               : name == "ready" ? Command::Ready
               : name == "clip" ? Command::Clip
               : name == "nr" ? Command::Nr
               : Command::Settle;
    return true;
  }
  if (name == "cap") {
    if (w.count != 2 || !decimal_shape(w.word[1])) return false;
    out.number = w.word[1];
    out.kind = Command::Cap;
    return true;
  }
  if (name == "wake") {
    // the seconds are optional, and a bad value is one second and not a refusal
    if (w.count > 1 && decimal_shape(w.word[1])) out.number = w.word[1];
    out.kind = Command::Wake;
    return true;
  }
  if (name == "probe") {
    if (w.count != 2 || !whole(w.word[1], out.n)) return false;
    if (out.n < 0) out.n = 0;
    out.kind = Command::Probe;
    return true;
  }
  if (name == "reload") {
    out.kind = Command::Reload;
    return true;
  }
  if (name == "quality") {
    if (w.count != 2 || !whole(w.word[1], out.n)) return false;
    if (out.n < 0) out.n = 0;
    if (out.n > kQualityMost) out.n = kQualityMost;
    out.kind = Command::Quality;
    return true;
  }
  return false;
}

// A word of the right shape as a number. strtod and no reader of our own, so that "cap
// 59.94" gives the very double that --max-fps 59.94 gives through wcstod, and the loop does
// not take the same limit for a new one and start the capture again for nothing.
bool number(std::string_view word, double& out) {
  if (!decimal_shape(word)) return false;
  const std::string text(word);
  char* end = nullptr;
  const double v = strtod(text.c_str(), &end);
  if (end != text.c_str() + text.size() || !std::isfinite(v)) return false;
  out = v;
  return true;
}

// The bytes of a path as the lens wrote them. Python writes the pipe in the ANSI code page
// unless it runs in UTF-8 mode, and nothing in the bytes says which. Text that is valid
// UTF-8 is all but never anything else, so that is tried first, strictly.
std::wstring decoded(std::string_view bytes) {
  if (bytes.empty()) return std::wstring();
  const int size = (int)bytes.size();
  int n = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, bytes.data(), size, nullptr, 0);
  UINT page = CP_UTF8;
  DWORD flags = MB_ERR_INVALID_CHARS;
  if (n <= 0) {
    page = CP_ACP;
    flags = 0;
    n = MultiByteToWideChar(page, flags, bytes.data(), size, nullptr, 0);
  }
  if (n <= 0) return std::wstring();
  std::wstring out((size_t)n, L'\0');
  MultiByteToWideChar(page, flags, bytes.data(), size, out.data(), n);
  return out;
}

}  // namespace

bool parse_command(const std::string& line, Command& out) {
  out = Command();
  Parsed p;
  if (!parse_line(line, p)) return false;
  out.kind = p.kind;
  out.x = p.x;
  out.y = p.y;
  out.n = p.n;
  out.on = p.on;
  if (p.kind == Command::Cap) {
    double fps = 0.0;
    if (!number(p.number, fps)) return false;  // too large for a double: not a limit
    out.value = fps > 0.0 ? fps : 0.0;
  } else if (p.kind == Command::Wake) {
    double seconds = 1.0;
    if (p.number.empty() || !number(p.number, seconds)) seconds = 1.0;
    out.value = seconds;
  } else if (p.kind == Command::Shot) {
    out.text = decoded(p.text);
    if (out.text.empty()) return false;
  }
  return true;
}

// ---------------------------------------------------------------- the reader

namespace {

// A line longer than this is no command: the longest real one is "shot" with a path.
constexpr size_t kLongestLine = 65536;

// Cuts the bytes of stdin into lines, however the reads happen to split them. A line is
// handed on without its line feed, and with the carriage return Python's text mode puts
// before it, which the parser takes off as a blank.
struct LineCutter {
  std::string line;    // the bytes since the last line feed
  bool skip = false;   // this line outgrew the limit and is dropped up to its end
  size_t longest = kLongestLine;

  // Hands every line these bytes complete to take(line). True as soon as take() says so,
  // and the bytes after that line are then left unread: that is "quit".
  template <class Take>
  constexpr bool feed(const char* bytes, size_t count, Take&& take) {
    size_t from = 0;
    for (size_t i = 0; i < count; ++i) {
      if (bytes[i] != '\n') continue;
      line.append(bytes + from, i - from);
      from = i + 1;
      const bool stop = !skip && line.size() <= longest && take(line);
      line.clear();
      skip = false;
      if (stop) return true;
    }
    line.append(bytes + from, count - from);
    if (line.size() > longest) {
      line.clear();
      skip = true;
    }
    return false;
  }

  // The end of the input: a last line without its line feed still counts, as it does for
  // Python's "for line in sys.stdin".
  template <class Take>
  constexpr bool finish(Take&& take) {
    const bool stop = !skip && !line.empty() && take(line);
    line.clear();
    skip = false;
    return stop;
  }
};

}  // namespace

struct CommandReader::Impl {
  // What the reading thread and the object share. The thread can outlive the object,
  // blocked in a read that nothing can end, so this block belongs to both and goes when
  // the later of the two lets go of it.
  struct Shared {
    std::mutex lock;
    std::deque<Command> queue;
    bool stopped = false;    // stop() was called: nothing more is queued or signalled
    HANDLE event = nullptr;  // auto-reset, set after every push
    HANDLE in = nullptr;     // the process's stdin, not ours to close
    bool pipe = false;

    ~Shared() {
      if (event) CloseHandle(event);
    }

    void push(Command&& command) {
      std::lock_guard<std::mutex> hold(lock);
      if (stopped) return;
      queue.push_back(std::move(command));
      SetEvent(event);
    }
  };

  std::shared_ptr<Shared> shared;
  bool attached = false;

  static bool take(Shared& shared, const std::string& line);
  static void read_all(std::shared_ptr<Shared> shared);
};

// One line in, parsed and queued. True when it was "quit": nothing is read after that, as
// in the presenter.
bool CommandReader::Impl::take(Shared& shared, const std::string& line) {
  Command command;
  if (!parse_command(line, command)) return false;
  const bool quit = command.kind == Command::Quit;
  shared.push(std::move(command));
  return quit;
}

// The thread. It ends on "quit", at the end of stdin and on any read error, and each of
// the last two queues a Quit: the lens closing its end of the pipe is how it tells a
// presenter to leave, and a lens that died must not leave a topmost window behind.
void CommandReader::Impl::read_all(std::shared_ptr<Shared> shared) {
  try {
    LineCutter cut;
    auto take = [&shared](const std::string& line) { return Impl::take(*shared, line); };
    char bytes[4096];
    for (;;) {
      DWORD got = 0;
      if (!ReadFile(shared->in, bytes, sizeof(bytes), &got, nullptr)) {
        const DWORD code = GetLastError();
        if (code == ERROR_BROKEN_PIPE) note("commands: the lens closed stdin");
        else note("commands: reading stdin failed, error %lu", code);
        break;
      }
      if (got == 0) {
        // A file ends this way. A pipe hands an empty write over like this, which is not
        // its end: that comes as ERROR_BROKEN_PIPE above.
        if (shared->pipe) {
          Sleep(1);
          continue;
        }
        note("commands: stdin is at its end");
        break;
      }
      if (cut.feed(bytes, got, take)) return;
    }
    if (cut.finish(take)) return;
  } catch (...) {
    // only an allocation can throw in there, and then the engine had better leave
  }
  try {
    Command quit;
    quit.kind = Command::Quit;
    shared->push(std::move(quit));
  } catch (...) {
  }
}

CommandReader::CommandReader() {}

CommandReader::~CommandReader() {
  stop();
  delete impl_;
  impl_ = nullptr;
}

bool CommandReader::start(std::string& err) {
  // Once. A second thread on the same handle would split the lines between the two.
  if (impl_) return true;
  err.clear();

  Impl* made = nullptr;
  try {
    made = new Impl;
    made->shared = std::make_shared<Impl::Shared>();
  } catch (...) {
    delete made;
    err = "out of memory";
    return false;
  }
  Impl::Shared& shared = *made->shared;

  shared.event = CreateEventW(nullptr, FALSE, FALSE, nullptr);  // auto-reset, not set
  if (!shared.event) {
    err = strf("CreateEvent failed, error %lu", GetLastError());
    delete made;
    return false;
  }

  // Started by the lens, stdin is a pipe. Started by hand, a windowed program has no stdin
  // at all, or a number left over from a parent that had none to give, which GetFileType
  // tells apart from a real handle.
  HANDLE in = GetStdHandle(STD_INPUT_HANDLE);
  DWORD type = FILE_TYPE_UNKNOWN;
  if (in == INVALID_HANDLE_VALUE) in = nullptr;
  if (in) {
    SetLastError(NO_ERROR);
    type = GetFileType(in);
    if (type == FILE_TYPE_UNKNOWN && GetLastError() != NO_ERROR) in = nullptr;
  }
  if (in) {
    shared.in = in;
    shared.pipe = type == FILE_TYPE_PIPE;
    try {
      // Detached: it may sit in ReadFile for as long as the lens says nothing, and no
      // one waits for it. The process leaves through leave_now().
      std::thread(Impl::read_all, made->shared).detach();
    } catch (...) {
      err = "the thread that reads stdin could not be started";
      delete made;
      return false;
    }
    made->attached = true;
  }
  impl_ = made;
  return true;
}

bool CommandReader::attached() const { return impl_ && impl_->attached; }

HANDLE CommandReader::event() const { return impl_ ? impl_->shared->event : nullptr; }

bool CommandReader::next(Command& out) {
  if (!impl_) return false;
  Impl::Shared& shared = *impl_->shared;
  std::lock_guard<std::mutex> hold(shared.lock);
  if (shared.queue.empty()) return false;
  out = std::move(shared.queue.front());
  shared.queue.pop_front();
  return true;
}

void CommandReader::stop() {
  if (!impl_) return;
  // From here on the thread queues nothing and sets nothing, whatever it still reads. The
  // event itself stays open for as long as this object lives, since the loop may still
  // have it in a wait, and is closed with the shared block.
  Impl::Shared& shared = *impl_->shared;
  std::lock_guard<std::mutex> hold(shared.lock);
  shared.stopped = true;
  shared.queue.clear();
}

// ---------------------------------------------------------------- pixels

namespace {

// The largest side a picture may have here. Far above any lens (a D3D12 texture ends at
// 16384, and the side by side picture is two of those and the gap), and small enough that
// no size worked out below leaves 32 bits.
constexpr int kLargestSide = 65536;

// The gap between the two halves of the side by side picture, as lens_presenter.py has
// it: 8 pixels of grey 90.
constexpr int kGap = 8;
constexpr uint8_t kGapGrey = 90;

// What CF_DIB starts with: a BITMAPINFOHEADER, written here byte by byte.
constexpr size_t kDibHeader = 40;
static_assert(sizeof(BITMAPINFOHEADER) == kDibHeader);

// One row of RGB into BGR, the order the PNG encoder takes its 24 bit pixels in.
constexpr void swap_red_blue(const uint8_t* rgb, uint8_t* bgr, int pixels) {
  for (int i = 0; i < pixels; ++i) {
    bgr[0] = rgb[2];
    bgr[1] = rgb[1];
    bgr[2] = rgb[0];
    rgb += 3;
    bgr += 3;
  }
}

// before, the gap, after, row by row into out: (2 * width + kGap) * height * 3 bytes.
constexpr void join_rows(const uint8_t* before, const uint8_t* after, int width, int height,
                         uint8_t* out) {
  const size_t row = (size_t)width * 3;
  for (int y = 0; y < height; ++y) {
    out = std::copy_n(before + (size_t)y * row, row, out);
    out = std::fill_n(out, (size_t)kGap * 3, kGapGrey);
    out = std::copy_n(after + (size_t)y * row, row, out);
  }
}

constexpr void put16(uint8_t* at, uint32_t v) {
  at[0] = (uint8_t)(v & 0xFF);
  at[1] = (uint8_t)((v >> 8) & 0xFF);
}

constexpr void put32(uint8_t* at, uint32_t v) {
  put16(at, v & 0xFFFF);
  put16(at + 2, v >> 16);
}

// The clipboard's bitmap into out, kDibHeader + width * height * 4 bytes: the header, then
// the rows from the bottom one up, each pixel as blue, green, red and an alpha of 255.
// The same bytes lens_presenter.py's clipboard_image packs.
constexpr void fill_dib(uint8_t* out, const uint8_t* rgb, int width, int height) {
  put32(out + 0, (uint32_t)kDibHeader);                        // biSize
  put32(out + 4, (uint32_t)width);                             // biWidth
  put32(out + 8, (uint32_t)height);                            // biHeight: above 0, bottom up
  put16(out + 12, 1);                                          // biPlanes
  put16(out + 14, 32);                                         // biBitCount
  put32(out + 16, 0);                                          // biCompression: BI_RGB
  put32(out + 20, (uint32_t)((size_t)width * height * 4));     // biSizeImage
  put32(out + 24, 2835);                                       // biXPelsPerMeter: 72 an inch
  put32(out + 28, 2835);                                       // biYPelsPerMeter
  put32(out + 32, 0);                                          // biClrUsed
  put32(out + 36, 0);                                          // biClrImportant
  uint8_t* at = out + kDibHeader;
  for (int y = height - 1; y >= 0; --y) {
    const uint8_t* row = rgb + (size_t)y * width * 3;
    for (int x = 0; x < width; ++x) {
      at[0] = row[2];
      at[1] = row[1];
      at[2] = row[0];
      at[3] = 255;
      at += 4;
      row += 3;
    }
  }
}

// The mean of |a - b| over n bytes, 0 for none. What numpy's abs(cur - prev).mean() gives
// for the presenter's int16 arrays.
constexpr double mean_abs(const uint8_t* a, const uint8_t* b, size_t n) {
  if (n == 0) return 0.0;
  uint64_t sum = 0;
  for (size_t i = 0; i < n; ++i) sum += a[i] > b[i] ? a[i] - b[i] : b[i] - a[i];
  return (double)sum / (double)n;
}

// The probe's two figures: the median, the upper one of an even count as the presenter's
// d[len(d) // 2] is, and the largest. False when there is no difference to report.
constexpr bool summary(std::vector<double> d, double& median, double& largest) {
  if (d.empty()) return false;
  std::sort(d.begin(), d.end());
  median = d[d.size() / 2];
  largest = d.back();
  return true;
}

// ---------------------------------------------------------------- the PNG

// One picture through the Windows Imaging Component's PNG encoder. created says whether
// this call made the file, which is when a failure may take it away again.
HRESULT encode_png(const std::wstring& path, const uint8_t* rgb, int width, int height,
                   bool& created) {
  created = false;
  ComPtr<IWICImagingFactory> factory;
  HRESULT hr = CoCreateInstance(CLSID_WICImagingFactory, nullptr, CLSCTX_INPROC_SERVER,
                                IID_PPV_ARGS(&factory));
  if (FAILED(hr)) return hr;
  ComPtr<IWICStream> stream;
  hr = factory->CreateStream(&stream);
  if (FAILED(hr)) return hr;
  hr = stream->InitializeFromFilename(path.c_str(), GENERIC_WRITE);  // replaces the file
  if (FAILED(hr)) return hr;
  created = true;
  ComPtr<IWICBitmapEncoder> encoder;
  hr = factory->CreateEncoder(GUID_ContainerFormatPng, nullptr, &encoder);
  if (FAILED(hr)) return hr;
  hr = encoder->Initialize(stream.Get(), WICBitmapEncoderNoCache);
  if (FAILED(hr)) return hr;
  ComPtr<IWICBitmapFrameEncode> frame;
  hr = encoder->CreateNewFrame(&frame, nullptr);
  if (FAILED(hr)) return hr;
  hr = frame->Initialize(nullptr);
  if (FAILED(hr)) return hr;
  hr = frame->SetSize((UINT)width, (UINT)height);
  if (FAILED(hr)) return hr;
  // 24 bits and no alpha in the file. The encoder answers with the format it will really
  // write, and any other answer would mean these bytes are not what it expects.
  WICPixelFormatGUID format = GUID_WICPixelFormat24bppBGR;
  hr = frame->SetPixelFormat(&format);
  if (FAILED(hr)) return hr;
  if (format != GUID_WICPixelFormat24bppBGR) return WINCODEC_ERR_UNSUPPORTEDPIXELFORMAT;

  // The rows go over in strips of about a megabyte, turned from RGB to BGR on the way, so
  // no second copy of a 46 MB picture is ever held. Each row starts on a multiple of four
  // bytes, which every width's stride is then sure to satisfy.
  const size_t tight = (size_t)width * 3;
  const size_t stride = (tight + 3) & ~(size_t)3;
  const int rows_a_strip = (int)std::max<size_t>(1, ((size_t)1 << 20) / stride);
  const std::unique_ptr<uint8_t[]> strip(new (std::nothrow) uint8_t[stride * rows_a_strip]());
  if (!strip) return E_OUTOFMEMORY;
  for (int y = 0; y < height; y += rows_a_strip) {
    const int rows = std::min(rows_a_strip, height - y);
    for (int r = 0; r < rows; ++r) {
      swap_red_blue(rgb + (size_t)(y + r) * tight, strip.get() + (size_t)r * stride, width);
    }
    hr = frame->WritePixels((UINT)rows, (UINT)stride, (UINT)(stride * rows), strip.get());
    if (FAILED(hr)) return hr;
  }
  hr = frame->Commit();
  if (FAILED(hr)) return hr;
  return encoder->Commit();
}

}  // namespace

bool write_png(const std::wstring& path, const uint8_t* rgb, int width, int height,
               std::string& err) {
  HRESULT hr = E_INVALIDARG;
  bool created = false;
  if (rgb && width >= 1 && height >= 1 && width <= kLargestSide && height <= kLargestSide) {
    // COM for this thread and for this call. S_FALSE means the thread had it already, and
    // that still wants its pair. RPC_E_CHANGED_MODE means the thread has it in the other
    // mode, which serves as well and is not ours to end. Everything encode_png holds is
    // released when it returns, before COM goes.
    const HRESULT com = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    hr = encode_png(path, rgb, width, height, created);
    if (SUCCEEDED(com)) CoUninitialize();
  }
  if (SUCCEEDED(hr)) return true;
  // Half a PNG under a screenshot's name is worse than none. Only a file this call made:
  // one that could not even be opened is somebody else's and stays.
  if (created) DeleteFileW(path.c_str());
  err = "cannot write " + narrow(path) + " " + hr_text(hr);
  return false;
}

// ---------------------------------------------------------------- the clipboard

bool clipboard_image(const uint8_t* rgb, int width, int height) {
  if (!rgb || width < 1 || height < 1 || width > kLargestSide || height > kLargestSide) return false;
  const uint64_t pixels = (uint64_t)width * (uint64_t)height * 4;
  if (pixels > 0x7FFFFFFFull - kDibHeader) return false;  // the header counts them in 32 bits
  HGLOBAL memory = GlobalAlloc(GMEM_MOVEABLE, (SIZE_T)(kDibHeader + pixels));
  if (!memory) return false;
  uint8_t* at = (uint8_t*)GlobalLock(memory);
  if (!at) {
    GlobalFree(memory);
    return false;
  }
  fill_dib(at, rgb, width, height);
  GlobalUnlock(memory);

  // Another program may hold the clipboard for a moment. No window is named as its owner,
  // as in the presenter. The documentation of OpenClipboard says SetClipboardData then
  // fails. That holds for data promised for later, which needs a window to ask. Memory
  // handed over outright is taken, and the presenter has put its screenshots there this
  // way since 0.4.0.
  bool open = false;
  for (int attempt = 0; attempt < 10 && !open; ++attempt) {
    open = OpenClipboard(nullptr) != FALSE;
    if (!open) Sleep(50);
  }
  if (!open) {
    GlobalFree(memory);
    return false;
  }
  EmptyClipboard();
  const bool taken = SetClipboardData(CF_DIB, memory) != nullptr;
  CloseClipboard();
  // The memory is the system's once the clipboard has taken it, and still ours when not.
  if (!taken) GlobalFree(memory);
  return taken;
}

// ---------------------------------------------------------------- the screenshot

namespace {

// One file being written, perhaps on a thread of its own. The thread is the last member so
// that it is the first to go: its destructor waits for it, while ok and err still exist.
struct Encoding {
  bool ok = false;
  std::string err;
  std::jthread thread;
};

// Writes the PNG on a thread of its own, or right here when no thread is to be had. The
// path and the pixels have to outlive the Encoding.
void encode_beside(Encoding& job, const std::wstring& path, const uint8_t* rgb, int width,
                   int height) {
  auto work = [&job, &path, rgb, width, height] {
    try {
      job.ok = write_png(path, rgb, width, height, job.err);
    } catch (...) {
      job.ok = false;
      job.err = "out of memory";
    }
  };
  try {
    job.thread = std::jthread(work);
  } catch (...) {
    work();
  }
}

// Writes a NumPy array file, version 1.0 of the format: the magic string, the version, the
// header's length in two bytes, the header as a Python dictionary padded with spaces to a
// multiple of 64 bytes and ending in a newline, then the data as it lies in memory. Here
// the array is height x width x 4 halves ('<f2', float16). A file that could not be
// written whole is deleted, so no half file stays under the name.
bool write_npy_f16(const std::wstring& path, const uint16_t* halves, int width, int height, std::string& err) {
  std::string header = strf("{'descr': '<f2', 'fortran_order': False, 'shape': (%d, %d, 4), }", height, width);
  const size_t preamble = 10;  // magic, version, header length
  size_t padded = header.size() + 1;
  if ((preamble + padded) % 64) padded += 64 - (preamble + padded) % 64;
  header.resize(padded - 1, ' ');
  header.push_back('\n');
  std::string head = "\x93NUMPY";
  head.push_back('\x01');
  head.push_back('\x00');
  head.push_back((char)(padded & 0xFF));
  head.push_back((char)((padded >> 8) & 0xFF));
  head += header;

  HANDLE h = CreateFileW(path.c_str(), GENERIC_WRITE, 0, nullptr, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
  if (h == INVALID_HANDLE_VALUE) {
    err = "cannot write " + narrow(path) + strf(" error %lu", GetLastError());
    return false;
  }
  bool ok = true;
  DWORD done = 0;
  ok = WriteFile(h, head.data(), (DWORD)head.size(), &done, nullptr) && done == head.size();
  const uint8_t* bytes = (const uint8_t*)halves;
  size_t left = (size_t)width * (size_t)height * 8;
  while (ok && left > 0) {
    const DWORD ask = (DWORD)std::min<size_t>(left, 1u << 24);
    ok = WriteFile(h, bytes, ask, &done, nullptr) && done == ask;
    bytes += done;
    left -= done;
  }
  CloseHandle(h);
  if (!ok) {
    DeleteFileW(path.c_str());
    err = "cannot write " + narrow(path);
  }
  return ok;
}

std::string save_shot_files(const Shot& shot) {
  const int width = shot.width, height = shot.height;
  if (width < 1 || height < 1 || width > kLargestSide / 2 - kGap || height > kLargestSide) {
    return strf("shot failed a picture of %dx%d cannot be saved", width, height);
  }
  const size_t bytes = (size_t)width * (size_t)height * 3;
  if (shot.before.size() != bytes) return "shot failed there is no captured frame to save";
  const bool both = !shot.after.empty();
  if (both && shot.after.size() != bytes) return "shot failed the presented picture has another size";

  const std::wstring before_path = shot.base + L"-before.png";
  const std::wstring after_path = shot.base + L"-after.png";
  const std::wstring joined_path = shot.base + L"-side-by-side.png";
  const int joined_width = 2 * width + kGap;
  std::vector<uint8_t> joined;
  bool joined_ok = false;
  std::string joined_err;

  // The three files are encoded side by side: the two single pictures on threads of their
  // own while this one joins and writes the third. The lens waits 5 s for the reply and
  // then calls the screenshot lost. Measured with this encoder (through WPF's wrapper of
  // it, default options, one core) on this project's two 6144x2526 Blender pictures:
  // 0.30 s and 0.48 s for the two, 0.79 s for the 12296x2526 side by side one, so 1.6 s
  // one after another and about half of that this way. A slower processor or a noisier
  // picture has that much more room.
  // Declared after everything the threads read, so they are waited for before any of it
  // goes.
  Encoding before, after;
  encode_beside(before, before_path, shot.before.data(), width, height);
  if (both) {
    encode_beside(after, after_path, shot.after.data(), width, height);
    joined.resize((size_t)joined_width * (size_t)height * 3);
    join_rows(shot.before.data(), shot.after.data(), width, height, joined.data());
    joined_ok = write_png(joined_path, joined.data(), joined_width, height, joined_err);
  }
  if (before.thread.joinable()) before.thread.join();
  if (after.thread.joinable()) after.thread.join();

  // The reply names what was done, in the presenter's order, and the first thing in that
  // order that failed is the reason.
  if (!before.ok) return "shot failed " + before.err;
  std::string done = "shot done before";
  if (both) {
    if (!after.ok) return "shot failed " + after.err;
    done += ", after";
    if (!joined_ok) return "shot failed " + joined_err;
    done += ", side by side";
    if (shot.clipboard && clipboard_image(joined.data(), joined_width, height)) done += ", clipboard";
  }
  // the raw 16-bit frame and the picture drawn in 16-bit floats, for a test: last, so the
  // pictures are there whatever becomes of them
  if (!shot.raw.empty()) {
    if (shot.raw.size() != (size_t)width * (size_t)height * 4) return "shot failed the raw frame has another size";
    std::string raw_err;
    if (!write_npy_f16(shot.base + L"-raw.npy", shot.raw.data(), width, height, raw_err)) return "shot failed " + raw_err;
    done += ", raw";
  }
  if (!shot.out.empty()) {
    if (shot.out.size() != (size_t)width * (size_t)height * 4) return "shot failed the drawn picture has another size";
    std::string out_err;
    if (!write_npy_f16(shot.base + L"-out.npy", shot.out.data(), width, height, out_err)) return "shot failed " + out_err;
    done += ", out";
  }
  return done;
}

}  // namespace

std::string save_shot(const Shot& shot) {
  try {
    return save_shot_files(shot);
  } catch (...) {
    // Only an allocation throws in there: the joined picture is 93 MB at 6144x2526.
    return "shot failed out of memory";
  }
}

// ---------------------------------------------------------------- the probe

namespace {

// One more presented picture for a probe that is running. True when it was the last one.
// N pictures give N - 1 differences: the first has nothing before it, and neither has one
// of another size, which starts the comparison over.
constexpr bool probe_add(ProbeRun& run, const std::vector<uint8_t>& picture) {
  if (!run.prev.empty() && run.prev.size() == picture.size()) {
    run.diffs.push_back(mean_abs(run.prev.data(), picture.data(), picture.size()));
  }
  run.prev = picture;
  return --run.left <= 0;
}

}  // namespace

void ProbeRun::begin(int n) {
  left = n > 0 ? n : 0;
  prev.clear();
  diffs.clear();
}

bool ProbeRun::add(const std::vector<uint8_t>& sparse_rgb, std::string& reply) {
  reply.clear();
  if (left <= 0) return false;
  try {
    if (!probe_add(*this, sparse_rgb)) return false;
    double median = 0.0, largest = 0.0;
    if (summary(diffs, median, largest)) {
      reply = strf("probe n=%d median=%.3f max=%.3f", (int)diffs.size(), median, largest);
    } else {
      // written out, since printf's own text for a NaN is not Python's
      reply = "probe n=0 median=nan max=nan";
    }
  } catch (...) {
    // out of memory: the probe ends here with nothing to report
    left = 0;
    reply = "probe n=0 median=nan max=nan";
  }
  std::vector<uint8_t>().swap(prev);
  return true;
}

double mean_abs_diff(const std::vector<uint8_t>& a, const std::vector<uint8_t>& b) {
  if (a.size() != b.size()) return 0.0;
  return mean_abs(a.data(), b.data(), a.size());
}

// ---------------------------------------------------------------- checked when compiled
//
// The compiler works every one of these out, and the build stops at the first that no
// longer holds. They are the protocol's leniency in examples: each line is one the lens
// sends, or one the presenter is known to ignore.

namespace {

constexpr bool parses(std::string_view line, Command::Kind kind) {
  Parsed p;
  return parse_line(line, p) && p.kind == kind;
}

constexpr bool ignored(std::string_view line) {
  Parsed p;
  return !parse_line(line, p);
}

// as the lens writes them: Python's text mode ends every line with a carriage return too
static_assert(parses("quit\r", Command::Quit) && parses("quit now", Command::Quit));
static_assert(parses("pause\r", Command::Pause) && parses("resume\r", Command::Resume));
static_assert(parses("stop-capture\r", Command::StopCapture) && parses("reload\r", Command::Reload));
static_assert(ignored("") && ignored(" \t\r") && ignored("QUIT") && ignored("frobnicate 1"));

static_assert([] {
  Parsed p;
  return parse_line("crop 12 -7\r", p) && p.kind == Command::Crop && p.x == 12 && p.y == -7 &&
         parse_line("  crop\t+3   4 ", p) && p.x == 3 && p.y == 4;
}());
static_assert(ignored("crop") && ignored("crop 1") && ignored("crop 1 2 3") &&
              ignored("crop 1.5 2") && ignored("crop x 2") && ignored("crop 1 -"));
static_assert([] {
  Parsed p;
  return parse_line("crop 99999999999 -99999999999", p) && p.x == INT_MAX && p.y == INT_MIN &&
         parse_line("crop 2147483647 -2147483648", p) && p.x == INT_MAX && p.y == INT_MIN &&
         parse_line("crop 2147483646 -2147483647", p) && p.x == INT_MAX - 1 && p.y == INT_MIN + 1;
}());

static_assert([] {
  Parsed p;
  return parse_line("live 1", p) && p.kind == Command::Live && p.on &&
         parse_line("live 0", p) && p.kind == Command::Live && !p.on &&
         parse_line("ready off", p) && p.kind == Command::Ready && !p.on &&
         parse_line("clip no", p) && p.kind == Command::Clip && !p.on &&
         parse_line("clip 1\r", p) && p.kind == Command::Clip && p.on &&
         parse_line("nr 0", p) && p.kind == Command::Nr && !p.on &&
         parse_line("nr yes", p) && p.kind == Command::Nr && p.on &&
         parse_line("settle 0\r", p) && p.kind == Command::Settle && !p.on &&
         parse_line("settle 1", p) && p.kind == Command::Settle && p.on &&
         parse_line("ready OFF", p) && p.on;
}());
static_assert(ignored("live") && ignored("live 1 2") && ignored("nr") && ignored("clip") &&
              ignored("settle") && ignored("settle 1 0") && ignored("settled 1"));

static_assert([] {
  Parsed p;
  return parse_line("probe 5", p) && p.kind == Command::Probe && p.n == 5 &&
         parse_line("probe -3", p) && p.n == 0 && parse_line("probe 0", p) && p.n == 0;
}());
static_assert(ignored("probe") && ignored("probe 2.0") && ignored("probe 1 2") && ignored("probe n"));

static_assert([] {
  Parsed p;
  return parse_line("quality 3\r", p) && p.kind == Command::Quality && p.n == 3 &&
         parse_line("quality 0", p) && p.n == 0 && parse_line("quality 4", p) && p.n == 4 &&
         parse_line("quality -1", p) && p.n == 0 && parse_line("quality 9", p) && p.n == 4;
}());
static_assert(ignored("quality") && ignored("quality 2.0") && ignored("quality 1 2") &&
              ignored("quality high") && ignored("qualities 1"));

static_assert([] {
  Parsed p;
  return parse_line("cap 60\r", p) && p.kind == Command::Cap && p.number == "60" &&
         parse_line("cap 59.94", p) && p.number == "59.94" &&
         parse_line("cap -1e1", p) && p.number == "-1e1" && parse_line("cap .5", p) &&
         parse_line("cap 5.", p) && parse_line("cap 0", p) && p.number == "0";
}());
static_assert(ignored("cap") && ignored("cap fast") && ignored("cap 60 1") && ignored("cap inf") &&
              ignored("cap nan") && ignored("cap 0x10") && ignored("cap 1e") && ignored("cap .") &&
              ignored("cap -") && ignored("cap 1e+") && ignored("cap 1.2.3"));

static_assert([] {
  Parsed p;
  return parse_line("wake\r", p) && p.kind == Command::Wake && p.number.empty() &&
         parse_line("wake 2.5", p) && p.kind == Command::Wake && p.number == "2.5" &&
         parse_line("wake soon", p) && p.kind == Command::Wake && p.number.empty() &&
         parse_line("wake 3 4", p) && p.number == "3";
}());

static_assert([] {
  Parsed p;
  return parse_line("shot C:\\Users\\a b\\lens-20261001-1pass \r\n", p) &&
         p.kind == Command::Shot && p.text == "C:\\Users\\a b\\lens-20261001-1pass" &&
         parse_line("shot \t x y", p) && p.text == "x y" && parse_line("  shot z", p) &&
         p.text == "z";
}());
static_assert(ignored("shot") && ignored("shot   \r") && ignored("shots x"));

// two pixels of RGB as the encoder wants them
static_assert([] {
  const uint8_t rgb[6] = {1, 2, 3, 4, 5, 6};
  uint8_t bgr[6] = {};
  swap_red_blue(rgb, bgr, 2);
  return bgr[0] == 3 && bgr[1] == 2 && bgr[2] == 1 && bgr[3] == 6 && bgr[4] == 5 && bgr[5] == 4;
}());

// two pictures of one pixel by two rows, side by side: before, eight of grey, after
static_assert([] {
  const uint8_t before[6] = {1, 2, 3, 4, 5, 6};
  const uint8_t after[6] = {7, 8, 9, 10, 11, 12};
  const size_t row = (size_t)(1 + kGap + 1) * 3;
  uint8_t out[2 * (1 + kGap + 1) * 3] = {};
  join_rows(before, after, 1, 2, out);
  for (size_t i = 3; i < 3 + (size_t)kGap * 3; ++i) {
    if (out[i] != kGapGrey || out[row + i] != kGapGrey) return false;
  }
  return out[0] == 1 && out[1] == 2 && out[2] == 3 && out[row - 3] == 7 && out[row - 2] == 8 &&
         out[row - 1] == 9 && out[row] == 4 && out[row + 2] == 6 && out[2 * row - 3] == 10 &&
         out[2 * row - 1] == 12;
}());

// a 2x2 picture as the clipboard's bitmap: the 40 byte header, then the bottom row first,
// blue first, alpha 255
static_assert([] {
  const uint8_t rgb[12] = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12};
  uint8_t dib[kDibHeader + 16] = {};
  fill_dib(dib, rgb, 2, 2);
  const uint8_t header[kDibHeader] = {40, 0, 0, 0, 2, 0, 0, 0, 2, 0, 0, 0, 1, 0, 32, 0, 0, 0, 0, 0,
                                      16, 0, 0, 0, 0x13, 0x0B, 0, 0, 0x13, 0x0B, 0, 0, 0, 0, 0, 0,
                                      0, 0, 0, 0};
  const uint8_t pixels[16] = {9, 8, 7, 255, 12, 11, 10, 255, 3, 2, 1, 255, 6, 5, 4, 255};
  for (size_t i = 0; i < kDibHeader; ++i) {
    if (dib[i] != header[i]) return false;
  }
  for (size_t i = 0; i < 16; ++i) {
    if (dib[kDibHeader + i] != pixels[i]) return false;
  }
  return true;
}());

// the probe: the mean of the absolute differences, the upper median, the largest
static_assert([] {
  const uint8_t a[4] = {0, 10, 255, 7};
  const uint8_t b[4] = {4, 6, 0, 7};
  return mean_abs(a, b, 4) == (4 + 4 + 255 + 0) / 4.0 && mean_abs(a, b, 0) == 0.0;
}());
static_assert([] {
  double median = 0.0, largest = 0.0;
  return summary({3.0, 1.0, 4.0, 2.0}, median, largest) && median == 3.0 && largest == 4.0 &&
         summary({5.0}, median, largest) && median == 5.0 && largest == 5.0 &&
         summary({2.0, 1.0, 3.0}, median, largest) && median == 2.0 && !summary({}, median, largest);
}());

// three pictures give two differences, and one picture gives none
static_assert([] {
  const std::vector<uint8_t> a = {0, 0, 0}, b = {3, 0, 0}, c = {3, 6, 0};
  ProbeRun run;
  run.left = 3;
  if (probe_add(run, a) || !run.diffs.empty()) return false;
  if (probe_add(run, b) || run.diffs.size() != 1) return false;
  if (!probe_add(run, c) || run.diffs.size() != 2) return false;
  ProbeRun one;
  one.left = 1;
  return run.diffs[0] == 1.0 && run.diffs[1] == 2.0 && run.left == 0 && probe_add(one, a) &&
         one.diffs.empty();
}());

// a picture of another size is compared with nothing, and the next one with it
static_assert([] {
  const std::vector<uint8_t> first = {0, 0, 0}, wide = {9, 9, 9, 9, 9, 9}, next = {9, 9, 9, 9, 9, 3};
  ProbeRun run;
  run.left = 4;
  return !probe_add(run, first) && !probe_add(run, wide) && run.diffs.empty() &&
         !probe_add(run, next) && run.diffs.size() == 1 && run.diffs[0] == 1.0 &&
         probe_add(run, next) && run.diffs.size() == 2 && run.diffs[1] == 0.0;
}());

// What a LineCutter hands on for these reads: each line in brackets, and a "!" where a
// line said stop, which "quit" does here as it does in the reader.
constexpr std::string cut_up(std::initializer_list<std::string_view> reads, size_t longest) {
  LineCutter cut;
  cut.longest = longest;
  std::string seen;
  auto take = [&seen](const std::string& line) {
    seen += '[';
    seen += line;
    seen += ']';
    return line == "quit";
  };
  for (const std::string_view read : reads) {
    if (cut.feed(read.data(), read.size(), take)) return seen + '!';
  }
  if (cut.finish(take)) return seen + '!';
  return seen;
}

// lines cut wherever the reads fall, an empty line, and nothing read after "quit"
static_assert(cut_up({"cro", "p 1 2\r\npau", "se\r\n\r\nqu", "it\nnever read\n"}, 64) ==
              "[crop 1 2\r][pause\r][\r][quit]!");
// a last line without its line feed
static_assert(cut_up({"pause\nresume"}, 64) == "[pause][resume]");
static_assert(cut_up({"pause\n", "qu", "it"}, 64) == "[pause][quit]!");
static_assert(cut_up({"", "\n", "x\n", ""}, 64) == "[][x]");
// a line over the limit is dropped whole, whether a read ends inside it or not, and the
// line after it is read as usual
static_assert(cut_up({"0123456789", "0123456789\nlive 1\n"}, 16) == "[live 1]");
static_assert(cut_up({"abcdefgh", "ijkl\nok\n"}, 4) == "[ok]");
static_assert(cut_up({"abcdefgh"}, 4) == "" && cut_up({"abcd"}, 4) == "[abcd]");

}  // namespace
