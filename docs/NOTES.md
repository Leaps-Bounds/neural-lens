# Engineering notes

Measurements, constraints and Win32 details behind the implementation. Most of the rejected
approaches below look reasonable on paper and fail only when measured, so each one is kept
alongside the number that ruled it out. Read this before changing the capture path or the pass
chain.

## The multi-pass chain

The add-on that works in mpv, `renodx-dlss5` v4.7, has **no pass control**. Its complete set of
settings is `EnableHooks, NRAutoMask, NRColorStrength, NRDepthMode, NREnableUpscaling,
NRIntensity, NRLocalStructure, NRLocalTone, NRMVecScaleX, NRMVecScaleY, NRPaperWhiteScale,
NRPreset, NRScreenshotKey, NRSkinStructure, NRStyle, NRToggleKey, NRTransferStrength,
NRUICorrection, NeuralUplift`. The newer `renodx-dlss` add-on does have
`DirectNeuralRenderingPassCount`, but it will not inject into mpv at all (see Dead ends), so it
is not an option here.

Passes are therefore made by chaining: stage N captures stage N-1's mpv window with WGC and
renders it again. Cumulative change from the raw source, as mean absolute difference out of 255:

```
                        stacked      side by side control
1 pass                    7.71               7.71
2 passes                 14.05              14.06
3 passes                 19.45              19.52
same chain, NR disabled   0.24  (round trip is nearly lossless)
```

The stacked and separated columns agreeing is what establishes that stacking is sound rather
than merely different.

### Every stage must be on the magnifier's exclude list

`MagSetWindowFilterList` starts out excluding the host, the chrome and stage 1's mpv. Stack
stages 2 and 3 on the same rect **without adding them** and the magnifier renders them back into
stage 1's input, which is a fast and total feedback loop:

```
with the stages excluded        7.71 / 14.05 / 19.45
with stages 2 and 3 missing     7.70 / 62.52 / 61.23   (dark blob, ghosted text, saturated)
```

`refresh_filter()` rebuilds the whole list after every add or remove for this reason. The call
must happen inside the process that owns the magnifier.

The list must also cover **transient** windows of the same process: the popup menu, the resize
outline, the settings dialog and any message box. Listing windows by name cannot cover these,
because they are created and destroyed on demand, and anything missed is rendered into stage 1's
input, neural rendered along with the desktop, and saved into screenshots. `refresh_filter()`
therefore enumerates every visible top-level window owned by the process, and a 200 ms timer
re-applies the list, since a popup menu offers no hook to refresh from. Screenshots additionally
wait for the chain to flush, because frames containing a window that has just closed are still
in flight, and the visible stage lags the source by the pipeline latency.

## Resize restarts the process

Live resize is unavailable because a resize recreates mpv's swapchain, and the Neural Rendering
add-on responds by releasing its DLSS feature and crashing with 0xC0000005. Moving the lens is
safe, because that only repositions windows and re-aims the magnifier.

The menu's resize writes the new geometry into the state file and starts a fresh copy of the
process. `quit()` terminates each stage and waits for it, and the handover then waits a further
second before starting the replacement, because stage windows are found by **exact title match**
and a lingering mpv window would let the new stage 1 bind to the old one.

### The handover must not use `os.execv`

On Windows `os.execv` goes through the CRT, which does **not** quote arguments containing
spaces. A script path such as `C:\...\Coding\DLSS 5\neural-lens\neural_lens.py` therefore
reaches the replacement process split at the space, and it exits immediately with
`can't open file`.

`execv` does not raise in this case. It starts a broken process successfully while the original
is already gone, so a `try`/`except` around it with a `subprocess` fallback never fires and the
failure is silent: no window, no console output, no log entry.

`subprocess.Popen` quotes correctly through `list2cmdline`. The replacement's own output is
redirected to `logs/restart.log`, because the console it was launched from can close along with
the outgoing process.

The failure only occurs when the script path contains a space, so any test of this path must run
from such a path. Verified two ways: 1200x800 at (1800, 700) resized to 960x640 at (1860, 740)
returning at exactly that size and position with capture running, the pass count carried across
and no orphaned mpv; and the same flow driven from a batch file inside a directory whose name
contains a space.

## Dead ends

### Desktop Duplication (ddagrab) under the lens

It cannot see beneath an occluding window, whether or not that window is excluded from capture,
and not even when something is actively repainting underneath it.

```
capture a region away from the lens          YAVG 45.7    real content
capture exactly where the lens sits          YAVG 18.0    black is 16

magnifier repainting that rect, no lens      YAVG 45.96
same, with an excluded lens on top           YAVG 20.04   black again
```

`WDA_EXCLUDEFROMCAPTURE` removes a window from the capture, but it does not make Windows render
the desktop behind it. Nothing composites an occluded region, so the duplication buffer stays
empty there and only transient dirty rects land in it. The symptom is a black viewport that
accumulates mouse trails and window drag smears, and that carries stale content when the lens
moves.

Two caveats when testing this. A static window over another static window does capture
correctly, because DWM still holds both buffers, so that case does not generalise: a Vulkan
swapchain presenting sixty times a second means the region beneath it is never redrawn. And
sample YAVG rather than chroma, because a chroma only check gives a false pass.

### gdigrab or BitBlt of the magnifier window

