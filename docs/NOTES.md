# Engineering notes

Measurements, constraints and Win32 details behind the implementation. Most of the rejected
approaches below look reasonable on paper and fail only when measured, so each one is kept
alongside the number that ruled it out. Read this before changing the capture path, the
presenter or the passes.

## The presenter

`lens_presenter.py` is a glfw window with a Vulkan swapchain, `B8G8R8A8_UNORM`, in mailbox mode
where the surface offers it. Installed, it is `lens-presenter.exe`, frozen beside
`NeuralLens.exe`. From source, `lens-presenter.exe` in the stack folder is a copy of `python.exe`,
with a `pyvenv.cfg` beside it naming the real interpreter with `include-system-site-packages =
true`, and a `.pth` file naming the packages of the Python that ran the setup, so a virtual
environment works too.

Each captured frame is copied into a host visible staging buffer, from there into the next
swapchain image, and presented. Between arrivals the last frame is presented again at the
display's rate, copied in afresh each time, so a repeat never re-runs Neural Rendering on its
own output. A frame that arrives before the loop has taken the previous one replaces it. Every
present is a composition, and the monitor capture delivers a frame per composition, so the loop
runs at the display's rate even over a still.

The window is created hidden, given `WS_EX_TOOLWINDOW` and `WS_EX_NOACTIVATE`, and then shown
without activation, so no taskbar button ever appears, not even while it loads. It is excluded
from capture with `WDA_EXCLUDEFROMCAPTURE`. The process is per monitor DPI aware, version 2, set
before glfw initialises, as the lens is.

It reads `crop X Y`, `shot BASE`, `probe N` and `quit` on stdin, and prints a stats line a
second: new pictures presented, frames arrived, repeats, frames replaced by a newer one before
they were taken, and the meter, the median of the present call minus the capture's own
timestamp. `--source pattern` presents a still with detail and captures nothing; the stack
setup's self test uses it. The lens finds the presenter's window by its process id and glfw's
window class, `GLFW30`, which works the moment the window is visible.

**Delay.** Measured with a separate process flipping a window between black and white, and two
Windows Graphics Capture sessions in the harness timestamping the moment each mean crosses mid
grey, one on the flipper and one on the presenter's window, placed beside it so it could be
captured. Both pass through the compositor once, so that cancels:

```
window capture of the flipper, mailbox         8 ms   meter -5
monitor capture cropped to the flipper         8 ms
window capture, fifo                           5 ms
```

The capture's timestamp names the composition the frame belongs to, so the meter can read
negative; the title bar adds a refresh and a half, which put 8 against 8. With the lens itself at
one pass, the meter with that allowance reads 10 ms at 118 fps windowed at 1400x1000, and
fullscreen at 6144x2558 47 ms at 42 fps, or 33 ms at 58 fps with the Cost Scaler on.

**Effect parity, and a trap.** On the same still the presenter's after image first differed
from its before by 2.5, where earlier runs with mpv as the host had measured 4.5, with identical
before images. Neither a 10 bit swapchain nor an sRGB one changed it. The add-on's own
`active settings` log line did: the runs had straddled a change of `NRIntensity` from 1.31 to
1.7 and `NRStyle` from 1 to 0, made in the overlay between them. mpv measured again under the
same settings: 2.57. So the effect is the same through either host, and before comparing effects
across runs, compare the `active settings` lines. A 10 bit swapchain stayed optional,
`LENS_PRESENTER_10BIT=1`, blitting through an intermediate image: it cost frame rate, 91 against
118, for no difference to the effect.

**One monitor.** The presenter captures the monitor the lens was on when it started, and clamps
its crop to that monitor, so a lens over the monitor's edge shows a shifted picture and a lens
larger than the monitor gets no frames at all. When a drag ends with the lens's centre on another
monitor, the lens restarts the presenter there.

Binding notes: `vkMapMemory` in the vulkan package returns a buffer object, so
`np.frombuffer(mapped, ...)` works on it directly. Monitor capture frames carry alpha 255
throughout. windows-capture numbers monitors from 1 in `EnumDisplayMonitors` order.

## Capture under the lens's own windows

**Windows Graphics Capture of the monitor composes the desktop beneath an excluded window.** With
a window excluded through `WDA_EXCLUDEFROMCAPTURE` on top of a still, the captured region matched
the bare still exactly, a mean absolute difference of 0.0 before and after moving the cursor
across it. Desktop Duplication shows black there instead; see Dead ends.

