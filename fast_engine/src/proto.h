// proto.h: the lens's side of the conversation that does not touch the GPU.
//
//   - the commands on stdin, read by a thread and handed to the main loop
//   - the screenshot: PNG files and the clipboard
//   - the probe's arithmetic
//
// The protocol is lens_presenter.py's, whose docstring is the reference, plus four commands
// of this engine's own, "nr", "reload", "settle" and "quality". What goes out on stdout is the
// main loop's business (main.cpp); the reply texts built here are handed back for it to
// say().
#pragma once

#include "common.h"

// ---------------------------------------------------------------- commands on stdin

// One line of stdin, parsed. Which fields mean something depends on the kind.
struct Command {
  enum Kind {
    Crop,         // crop X Y          x, y: move the captured region
    Shot,         // shot BASE         text: BASE, everything after "shot ", spaces and all
    Probe,        // probe N           n: read back the next N presented pictures, 0 or more
    Pause,        // pause
    Resume,       // resume
    Live,         // live 1|0          on
    Wake,         // wake [SECONDS]    value: seconds, 1 when not given or not a number
    Cap,          // cap N             value: pictures a second, 0 or more, 0 no limit
    Ready,        // ready 1|0         on
    Clip,         // clip 1|0          on: screenshots also go to the clipboard
    StopCapture,  // stop-capture      end the capture as Windows does, for tests
    Quit,         // quit, and the end of stdin
    Nr,           // nr 1|0            on: the network on or off
    Reload,       // reload            read the settings in ReShade.ini again
    Settle,       // settle 1|0        on: a picture come to rest goes through the network again
    Quality,      // quality N         n: the quality step to switch to, 0 to 4
  };
  Kind kind = Quit;
  int x = 0;
  int y = 0;
  int n = 0;
  bool on = false;
  double value = 0.0;
  std::wstring text;
};

// Parses one line as lens_presenter.py's commands() does. Any thread, no state.
//   - Words are separated by blanks. The first is the command, in lower case as written.
//   - "live", "ready", "clip", "nr" and "settle" take exactly one word: off for "0", "off"
//     and "no", on for anything else.
//   - "crop" needs exactly two whole numbers, "probe" and "quality" exactly one, "cap"
//     exactly one number. A negative probe or cap counts as 0, and a quality outside 0 to 4
//     as the nearer of the two. With the wrong count or something that is not a number the
//     line is ignored, as the presenter ignores it. A whole number is
//     a sign if any and digits, and one beyond an int is held at the end of the range. A
//     number is a plain decimal, with or without a point or an exponent: "inf", "nan" and
//     hexadecimal are not numbers here.
//   - "quit", "pause", "resume", "stop-capture" and "reload" go by their first word alone,
//     whatever follows it.
//   - "shot" keeps the rest of the line after "shot " with the blanks at both ends taken
//     off, so a path with spaces in it works. The lens writes the pipe in the ANSI code
//     page unless Python runs in UTF-8 mode, so the bytes are read as UTF-8 when they are
//     valid UTF-8 and in the ANSI code page otherwise.
// Returns false for an empty line, an unknown command or one with bad values: nothing is
// to be done for it.
bool parse_command(const std::string& line, Command& out);

// Reads stdin on a thread of its own and queues the commands for the main loop.
class CommandReader {
 public:
  CommandReader();
  ~CommandReader();  // calls stop()
  CommandReader(const CommandReader&) = delete;
  CommandReader& operator=(const CommandReader&) = delete;

  // Starts the thread. Main thread, once.
  //   - Lines are read from the process's stdin handle with ReadFile, split at line feeds,
  //     a carriage return before one dropped, and parsed with parse_command(). A line of
  //     more than 65536 bytes is no command and is dropped whole.
  //   - "quit" is queued and ends the thread: nothing after it is read, as in the
  //     presenter.
  //   - The end of the file, or any read error, queues one Quit and ends the thread: the
  //     lens closing its end of the pipe is how it tells a presenter to leave, and a lens
  //     that died must not leave a topmost window behind. A last line without its line
  //     feed is still taken first.
  //   - With no stdin handle at all (started by hand, not by the lens), or one that is
  //     not a handle, nothing is queued and attached() is false. The loop decides what
  //     that means: it leaves at once unless --lifetime bounds the run.
  // false with err only when the event or the thread cannot be created.
  bool start(std::string& err);