Blank whether occluded or not. The magnifier composites through DWM, and BitBlt sees only the
window's own GDI surface, which is empty.

### MagSetImageScalingCallback

Deprecated. It is accepted and returns TRUE, and then the next Mag call deadlocks when driven
from ctypes, most likely because the callback takes structures by value. Unnecessary anyway,
since WGC can capture the host window directly.

### The newer renodx-dlss add-on (the one with PassCount)

Will not inject into mpv on either `--gpu-api=vulkan` or `d3d11`. Zero
`DLSS-NR direct: EvaluateFeature` in both cases, both stopping at
`WARN NVNGX parameter module is not loaded yet: nvngx.dll`, and the Vulkan attempt segfaulted
mpv. It requires `nvngx.dll` loaded by a real DLSS integration, which mpv cannot provide.

### UDP transport

Resyncs badly after a restart: 353 buffering events, with frames arriving every few seconds. A
pipe and TCP both measured 60 fps, and nothing restarts mid session, so it buys nothing.

### `--untimed`

Makes mpv present as fast as it can rather than on the stream's timing. Presents then outnumber
frame arrivals by roughly sixty to one, so Neural Rendering reprocesses its own output until the
picture collapses. Never add it. See also the rate section below, which is the same failure
reached through a declared frame rate that is too high.

### An in-app NR health indicator

Comparing the frame sent to mpv against the frame actually displayed separates NR on from NR off
by only 1.4x: 0.58 off, 0.82 on, and 1.7 on in a different scene, so the scene matters more than
the setting. Whole frame averaging at 1/8 stride washes out exactly the local detail that Neural
Rendering changes, so such an indicator raises false alarms. The F6 toggle is unambiguous
instead, measuring 12.7/255 on plain text.

## Gotchas

- WGC cannot find a `WS_EX_TOOLWINDOW` window. The magnifier host must be a plain popup, and it
  should be captured by `window_hwnd` rather than by name.
- `windows_capture` dispatches handlers by function `__name__`. They must literally be called
  `on_frame_arrived` and `on_closed`, or it raises ValueError.
- `frame.frame_buffer` is row padded and non contiguous (stride 2304 for width 560), so it
  cannot go straight down a pipe. Slice `[:h, :w, :]`, `np.copyto` it into a reused buffer and
  write that buffer's memoryview. Do not write from the capture callback itself; see the frame
  rate section.
- The opening frame of a freshly started capture session is sometimes handed over uninitialised
  and comes back black, measured at roughly one sample in 14. Skip the first frames and reject
  an all zero buffer. This affects saved screenshots as well as measurement.
- Passing `HWND_TOPMOST` as Python `-1` through ctypes silently fails on x64, because a 32 bit
  int goes into a pointer parameter. Use `ctypes.c_void_p(-1)`. mpv resets its own z order
  anyway, so give it `--ontop` rather than forcing the z order from outside.
- Stage windows share a title prefix, so find them by **exact** title match. Substring matching
  returns the wrong stage.
- `MagSetWindowTransform` is optional, and it deadlocks if called after the scaling callback has
  been set. Skip it; the identity transform is the default.
- The lens is deliberately **not** excluded from capture, which is what makes its output
  measurable with ddagrab. See-through was verified that way: the lens output correlated 0.997
  with ground truth of the region behind it.
- `RegisterHotKey` posts `WM_HOTKEY` to the registering thread's message queue. It must be
  registered on the same thread that pumps messages, not on a thread whose queue belongs to
  something else such as a tkinter mainloop.
- **The tkinter mainloop dispatches `WM_PAINT` for the magnifier host.** Blocking it stops the
  source repainting, and window capture then stops delivering frames, because capture delivers
  on recomposition. Anything that waits for a frame, the screenshot included, must run on a
  worker thread and marshal widget updates back with `after(0, ...)`. Waiting for a frame on the
  mainloop cannot succeed: the frame can only arrive if the wait returns first.
- On a decorated toplevel, `winfo_x`/`winfo_y` give the **frame** origin while
  `winfo_rootx`/`winfo_rooty` give the **client area**, and `geometry()` positions the frame. The
  decoration thickness is unknown until the window manager has mapped the window, so measuring it
  straight after `update_idletasks()` reads zero and any correction based on it does nothing.
  Measure it from an `after()` callback. Here the offset was 9 by 38 pixels.
- `GetAsyncKeyState` is the only reliable way to tell whether a mouse button is still held during
  a window manager resize. Tk sees no button events for the whole drag, because the window
  manager holds the mouse capture, so a settle timer alone cannot distinguish a pause mid drag
  from the end of one.
- `evaluation succeeded (count=` in `ReShade.log` is a **milestone line**, emitted at count 1 and
  count 60 and then not again. The number of occurrences is not a measure of how much Neural
  Rendering ran.
- **ReShade rotates its log.** A second instance in the same folder cannot open `ReShade.log`, so
  it writes `ReShade.log1`, and a third writes `ReShade.log2`. A multi-pass run therefore leaves
  one log per stage, and `feature=18` appears once per *file* rather than once per run. Anything
  that archives or inspects logs must cover all of them.

### The taskbar button is the tk root