An excluded window is invisible to every capture, window capture included, so the lens's output
cannot be captured from outside while it is excluded. The screenshots and the steadiness probe
read the presenter's own swapchain back instead.

Every window the lens owns is excluded: the chrome and the presenter when they are created, the
menu and the A/B divider when they open, and anything else by a timer that re-applies the
exclusion to every visible top-level window of the process every 200 ms, since dialogs and
message boxes offer no hook to act on.

## Why the stack is the program's folder

ReShade, loaded as a Vulkan layer, reads `ReShade.ini`, and through it the add-ons and shaders,
from the folder of the executable it attaches to. With `lens-presenter.exe` one folder above the
stack and the stack as its working directory, the layer did not attach, and `ReShade64.dll` 6.8.0
names no environment variable that points it elsewhere. So installed, the program's folder is the
stack, and from source the stack folder holds the interpreter's copy. The allow list,
`ReShadeApps.ini` beside the layer, names that one executable.

## Passes inside the add-on

**The v5 line of the add-on runs the passes itself** (renodx-dlss5 5.2.1 from the RHI
repository, and the v5.0 beta before it): `NRPasses` in its `[RenoDX.DLSS5]` section of
ReShade.ini, read only when the process starts. An edit while it ran had changed nothing twelve
seconds later, and a process that is terminated does not write the file back, so the lens writes
the key after the old presenter is gone and before the new one spawns.

The add-on does write its settings back within about a second of a change made in its overlay:
`NeuralUplift` was on disk 1.3 s after F6. So while the overlay is open, and for four seconds
after Done, the lens reads `NRPasses` back from the file, and a changed count becomes the title
bar's count with nothing restarted, since the add-on is already running it.

Against chaining whole pipelines, which is how 0.1.0 made passes, RTX 5090, 2400x1800 over a
still:

```
                              ceiling   at 60 fps          effect
2 chained stages               52 fps   95% GPU, 494 W    9.87
2 passes inside the add-on     69 fps   86% GPU, 482 W    9.95
3 chained stages               33 fps                     13.86
3 passes inside the add-on     53 fps                     13.74
```

Effect is the mean absolute difference of the after screenshot from the before, out of 255; the
two two-pass outputs differ from each other by 1.6.

Through the presenter, a 1400x1000 lens over a still with the add-on at its defaults, chained
history off as it ships: frames a second, the delay meter's reading, the change to the picture,
and the change between consecutive presented pictures, both out of 255:

```
passes   frame rate   delay   change   consecutive
1          118 fps    10 ms    2.30      0.42
2          107 fps    13 ms    3.58      0.51
3           89 fps    23 ms    4.89      0.65
4           74 fps    29 ms    6.21      0.76
```

**Flicker at two passes and up.** The add-on's own text: passes beyond the first are stateless by
default and can flicker; try the chained history toggle. Measured with the presenter's readback of
consecutive presented pictures over a still, mean absolute difference out of 255, first with
`NRIntensity=1.7` and `NRStyle=0`, then at the add-on's defaults. At the defaults the two and
three pass pairs were measured twice, in both orders, with the same result, and four passes once:

```
            NRIntensity 1.7, style 0        the add-on's defaults
passes      chained off     on              chained off     on
1             0.31                            0.42
2             0.46          0.37              0.51          0.59
3             0.60          0.34              0.65          0.66
4                           0.35              0.76          0.68
```

So whether chained history steadies the picture depends on the settings and the pass count, and
the lens leaves `NRChainedHistory` to the add-on, which keeps it off by default. The settings set
the floor as well: `NRIntensity=1.31` with `NRStyle=1` gave 0.12 at one pass.

Traps: this add-on line resets its whole section to built-in defaults when `ConfigVersion` is
missing or older than its own, and writes `ConfigVersion=2`, without a log line. Its own working
resolution setting (`NRFollowInputRes`, `NRResolutionScale`) scales against a game's DLSS render
resolution, which the lens has none of: with `NRFollowInputRes=2` and `NRResolutionScale=0.75`
the log still said `NR input 2400x1800`, at the same cost and with the same output.

The newer `renodx-dlss` add-on, with `DirectNeuralRenderingPassCount`, does not inject at all;
see Dead ends.

## The add-on's defaults on a new install