  // Whether there was a stdin handle to read. Valid after start().
  bool attached() const;

  // An auto-reset event, set whenever a command has been queued. The loop puts it into
  // its wait and, on every wake, calls next() until it returns false. Valid from start()
  // until the object is destroyed.
  HANDLE event() const;

  // Takes the oldest queued command. false when the queue is empty. Main thread.
  bool next(Command& out);

  // Stops caring about stdin: from here on nothing is queued, next() gives nothing and
  // the event is never set again. The thread may still be blocked in ReadFile, which
  // cannot be interrupted on every kind of handle, so it is not joined: the process is
  // about to leave anyway. The event itself stays open until the object is destroyed, as
  // event() promises, since the loop may still have it in a wait. Safe to call twice.
  void stop();

 private:
  struct Impl;
  Impl* impl_ = nullptr;
};

// ---------------------------------------------------------------- the screenshot

// Writes an 8 bit RGB PNG, without alpha. rgb is tight: width * height * 3 bytes, top row
// first. Any thread: it uses the Windows Imaging Component and initialises COM for the
// call itself. The file is replaced when it exists.
// false with err, "cannot write <path> 0x...". A file this call began and could not
// finish is removed again.
bool write_png(const std::wstring& path, const uint8_t* rgb, int width, int height,
               std::string& err);

// Puts a picture on the clipboard as a device independent bitmap (CF_DIB), 32 bit and
// bottom up, which every program pastes. Any thread. The clipboard may be held by another
// program for a moment, so opening it is tried ten times, 50 ms apart.
// false when it could not be done. That is not worth an error to the user: the files are
// saved all the same.
bool clipboard_image(const uint8_t* rgb, int width, int height);

// Everything a "shot BASE" needs once the pictures are read back from the GPU.
struct Shot {
  std::wstring base;            // BASE as it came in the command
  int width = 0;
  int height = 0;
  std::vector<uint8_t> before;  // the captured frame, tight RGB8 (Pipeline::read_native)
  std::vector<uint8_t> after;   // what was presented (Pipeline::read_target), or empty
                                // when there is none
  bool clipboard = false;       // the state of "clip"
};

// Saves the screenshot exactly as lens_presenter.py does and returns the reply line:
//   BASE-before.png        the captured frame
//   BASE-after.png         the presented picture, when there is one
//   BASE-side-by-side.png  before, a separator 8 pixels wide of grey 90, after
//   and, with clipboard set, the side by side picture on the clipboard
// The reply is "shot done before, after, side by side, clipboard", naming only what was
// done, or "shot failed REASON" when a file could not be written. The caller passes it
// to say().
// Any thread, and it should not be the main one: encoding three PNGs of a fullscreen
// picture (the side by side one is 12296x2526 for a 6144x2526 lens) takes long enough to
// hold up the window's messages and to look like a hang to the watchdog. It touches no
// GPU and no shared state.
// The lens waits 5 s for the reply, so the three files are encoded at the same time, two
// of them on threads this call starts and waits for. Measured with the same encoder on
// two 6144x2526 pictures: 0.30 s and 0.48 s for the single ones, 0.79 s for the side by
// side one, 1.6 s had they been written one after another.
std::string save_shot(const Shot& shot);

// ---------------------------------------------------------------- the probe

// "probe N": how steady the output is. The next N presented pictures are read back, every
// 4th texel each way (Pipeline::read_target_sparse), and each is compared with the one
// before it: the mean absolute difference over all bytes, out of 255. As in
// lens_presenter.py, N pictures give N - 1 differences, and the reply names that count.
struct ProbeRun {
  int left = 0;                // pictures still to read; 0 means no probe is running
  std::vector<uint8_t> prev;   // the picture before, empty at the start
  std::vector<double> diffs;

  // "probe N" came in: start over. N of 0 or less ends a running probe without a reply.
  void begin(int n);

  // One more presented picture. Returns true when it was the last one, and reply is then
  // the line to say(): "probe n=N median=M max=X" with three decimals, the median being
  // the upper one of an even count, "nan" for both when there is no difference to report.
  // Pictures must all have the same size; one of another size starts the comparison over.
  bool add(const std::vector<uint8_t>& sparse_rgb, std::string& reply);
};

// The mean absolute difference of two byte arrays of the same length, 0 when they are
// empty or differ in length.
double mean_abs_diff(const std::vector<uint8_t>& a, const std::vector<uint8_t>& b);