The title bar is an override redirect window that never activates, so the mouse reaches the
application under the lens, and that combination has no taskbar button. The hidden tk root
stands in: titled, fully transparent, and parked minimised. Restoring it from the taskbar fires
`<Map>`, the handler re-asserts topmost on every stage in chain order and then on the bar, and
minimises the root again before it can be seen. `raise_chrome` alone would not do, since it
re-asserts only the bar. Tk toplevels on Windows are not owned by the root, which was measured
rather than assumed: the bar stayed visible with the root minimised, and restoring fired exactly
one `<Map>`. Close window on the button arrives as the root's delete request and quits the lens.

### No console

The launcher starts the lens under pythonw. `sys.stdout` is None there, so at import everything
printed is redirected to `lens.log` in the log folder, with the previous one first rolled into a
stamped copy so the archive's pruning covers it. `GetConsoleWindow()` returning zero is what
turns the messages that used to wait for Enter into dialogs, including a stage that never opened
its window and an unexpected traceback out of `main()`. A harness driven from a tool with no
console window sees the same, so any test that reaches a fatal path has to replace
`messagebox.showerror` first, or it blocks on a dialog nobody will dismiss.

### Per monitor DPI awareness

A 1400x760 lens on the 5090's secondary monitor produced a 1680x912 chain: ReShade created its
Neural Rendering resources at 1680x912 and the Feed delivered frames at 1680x912, while
`GetWindowRect` from inside the lens said 1400x760. The ratio, 1.2, is not a scaling factor,
it is the ratio of two: 150 percent over 125. The lens was system DPI aware, which keeps the DPI
the session logged on with and lives in a coordinate space Windows virtualizes against each
monitor, so a window it placed on a monitor whose scaling differed from that was rescaled by
Windows on the way, and the lens never saw the real size. The lens is now per monitor DPI
aware, version 2, so every coordinate it uses is a physical pixel on whichever monitor it is on.

Verified on the 4070 with the primary monitor switched to 125 percent while the session had
logged on at 100: the lens asked for 1400x760, a per monitor aware probe measured the stage
window at 1400x760 physical, ReShade created its resources at 1400x760, and the chrome measured
1404x796 with both windows reporting 120 DPI, so nothing is bitmap stretched either. The same
test before the change also agreed on the primary, which is what separated "follows the
monitor" from "follows the geometry" and pointed at the secondary monitor's scaling context.
Fonts follow the monitor's DPI now; the bar is 34 pixels and holds a 10 point label up to 200
percent.

### Fullscreen

Experimental, and the least tested part of the lens. It has had far less exercise than the
windowed path, and is shipped to be tried and reported on rather than relied on.

Two things bit when the lens first covered a whole monitor:

- **A layered window larger than the screen comes up blank.** The windowed chrome is the
  picture plus a title bar plus a border, so over a whole monitor it was 3844x2194 on a
  3840x2160 display. It existed, was visible and topmost, and drew nothing. Fullscreen the
  chrome is therefore just the bar, 3840x34, laid over the top edge of the picture.
- **mpv climbs above the chrome.** With the chrome raised after the stages were spawned, the
  stage still ended up above it a few seconds later, so the bar could not be seen or clicked.
  The lens now walks the z-order above its chrome on the 200 ms filter timer and raises the
  chrome again whenever a stage is found there. Menus and dialogs are not stages, so they
  stay above.

### The A/B divider

The divider is a thin topmost window of this process, so the magnifier already excludes it,
and every stage is clipped with `SetWindowRgn` to the left of it. Two things about dragging it:

- **Tk ignores `geometry()` on a window while the mouse button is held on it.** The split
  value followed the drag and the clip moved, but the line itself stayed where it was until
  release, which reads as "the slider is locked". The divider is moved with `SetWindowPos`
  instead, like the stages.
- The drag follows the mouse from a thread polling the button and the cursor rather than Tk's
  motion events, so it keeps working after the pointer leaves the fourteen pixel window. The
  governor is told to ignore its counters for a few seconds around the toggle, because the
  clip shows up as black in the visible stage's capture.

The fullscreen chain keeps its pass count and best held rate in `lens-state-fullscreen.txt`,
because the windowed state file is what the way back restores, and a rate that suits a
1400x1000 lens is far too high for eight million pixels.

## Measurement pitfalls

- **Never measure with a moving source.** A reading of 16.1% changed pixels came from an animated
  element being in frame; the static half of the same image gave the real figure. Check that the
  source is unchanged across samples before trusting any difference in the output.
- **Establish a noise floor** by capturing the same state twice before trusting a difference.
- **Do not infer NR state from the F6 toggle log.** The focus dance the lens used to deliver keys
  sometimes failed to register a press, which inverts the inference. ReShade's own keys, Home
  for the overlay and F5 for its screenshot, are now posted to each stage's message queue
  (`WM_KEYDOWN` and `WM_KEYUP` to the window), which ReShade reads without the window having
  focus and which does not drop. **F6 is different.** It belongs to the add-on, which reads it
  through `GetAsyncKeyState`, the physical keyboard. Posted to the stage it did nothing in three
  runs, with or without focus, while one genuine keystroke with no focus at all toggled it,
  measured as the in-to-out difference over the same still going from 1.20 to 2.22. So the menu
  sends F6 as a real keystroke with the stage briefly focused, to shield whatever is under the
  lens from it, and the lens polls the same key the same way to track the state, seeded from
  `NeuralUplift` in `ReShade.ini`, which the add-on honours at start and writes only at exit. A
  toggle made with the mouse inside the overlay involves no key and is not seen until the next
  launch. The advice stands anyway: measure absolutely, capture the region with the lens absent,
  then with the lens over it. Passthrough means off, a large difference means on.
