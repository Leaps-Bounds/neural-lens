// selftest_main.cpp: the entry of lens-fast-selftest.exe, a console program that holds only
// the GPU side: selftest, pipeline, nr, gpu and common.
//
// It takes the engine's own command line, so the same arguments work here and with
// lens-fast.exe --selftest.
#include "common.h"
#include "selftest.h"

int wmain(int argc, wchar_t** argv) {
  set_quiet_failures();

  Options o;
  std::string err;
  if (!parse_options(argc, argv, o, err)) {
    fail("%s", err.c_str());
    return exit_code::usage;
  }
  if (o.help || !o.selftest) {
    say("lens-fast-selftest.exe --stack DIR --selftest IMAGE OUTDIR [--passes N] [--quality N] "
        "[--work-size W H | --work-scale S | --work-max W H] [--data DIR] [--switches LIST] "
        "[--switch-frames N] [--switch-rest S]");
    return o.help ? exit_code::ok : exit_code::usage;
  }
  const int code = run_selftest(o);
  // Out as the engine leaves on every path: not through the C runtime's exit, which would
  // run the Neural Rendering runtime's unload code (see leave_now). Every line is already
  // written, say() holds nothing back.
  leave_now(code);
}
