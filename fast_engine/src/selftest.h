// selftest.h: the pipeline run on a picture from a file, with no window and no capture.
//
// It is how the GPU side is proven before anything goes on screen, and how it is measured:
// the picture is uploaded as if it were a captured frame, taken through ingest and render
// into a target of the test's own, timed stage by stage, and the results are written as
// pictures that tools\score_selftest.py scores. The probe's reference picture has a grey
// change of 3.21 against the original and an edge figure of 270 where the original has 273,
// and where that reference is at hand the scorer also compares with it byte for byte.
//
// Both lens-fast-selftest.exe and lens-fast.exe --selftest end up here.
#pragma once

#include "common.h"

// Runs the self test described by o: o.selftest_image, o.selftest_outdir, o.stack_dir,
// o.data_dir, o.passes, the quality step or the option that gives the work size, and
// o.switches. Main thread. Nothing appears on screen.
// It prints its progress and its numbers on stdout, one say() a line, and returns the
// process's exit code: exit_code::ok when every picture was written, exit_code::failed
// after an "engine failed REASON" line.
int run_selftest(const Options& o);