- Neural Rendering's strength scales with local detail, about 4.5x stronger on the most detailed
  tenth of an image than on the flattest half. Flat content changing very little is expected.
- **Never assert an absolute difference for Neural Rendering.** The strength depends on what is
  under the lens, so a threshold calibrated on detailed video fails on flat interface content,
  and it fails by looking exactly like a broken feature. Assert the shape instead, which is
  content independent: the change concentrates in detailed areas. One pair over flat interface
  measured 1.29 overall, which looks like nothing against the 7.71 reference, yet 6.21 on the
  most detailed tenth against 0.654 on the flattest half, a ratio of 9.5x. Round trip loss with
  NR off is 0.24 spread evenly, so no such ratio can come from the capture path. Ratios of 4.8x
  and 5.6x have been measured on other content.
- **The detail ratio is itself content dependent, so calling it content independent above is
  only half true.** It works where the image has genuinely flat areas to contrast against. Dense
  photographic content has none: a still frame of film footage measured 2.24x, 2.51x and 2.67x
  across three captures of a bit for bit identical source, with the flattest half of the image
  still carrying a gradient of 3.0 and only 0.1 to 1.0 percent of pixels unchanged. There is no
  flat half, so the ratio compresses while Neural Rendering works normally. Gate the assertion
  on the flattest half actually being flat, and where it is not, assert only that the effect
  sits far above the 0.24 round trip floor.
- **Check that the source held still before trusting any before and after pair.** Saving two
  captures and comparing them costs nothing and settles it: a suspected moving source turned out
  to be byte identical, same sha256 across 28 minutes, which killed a plausible explanation
  before it was acted on.
- **Drive the real application rather than a mock.** `neural_lens.py` guards its entry point with
  `if __name__ == "__main__"`, so a harness can import it, wrap `Lens.__init__` to obtain the
  running instance, and schedule real menu actions on the real mainloop.

## Where the frame rate goes

Nothing here is GPU bound; the GPU sits near 30 percent at any pass count.

The largest single factor is a library default. `windows_capture`'s `WindowsCapture(...)` takes
a `minimum_update_interval` parameter whose default throttles delivery to roughly 60 frames per
second. Setting it to `0` more than doubles delivery on an identical source:

```
window capture, defaults                    59.4 fps
window capture, minimum_update_interval=0  124.6 fps
window capture, dirty_region True / False   59.0 / 58.6   (irrelevant)
```

End to end in the lens at 1400x1000, before and after removing the throttle:

```
            before   after     GPU after
1 pass        58.4   111.4        32%
2 passes      49.8    84.7        57%
3 passes      44.3    89.9        80%
```

The fps counter increments in stage 1's capture callback, so at multi-pass it reports capture
rate rather than what the final stage presents, which is why three passes can appear faster than
two. Treat the multi-pass figures as input side only.

Two further factors, both in how the lens drives itself:

1. **tkinter's `after()` is too coarse to pace repaints.** An `after(16)` tick lands nearer 20 ms,
   which caps the lens at 47 to 52 fps. A thread pacing `InvalidateRect` fixes it. Calling
   `InvalidateRect` from another thread only posts `WM_PAINT`; tkinter's mainloop dispatches it,
   because the host window belongs to that thread.
2. **The multi-megabyte `stdin.write` into mpv blocks the WGC delivery thread.** Removing the
   write entirely measures 58.7 fps against 50.5 with it inline. A writer thread with a one slot
   handoff absorbs the stall. The slot is overwritten rather than queued, because for a live view
   only the newest frame is worth having.

### The rate declared to mpv must never exceed what arrives

`--demuxer-rawvideo-fps` tells mpv how fast the stream is, and mpv presents at that rate. Declare
more than the chain delivers and mpv presents without a new frame to draw, so Neural Rendering
re-runs over its own previous output. The picture crushes toward black over a few seconds, a
fresh frame eventually forces a reset, and it repeats. This is the same failure as `--untimed`.

Throughput divides roughly by the number of stages, because every pass is another full capture
and present. Samples out of 14 that collapsed, at 1314x1332 on a 120 Hz display:

```
            1 stage   2 stages   3 stages   4 stages
120 fps       0/14       8/14       4/14
 90 fps                  0/14
 60 fps                  0/14       0/14       4/14
 30 fps                  0/14
```

Dividing alone is not enough. Declaring exactly what the chain delivers is already broken,
because ordinary jitter then lands some presents with no new frame. That does not collapse the
picture, it shimmers, which is why it survived the collapse testing above. Measured as frame to
frame change on a static source, where the floor is 0.146 out of 255:

```
one stage, about 119 frames a second arriving
    120 declared   1.637       0 percent headroom
    110 declared   0.220       5 percent
    100 declared   0.150      16 percent
     90 declared   0.148      24 percent
```

So `_fps_for` declares `(BASE_FPS * 5 // 6) // stages`, giving 100, 50, 33 and 25 on a 120 Hz
display. Verified at every pass count: 0.150, 0.139, 0.135 and 0.133, against 1.637 at one stage
and 0.225 at two under the previous rule.

