# Engineering notes

What was tried and rejected, each with the measurement that killed it, plus the Win32 details
that are easy to get wrong. Worth reading before changing the capture path, because most of
these look reasonable on paper and fail only when measured.

## The multi-pass chain

The add-on that works in mpv, `renodx-dlss5` v4.7, has **no pass control**. Its complete set of
settings is `EnableHooks, NRAutoMask, NRColorStrength, NRDepthMode, NREnableUpscaling,
NRIntensity, NRLocalStructure, NRLocalTone, NRMVecScaleX, NRMVecScaleY, NRPaperWhiteScale,
NRPreset, NRScreenshotKey, NRSkinStructure, NRStyle, NRToggleKey, NRTransferStrength,
NRUICorrection, NeuralUplift`. The newer `renodx-dlss` add-on does have
`DirectNeuralRenderingPassCount`, but it will not inject into mpv at all (see below), so it is
not an option here.

So passes are made by chaining: stage N captures stage N-1's mpv window with WGC and renders
it again. Measured cumulative change from the raw source:

```
                        stacked      side by side control
1 pass                    7.71               7.71
2 passes                 14.05              14.06
3 passes                 19.45              19.52
same chain, NR disabled   0.24  (round trip is nearly lossless)
```

The stacked and separated numbers agreeing is the proof that stacking is sound.

### The trap: every stage must be on the magnifier's exclude list

`MagSetWindowFilterList` starts out excluding the host, the chrome and stage 1's mpv. Stack
stages 2 and 3 on the same rect **without adding them**, and the magnifier renders them back
into stage 1's input. That is a feedback loop, and it is fast and total:

```
with the stages excluded        7.71 / 14.05 / 19.45
with stages 2 and 3 missing     7.70 / 62.52 / 61.23   (dark blob, ghosted text, saturated)
```

`refresh_filter()` rebuilds the whole list after every add or remove for exactly this reason.
The call has to happen inside the process that owns the magnifier.

## Dead ends

### Desktop Duplication (ddagrab) under the lens

It cannot see beneath an occluding window, whether or not that window is excluded from
capture, and not even when something is actively repainting underneath it.

```
capture a region away from the lens          YAVG 45.7    real content
capture exactly where the lens sits          YAVG 18.0    black is 16

magnifier repainting that rect, no lens      YAVG 45.96
same, with an excluded lens on top           YAVG 20.04   black again
```

`WDA_EXCLUDEFROMCAPTURE` removes a window from the capture, but it does not make Windows
render the desktop behind it. Nothing composites an occluded region, so the duplication buffer
stays empty there and only transient dirty rects ever land in it. The symptom is a black
viewport that gradually accumulates mouse trails and window drag smears, and that carries
stale content along when the lens is moved.

One earlier test seemed to disprove this and was misleading: a static window over another
static window captures correctly, because DWM still holds both buffers. A Vulkan swapchain
presenting sixty times a second means the region beneath it is never redrawn. Also sample
YAVG rather than chroma; a chroma only check gave a false pass.

### gdigrab or BitBlt of the magnifier window

Blank whether occluded or not. The magnifier composites through DWM, and BitBlt only sees the
window's own GDI surface, which is empty.

### MagSetImageScalingCallback

Deprecated. It is accepted and returns TRUE, and then the next Mag call deadlocks when driven
from ctypes, most likely because the callback takes structures by value. Made unnecessary by
capturing the host window with WGC instead.

### The newer renodx-dlss add-on (the one with PassCount)

Will not inject into mpv on either `--gpu-api=vulkan` or `d3d11`. Zero
`DLSS-NR direct: EvaluateFeature` in both cases, both stopping at
`WARN NVNGX parameter module is not loaded yet: nvngx.dll`, and the Vulkan attempt segfaulted
mpv. It needs `nvngx.dll` loaded by a real DLSS integration, which mpv cannot provide.

### UDP transport

Resyncs badly after a restart: 353 buffering events, with frames arriving every few seconds.
Moot now that nothing restarts. A pipe and TCP both measured 60 fps.

### `--untimed`

The original runaway neural blob. Presents outnumbered frame arrivals, so Neural Rendering
reprocessed its own output roughly sixty times per source frame until the picture collapsed.
Never add it.

### An in-app NR health indicator