With a section holding only `ConfigVersion=2`, 5.2.1 ran at its defaults, logged as
`intensity=1.000000 color_strength=1.000000 transfer=1.000000 paper_white=2.537500 preset=0
style=0 enabled=ON`, wrote back `EnableHooks=2`, `NeuralUplift=1` and `NREnableUpscaling=0`, and
created and evaluated feature 18 at one pass. So that is all the setup writes into the section,
and a repair keeps whatever the section holds.

The add-on's developer asked, for the v5 line, that the proxy codec be set to Classic,
`NRCodecMode=0`. Interleaved over a still at the defaults, one pass, twice each: the change
between consecutive presented pictures measured 0.42 with the default codec and 0.40 with
Classic, the change to the picture 2.30 and 2.19, and the frame rate 118 and 116. So the default
stays.

## The Cost Scaler

xenmods' DLSSNR-Cost-Scaler is a proxy `nvngx_dlssnr.dll` that runs the model at a fraction of
the frame and composites the delta back onto the native frame. It implements four D3D12 NGX
entry points and forwards the other 51, every Vulkan one included, to `nvngx_dlssnr_real.dll`.
It works in the lens because Neural Rendering there is a **D3D12 NGX session behind the Feed's
Vulkan transport**: `dlss5-feed.log` says `opening D3D12 session (Vulkan transport)`, and neither
add-on carries a single `NVSDK_NGX_VULKAN` symbol. The add-on logs the proxy as
`custom runtime accepted; untested build` and carries on. The proxy logs its settings and its
working size in `nvngx_dlssnr_proxy.log`, switched off included, and reads its ini when it starts
and again within a second of a change.

The setup writes the proxy's own ini with four changes: `EnableProxy = 0`, since the lens decides;
`EnableHotkeys = 0`, since its hotkeys are polled globally and a desktop program must not answer
Ctrl+Alt+PageUp in every window; `EnableDepthAwareResolve = 0`, which works from the depth the
Feed synthesises and was off for every measurement below; and `EnableGovernor = 0`, its default.

Measured with 0.1.0's pipeline, passes inside the add-on, most frames a second presented:

```
                                     off    0.75    0.50    0.35
fullscreen 6144x2558, 1 pass          30      43      43      44
fullscreen 6144x2558, 2 passes        23      31      43      43
windowed 2400x1800, 1 pass            97      88
windowed 2400x1800, 2 passes          69      86      91
windowed 1400x1000, 1 pass           100     100
```

Through the presenter, fullscreen at 6144x2558 over a still with the add-on at its defaults and
the proxy at the lens's own scale; the one pass pair was measured twice with the same result. The
delay is the meter's reading, the change is from the untouched source out of 255, and the power
is one reading of the card's draw:

```
                         frame rate   delay   change   power
one pass, off              42 fps    47 ms    1.63     557 W
one pass, on at 0.70       58 fps    33 ms    1.22     500 W
two passes, off            26 fps    78 ms    2.98     576 W
two passes, on at 0.50     54 fps    36 ms    2.22     503 W
```

Effect, the after screenshot against the before as mean absolute difference out of 255, at
2400x1800 with two add-on passes: 9.95 native, 8.59 at 0.75, 5.62 at 0.50. Power at a matched
60 fps, one pass: 314 W to 261 W. It pays where the neural pass is the limit, fullscreen and
multi-pass, and costs a little where it is not, which is why the lens turns it on for fullscreen
only. One pass wants about 0.7 on that panel and two passes 0.5, so the rule is a working area of
8 megapixels over all the passes, re-applied whenever the pass count changes.

## Resize restarts the process

A resize would recreate the swapchain, and the Neural Rendering add-on responds to a recreated
swapchain by releasing its DLSS feature and crashing with 0xC0000005. Moving the lens is safe,
because that only repositions windows and moves the crop.

The menu's resize writes the new geometry into the state file and starts a fresh copy of the
process once `quit()` has ended the presenter and waited for it, and a further second has
passed.

### The handover must not use `os.execv`

On Windows `os.execv` goes through the CRT, which does **not** quote arguments containing
spaces. A script path such as `C:\Some Folder\neural-lens\neural_lens.py` therefore
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
and nothing left running; and the same flow driven from a batch file inside a directory whose
name contains a space.

## Dead ends

### mpv as the host

0.1.0 hosted the neural pass in mpv. A Magnification API window under the lens rendered the
desktop for the lens rectangle, Windows.Graphics.Capture captured that window by its handle, raw
BGRA frames went into mpv's standard input, and ReShade's Vulkan layer hooked mpv's swapchain. It
worked, and three things about it could not be fixed from outside mpv:

- **Delay.** mpv plays a stream at a declared rate, so every frame in its readahead is delay.
  With the readahead cut from eight frames to two and `--video-latency-hacks` on, a flip under
  the lens took 68 to 70 ms to reach the output at 99 fps, 136 ms with eight frames, and 183 ms
  at 33 fps. One frame of readahead measured 63 ms and left no slack for a late frame, which
  shimmered. The presenter measures 8 ms and, fullscreen, 33 ms.
- **Rate.** Declaring more than the pipeline delivers makes mpv present without a new frame, and
  Neural Rendering then re-runs over its own output until the picture crushes toward black and
  recovers, over and over. `--untimed` does the same thing at once. Declaring exactly what arrives
  shimmers instead: one stage with 119 frames a second arriving measured 1.637 out of 255 at 120
  declared, 0.220 at 110 and 0.150 at 100, against a floor of 0.146. So 0.1.0 declared five
  sixths of the display rate and governed a playback speed live from the presented rate, the
  brightness out against in, and the output's frame to frame change on still content, with limits
  that expired and retakes of levels already held. A rule calibrated on one GPU did not survive
  another: on an RTX 4070 SUPER two passes at the rule's 50 presented 40 and shimmered, and a
  2000x1400 lens at 100 presented 27 and collapsed. The presenter presents the captured frame
  again instead of a stale one, so neither failure can occur, and nothing needs governing.
- **Passes.** Before the add-on could run several passes, each extra pass was another mpv
  capturing the one before, stacked on the same rectangle: cumulative change 7.71, 14.05 and
  19.45 for one, two and three passes, 0.24 with Neural Rendering off. Every stage had to be on
  the magnifier's exclude list, or the magnifier rendered it back into the first stage's input
  and the picture collapsed into a feedback loop, 62.52 at two passes with a stage missing. See
  Passes inside the add-on for what replaced it.

The 0.1.0 tag's copy of this file has the full measurements of the governor, the readahead and
the chain.

### Desktop Duplication (ddagrab) under the lens

It cannot see beneath an occluding window, whether or not that window is excluded from capture,
and not even when something is actively repainting underneath it.

```
capture a region away from the lens          YAVG 45.7    real content
capture exactly where the lens sits          YAVG 18.0    black is 16

magnifier repainting that rect, no lens      YAVG 45.96
same, with an excluded lens on top           YAVG 20.04   black again
```

`WDA_EXCLUDEFROMCAPTURE` removes a window from the capture, but it does not make Desktop
Duplication show the desktop behind it: nothing composites the occluded region into the
duplication buffer, so it stays empty there and only transient dirty rects land in it. The
symptom is a black viewport that accumulates mouse trails and window drag smears. Windows
Graphics Capture of the monitor does compose it; see Capture under the lens's own windows.

Two caveats when testing this. A static window over another static window does capture
correctly, because DWM still holds both buffers, so that case does not generalise: a Vulkan
swapchain presenting sixty times a second means the region beneath it is never redrawn. And
sample YAVG rather than chroma, because a chroma only check gives a false pass.

### gdigrab or BitBlt of a magnifier window

Blank whether occluded or not. The magnifier composites through DWM, and BitBlt sees only the
window's own GDI surface, which is empty.

### MagSetImageScalingCallback

Deprecated. It is accepted and returns TRUE, and then the next Mag call deadlocks when driven
from ctypes, most likely because the callback takes structures by value.

### The newer renodx-dlss add-on (the one with PassCount)

Will not inject into mpv on either `--gpu-api=vulkan` or `d3d11`. Zero
`DLSS-NR direct: EvaluateFeature` in both cases, both stopping at
`WARN NVNGX parameter module is not loaded yet: nvngx.dll`, and the Vulkan attempt segfaulted
mpv. It requires `nvngx.dll` loaded by a real DLSS integration, which a capture host cannot
provide.

### UDP transport

Resynced badly after a restart: 353 buffering events, with frames arriving every few seconds. A
pipe and TCP both measured 60 fps, and nothing restarts mid session, so it bought nothing.

### An in-app NR health indicator

Comparing the frame sent to the host against the frame actually displayed separates NR on from NR
off by only 1.4x: 0.58 off, 0.82 on, and 1.7 on in a different scene, so the scene matters more
than the setting. Whole frame averaging at 1/8 stride washes out exactly the local detail that
Neural Rendering changes, so such an indicator raises false alarms. The F6 toggle is unambiguous
instead, measuring 12.7/255 on plain text.