Stages after the first are fed by the stage before them, which presents at this same rate, so
they sit at parity by construction and dividing cannot change that. What makes parity safe is a
longer frame interval, which is why two stages at 60 measured 0.225 while three at 40 and four
at 30 sat at the floor: 16.7 ms leaves room for jitter to slip past a present, 25 ms does not.

This assumes the chain delivers close to the display rate. That holds at 120 Hz and is untested
on a faster panel, where the ceiling itself would be too high.

Two consequences:

- **The rate is fixed when mpv spawns.** Changing the pass count must respawn every stage rather
  than append one on the end, since leaving an existing stage at its old rate reproduces the
  collapse. `set_passes` rebuilds the whole chain.
- **Rebuilding needs a per stage stop flag.** The writer thread exits only on `lens.closing` or a
  failed write, so tearing a stage down while the lens stays open would strand it on a condition
  nothing will signal again.

Note that four stages at 60 fps collapses, so a fixed rate that works at two and three stages is
not sufficient at four.

### The fixed rule does not survive another GPU, and what replaced it

The rule above was calibrated on an RTX 5090 at 1400x1000. Measured on an RTX 4070 SUPER with
driver 616.56, capturing the visible stage and taking the mean absolute frame to frame change
out of 255 on a still, dense source (floors: 0.03 with Neural Rendering off, about 0.65 with it
on at one pass, about 0.36 at two or three passes). "Spikes" are frames above 1.0:

```
lens        passes  declared     presented   result
1400x1000   1       100 (rule)   100         at floor, 17 spikes in 995 frames
1400x1000   1       35 to 60     = declared  clean
1400x1000   2        50 (rule)    40         shimmer, 55 spikes, brightness 112 to 116
1400x1000   2        24 or 32    = declared  clean
1400x1000   3        33 (rule)    29         shimmer, 24 spikes
1400x1000   3        24           24         clean
2000x1400   1       100 (rule)    27         collapse, mean 14, brightness 47 to 74
2000x1400   1        24           24         clean
3840x2126   1       100 (rule)    10         a slideshow, delivery into stage 1 fell to 61
3840x2126   1        24           24         held, delivery into stage 1 only 30
```

Capture into stage 1 stays at 120 whenever the GPU is not overloaded, so stage 1's counter
cannot see any of it. Capacity also moves at runtime: the same one pass lens went from holding
100 to holding about 60 once a video was playing beside it. On driver 610.47 the one pass rule
collapsed outright in 3 of 5 runs.

So the rate is governed instead. Every stage is declared at the display rate and presents at a
playback speed set over mpv's IPC pipe, which changes live. Each stage after the first runs at
five sixths of the stage feeding it, because equal rates at two passes were clean at 35 and
shimmered at 37. Once a second the governor reads:

- the frames the visible stage presents, from a counting only capture of its window, against
  the rate it was asked for. Presenting 87 of 90 is not a shortfall: the margin is 8 percent of
  the target, because 3 percent was tight enough that near perfect delivery dropped a lens from
  90 to 58. A mild shortfall backs off to 95 percent of what was presented, which is by
  definition achievable; a severe one, more than a quarter short, backs off to two thirds,
  since the presented figure is then not to be trusted either.
- the mean brightness entering stage 1 against the mean brightness shown. Neural Rendering moves
  it by two or three percent; a collapse moves it by half or more, and can do so while every
  frame is presented on time (one pass at 90 presented 90 and showed 153 for 115). Two seconds
  of that halves the rate.
- while the source is still (its own sampled change under 0.5), the frame to frame change of
  the output. A frame counts as a jump when it differs from the one before by more than a
  limit that scales with the gap between them: 1.5 out of 255 at 78 fps, where it was
  calibrated, so 7.8 at 15 fps and 1.3 at 90. A fixed 1.5 fired more readily the lower the
  rate already was, which is backwards, and trapped a lens at 12 on a chain that went on to
  hold 90. More than a quarter of frames jumping, or a median above 1.5, marks the level as
  failed, but only when the reading repeats a second later. The broken calibration had 47
  percent of frames jumping and a clean one none, so a quarter sits well inside that; 3
  percent was close enough to nothing that ordinary content crossed it, 9 frames in 275.
  Another process taking the GPU spiked the median to 1.51 and 1.77 for four seconds and then
  settled to between 0.12 and 0.46 while it was still running, so a single reading is an event
  rather than a level. Just over the knee the shimmer is continuous rather than spiky: one
  pass at 83 on a loaded 4070 changed by about 3 every frame.

A failed level falls back to the last level a probe departed from, since a level near the knee
can take fifteen seconds to show its shimmer and cannot be trusted sooner. Probes into new
ground go halfway to the lowest failed level, only while the source is still, and stop when the
step is under a twentieth of the rate.

Ground the chain has already held is different. The highest rate it held is remembered, and
after a knock down it is retaken in halving steps on a two sample window with half a second of
settling, about three seconds a step, moving content included, because the level is known to
work and only a chain that has since changed could refuse it. The recorded limit does not apply
on the way back: a knock down records the limit at the floor it fell to, and gating the return
behind it parked the lens at that floor until the limit expired, 30 seconds on the 5090 and 58
on the 4070, since the wait is the retest interval, whatever it has grown to. A limit the chain
is then running at or above is dropped, or it clamps the cap under the running rate and throws
the lens back to the floor, measured as 35 to 12 every 17 seconds. A retake that fails lowers
the remembered level to just under the rate that failed, so a level the GPU can no longer carry
is not chased. Measured on the 4070 at 2936x1530, one pass over a still: settled at 37, knocked
to 12 for 15 seconds, retook 37 in 16 seconds after release in five steps; the same run took 94
seconds before, and 64 on the 5090.