Comparing the frame sent to mpv against the frame actually displayed separated NR on from NR
off by only 1.4x (0.58 off, 0.82 on, and 1.7 on in a different scene, so the scene mattered
more than the setting). Whole frame averaging at 1/8 stride washes out exactly the local
detail that Neural Rendering changes. It would have raised false alarms, so it was removed.
The F6 toggle is unambiguous instead, measuring 12.7/255 on plain text.

## Gotchas

- WGC cannot find a `WS_EX_TOOLWINDOW` window. The magnifier host must be a plain popup, and
  it should be captured by `window_hwnd` rather than by name.
- `windows_capture` dispatches handlers by function `__name__`. They must literally be called
  `on_frame_arrived` and `on_closed`, or it raises ValueError.
- `frame.frame_buffer` is row padded and non contiguous (stride 2304 for width 560), so it
  cannot go straight down a pipe. Slice `[:h, :w, :]`, `np.copyto` it into a reused buffer
  and write that buffer's memoryview. Do not write from the capture callback itself; see
  the frame rate section below.
- Passing `HWND_TOPMOST` as Python `-1` through ctypes silently fails on x64, because a 32 bit
  int goes into a pointer parameter. Use `ctypes.c_void_p(-1)`. mpv resets its own z order
  anyway, so give it `--ontop` rather than forcing the z order from outside.
- Stage windows share a title prefix, so find them by **exact** title match. Substring
  matching returns the wrong stage.
- `MagSetWindowTransform` is optional, and it deadlocks if called after the scaling callback
  has been set. Skip it; the identity transform is the default.
- The lens is deliberately **not** excluded from capture, which is what makes its output
  measurable with ddagrab. That is how see-through was verified: the lens output correlated
  0.997 with ground truth of the region behind it.
- `RegisterHotKey` posts `WM_HOTKEY` to the registering thread's message queue. It has to be
  registered on the same thread that pumps messages, not on a thread whose queue belongs to
  something else such as a tkinter mainloop.

## How to measure this thing without fooling yourself

Several wrong conclusions during development came from bad measurement rather than bad code.

- **Never measure with a moving source.** An early A/B read 16.1% changed pixels, but an
  animated avatar was in frame. The static half of the same image showed the real figure.
- **Establish a noise floor** by capturing the same state twice before trusting any difference.
- **Do not infer NR state from the F6 toggle log.** The focus dance sometimes fails to register
  a press, which inverts the inference. Measure absolutely instead: capture the region with the
  lens absent, then with the lens over it. Passthrough means off, a large difference means on.
- Neural Rendering's strength scales with local detail, about 4.5x stronger on the most
  detailed tenth of an image than on the flattest half. Flat content changing very little is
  expected, not a fault.

## Where the frame rate actually goes

Nothing here is GPU bound; the GPU sits near 30 percent at any pass count. The rate is set by
two things in the lens itself, and finding them took several wrong turns worth recording.

```
WGC on an ordinary animating window                    59.0 fps
magnifier host, paced at 120 Hz, 1400x1000             59.0 fps
magnifier host, paced at 120 Hz, 350x250               59.0 fps   (size is irrelevant)
lens driven by tkinter after(16)                       47.1 fps
lens, paced pump thread, write still inline            50.5 fps
lens, paced pump thread, capture only (no pipe write)  58.7 fps
lens, paced pump thread + writer thread                58.4 fps
```

1. **tkinter's `after()` is too coarse to pace repaints.** An `after(16)` tick lands nearer
   20 ms, which capped the lens around 50. A thread pacing `InvalidateRect` at 120 Hz fixes it.
   `InvalidateRect` from another thread only posts `WM_PAINT`; tkinter's mainloop dispatches it,
   since the host window belongs to that thread.
2. **The 5.6 MB `stdin.write` into mpv blocks the WGC delivery thread.** Removing the write
   entirely measured 58.7 against 50.5 with it. A writer thread with a one slot handoff absorbs
   the stall. The slot is overwritten rather than queued, because for a live view only the
   newest frame matters.

**The Magnification API is not the bottleneck.** An earlier measurement of 51.6 fps for it was
an artifact: that harness paced its own pump loop with `time.sleep(0.02)`, which is 50 Hz. It
measured my sleep interval, not the magnifier.

Things that measured as pure noise and are not worth redoing: replacing the double per frame
copy (2.93 ms to 0.18 ms), removing a redundant `MagSetWindowSource` from every tick, and
raising the Windows timer resolution with `timeBeginPeriod(1)`. All three are kept because they
are strictly cheaper, but none of them moved the frame rate.