## Gotchas

- `windows_capture` dispatches handlers by function `__name__`. They must literally be called
  `on_frame_arrived` and `on_closed`, or it raises ValueError.
- `WindowsCapture(...)` takes a `minimum_update_interval` whose default throttles delivery to
  about 60 frames a second. Setting it to `0` more than doubles delivery on an identical source:
  59.4 against 124.6.
- `frame.frame_buffer` is row padded and non contiguous (stride 2304 for width 560). Slice
  `[:h, :w, :]` and `np.copyto` it into a reused buffer; `ascontiguousarray().tobytes()` costs
  two full copies, measured at 2.93 ms per 1400x1000 frame against 0.18 ms.
- The opening frame of a freshly started window capture session is sometimes handed over
  uninitialised and comes back black, measured at roughly one sample in 14. Skip the first
  frames and reject an all zero buffer.
- Passing `HWND_TOPMOST` as Python `-1` through ctypes silently fails on x64, because a 32 bit
  int goes into a pointer parameter. Use `ctypes.c_void_p(-1)`.
- Find a child process's window by its process id rather than its title. A window is visible
  before its title is set: mpv's showed "mpv" for a second and a half before taking its
  configured title, with a taskbar button all that time.
- A window with `WS_EX_TOOLWINDOW` or `WS_EX_NOACTIVATE` has no taskbar button. Set the styles
  while the window is still hidden, or the button appears while it loads. Windows Graphics
  Capture cannot find a tool window by its handle, which does not matter for a window nobody
  captures.
- `WindowFromPoint` skips click-through windows. To see what is stacked over the lens, walk the
  z-order with `GetWindow(h, GW_HWNDPREV)`.
- **Windows puts a maximised or full screen window that becomes the foreground above every topmost
  window.** Measured with the Photos app maximised over a windowed lens: it sat above the
  presenter and stayed there, and only a fresh `HWND_TOPMOST` brought the lens back. The lens
  walks the z-order above the presenter every 200 ms and raises itself when a visible window that
  is neither its own nor itself topmost overlaps it.
- `tk_popup` is a native `TrackPopupMenu`. It blocks Tk's main loop until the menu closes, and it
  dismisses on an outside click or Escape only while its owner is the foreground window, which a
  title bar that never activates is not. The menu is a Tk window of the lens's own instead, closed
  by a 30 ms poll of the mouse buttons and Escape through `GetAsyncKeyState`.
- `RegisterHotKey` posts `WM_HOTKEY` to the registering thread's message queue. It must be
  registered on the same thread that pumps messages, not on a thread whose queue belongs to
  something else such as a tkinter mainloop.
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
  it writes `ReShade.log1`, and a third writes `ReShade.log2`. Anything that archives or inspects
  logs must cover all of them.

### The taskbar button is the tk root

The title bar is an override redirect window that never activates, so the mouse reaches the
application under the lens, and that combination has no taskbar button. The hidden tk root
stands in: titled, fully transparent, and parked minimised. Restoring it from the taskbar fires
`<Map>`, the handler re-asserts topmost on the presenter and then on the bar, and minimises the
root again before it can be seen. `raise_chrome` alone would not do, since it re-asserts only the
bar. Tk toplevels on Windows are not owned by the root, which was measured rather than assumed:
the bar stayed visible with the root minimised, and restoring fired exactly one `<Map>`. Close
window on the button arrives as the root's delete request and quits the lens.

### No console

The installed lens is a windowed program, and the launcher starts the lens under pythonw.
`sys.stdout` is None there, so at import everything printed is redirected to `lens.log` in the
log folder, with the previous one first rolled into a stamped copy so the archive's pruning covers
it. `GetConsoleWindow()` returning zero is what turns the messages that used to wait for Enter into
dialogs, including a presenter that never opened its window and an unexpected traceback out of
`main()`. A harness driven from a tool with no console window sees the same, so any test that
reaches a fatal path has to replace `messagebox.showerror` first, or it blocks on a dialog nobody
will dismiss.

The presenter catches any unhandled error itself, prints the traceback to its stderr, which the
lens keeps in `presenter-stderr.log`, and exits: frozen without a console, an unhandled error
would otherwise stop in a dialog of the bootloader's while the lens waited for a window. From
source, the lens starts the interpreter's copy with `CREATE_NO_WINDOW`, since `python.exe` would
otherwise open a console of its own under a lens that has none.