The lowest failed level expires. It clears once the output has been clean for twenty seconds and
the level is at least thirty seconds old, and the wait before the next clearing doubles to a ten
minute cap, so a real limit is re-tested less and less often while a stale one is gone inside a
minute. Without this, one load event capped the chain for the rest of the session: a session
that held 94 for 165 seconds cascaded to 34 and never exceeded 39 again, and a deliberate
reproduction converged to 77 of a possible 99. With expiry, a 5090 at one pass under 45 seconds
of GPU load went 100, down to 62, back to 99 about thirty seconds after the load stopped. A
synthetic ceiling at 70, imposed with the input left intact, converged to exactly 70 and
returned to 99 once lifted.

Telling a passing load apart from a real limit by watching the rate frames arrive into stage 1
was tried and dropped. Arrival holds at the pump rate while the chain alone collapses and falls
when another process takes the GPU, which separates the two cleanly at one pass: 120 alone, 60
while sharing, 120 again within seconds. At four passes the lens is itself the heavy process.
Arrival averaged 98 against a line of 114, so every shortfall looked like somebody else's load,
no limit was ever recorded, and the rate hunted over a 19 fps range with runaways and output
floors of 13.8 and 82.7. With the rule removed and expiry alone, the same test settles to a
4 fps spread at a visible 41.7.

The sixth field of the state file is the highest rate the chain actually held, not the rate it
was running when it closed. Saving the instantaneous rate meant a lens closed during a load
event reopened at the depressed rate: two runs that each held 99 for over two minutes saved 97
and 91.

The brightness runaway test judges the output against the range the input has occupied over the
last second and a half, not its latest value. The output lags the input by the pipeline delay
plus up to a few frames of sampling, so on content whose brightness moves the two describe
different moments and disagree while nothing is wrong. Measured on a scrolling source whose
field cross-fades between dark and bright every couple of seconds, the way a video with scene
changes does: a one pass chain that had just held 100 fps pinned went 100, 50, 25, 12 in 27
seconds on false runaways and stayed at 12 for the rest of the run, which is what the user's own
log showed over a video. With the range test the same source held 100 for the full 90 seconds
with no verdict at all. On a still the range is a point, so the test is unchanged there: four
passes pushed past capacity over a still still draws runaway verdicts. The stated limit is that
over moving content a crush toward black on a scene that already reaches near black lands inside
the input's own range and is not caught; a crush toward white over a scene that never reached it
still is, and the presented shortfall test is unaffected. That is no worse than before, when the
test fired constantly on motion and so was useless there.

At four passes the governor used to hunt over a detailed still, for two separate reasons on two
cards. On the 5090 the pinned measurement showed it was not capacity: stage 1 pinned at 43, 60,
72 and 85, which is visible 25 to 49, left the picture intact at every one, brightness 48 in and
48 out, floor 0.19, with only a mild shortfall at the top, while the runaway verdicts in the
governed run all fired within seconds of a probe step. A speed change at four passes ripples
through four stages and four buffers, and the brightness excursion it causes outlasted the 1.5
second settle window, so the governor read a transition as a collapse and backed off to half.
The settle window now grows with the pass count, half as long again per stage after the first,
so 3.75 seconds at four passes. On the 4070 there were no runaways at all and the hunt was 35 and
37 alternating every ten seconds: a retake of the remembered level failed by a hair, correctly
lowered that level by one, and the next retake step of two overshot straight back to the level
that had just failed. A retake now never goes past the level it is retaking. Measured on the
4070 at four passes over the still: rate 35 to 39 over the last 90 seconds, a spread of 4, where
it had been 32 to 37 on a ten second cycle. What moves is the recorded limit being re-tested on
its doubling interval, a brief shortfall each time that falls straight back.

Measurement traps that cost time here: F6 is persisted by the add-on as `NeuralUplift=0` in
ReShade.ini, so one toggle turns Neural Rendering off for every later launch; a full frame
difference inside the capture callback costs 10 ms at 1400x1000 and caps the capture near 40,
which looks exactly like a chain limit; the ReShade frametime overlay in the corner of the stage
reports mpv's own present cadence and is an independent witness.

### Where the delay goes

Measured with a separate process flipping a window between black and white under the lens, and
two Windows Graphics Capture sessions in the harness, one on the flipper and one on the visible
stage, each timestamping the moment its mean crosses mid grey. Both pass through the compositor
once, so that cancels and the difference is the lens pipeline. One pass, 1400x1000, the rate
pinned at 99, 21 flips per run:

```
mpv readahead                                    median   p90    presented
8 frames, the old default                        136 ms   147    98.9 fps
2 frames                                          78 ms    91    99.0
2 frames + --video-latency-hacks=yes              68 ms    76    98.9
  + --vulkan-swap-mode=mailbox                    69 ms    75    98.8
1 frame + hacks + mailbox + --swapchain-depth=1   63 ms    69    98.9
```

