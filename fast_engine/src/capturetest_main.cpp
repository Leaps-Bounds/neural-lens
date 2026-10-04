// capturetest_main.cpp: the entry of lens-fast-capturetest.exe, a console program that holds
// only the capture: capturetest, capture and common.
//
// It takes the engine's own command line, so the same arguments work here and with
// lens-fast.exe --capturetest.
#include "capturetest.h"
#include "common.h"

int wmain(int argc, wchar_t** argv) {
  set_quiet_failures();

  Options o;
  std::string err;
  if (!parse_options(argc, argv, o, err)) {
    fail("%s", err.c_str());
    return exit_code::usage;
  }
  if (o.help || !o.capturetest) {
    say("lens-fast-capturetest.exe --at X Y --size W H --capturetest SECONDS [--crop X Y] "
        "[--max-fps N]");
    return o.help ? exit_code::ok : exit_code::usage;
  }
  return run_capturetest(o);
}
