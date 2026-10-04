// capturetest.h: the capture run on its own, with no window and no network.
//
// It captures the monitor under the --at / --size rectangle for a number of seconds and
// reports what arrived: frames a second, drops, the callback's cost, and whether a slot
// read back from the D3D12 side holds the picture it should. The capture is the part of
// the engine that replaces the Vulkan presenter's trip through the CPU, so this is where
// its cost is measured by itself.
//
// The capture test program does not link gpu.cpp: it makes the plain D3D12 device and
// queue it needs itself, on the adapter that shows the monitor.
//
// Both lens-fast-capturetest.exe and lens-fast.exe --capturetest end up here.
#pragma once

#include "common.h"

// Runs the capture test described by o: o.x, o.y, o.width, o.height, o.crop_x, o.crop_y,
// o.max_fps (through capture_interval_ms) and o.capturetest_seconds. Main thread. Nothing
// appears on screen. It prints on stdout, one say() a line, and returns the process's exit
// code: exit_code::ok when frames arrived, exit_code::failed after an "engine failed
// REASON" line.
int run_capturetest(const Options& o);