The readahead is the cost. The lens plays slower than frames arrive, so the buffer is always
full and every frame in it is delay, ten milliseconds each at 99 fps and more at lower rates.
Two frames plus the latency hacks is what ships. Mailbox changed nothing. One frame gains five
milliseconds but leaves no slack for a late frame, which is what makes the picture shimmer, so
two is the floor. The flipper is featureless and can show stutter but not shimmer, so the two
frame buffer was checked separately over a detailed still: an output floor of 0.341 against
0.343 with eight frames, zero jumps, and 100 fps held in both.

### What does not cause the 60 fps ceiling

Each of these was measured and ruled out, so they are not worth re-investigating:

- **The Magnification API.** Paced properly it delivers the same rate as an ordinary window, and
  the magnified region's size makes no difference (1.4 Mpx and 0.1 Mpx both measure 59.0). A
  reading of 51.6 fps for it is an artifact of a harness pacing its own pump loop with
  `time.sleep(0.02)`, which is 50 Hz.
- **The compositor.** `DwmFlush` returns about 148 times a second on this machine against a
  120 Hz display, so composition is not the constraint.
- **The test source.** A tkinter source issues about 924 redraws a second.
- **Invalidation frequency.** Locking invalidation to composition with `DwmFlush` and free
  running at 240 Hz both produce 59, because the throttle is downstream of invalidation.

Measured as noise and not worth redoing: replacing a double per frame copy (2.93 ms to 0.18 ms),
removing a redundant `MagSetWindowSource` from every tick, and raising Windows timer resolution
with `timeBeginPeriod(1)`. All three are kept because they are strictly cheaper, but none moved
the frame rate.

### Benchmark harness requirements

- A magnifier host needs a **real Win32 message pump on its owning thread**, or `WM_PAINT` is
  never processed, the magnifier never redraws, and capture delivers almost nothing. A rig that
  only calls `time.sleep()` in the main thread measures zero. Run a proper `PeekMessage` and
  `DispatchMessage` loop, or instrument the real lens.
- Window capture delivers frames when a window is **recomposited**, so a static source with no
  forced invalidation produces almost no frames. That is not a failure of the capture path.

## The installer and the stack setup

The lens is frozen with PyInstaller and wrapped by Inno Setup into a per user installer,
`PrivilegesRequired=lowest`, into a folder the user chooses, `%LOCALAPPDATA%\Programs\NeuralLens`
by default. The installer holds the lens and nothing else. `neural_stack.py` fetches the neural
stack on first run, or from a Start Menu entry, or from the command line, into `stack` in that
same folder, with the Vulkan layer in `ReShade` beside it and the downloads in `downloads`
until the self test passes. The lens keeps its state, logs and screenshots in `data` there
too. So an install is one folder plus one registry value naming the layer, and the uninstaller
runs the exe's own `--uninstall-stack` for the value and deletes the folder. A DLL the user
points the setup at is copied in after its hash check and only the copy is recorded, so an
uninstall never reaches the original.

Nothing is bundled, and licences force that rather than taste. mpv's `Copyright` file makes
the build GPL, since it carries the `direct3d` output; bundling would oblige us to provide
source for a binary we did not build. The motion vector shader the author's own setup uses,
LumeniteFX, publishes no licence and no releases, so a new install gets ReshadeMotionEstimation,
CC BY-NC 4.0, provider 0 in `DLSS5_Feed.fx`, chosen by the measurement below, with VORT, MIT,
provider 2 with `V_MV_MODE=1`, as the alternative. NVIDIA's runtimes come from
the RHI project's manifest, which carries no hashes, so the hashes live in `neural_stack.py`
and a download matching none is refused. ReShade's DLL comes straight out of its setup exe,
which is a zip, with nothing of ReShade's executed.

Three facts measured while building it:

- **The RHI manifest's 40 series build is not the one people already hold.** The manifest's
  `310.8.SF-v2` zip unpacks to a file of 165,830,144 bytes, version 310.8.SF.0, unsigned, hash
  6EB209E7...; the earlier community build is 165,840,496 bytes, version 310.8.0.0, signed by
  NVIDIA with a hash mismatch, hash 8270B350.... Both run Neural Rendering on an RTX 4070 SUPER,
  so both are accepted.
- **A per user Vulkan layer coexists with a machine wide ReShade only under a different
  name.** The loader loads one implicit layer per name, HKLM before HKCU, so a per user copy
  named `VK_LAYER_reshade` is skipped wherever a machine wide one exists. The layer is
  registered as `VK_LAYER_reshade_neural_lens`, with its own `ReShadeApps.ini` listing only
  the stack's mpv, so each ReShade hooks only what it lists. Verified on a machine with the
  machine wide layer present: the self test attached, loaded both add-ons and evaluated.
- **`ReShadeApps.ini` is an allow list**, so the per user layer is loaded into every Vulkan
  process and leaves each one alone unless it is listed.

The card is identified by compute capability from the driver's own `nvidia-smi`, 8.9 for Ada
and 12 for Blackwell, rather than by marketing names. The self test feeds this mpv raw frames
on stdin, as the lens does, for nine seconds and reads `ReShade.log` for `feature 18 created`
and `evaluation succeeded`; `0xbad00001` is reported as the wrong model for the card.

`install-record.json` in the stack folder lists every file written and the registry value
set, and `--uninstall-stack` removes exactly that. The Inno uninstaller asks before calling it,
defaulting to keep, so a silent uninstall never deletes the download.