### Per monitor DPI awareness

A 1400x760 lens on the 5090's secondary monitor once produced a 1680x912 picture: ReShade created
its Neural Rendering resources at 1680x912 and the Feed delivered frames at 1680x912, while
`GetWindowRect` from inside the lens said 1400x760. The ratio, 1.2, is not a scaling factor, it
is the ratio of two: 150 percent over 125. A system DPI aware process keeps the DPI the session
logged on with and lives in a coordinate space Windows virtualizes against each monitor, so a
window placed on a monitor whose scaling differed from that was rescaled by Windows on the way.
The lens and the presenter are per monitor DPI aware, version 2, so every coordinate either uses
is a physical pixel on whichever monitor it is on.

Verified on the 4070 with the primary monitor switched to 125 percent while the session had
logged on at 100: the lens asked for 1400x760, a per monitor aware probe measured the picture's
window at 1400x760 physical, ReShade created its resources at 1400x760, and the chrome measured
1404x796 with both windows reporting 120 DPI, so nothing is bitmap stretched either. Fonts follow
the monitor's DPI; the bar is 34 pixels and holds a 10 point label up to 200 percent.

### Fullscreen

- **A layered window larger than the screen comes up blank.** The windowed chrome is the picture
  plus a title bar plus a border, so over a whole monitor it was 3844x2194 on a 3840x2160
  display. It existed, was visible and topmost, and drew nothing. Fullscreen the chrome is
  therefore just the bar, laid over the top edge of the picture.
- **A borderless window that covers a monitor exactly is taken over by the compositor's
  fullscreen path**, and the title bar on top of it stops being drawn. The picture is two pixels
  short of the monitor's height.
- **The picture's window can climb above the chrome.** The lens walks the z-order above its
  chrome on the 200 ms timer and raises the chrome again whenever the presenter is found there.
  Menus and dialogs are not the presenter, so they stay above.
- **The ReShade overlay keeps its tabs along the top edge, under the bar.** In tweak mode the bar
  becomes an 840 pixel strip in the bottom right corner and returns on Done. Not the whole bottom
  edge: the overlay reaches nearly to the bottom of the monitor, with its Reload button spanning
  its width there, and it is anchored top left, so the far corner is clear. At 780 pixels Tk's
  packer dropped the minus button. The picture's origin is fixed when the lens starts rather than
  derived from the bar, which moves.

The fullscreen lens keeps its pass count in `lens-state-fullscreen.txt`, because the windowed
state file is what the way back restores.

### The A/B divider

The divider is a thin topmost window of this process, excluded from capture like the rest, and
the presenter is clipped with `SetWindowRgn` to the left of it. Two things about dragging it:

- **Tk ignores `geometry()` on a window while the mouse button is held on it.** The split value
  followed the drag and the clip moved, but the line itself stayed where it was until release,
  which reads as "the slider is locked". The divider is moved with `SetWindowPos` instead.
- The drag follows the mouse from a thread polling the button and the cursor rather than Tk's
  motion events, so it keeps working after the pointer leaves the fourteen pixel window.

## Measurement pitfalls

- **Never measure with a moving source.** A reading of 16.1% changed pixels came from an animated
  element being in frame; the static half of the same image gave the real figure. Check that the
  source is unchanged across samples before trusting any difference in the output.
- **Establish a noise floor** by capturing the same state twice before trusting a difference.
- **Compare the add-on's `active settings` lines** in `ReShade.log` before comparing effects
  across runs. A setting changed in the overlay between two runs moves the effect by more than
  most code changes; see Effect parity above.
- **Keep the GPU to the lens.** Another process taking the GPU lowers what the lens presents and
  changes the delay, and it does so unevenly.
- **F6 belongs to the add-on, which reads it through `GetAsyncKeyState`**, the physical keyboard.
  Posted to the window it did nothing in three runs, with or without focus, while one genuine
  keystroke with no focus at all toggled it, measured as the in-to-out difference over the same
  still going from 1.20 to 2.22. So the menu sends F6 as a real keystroke with the presenter
  briefly focused, to shield whatever is under the lens from it, and the lens polls the same key
  the same way to track the state, seeded from `NeuralUplift` in `ReShade.ini`. ReShade's own
  keys, Home for the overlay and F5 for its screenshot, are posted to the presenter's message
  queue and held for longer than a frame, since ReShade notices a key only when it polls, once per
  present. Measure absolutely anyway: capture the region with the lens absent, then with the lens
  over it.