Four things the first run offer did that the Start Menu entry did not, found by driving the
offer end to end against the built exe:

- **The setup window was blank for five seconds.** The first console program started while a
  shown topmost Tk window is up took 5.2 seconds under pythonw and the exe, 0.1 seconds with
  the window hidden or from a console, measured with `nvidia-smi` alone. Console children now
  run with `CREATE_NO_WINDOW` and a null stdin, and the card is identified before the window
  exists: laid out in 0.6 seconds from the exe.
- **The install folder showed empty, and typing into it changed nothing.** At the offer that
  follows a found but bare mpv, the lens's own Tk root already exists and is tkinter's default
  root, so a `StringVar()` without a master lived in that interpreter while the entries lived
  in the setup window's. Every variable in the wizard is now made on the window's own Tk. The
  Start Menu entry, which has one Tk, never showed it.
- **Set it up failed with "main thread is not in main loop".** The install thread read the
  fields with `.get()`, which Tk allows from another thread only while the main thread is in
  `mainloop`; at the offer it is in `wait_window`. The fields are read on the main thread when
  the button is pressed and the thread gets strings.
- **A relaunch after the setup found the bare mpv again.** The relaunch reused the arguments
  it was started with, so an `--mpv-dir` or ini `mpv_dir` that led to the offer was found
  first and the offer came back. The wizard now returns the folder it installed into and the
  relaunch names it first.

### VORT against LumeniteFX, measured before publishing VORT

The self test passed with VORT's shader failing to compile, because a still needs no motion
vectors: four of its includes were missing from a hand picked list, the Feed logged "no known
VORT shader is installed: motion vectors will be zero", and nothing else said so. The setup now
fetches VORT's whole include folder and its blue noise texture, and the self test reads the
Feed's provider line and fails on "none".

With that fixed, the same lens ran over the same scrolling source on both stacks at a fixed
30 fps, with Neural Rendering on and then off on each, so the provider was the only difference.
Sharpness is the variance of the Laplacian of the dumped output frames, higher is sharper:

```
                              NR on     NR off    kept
grid, 3 px a frame            LumeniteFX   2080      2509     83%
                              VORT         3128      3297     95%
page of text, 3 px a frame    LumeniteFX    671       938     72%
                              VORT          617       880     70%
frame to frame change, text   LumeniteFX   8.8       10.2
                              VORT         6.8        8.0
```

Those numbers said level on text and the frames said otherwise: on the page of text VORT's
output shows doubled letters at the ends of words where LumeniteFX's is nearly crisp, at a
slow scroll too. Sharpness cannot see a ghost, since a second edge adds high frequencies, and
VORT's lower frame to frame change is the ghost itself, a blend that lags. The measure that
agrees with the eye is the partial ink fraction of the page, the share of pixels between 40
and 160 out of 255 on a black on white page, where crisp text is bimodal and a ghost adds mid
greys:

```
scroll, px per source frame     1        3        6
LumeniteFX                    0.092    0.097    0.104
VORT                          0.099    0.109    0.106
```

A modest but visible step down at reading speeds, converging at fast scroll where both ghost.
Neither VORT's own options (its rest mode is for engine vectors) nor the Feed's validation
values (the author's preset holds the shader's defaults) changed it.

Every provider the Feed lists was then put through the same page at the same three speeds,
plus a control with no provider enabled at all, which the Feed answers with zero vectors:

```
                                                    slow    reading   fast    licence
Launchpad (iMMERSE, Pascal Gilcher)                 0.051   0.083     -       all rights reserved, permission needed
ReshadeMotionEstimation (Jakob Wapenhensch)         0.075   0.096     0.102   CC BY-NC 4.0
LumeniteFX Kernel                                   0.092   0.097     0.104   none
VORT (Vortigern)                                    0.099   0.109     0.106   MIT
dh_uber_motion (AlucardDH)                          0.112   0.113     0.108   GPL-2.0
no provider, zero vectors                           0.114   0.123     -
```

So the default a new install gets is ReshadeMotionEstimation, DRME, the Feed's provider 0
through the shared `texMotionVectors`: crisper than LumeniteFX on this test, and CC BY-NC 4.0
allows it to be fetched and used with credit in a free tool. Two things to know about it. Its
repository publishes no releases and was last touched in 2023, so the setup pins the commit.
And on ReShade 6.8 its first pass, the frame save, fails to compile with "cannot sample from
texture that is also used as render target"; the Feed's header warns that DRME then "silently
writes nothing", but measured here the estimator's remaining passes produce vectors that beat
every alternative, and the zero vector control is far worse, so the warning describes a
different case or an older build. VORT is fetched as well and can be chosen instead. Launchpad
was the best of all, but its licence requires the author's explicit permission to use it as
part of another project, so it was only ever run privately here; that permission is worth
asking for. qUINT is all rights reserved and no longer ships a motion shader. The setup still
takes a LumeniteFX copy the user already holds and configures provider 3 from it, which
distributes nothing; the author's own setup stays on LumeniteFX.

The washed out frames seen in the first, governed run over motion at 85 fps were the rate, not
the provider: at a fixed 30 no stack showed them, and the brightness of that run sat 8 percent
high, inside the runaway margin. A washout over moving content at a rate the chain cannot
carry is not yet caught.