- F6 is persisted by the add-on as `NeuralUplift=0` in ReShade.ini, so one toggle turns Neural
  Rendering off for every later launch.
- Neural Rendering's strength scales with local detail, about 4.5x stronger on the most detailed
  tenth of an image than on the flattest half. Flat content changing very little is expected.
- **Never assert an absolute difference for Neural Rendering.** The strength depends on what is
  under the lens, so a threshold calibrated on detailed video fails on flat interface content,
  and it fails by looking exactly like a broken feature. Assert the shape instead: the change
  concentrates in detailed areas. One pair over flat interface measured 1.29 overall, yet 6.21
  on the most detailed tenth against 0.654 on the flattest half, a ratio of 9.5x.
- **The detail ratio is itself content dependent.** It works where the image has genuinely flat
  areas to contrast against. Dense photographic content has none: a still frame of film footage
  measured 2.24x, 2.51x and 2.67x across three captures of a bit for bit identical source. Gate
  the assertion on the flattest half actually being flat, and where it is not, assert only that
  the effect sits well above the capture's own noise.
- **Check that the source held still before trusting any before and after pair.** Saving two
  captures and comparing them costs nothing and settles it.
- **Drive the real application rather than a mock.** `neural_lens.py` guards its entry point with
  `if __name__ == "__main__"`, so a harness can import it, wrap `Lens.__init__` to obtain the
  running instance, and schedule real menu actions on the real mainloop.

## The installer and the stack setup

The lens is frozen with PyInstaller from `installer\NeuralLens.spec` into two programs sharing one
folder, `NeuralLens.exe` and `lens-presenter.exe`, and wrapped by Inno Setup into a per user
installer, `PrivilegesRequired=lowest`, into a folder the user chooses,
`%LOCALAPPDATA%\Programs\NeuralLens` by default. The installer holds the lens and nothing else.
Setup fetches the neural stack during the installation, ticked by default, and `neural_stack.py`
runs the same fetch later from a Start Menu entry or the command line, into the install folder
itself, with the Vulkan layer in `ReShade` beside it and the downloads in `downloads` until the
self test passes. The lens keeps its state, logs and screenshots in `data` there too. So an
install is one folder plus one registry value naming the layer, and the uninstaller runs the
exe's own `--uninstall-stack` for the value and deletes the folder. A DLL the user points the
setup at is copied in after its hash check and only the copy is recorded, so an uninstall never
reaches the original.

Nothing of the stack is bundled, and licences force that rather than taste: NVIDIA's runtimes are
NVIDIA's, the RenoDX add-on has no published licence, and the default motion vector estimator is
CC BY-NC 4.0. NVIDIA's runtimes come from the RHI project's manifest, which carries no hashes, so
the hashes live in `neural_stack.py` and a download matching none is refused; the add-on and the
Cost Scaler are pinned releases whose archives and files are checked the same way. ReShade's DLL
comes straight out of its setup exe, which is a zip, with nothing of ReShade's executed.

Facts measured while building it:

- **The RHI manifest's `310.8.SF-v2` build is not the one many people already hold.** Its zip
  unpacks to a file of 165,830,144 bytes, version 310.8.SF.0, unsigned, hash
  6EB209E7...; the earlier community build is 165,840,496 bytes, version 310.8.0.0, signed by
  NVIDIA with a hash mismatch, hash 8270B350.... Both run Neural Rendering, so both are accepted.
- **A per user Vulkan layer coexists with a machine wide ReShade only under a different name.**
  The loader loads one implicit layer per name, HKLM before HKCU, so a per user copy named
  `VK_LAYER_reshade` is skipped wherever a machine wide one exists. The layer is registered as
  `VK_LAYER_reshade_neural_lens`, with its own `ReShadeApps.ini` listing only the presenter, so
  each ReShade hooks only what it lists. Verified on a machine with the machine wide layer
  present: the self test attached, loaded both add-ons and evaluated. The same rule means two
  installs of the lens on one account share one layer, whichever was registered first.
- **`ReShadeApps.ini` is an allow list**, so the per user layer is loaded into every Vulkan
  process and leaves each one alone unless it is listed.

The card is checked by compute capability from the driver's own `nvidia-smi`, 7.5 or higher
meaning the RTX 20 series and newer, rather than by marketing names; one model serves every card
that passes. The self test runs the presenter on its pattern source in a 960x540 window at the top
left for nine seconds, and reads `ReShade.log` for `feature 18 created` and `evaluation succeeded`,
the Feed's log for its motion vector provider, and the Cost Scaler's log for its load of the real
model. `0xbad00001` is reported as the model refusing the card.

`install-record.json` lists every file written and the registry value set, and
`--uninstall-stack` removes that, plus any layer value pointing inside the install that the record
did not know about. The Inno uninstaller calls it without asking and then deletes the whole
install folder.

**Upgrading from 0.1.0.** A record whose components include mpv marks a stack 0.1.0 assembled,
in `stack` inside the install, or in the same stack folder from source. The setup moves NVIDIA's
two runtimes to where it keeps them when their hashes check out, keeps ReShade's DLL when the
version matches, removes the rest by that record, the layer registration and the allow list that
named mpv included, and, installed, removes what is left of `stack`.

Four things the lens's own offer of the setup did that the Start Menu entry did not, found by
driving the offer end to end against the built exe:

- **The setup window was blank for five seconds.** The first console program started while a
  shown topmost Tk window is up took 5.2 seconds under pythonw and the exe, 0.1 seconds with
  the window hidden or from a console, measured with `nvidia-smi` alone. Console children now
  run with `CREATE_NO_WINDOW` and a null stdin, and the card is identified before the window
  exists: laid out in 0.6 seconds from the exe.
- **The install folder showed empty, and typing into it changed nothing.** At the offer, the
  lens's own Tk root already exists and is tkinter's default root, so a `StringVar()` without a
  master lived in that interpreter while the entries lived in the setup window's. Every variable
  in the wizard is made on the window's own Tk.
- **Set it up failed with "main thread is not in main loop".** The install thread read the
  fields with `.get()`, which Tk allows from another thread only while the main thread is in
  `mainloop`; at the offer it is in `wait_window`. The fields are read on the main thread when
  the button is pressed and the thread gets strings.
- **A relaunch after the setup found the incomplete folder again.** The relaunch reused the
  arguments it was started with, so a folder named on the command line or in the ini that led to
  the offer was found first and the offer came back. The wizard returns the folder it installed
  into and the relaunch names it first.

### VORT's includes, and the measure that agrees with the eye

The self test passed with VORT's shader failing to compile, because a still needs no motion
vectors: four of its includes were missing from a hand picked list, the Feed logged "no known
VORT shader is installed: motion vectors will be zero", and nothing else said so. The setup
fetches VORT's whole include folder and its blue noise texture, and the self test reads the
Feed's provider line and fails on "none".

Sharpness, the variance of the Laplacian of the output frames, cannot see a ghost, since a
second edge adds high frequencies, and a lower frame to frame change can be the ghost itself, a
blend that lags. The measure that agrees with the eye is the partial ink fraction of the page,
the share of pixels between 40 and 160 out of 255 on a black on white page, where crisp text is
bimodal and a ghost adds mid greys. VORT's own options (its rest mode is for engine vectors)
and the Feed's validation values did not change its result.

Every provider the Feed lists was put through the same page at three scroll speeds, plus a
control with no provider enabled at all, which the Feed answers with zero vectors:

```
                                                    slow    reading   fast    licence
Launchpad (iMMERSE, Pascal Gilcher)                 0.051   0.083     -       all rights reserved, permission needed
ReshadeMotionEstimation (Jakob Wapenhensch)         0.075   0.096     0.102   CC BY-NC 4.0
VORT (Vortigern)                                    0.099   0.109     0.106   MIT
dh_uber_motion (AlucardDH)                          0.112   0.113     0.108   GPL-2.0
no provider, zero vectors                           0.114   0.123     -
```

So the default a new install gets is ReshadeMotionEstimation, DRME, the Feed's provider 0
through the shared `texMotionVectors`: crisper than the others on this test, and CC BY-NC 4.0
allows it to be fetched and used with credit in a free tool. Two things to know about it. Its
repository publishes no releases and was last touched in 2023, so the setup pins the commit.
And on ReShade 6.8 its first pass, the frame save, fails to compile with "cannot sample from
texture that is also used as render target"; the Feed's header warns that DRME then "silently
writes nothing", but measured here the estimator's remaining passes produce vectors that beat
every alternative, and the zero vector control is far worse, so the warning describes a
different case or an older build. VORT is fetched as well and can be chosen instead. Launchpad
measured best of all, but its licence requires its author's explicit permission to use it as
part of another project, so it is not fetched. qUINT is all rights reserved and no longer ships
a motion shader.
