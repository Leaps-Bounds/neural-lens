# Engineering notes

Measurements, constraints and Win32 details behind the implementation. Most of the rejected
approaches below look reasonable on paper and fail only when measured, so each one is kept
alongside the number that ruled it out. Read this before changing the capture path, the
presenter, the fast engine or the passes.

## The presenter

`lens_presenter.py` is a glfw window with a Vulkan swapchain, `B8G8R8A8_UNORM`, in mailbox mode
where the surface offers it. Installed, it is `lens-presenter.exe`, frozen beside
`NeuralLens.exe`. From source, `lens-presenter.exe` in the stack folder is a copy of `python.exe`,
with a `pyvenv.cfg` beside it naming the real interpreter with `include-system-site-packages =
true`, and a `.pth` file naming the packages of the Python that ran the setup, so a virtual
environment works too.

Each captured frame is copied into a host visible staging buffer, from there into the next
swapchain image, and presented, and every present copies the staging buffer in afresh, so a
repeat never re-runs Neural Rendering on its own output. A frame that arrives before the loop has
taken the previous one replaces it. Every present is a composition, and the monitor capture
delivers a frame per composition, so up to 0.2.1 the loop drove itself at the display's rate
even over a still, see Idle when nothing changes.

### Idle when nothing changes

The capture thread compares each frame with the last before handing it over, first a sample of
every sixteenth pixel each way, which catches motion in microseconds, then every byte, eight at
a time through a uint64 view. A frame the same as the last is counted as arrived, so the
capture is known to be alive, and dropped. The loop then presents only for a fresh frame, or as
a heartbeat every quarter second, which keeps ReShade's hotkeys polled and, since each present
is a composition, keeps frames arriving for the watchdog. Over a still that is four presents a
second in place of a hundred and twenty. `live 1` on stdin presents at the display's rate while
the ReShade overlay is open, since the overlay is drawn and read on presents, and `wake` does
the same for a second. The add-on reads F6 on a present, so the lens sends `wake` the moment it
sees the key, and reads the add-on's answer back from ReShade.ini two and a half seconds later
in case it was missed all the same. A screenshot or a probe present at once.

A fresh presenter presents at the display's rate for its first twelve seconds whatever arrives,
and for three seconds after a resume. The add-on builds its neural feature on the first frames it
is shown, and at four a second it did not. A presenter that idled from birth over a still showed no
Neural Rendering six seconds in, and its ReShade.log never logged a feature at all.

Measured with a test that took five second samples of nvidia-smi and GetProcessTimes, on the
RTX 5090 at 1400x1000 with one pass, the machine reading 1 percent and 45 W with nothing running.
Over a still, idling, the GPU read 0 percent and 53 W, the presenter used 0.17 s of CPU, five
frames a second arrived and none was presented, and a screenshot after the warm-up still showed
Neural Rendering applied, a change of 2.10 out of 255. The same still with `live 1`, which is how
every version before presented, read 57 percent, 222 W and 2.02 s. A square bouncing 33 times a
second read 21 percent, 114 W, 0.80 s and 33.8 new pictures a second, and one bouncing 60 times
a second read 36 percent, 166 W, 1.25 s and 58.6 new pictures a second.

The comparison costs about half a millisecond at 1400x1000 and a few milliseconds at 6144x2560,
and only when a frame arrives. Over a still, frames arrive at the heartbeat's rate.

The idle loop waits on the window's own message queue, `glfw.wait_events_timeout`, and the
capture thread and the command thread post an empty event to end the wait. A first version
waited on the capture's condition variable instead, and a loop asleep there answers no window
messages. The lens moves the picture's window with `SetWindowPos`, which waits for the window's
thread to answer, so each mouse movement of a drag took 267 ms on average and up to 469 ms,
against 11 ms while presenting live, measured by a test that times each step of a drag. Waiting
on the message queue, the same move takes 0.3 ms idle and 3 ms live.

The window is created hidden, given `WS_EX_TOOLWINDOW` and `WS_EX_NOACTIVATE`, and then shown
without activation, so no taskbar button ever appears, not even while it loads. It is excluded
from capture with `WDA_EXCLUDEFROMCAPTURE`. The process is per monitor DPI aware, version 2, set
before glfw initialises, as the lens is.

It reads `crop X Y`, `shot BASE`, `probe N`, `pause`, `resume`, `live 1|0`, `wake` and `quit`
on stdin, and prints a stats line a
second: new pictures presented, frames arrived, repeats, frames replaced by a newer one before
they were taken, and the meter, the median of the present call minus the capture's own
timestamp. `--source pattern` presents a still with detail and captures nothing, and the stack
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
negative. The title bar adds a refresh and a half, which put 8 ms against 8 ms. With the lens
itself at one pass, the meter with that allowance reads 10 ms at 118 fps windowed at 1400x1000,
and fullscreen at 6144x2558 47 ms at 42 fps, or 33 ms at 58 fps with the Cost Scaler on.

**Effect parity, and a trap.** On the same still the presenter's after image first differed
from its before by 2.5, where earlier runs with mpv as the host had measured 4.5, with identical
before images. Neither a 10 bit swapchain nor an sRGB one changed it. The add-on's own
`active settings` log line showed why. The runs had straddled a change of `NRIntensity` from 1.31 to
1.7 and `NRStyle` from 1 to 0, made in the overlay between them. Measured again under the same
settings, mpv gave 2.57. So the effect is the same through either host, and before comparing
effects across runs, compare the `active settings` lines. A 10 bit swapchain stayed optional,
`LENS_PRESENTER_10BIT=1`, blitting through an intermediate image. It cost frame rate, 91 fps
against 118 fps, for no difference to the effect.

**One monitor.** The presenter captures the monitor the lens was on when it started, and clamps
its crop to that monitor, so a lens over the monitor's edge would show a shifted picture and a
lens larger than the monitor would get no frames at all. So the lens keeps itself on one monitor.
`fit_rect` moves it, and shrinks it keeping its proportions, into the work area of the monitor
under its centre when it starts, when a resize ends and when a drag ends. A lens that has to
shrink gets a new picture at the smaller size, since a new size needs a new swapchain. A new
install opens at 1400x1000, fitted to and centred on the main monitor. When a drag ends with the
lens's centre on another monitor, the lens restarts the presenter there.

**Display changes end the capture.** With a second monitor switched on while the lens ran, the
presenter went on presenting its last frame. A red and green square flashed under the lens's
centre never reached the Neural Rendering input, and switching the monitor off again did not bring
the capture back. The main monitor's handle changed with each change. Two things recover it:

- The lens reads the monitor layout on its 200 ms timer and starts a new presenter once a changed
  layout has held still for a second. With a real monitor switched on and then off, each change
  gave a new presenter within about three seconds. After the first, its picture matched the still
  exactly, and after the second, the flashed square reached the input.
- The presenter reports a capture that has stopped delivering as `capture lost`. That is a closed
  capture, frames that no longer cover the lens, or a monitor capture silent for three seconds,
  since a monitor capture delivers a frame for every composition, over a still desktop too. The
  lens then starts a new presenter after a wait that begins at a second and doubles up to a
  minute, until a presenter has run for half a minute, because a screen that is off or locked is
  silent as well. windows-capture's `stop()` does not call `on_closed`, so the silence is what
  caught a stopped capture in the harness, with a new presenter 6.6 s after the stop.

**Binding notes.** `vkMapMemory` in the vulkan package returns a buffer object, so
`np.frombuffer(mapped, ...)` works on it directly. Monitor capture frames carry alpha 255
throughout. windows-capture numbers monitors from 1 in `EnumDisplayMonitors` order.

### The first frame after a rest

Idling has a cost the 8 ms figure above does not show, since that was measured before the
presenter idled. It is the first frame after a rest. It was measured on an RTX 4070 SUPER with
a 120 Hz display, using a 1400x1000 presenter at one pass capturing a window that flips black
and white and sits still between flips, flip to flip through the compositor both ways, nine
flips a case:

```
                                                       first frame after rest
presenting continuously, as before 0.3.0               17 ms median, 8 to 26
idle, four presents a second, GPU clock locked at 2010  52 ms flat
idle, four a second, clocks free, 1.2 s still           67 ms median, 30 to 118
idle, four a second, clocks free, 12 s still            65 ms median, up to 156
idle, four a second, Neural Rendering off, 12 s still   62 ms median, up to 82
```

There are two causes, and neither is the neural pass. With the clock locked, a lone present
after silence still reaches the screen 35 ms later than a frame in a stream, while the
presenter's meter shows it presented within 2 ms of the capture. A sporadic present takes the
compositor's slow path where a stream gets the fast one. With clocks free, the card drops to
210 MHz within a second of resting, and a flip that meets it at 225 to 675 MHz costs anything
from 30 to 156 ms. Locking the clock removed every outlier, and a sampler reading `nvidia-smi`
at 10 Hz showed the clock at each flip tracking the delay.

What a heartbeat buys, 12 seconds still, clocks free, GPU use and power over the quiet time:

```
presents a second while still   first frame after rest    GPU    power
4, as 0.3.0 shipped              62 ms median, 31 to 151   16%    40 W
30                               21 ms median, 17 to 39    35%    58 W
60                               17 ms median, 12 to 25    41%    68 W
the machine idle, no lens                                   0%    14 W
```

So the presenter keeps thirty presents a second for ten seconds after any new picture and four a
second after, and `ready` keeps thirty throughout. On the same rig a 5 second pause, inside the
cooldown, gave 21 ms median, a 12 second pause gave 69 ms, 65 to 76 ms, with the spikes gone since
the clocks never fall as far, and 12 seconds with `ready` gave 21 ms. The presenter's meter
cannot see any of this, since it measures from the capture's composition to the present call,
which is where the delay is not.

Measured again on an RTX 5090 with the same rig, a 6144x2560 display at 120 Hz, and the
presenter as it now is, thirty a second for ten seconds after a change and four a second after,
nine flips a case:

```
                                          first frame after rest
1.2 s still                               10 ms median, 9 to 12; one flip of eleven at 200
12 s still                                10 ms median; three flips of nine at 181 to 182
30 s still                                13 ms median; four of nine at 180 to 222
12 s still, heartbeat forced to 100 ms    10 ms median; one of nine at 217
12 s still, ready, thirty throughout       9 ms median; one of nine at 198
```

On this card the first frame after a rest costs nothing beyond the stream's 10 ms, and the
clock at the flip, 180 to 390 MHz after every long pause, made no difference to it. What the
card has instead is a second mode near 200 ms. It is a fixed delay that a faster heartbeat did
not shorten and `ready` did not remove, it appeared once even at 1.2 s pauses, and the
presenter's meter never saw it, reading 1 to 8 ms on those flips as on the others. It happens
after the present, in the compositor, the driver or the display path, and it grows more likely
the longer the whole machine has been quiet. So `ready` buys nothing on this card, and the
outlier is not the lens's to fix.

All of this is the presenter. The fast engine rests at fifteen repeats a second, for a reason of
its own, see The still screen and the settle.

### The frame rate limit

The presenter's `--max-fps N`, and `cap N` on its stdin, show at most N new pictures a second. A
picture that arrives before its turn waits for it, and a newer one arriving meanwhile replaces it,
so what is shown is the newest at its time. The turns keep a steady beat, each one a period after
the last, at least half a period after the picture before, and starting again from a picture that
came long after its turn. Counting each period from the end of the last present instead would add
the present's own time to every period. A repeated present runs the neural pass as a new one does,
so with a limit the heartbeat is never faster than the limit either.

The capture is asked for fewer frames too, through windows-capture's `minimum_update_interval`.
Windows rounds that interval up to whole refreshes. At 120 Hz, 11 ms gave 60 frames a second and
23 ms gave 40 frames a second. The presenter sets it half a refresh below the most whole
refreshes between frames that still deliver at least the limit, so 12 ms for 60 and 29 ms for 30
at 120 Hz, and leaves the capture alone where one refresh is already that, as for 60 on a 100 Hz
screen. A change of limit starts the capture again with the new interval.

Measured on an RTX 5090 at 120 Hz, one pass, over a white square moving across noise, by a test
that profiles the presenter at each limit, in a window for the first row. Each figure is the
median of three runs, apart from the column at 30, which is the mean of two. The delay is the
title bar's, or its range over the runs:

```
                                    no limit             60                   30
1400x1000                       118 fps 183 W 10 ms  61 fps 129 W 10-16 ms  30 fps  83 W 28-39 ms
6144x2526, Cost Scaler at 0.50   63 fps 327 W 19 ms  60 fps 323 W 21-24 ms  31 fps 202 W 28-42 ms
```

The column at 30 is from the two runs with the interval above. A first run that asked for 23 ms
got 40 frames a second from the capture and drew 85 W windowed and 202 W fullscreen. A picture
waits up to one period for its turn, which is the added delay.

Fullscreen at 0.50 with no limit the capture delivered 63 to 64 frames a second, held there by the
GPU at 99 percent, since with ReShade off it delivered 116 to 117 a second. The presenter's own copies
take their share there. At 6144x2526 the grab of the lens's region out of the captured frame measured
3.0 to 3.7 ms, the comparison 0.8 to 0.9 ms and the copy into the staging buffer 3 to 7 ms, the
last waiting on the GPU, with the presenter at 0.7 to 1.1 of a core. Before any of that,
windows-capture copies and maps the whole monitor for every frame, whatever the lens's size, in
time these figures do not include. The fast engine keeps the frame on the GPU from the capture to
the screen and takes the presenter's place for a fullscreen lens. Its own limit works differently,
see The engine's frame rate limit.

## The fast engine

`lens-fast.exe` is the presenter of a fullscreen lens, a C++ program of the lens's own built from
`fast_engine`. It takes the presenter's command line and speaks its protocol on stdin and stdout,
so the lens drives either the same way, and `lens-fast.exe --help` prints both. Of its own it
reads `nr 1|0`, `reload`, `settle 1|0` and `quality N`, and prints `engine quality N work WxH`
and, as its last line when it fails, `engine failed REASON`. The lens finds its window by its
process id and its class, `NeuralLensFast`.

No ReShade and no add-on run in it. It loads the stack's `nvngx_dlssnr.dll`, which is the Cost
Scaler's proxy, by its full path, and through it NVIDIA's model, and creates and evaluates NGX
feature 18 on its own D3D12 device with a parameter object of its own. The call order and the
parameter names follow openNR's native adapter, whose MIT notice `nr.cpp` carries. No NVIDIA
header is included, and the runtime's functions are found with `GetProcAddress`. The six settings
it gives the model, the style, the intensity, local tone, local structure, skin structure and the
auto mask, are read from the add-on's section of `ReShade.ini` at the start and again on `reload`.
The model's motion vector and depth inputs are 1x1 textures of zeros. With full-size textures of
zeros the output was the same byte for byte, on 21 MiB more video memory.

One frame goes through five stages:

```
capture     the region under the lens is copied on the card, in the capture's own callback,
            into a texture that the D3D12 device shares
ingest      one compute pass downscales the region to the work size by area and compares
            every texel with the frame before
network     the model runs on the downscaled copy, once for each pass
composite   one triangle drawn straight into the back buffer:
            original + (bilinear(network output) - bilinear(network input))
present     a flip model swapchain in a click-through window that is out of the capture
```

A frame equal to the last ends at the comparison, and nothing is drawn for it. The composite adds
only what the network changed, scaled up, to the original at full size, so the original's own
detail is kept at any work size. It is the same kind of residual blend as the Matched Residual of
xenmods' DLSSNR-Cost-Scaler (MIT), which the lens has used since 0.2.0. The window stays hidden
until the first picture has been presented, 0.63 to 0.72 s after the process starts, and the
engine is gone 0.09 to 0.12 s after the lens closes it.

What the stages cost without a window, on an RTX 5090 with a 6144x2526 picture and a work size of
2560x1053. These are GPU times from timestamp queries, the medians of 300 frames after the first 120:

```
ingest, the downscale and the comparison     0.09 ms
network, one pass                            3.35 ms
composite                                    0.10 ms
the whole frame                              3.54 ms
a frame equal to the last                    0.07 ms
```

Two passes took 6.69 ms in the network. Creating the network took 255 to 270 ms in the self
tests, and 393 ms for two passes. The engine held 910 MiB of video memory. With the network's
strength at 0 the engine leaves the network out. A run through it at that strength gave the
original byte for byte in 3.34 ms. On screen at the same picture size, the capture's callback
took 0.08 to 0.13 ms of processor time a frame and the present call 0.13 to 0.18 ms, and the
engine used 0.06 to 0.11 of a core.

The downscale's weights and the composite's sample positions are computed on the CPU and handed
to the shaders. A division in the shader came out one unit in the last place off the rounded
quotient, which put 1500 of 8 million input bytes one level off in the downscale and 28 of 24.9
million output bytes in the composite. With the tables from the CPU the engine's pictures equal a
numpy replay of the same arithmetic byte for byte, at 16 picture sizes.

**The proxy's ini.** The proxy reads `nvngx_dlssnr.ini` beside the program that loaded it first
and beside its own DLL second. With the stack's ini at `EnableProxy = 1` and a scale of 0.50, and
an ini beside the engine at `EnableProxy = 0`, the proxy logged itself as off, the network took
3.370 ms and the composite equalled the reference byte for byte. With the two inis swapped the
proxy scaled, and the network took 2.373 ms. So the engine writes an ini of its own beside its
exe, with the proxy and its hotkeys off, and the lens leaves the stack's ini as it is while the
fast engine runs.

### The engine's capture

The engine captures the monitor with Windows.Graphics.Capture through C++/WinRT, with the cursor
and the border switched off on the session. Access is not asked for first, since that call can
put a prompt on screen.

- **A session left at its default interval delivers 60 frames a second.** On Windows 11 build
  26200, over a source that changed at every refresh of a 120 Hz display, a session whose
  `MinUpdateInterval` was not set delivered 59 to 60 frames a second, and with 1 ms it delivered
  117.7 a second. So the engine asks for 1 ms when there is no frame rate limit. The property came with
  Windows 11 24H2.
- **The engine's own presents bring no frame while they are shown directly.** The presenter's
  presents are compositions and come back from the capture as frames equal to the last. The
  engine's are shown without the compositor most of the time, see The present path and the
  delay, and then nothing comes back, so over a still screen no frame arrives at all. A capture
  that has delivered nothing for 3 s is therefore started again, and it is reported lost only
  when the new session brings no frame within 0.9 s. A new session's first frame came 8 to 17 ms
  after its start. That check cost 2.5 W over a still screen, 45.4 W with it against 42.9 W.
- **The copy, and the wait for it.** In the callback the capture's D3D11 device copies the region
  under the lens, GPU to GPU, into one of four textures that both devices share through NT
  handles, and signals a fence that both share. The copy was not yet done when the engine took
  the frame for 33 of 34 and 16 of 17 frames, so the D3D12 queue waits on the fence before it
  reads. The first frame read back through D3D12 equalled GDI's copy of the same screen rectangle
  exactly, a mean difference of 0.000 of 255. A crop at 6144x2526 is 62 MB, and the two devices
  with the four textures hold 287 MiB of video memory.
- **The capture item is kept across sessions.** Each `CreateForMonitor` left two handles in the
  process that releasing the item did not close, 83 handles over 40 restarts. With the item kept, a
  later start takes 5 to 7 ms, where it took about 40 ms with a new item each time.
- **A new interval is set on the running session.** `MinUpdateInterval` took a new value on a
  live session in 0.13 ms, and the first frame under a limit of 30 came 29.4 to 31.0 ms after
  the change. Starting the session again took 19.8 to 21.5 ms.

### The engine's frame rate limit

The limit is kept in the capture, where it acts at the moment a frame arrives. A frame is taken or
left out there and then, a frame left out is not copied, and none waits for a turn. The beat runs
on the frames' own timestamps, which lie on the display's refresh grid to 0.002 ms, so the same
frames are taken whatever else the computer is doing. A frame is taken when its timestamp has come
within a quarter of a refresh of the next turn, and the turn then moves on by exactly one period.
A frame that comes before its turn is kept back without a copy and handed on only when no newer
one follows, so the last frame before a stop is still shown. On screen, 8 of 8 stops each at
limits of 30, 60, 80 and none left the source's last picture with the engine.

On an RTX 5090 at 6144x2526 with a work size of 2560x1053, over the moving square, a second
monitor at 1920x1080 and 60 Hz connected. The meter is the present call against the frame's
timestamp, and the delay is measured up to the refresh that showed the picture:

```
limit   new a second   meter      delay     call to screen   power
none    115.8          -14.9 ms   -8.3 ms   6.6 ms           247 W
80       79.7          -14.9 ms   -8.3 ms   6.6 ms           191 W
60       60.0          -14.8 ms   -8.3 ms   6.5 ms           154 W
30       30.0          -14.5 ms   -8.3 ms   6.2 ms            97 W
```

So with that monitor the delay is the same at every limit. With the second monitor at 144 Hz a
limit of 60 read lower than none, see A second monitor changes the figures under Measurement
pitfalls. At a limit of 80, 80.0 frames a second were copied of
117.0 that arrived. A loop that held the newest frame until its turn came presented it later, by
4.5 ms at a limit of 80 and 9.7 ms at 60, and copied every arriving frame, 37 a second more at 80,
each of 62 MB. By a model the rule gives the limit exactly at 78 pairings of display rate and
limit, where the rule of the loop that held frames missed 22 of them and gave 48 frames a second
for a limit of 50 at 120 Hz. The moving square's source misses 1 to 7 refreshes in some seconds,
which is why a limit of 80 reads 79.2 to 79.8 a second in the tables below.

### The work size, and what the network costs

The network works on a copy of the picture at the work size. Its time on an RTX 5090, without a
window, at 120 evaluations to warm up and 300 timed, differed by at most 0.015 ms between four
pictures, and by less than 0.01 ms for one work size reached from different picture sizes:

```
work size    megapixels   network
1536x384     0.59         2.21 ms
1536x640     0.98         2.37 ms
1920x1080    2.07         2.97 ms
2560x896     2.29         3.03 ms
2560x1024    2.62         3.27 ms
2560x1440    3.69         3.94 ms
```

Over the 69 work sizes measured, from 768x384 to 2560x1440, a straight line of 1.88 ms plus
0.53 ms a megapixel is within 0.12 ms of every one. So most of a pass does not depend on the
size, and halving the work size saves far less than half the time.

Sizes on multiples of 128 texels are the cheap and the strong ones:

- One row or one column past a multiple of 128 cost 0.03 to 0.28 ms more than the multiple
  itself. At 2560x641, 2560x648, 2560x1153 and 1536x641 the network also changed the picture only
  0.62 to 0.64 times as much as at the multiple.
- 8 to 16 rows past a multiple cost 0.05 to 0.14 ms more and were often weaker, 0.75 to 0.89.
- Sixteen rows or columns below a multiple cost the same as the multiple.
- Weak bands found in sweeps at 6144x2526 are 2560 wide at 912 to 960 rows and at 1424 and 1440
  rows, 0.83 to 0.88, every odd multiple of 8 from 648 to 760 rows, 0.62 to 0.66, and a width of
  1280, about a tenth under its neighbours.
- 2560x1440, which a 3840x2160 picture fitted into 2560x1440 gives, is one of them. 2560x1408 is
  2.4 percent cheaper and changes the picture 1.08 times as much.
- At work sizes 1236 to 1240 wide with 768 or 512 rows the network changed the picture 0.53 and
  0.57 times as much as at the picture's own size, where 1232 and 1248 wide kept 0.92 to 0.99.
  Only that band was searched.

So the engine never takes a plain share of the picture as its work size.
`fast_engine\src\work_table.h` holds the measured sizes for 20 picture sizes, made from the
measurements by `fast_engine\tools\make_work_table.py`. For any other picture size a rule in
`common.cpp` gives them, on multiples of 128 wherever a side is resampled.
`lens-fast.exe --steps W H` prints the five sizes for a picture.

### The quality steps

A quality step is a work size. Measured without a window on the Blender picture at 6144x2526,
against the picture fitted into 2560x1440, which is 2560x1053. Kept is the size of the network's
change to the picture, and the detail is the energy of that change's second difference across
and down, each as a share of the reference's:

```
step              work size    network    kept   detail across   detail down
the reference     2560x1053    3.36 ms    1.00   1.00            1.00
4 Quality         2560x1024    3.27 ms    1.00   1.04            1.00
3 Balanced        2560x896     3.03 ms    1.00   0.99            0.86
2 Performance     2176x896     2.84 ms    0.97   0.85            0.82
1 Low power       2560x640     2.70 ms    0.95   0.95            0.64
0 Lowest power    1536x640     2.37 ms    0.84   0.48            0.55
```

At Balanced no loss was seen at the picture's own size or enlarged three times, on a page of
text, thin lines, small type, a table grid, an interface, the Blender picture, and three harder
pictures, the Blender picture at half size, a character tiled edge to edge and a code editor in a
light and a dark theme. Black strokes came out 1.6 levels lighter than the reference's and 1 px
rules 3 levels darker, which is nearer the original, and the pixels beside a rule moved by 0.05
levels. Three evaluations into a picture, as in motion, the result was the same. At Lowest power
the light title bars of the interface picture were visibly lighter. The same five sizes serve
6144x2560, 5120x2160, 3840x1600 and 3440x1440, where Balanced kept 1.00 to 1.02.

Three other picture sizes, each against its own picture fitted into 2560x1440. A 3840x2160
picture is downscaled at every step. A picture that fits 2560x1440 runs at its own size at
Quality, so every step below that is a resampling:

```
picture     step             work size    network    kept   detail down
3840x2160   4 Quality        2560x1408    3.84 ms    1.08   1.07
            3 Balanced       2560x1152    3.42 ms    1.10   0.92
            2 Performance    2176x1152    3.17 ms    1.05   0.83
            1 Low power      2560x896     3.03 ms    1.10   0.72
            0 Lowest power   1536x896     2.59 ms    0.92   0.49
2560x1440   4 Quality        2560x1440    3.94 ms    1.00   1.00
            3 Balanced       2560x1152    3.42 ms    1.05   0.43
            2 Performance    2560x1024    3.27 ms    1.05   0.35
            1 Low power      2560x896     3.03 ms    1.06   0.31
            0 Lowest power   1536x896     2.59 ms    0.95   0.19
1920x1080   4 Quality        1920x1080    2.97 ms    1.00   1.00
            3 Balanced       1920x896     2.74 ms    1.01   0.38
            2 Performance    1920x768     2.61 ms    0.99   0.30
            1 Low power      1920x640     2.52 ms    1.03   0.26
            0 Lowest power   1152x640     2.31 ms    0.91   0.17
```

On a picture that fits 2560x1440 the first step down keeps the size of the network's change and
takes away about 60 percent of the one texel texture it adds down the picture. That showed
faintly as smoother grain on one picture at three times its size, and not at the picture's own
size. Even four rows of resampling, 1600x900 to 1600x896, took half of it. So the default follows
the picture's size. It is Balanced for a picture larger than 2560x1440 in width or in height,
where every step is a downscale and Balanced showed no loss, and Quality for a picture within it,
where Quality is the picture's own size. The engine applies the rule when it is given no
`--quality`, and names the step at the end of its ready line.

`quality N` changes the step while the engine runs. The network for the new size is made beside
the one in use, on a second thread, in 116 to 198 ms, while the loop goes on drawing new pictures
with the network's last change. On screen the first picture at the new size came 132 to 158 ms
after the command and no picture stood longer than 24.8 ms. Made on the loop's own thread, the
new network held the picture for 112 to 157 ms. The stack gives a replaced network up only after
the new one has run between 33 and 64 times, and its video memory comes back about 10 s later,
inside the next run. So a picture at rest after a switch goes through the network 64 times, and
once more 14 s later, unless the settle is switched off. Over 24 switches without a window the
engine went from 847 MiB to 1371 MiB at the most and was back at 847 MiB 10.2 s after the last.

### Frames a second and power at each step

On an RTX 5090, driver 617.14, with a 6144x2560 display at 120 Hz and a second monitor at
1920x1080 and 60 Hz connected. The engine ran by itself at 6144x2526 with one pass. Power is the
card's whole draw, the median of 30 samples a second apart, and the network's time is from the
engine's own timestamp queries.

Over a white square that moves across noise 120 times a second, where the source alone drew 51.0
to 52.4 W:

```
                             no limit                         limit 80
step, work size              new a second  power   network    new a second  power   network
4 Quality, 2560x1024         116.1         240 W   3.29 ms    79.2          185 W   3.29 ms
3 Balanced, 2560x896         116.2         220 W   3.04 ms    79.8          169 W   3.04 ms
2 Performance, 2176x896      116.4         202 W   2.85 ms    79.5          154 W   2.85 ms
1 Low power, 2560x640        115.9         186 W   2.71 ms    79.6          145 W   2.71 ms
0 Lowest power, 1536x640     116.8         154 W   2.37 ms    79.6          124 W   2.38 ms
2560x1053, no step           115.9         243 W   3.38 ms    79.3          189 W   3.38 ms
```

The other stages were the same in every row. On the card, ingest took 0.10 to 0.13 ms, and
0.26 ms at 1536x640, and the composite 0.10 to 0.11 ms. The capture's callback took 0.08 to
0.10 ms and the present call 0.13 to 0.15 ms of processor time. The card read 48, 45, 43, 42 and
39 percent busy with no limit.

Over the whole picture of noise scrolling 8 pixels a step, 120 steps a second, so that every pixel
changes at every refresh, where the source alone drew 65.3 to 68.5 W:

```
                             no limit                         limit 80
step, work size              new a second  power   network    new a second  power   network
3 Balanced, 2560x896         120.2         225 W   3.54 ms    80.0          178 W   3.47 ms
2 Performance, 2176x896      119.8         209 W   3.33 ms    80.0          167 W   3.55 ms
2560x1053, no step           120.0         254 W   3.94 ms    80.0          198 W   4.09 ms
```

Four runs of one row read 252.7 to 257.5 W, so a row is good to about 2.5 W. The square's table
taken earlier the same afternoon, with an older build of the engine, read 1 to 5 W more in every
row, in the same order.

In the lens, fullscreen at 6144x2558 over the moving square, six whole runs of the fast engine at
Balanced gave 114.4 to 116.7 new pictures a second on 216 to 220 W, the medians 115 a second and 218 W,
and with the limit at 60 it drew 130 to 132 W, the median 131 W. At Performance it showed 114.5 to
117.5 a second on 202 to 206 W, and with two passes at Balanced 103 to 110 a second on 315 to
326 W. The ReShade engine, with the Cost Scaler at 0.50, showed 60.9 to 62.4 a second on 326 to
332 W over eleven runs, the medians 62 a second and 330 W.

### The present path and the delay

The engine's window is layered, click-through, topmost and out of the capture, and takes a flip
model swapchain, flip discard with two buffers, from `CreateSwapChainForHwnd`. A swapchain made
for DirectComposition worked as well and cost the same power for each picture, 240 W at 112.3 new
pictures a second against 245 W at 115.3 a second, with one monitor. The engine makes that one when
`CreateSwapChainForHwnd` refuses, and `--present dcomp` asks for it outright.

Measured at 6144x2526 on the 120 Hz display with a second monitor at 1920x1080 and 60 Hz
connected, from a record of every present, 4859 pictures with no limit and 3341 at a limit of 80.
A frame's timestamp is from the capture, the moment a present is shown from DXGI's frame
statistics, and what the compositor did from its own statistics:

- A frame's timestamp lies on the display's refresh grid to 0.002 ms and equals the target of a
  compositor frame. The compositor begins that frame 16.6 ms, two refreshes, before its target,
  and the capture delivers it 15.97 ms before its timestamp.
- The present call comes 0.92 ms after the frame arrived, and the picture is on screen 6.70 ms
  after the call, 5.6 to 6.9 ms.
- The picture is on screen 8.3 ms before the frame's own timestamp. With no limit 4711 pictures
  were shown one refresh before the frame's own, 142 at it, 3 one after and 3 two after. At a
  limit of 80 it was 3251, 60, 29 and 1, the 29 being frames the limit had kept back.
- The compositor itself presented to that display in 8 of 3188 and 14 of 5054 of its frames, so
  the engine's swapchain is shown directly and not composed.

So with the second monitor at 60 Hz the compositor's own pictures take two refreshes to reach the
screen and the engine's take one, and the lens's picture is on screen one refresh before the
desktop frame it was made from. With the second monitor at 144 Hz the delay read about 8.5 ms,
see A second monitor changes the figures under Measurement pitfalls. The meter, the present call
against the timestamp, read -15.0 ms in these runs and -6.6 ms for the same picture with one
monitor, where the compositor works one refresh ahead and not two. No constant added to the meter
gives the delay in both, so the engine reports the delay itself, as `delay=` on its stats line,
and the lens shows that, never below zero. It reads `nan` in a second in which no present's
refresh was learned, and the lens keeps its last reading.

Over a source that changes at every refresh, pictures can come to be shown a refresh late for
seconds on end. The swapchain has two buffers. After a present the next back buffer is the one on
screen until the next refresh, so a render into it waits for that refresh, and the next frame
waits behind that render. Once one picture is finished a refresh late, every picture after it is
late too, for as long as a frame comes at every refresh, and one refresh without a render ends
it. Over the whole picture of noise scrolling at 120 steps a second with no limit, a loop with
no rule for this showed the pictures at their frames' own refresh in most seconds, with single
seconds at -8.3 ms and stretches of 4 to 40 s at 8.3 ms. So when the pictures of such a run have
been late for a quarter of a second, the loop leaves one frame out. When they are as late again
within 2 s of a frame left out, the wait before the next one doubles, up to 64 s. Over the
scrolling picture for 45 s, with the loop made to stand still for 9 ms every 7 s so that such
runs begin, 2311 of 5384 pictures were shown late without the rule and 166 of 5384 with it, for
5 frames left out. With the rule and no stalls, all 3601 pictures of 30 s were shown at their
frames' own refresh. At a limit of 80 the delay was -8.3 ms throughout.

### The still screen and the settle

A present of the engine reaches the screen in one of two ways. Shown directly, it is on screen
4.7 ms after the call and no frame comes back from the capture. Composed, it is on screen 13 to
22 ms after the call and comes back from the capture as a frame equal to the last, 1 to 10 ms
after the call. Which it is follows from the presents before it:

- After two seconds with no present, every present was composed, in 20 of 20 trials.
- Presents at the display's rate bring the swapchain onto the direct path. The first 74 to 77
  were composed and the ones after them direct, in 20 of 20 trials.
- Once there, 12 to 30 presents a second held it. With 8 or 4 a second, or none, the next
  present was composed again.
- A window just made was composed in 4 of 5 starts of one series and direct in 4 of 4 of another.

So over a picture that does not change the engine repeats its picture 15 times a second, or on
every eighth refresh of a display faster than 120 Hz, and 30 times a second with `ready`. When
the repeats come back from the capture it repeats at the display's rate until they stop coming
back, which took 0.25 to 1.8 s. After 4 s of that it gives up, makes no repeats at all, since
composed ones cost more than none, and tries again 5, 10, 20 and up to 300 s later. Under a
frame rate limit of 15 a second or fewer it makes no repeats either, unless `ready` asks for
them. Over a still picture at 6144x2526, with a second monitor connected, the card drew:

```
repeats a second     path       power     first new picture after 12 s of rest
none                 composed   44.7 W    one refresh after its frame's own
4                    composed   46.3 W    one refresh after its frame's own
15                   direct     45.3 W    one refresh before its frame's own, or at it
30                   direct     47.4 W    one refresh before its frame's own, or at it
15                   composed   50.0 W    one refresh after its frame's own
```

The first new picture after a rest is on screen 8 to 17 ms earlier on the direct path. Other
figures over a still screen at that size:

- The engine's window, drawing nothing, holds the card's memory clock at 7001 MHz. The card drew
  42.1 W with no network loaded and 44.6 W with the engine paused, against 29.0 to 31.5 W for the
  desktop and the source alone at 810 MHz.
- A caret that blinks every 530 ms, 1.9 new pictures a second, drew 47.1 to 49.2 W against 44.4
  to 46.4 W for the still picture.
- A pointer moved over the still screen makes the compositor compose, and 115 to 120 frames a
  second arrive that are equal to the last. Each is copied and compared, and the card drew 65.8 W
  against 44.4 W at rest.

**The settle.** The network carries its own history from one run to the next, so its first run on
a picture that has just stopped moving is not what it makes of that picture after a few runs. A
picture that has come to rest after a large change therefore goes through the network up to four
more times. Without a window, after ten frames that scrolled 8 texels each, the first still
picture was 0.447 of 255 from the settled one on average, and 0.339, 0.263, 0.215 and 0.178 after
one to four more runs. On screen, after the whole picture had scrolled for 5 s and stopped, the
four runs moved the picture by 1.42 of 255 at a work size of 2560x1053, and by 1.74 to 1.95 over
six measurements at 2560x896, and two shots a second apart then differed by 0.0000. At rest
means no new picture for 150 ms, or for a period and a half of a frame rate limit, so it never
runs while the picture changes. It runs only when 8 or more of the picture's 256 tiles changed
since the last rest, so a blinking caret, which changes one tile, never starts it. A picture the
network starts without its history, after a pause or a jump of the crop by more than a quarter
of the lens, settles once at rest however little changed. `settle 0` and `--no-settle` switch it
off.

### Beside another program that uses the card

Measured on an RTX 5090 with one monitor at 119 Hz, the engine fullscreen at 6144x2526 with a work
size of 2560x1053 over the moving square. The other program was one process with no window that
blurs a 4K picture through Vulkan in ffmpeg. Beside the moving source alone it ran at 49.5 to
49.9 frames a second with the card 87 to 89 percent busy. Each row is a stretch of 30 s between
two stretches of 20 s with that program alone:

```
engine         the other program    it lost            engine, new a second   card
no limit       30.8 a second        18.9, 38 percent   90.2                   410 W, 97 percent
limit 60       37.3 a second        12.4, 25 percent   60.0                   403 W, 94 percent
limit 30       44.3 a second         5.4, 11 percent   30.0                   402 W, 92 percent
network off    44.9 a second         4.8, 10 percent   88.5                   376 W, 91 percent
two passes     28.5 a second        20.5, 42 percent   53.9                   419 W, 98 percent
```

A program that wants the whole card loses about the engine's share of it, and the frame rate
limit is what gives it back. With the network off each of the engine's frames still cost the
other program about 1.1 ms of its time. The engine alone drew 254 W at 115.2 new pictures a
second, and its network stage read 5.46 ms beside the other program where it reads 3.41 ms alone.

A program held to a rate that leaves room lost nothing. Held at 25 frames a second, with the card
42 percent busy, and at 30, with 55 percent, it kept 25.0 and 30.0 frames a second beside the
engine at no limit. Held at 40 it ran at 30.2 to 30.9 frames a second.

The engine's own figures show that the card is shared, and they cannot tell a program that just
fits from one that is losing frames. Held at 30, the other program had about 3 percent to spare
and lost nothing, and the network stage read 5.39 ms, the engine dropped 16.2 frames a second and
the card read 96 percent, against 5.46 ms, 16.0 frames a second and 97 percent beside the one that
lost 38 percent. With more room they differ. Held at 25, the network stage read 4.97 ms, the engine
dropped 8.5 frames a second and the card read 84 to 88 percent. A change of the limit tells the
two apart. With the engine switched between no limit and a limit of 30 every 6 s, the program
that wanted the whole card rose from 30.7 to 44.7 frames a second within 2 s, and the card's
total fell only from 96.5 to 91.8 percent and by 6 W. With the program held at 25 or at 30 its
rate did not move, the card's total fell from 85.7 to 59.0 and from 94.9 to 65.0 percent, and
the power by 98 W and 93 W.

A smaller work size gave less back than a limit. At no limit, a work size of 1843x758 left the
other program 33.2 frames a second where 2560x1053 left it 30.8 a second, while the engine showed
94 new pictures a second in place of 90 a second. At a limit of 60, with a second monitor
connected by then, the other program lost 9.4 frames a second beside a work size of 1843x758
against 12.0 a second beside 2560x1053.

### A game in front that keeps the card busy

Measured on an RTX 5090, driver 617.14, Windows 11 build 26200 with hardware-accelerated GPU
scheduling on, and one monitor at 6144x2560 and 120 Hz. A demanding game ran in borderless
fullscreen under a fullscreen lens on the fast engine, 6144x2558 at the Quality step, a work size
of 2560x1024, with one pass. In front means that the game's window had the foreground. Each row
gives the range of the lens's 10 s summaries in that test, see The lens's log, their new pictures
a second, which over the game are the game's own frames, and their median delay. The first six
rows ran on the engine as installed, and the last two on a build of it with the profile and
`LENS_FAST_SPLIT_WAIT=1`, see Switches for tests:

```
the game                                            new a second   delay
in front, G-SYNC on, Neural Rendering on            15.8 to 20.0   38.5 to 48.1 ms
in front, G-SYNC on, Neural Rendering off           19.5 to 20.7   43.5 to 43.8 ms
in front, G-SYNC off, Neural Rendering on           18.3 to 21.1   58.3 ms
in front, G-SYNC off, Neural Rendering off          17.9 to 23.5   50.0 ms
in view, another window in front                    about 19       16.7 ms
in front, the driver's frame rate limit at 17 fps   14.9 to 18.1   50.0 to 58.3 ms
in front, its own limit at 30 fps with room         30.0           0.0 to 8.3 ms
the same, Neural Rendering off                      30.0           0.0 ms
```

So the network's own work is a small part of the delay, and G-SYNC is not its cause. Over 88
summaries with the game in front on the engine as installed and Neural Rendering on, the median
was 58.3 ms, 78 of them lay between 38.5 and 58.3 ms, eight above, up to 100.0 ms, and two below.
For the runs with the game's own limit its settings were lowered so that it could hold 30 frames
a second. In the 13 minutes after those runs, on the same build, the medians with the game in
front and Neural Rendering on read 8.3 to 58.3 ms at 17.5 to 38.3 new pictures a second, and
33.3 to 41.7 ms for five minutes in which the game ran at 24.5 to 29.8 frames a second. So the
frame rate alone does not tell how far behind the lens falls.

Where the time goes, from the engine's stats lines with `LENS_PRESENTER_PROFILE=1` and
`LENS_FAST_STATS_NOTE=1`, see Switches for tests. Each figure is the median of the per second
figures, then the tenth to the ninetieth percentile, with Neural Rendering on. The first column
pools three runs, one without priority switches, one with the queue and the class at high, and
one with the class at high and the lens run as administrator, whose medians differed by 3.1 ms at
most in `iwall` and not at all in the delay. The second ran with `LENS_FAST_SPLIT_WAIT=1`:

```
                      in front, card busy         in front, its own limit at 30 fps with room
seconds               1150                        56
delay                 58.3 ms, 50.0 to 100.0      8.3 ms, 0.0 to 8.3
meter                 46.5 ms, 39.9 to 49.8       -1.6 ms, -4.2 to 0.3
wake                   5.9 ms, 0.2 to 14.9        0.19 ms, 0.17 to 0.36
iwall                 35.1 ms, 22.8 to 43.0       0.44 ms, 0.42 to 2.09
flip                  10.2 ms, 7.5 to 53.5         8.0 ms, 5.8 to 10.0
ahead                  3.3 ms, 2.0 to 4.9          3.0 ms, 1.1 to 5.5
ingest on the card    0.09 ms                     0.09 ms
network on the card    6.3 ms, 3.4 to 12.5        3.30 ms, 3.28 to 3.32
```

With the card busy the frame arrived 3.3 ms before its refresh and the ingest's work on the card
took 0.09 ms, yet the ingest call took 35.1 ms by the wall clock, waiting for the card, and the
present call came 46.5 ms after the frame's refresh. The network's span between its timestamps
stretched from 3.3 ms to 6.3 ms, and up to 27.8 ms. With the game held by its own limit with room
to spare every wait went.

`LENS_FAST_SPLIT_WAIT=1` takes the wait for the capture's copy apart from the ingest's own turn.
Over the first 171 s of that run with the game in front, at 28 new pictures a second, the copy's
wait read 6.4 ms, 3.2 to 15.2 ms, the ingest's own turn after it 23.4 ms, 13.9 to 30.5 ms, and
the flip, which takes in the render's turn on the card, 40.6 ms, 11.9 to 47.5 ms. The delay read
75.0 ms, 50.0 to 91.7 ms, in that run. So each job a new picture gives the card waits for a gap in
the game's work, and there are three: the capture's copy on the capture's D3D11 device, the
ingest, and the network with the composite before the flip.

The likely reading is in the card's scheduler. With hardware-accelerated GPU scheduling, Windows
puts the process whose window has the foreground in a band of its own, above every priority class
but realtime, so the game's work goes first whatever the engine asks for. Nothing the engine asked
for below realtime changed the delay. Not run as administrator, the queue and the class at high
were accepted, the class with status 0, and run as administrator the class read back as 4, high.
The engine's process at high priority on the processor changed nothing either. This fits the
reading, and it was not traced in the scheduler itself. The driver's frame rate limit at 17 fps
changed nothing, where the game's own limit with room to spare took every wait away. The likely
reading there is that the driver holds the game back before it presents a frame, so the pause
comes before the frame the lens captures and the lens's jobs meet the game's next frame, while
the game's own limit pauses after the frame it has shown. The realtime class, the only one above
that band, and a realtime queue, both of which need the right to raise priorities, were not
tried, and nor was hardware-accelerated GPU scheduling switched off.

A program with no window stands in for this only in part, since it is never in front. The engine
by itself, fullscreen at the Quality step with one pass over a picture changing 40 times a
second, read 0.0 to 8.3 ms alone. Beside one process with no window that blurs a 4K picture
through Vulkan in ffmpeg, the card at 90 percent, it read 16.7 ms with Neural Rendering on and
8.3 ms with it off. Beside four, the card at 100 percent, it read 58.3 ms and 41.7 ms, and showed
22 to 26 of the 40 new pictures a second. The network's span read 3.8 to 4.1 ms alone, 5.9 to
6.2 ms beside one and 13.4 to 14.0 ms beside four. The queue and the class at high, not run as
administrator, changed nothing, apart from one 25 s stretch beside four processes that read
50.0 ms in place of 58.3 ms.

**The warning.** A fullscreen lens says so when it falls behind like this. Each regular 10 s
summary while a fullscreen lens on the fast engine is in view hands its median delay to a check,
with the time its seconds began:

- A summary counts as behind when its median is at least three refreshes of the monitor the
  engine's window is on, less a tenth of a refresh. The line, three refreshes, is 3000 ms divided
  by that monitor's refresh rate as Windows has it at that moment, rounded to tenths of a ms as
  the engine gives its delay. That is 25.0 ms at 120 Hz, where a median of 24.2 ms counts and one
  of 24.1 ms does not, 20.8 ms at 144 Hz and 50.0 ms at 60 Hz. Where the rate cannot be read the
  line is 25.0 ms, and a median of 24.2 ms or more counts. The tenth of a refresh is there because
  Windows gives a rate such as 119.88 Hz as 119 Hz, which puts the line at 25.2 ms where the
  engine reads three refreshes as 25.0 ms.
- It counts only while one window has been in front for all the seconds the summary covers, that
  window is neither one of the lens's own nor the desktop or the taskbar, and no program is in
  exclusive fullscreen on the lens's monitor, where the lens draws nothing. The window in front is
  the one the 200 ms timer looks at, see The foreground in the log under Nothing of the lens goes
  into another program, and the check asks `GetForegroundWindow` and `GetClassNameW` once more as
  the summary is written. A look that found another window in front, or none, after the summary's
  seconds began starts the count again, and so does a window in front at the summary that the
  last look did not see. The desktop and the taskbar are told by their classes, `Progman`,
  `WorkerW`, `Shell_TrayWnd` and `Shell_SecondaryTrayWnd`. The first window a look finds as the
  lens goes fullscreen or comes back from minimised is no change, since the summaries start their
  seconds afresh then.
- A summary more than a tenth of a refresh below the line, one with no delay, one for which any of
  the above does not hold, and
  the lens out of fullscreen, minimised or on the ReShade engine each start the count again. A
  summary written at once before a change of state, see The lens's log, neither counts nor starts
  it again.
- At two in a row the log gets a line, and the notice shows the warning for 12 s in the warning
  colour, as a line of its own after those for a program in exclusive fullscreen and for a
  sentence the lens keeps up to be read, such as the fast engine giving way to the ReShade engine,
  and before the latest message. It says about how far behind the program in front the lens is,
  in whole ms, that the program most likely keeps the card fully busy, that a frame rate limit in
  that program, a little below the rate it reaches, lets the lens keep up, and that the warning
  can be switched off in Settings, Fullscreen. With the warning switched off only the log line
  comes.
- The program in front is only the most likely cause. A program with no window that keeps the
  card fully busy holds the lens back as well, as measured above, and the warning then still puts
  the delay down to the program in front.
- Then neither comes again for 600 s, whether the warning was shown or only logged. The count
  goes on, so a lens still behind after that says so again at the next summary. Switching the
  warning on in Settings ends the 600 s, so it comes at the next two summaries behind in a row.
- The switch is Warn when the lens falls behind, on the Fullscreen page of Settings, on to begin
  with. Off, the ini holds `fs_behind_warn = 0`, and on, the key is left out. Switching it off in
  Settings takes a warning that is up off the notice at once, and Save names
  `fs_behind_warn 0` or `fs_behind_warn 1` in its one line, see The lens's log.

### How the lens chooses the engine and falls back

A start gets the fast engine when the lens is fullscreen, `fullscreen_engine` is not `stack`,
`lens-fast.exe` is there, the Cost Scaler's files are in the stack, and the engine has not failed
in this run of the lens. The exe is looked for in the stack's `fast` folder, then, installed, in
the `fast` folder beside the lens's own exe, and from source in `fast_engine\bin`. Everything
else gets the presenter.

- **Neural Rendering on and off.** No add-on is there to read F6, so under the fast engine F6
  does nothing. The NR key, F9 to begin with, the menu and the NR settings panel switch it. The
  lens sends `nr 0` or `nr 1` and writes `NeuralUplift` into ReShade.ini, where the add-on keeps
  it, see Global hotkeys. An engine that starts with Neural Rendering off is told before its
  first picture. With it off the engine's shot equalled the capture exactly.
- **An engine that fails** prints `engine failed` with its reason and leaves. The lens then
  starts the presenter in its place and does not try the fast engine again until it is started
  again. Measured, with the engine ended while fullscreen the presenter's picture was up 2.7 s
  later. With an engine that could not start, the failure came 0.8 s after the click and the
  presenter's picture 1.8 to 2.0 s after it. A lens that is minimised when the engine ends is
  left as it is, and gets the presenter 1.1 to 1.2 s after it is restored.
- **An engine that gets no picture has not failed.** One that says its capture is lost before
  it has shown a window, or fails at its capture stage, is replaced by the presenter as a
  stand-in. When the stand-in has frames the lens starts the fast engine again, and while the
  desktop is not the user's, as under the lock screen, it starts nothing. Only a fast engine
  that again gets no picture where the stand-in just had them is ruled out. This was proven with
  a stand-in for the engine and one for the desktop test, not with a locked screen.
- **The split** sets a window region on the engine's window, as on the presenter's, and a flip
  model swapchain is clipped by it on both ways of making the swapchain.
- **The watchdog.** The engine's window is topmost and click-through over the whole screen, so
  a loop that hangs would leave its last picture over a desktop that goes on working unseen. A
  second thread ends the process when the loop has not turned for 5 s, or the start-up for 30 s.

### Switches for tests

The engine reads these from its environment, and the lens starts it with its own, so a lens
started with one set hands it on. None is set in use. The top of `fast_engine\src\main.cpp`
lists them with the loop's own tests, such as `LENS_FAST_NO_NETWORK`, `LENS_FAST_HEARTBEAT` and
`LENS_FAST_STALL`. These are the ones for finding where a picture's time goes and what changes
it:

- `LENS_PRESENTER_PROFILE=1` adds the profile to each stats line. `meter` and `delay` are as on
  the plain line, the present call and the refresh that showed the picture, each against the
  frame's timestamp. `flip` runs from the present call to that refresh, and `ahead` is how far the
  timestamp lay ahead of the frame's arrival. `ingest`, `nr` and `composite` are the stages' times
  on the card from timestamp queries, and `nr`, the network's span between its two timestamps,
  stretches while another program has the card. `wake` runs from a frame's arrival to the start of
  its ingest, `iwall` is the ingest call by the wall clock, its waits for the card included, and
  `cwait` is the part of that spent waiting on the CPU for the capture's copy, 0 unless
  `LENS_FAST_SPLIT_WAIT` is set. `meter`, `delay`, `flip` and `ahead` are medians over the second,
  and the other times means.
- `LENS_FAST_STATS_NOTE=1` writes each stats line to stderr as well, as a note with its time, so
  `presenter-stderr.log` keeps the profile's figures, which the lens does not log.
- `LENS_FAST_TRACE=FILE`, with the profile on, writes every present, every answer of the
  display's statistics and every compositor frame to that file as a line of text.
- `LENS_FAST_SPLIT_WAIT=1` has the ingest wait on the CPU for the capture's copy first, before
  the queue's own turn, where otherwise only the queue waits for it, on the fence the two devices
  share. The profile's `cwait` then gives the copy's wait apart. It gives up the overlap of the
  two waits.
- `LENS_FAST_QUEUE_PRIORITY=high` asks for the engine's D3D12 queue at high priority, and
  `realtime` for one at global realtime priority. A refusal falls back to a normal queue, and a
  note says which the engine has.
- `LENS_FAST_GPU_CLASS=above`, `high` or `realtime` sets the class of the engine's own process
  with the card's scheduler through gdi32's `D3DKMTSetProcessSchedulingPriorityClass`, and reads
  it back with `D3DKMTGetProcessSchedulingPriorityClass`, since a call that succeeds may still
  leave the class where it was. A note gives both, the class as 2 for normal, 3 above, 4 high and
  5 realtime. No other process is named.
- Either priority switch first switches on `SE_INC_BASE_PRIORITY_NAME`, the right to raise
  priorities, in the engine's own token. A process run as administrator holds that right
  switched off, and others do not hold it. Without it the scheduler keeps the classes and queues
  above high for the system. The class's note says whether the engine had it.

With both priority switches at high the self test's pictures were the same bit for bit. What
they changed in use is under A game in front that keeps the card busy.

### What is not measured

- **Displays at 60 Hz and at 240 Hz.** The repeats and the burst count refreshes there by rule,
  not by measurement.
- **The power at each step with one monitor.** The steps were measured with a second monitor
  connected. With one monitor, over a picture changing at every refresh, the delay read 0.0 ms in
  10 of 12 summaries and 8.3 and 12.5 ms in the other two, see the on-screen readout under
  Fullscreen in Gotchas.
- **HDR.** The engine was not run with HDR on. It captures 8-bit frames, which Windows clips at
  80 nits on a monitor with HDR on, see HDR, and presents an 8-bit swapchain.
- **A game under the lens, beyond its delay.** One demanding game was measured for the delay and
  for where a picture's time goes, see A game in front that keeps the card busy. The power, the
  steps and the picture were measured over a moving square, a scrolling picture and stills, and
  the test beside another program used one that has no window.
- **Motion at the steps.** The pictures the steps were judged on were stills, including stills
  three evaluations into a picture.
- **The steps on screen at other sizes.** The on-screen figures are all at 6144x2526 and
  6144x2558. The other picture sizes ran without a window.
- **Other cards, and other Windows versions.** Everything is from one RTX 5090 on Windows 11
  build 26200 with one build of the runtime, and the weak sizes may differ elsewhere.
- **A locked screen, a sleeping display and a monitor unplugged** under a fullscreen lens. The
  lens's handling of them was proven with stand-ins.
- **The screen itself.** The engine's window is out of every capture, so its picture was read
  back from the engine's own swapchain, and from a window that was not excluded.

## Global hotkeys

RegisterHotKey delivers WM_HOTKEY to the registering thread's queue, and Tk's loop never
hands that message out, so the combinations are registered on a thread of the lens's own
with a message queue, which waits on MsgWaitForMultipleObjectsEx and drains with
PeekMessage. The actions go through a queue the lens reads on a 50 ms timer, so they run on
the Tk thread. A registered combination is taken from every other program, which is why none
is set by default apart from the four below, and a combination another program already holds
fails to register and is named as such in Settings. Home, F5 and F6 alone are refused because
ReShade reads Home and F5 from the presenter's own messages and the add-on reads F6 with
GetAsyncKeyState, and a hotkey on them would take the key before either saw it. Injected input
fires them, which is how a test checks them with the desktop holding the keyboard.

Each combination belongs to one action. Settings refuses a combination that another of its rows
holds and names that row. A key from `HOTKEY_DEFAULTS` goes to its action only where no other
action has the same combination, which an ini from 0.5.1 can hold, since 0.5.1 accepted a bare
function key for any action, and the log names a default left out. The Hotkeys page shows that
action's row empty, with the default and the action that has it, as in
`F9 held for Live A/B split, on or off`. Save in Settings applies the same rule again to each
action that the ini has no line for, so the session holds the keys the next start will, and the
log names each key that changes that way. Where the ini gives two actions one combination, the
first in the order of the Hotkeys page holds it. The other is recorded apart from a key another
program holds, and the note and Settings name the action that has its key, where they would
otherwise say another program. Such a key never brings the note up. What the listener knows of a
key that another program or action holds stays while the lens has let that key go, as it does
the keys of a fullscreen lens in a window, until the lens asks for the key again or Settings
changes it.

Four actions are for a fullscreen lens, which has no title bar to click, and have keys from the
start, F7 for the lens menu, F8 for the NR settings, F9 for Neural Rendering off and on and F10
for the on-screen readout. They are registered only while the lens is fullscreen and in view,
and given back when it goes to a window, is minimised or quits, so another program loses them
only for that time. They are given back as well while a dialog of the lens's own is in front,
such as Settings, whose Hotkeys page has to receive them, or a message box, as the 200 ms timer
finds, and while a program in exclusive fullscreen is in front on the lens's monitor, see Nothing
of the lens goes into another program. Only a dialog counts. The hidden root that carries the
taskbar button, which a click on the button brings to the front, any minimised window, and the
lens menu, the style and profile lists, the NR settings panel, the note, the notice, the readout,
the title bar, the tab and the divider leave the keys with the lens. While the lens holds one,
another process that asks Windows for the same key is refused with error 1409, and the keys were
free again 0.4 s after the lens quit. They are single keys because RegisterHotKey takes only the
last key of a combination from the window in front. A modifier goes down first and reaches that
window as any key does, so with a combination such as Ctrl+Home a game under the lens gets the
Ctrl, and many games act on it. Under the ReShade engine
the NR settings key ends in a Home posted to the presenter, which opens ReShade's overlay. With
the hotkey's own key still down, ReShade would read that Home together with it, so the lens waits
for it to be let go, two seconds at most, before it posts.

While the lens menu or the NR settings panel is open over a fullscreen lens in view, the lens also
registers Up, Down, Left, Right, Enter and Escape with no modifier, and while only the note on
going fullscreen is up, Enter and Escape. They are the lens's own and are not set in Settings, and
they are the only keys it registers with no modifier that are not function keys. A key the lens
holds reaches it as WM_HOTKEY and is not posted to the window in front, so the menu and the panel
work from the keyboard while a game keeps the foreground. Whether a program that reads the
keyboard through raw input sees such a key as well was not measured. The keys are not held while
a dialog of the lens's own is in front, such as Settings, which needs them itself, judged as for
the four keys above, and the 200 ms timer looks at that again while the lens is fullscreen. Nor
are they held while a program in exclusive fullscreen is in front on the lens's monitor, where
the lens closes the menu, the panel and the note. Each is let go only once it is up, looked at
with GetAsyncKeyState every 50 ms, since a key let go while it is down repeats into the window in
front, Escape in a game included. The arrows repeat while held, and Enter and Escape act once a
press. The menu takes them first, then the panel, then the note.

- **In the menu** nothing is lit when it opens. Down lights the first entry that does something
  and Up the last, both wrap round, and the pointer and the keys move one highlight. Enter
  chooses the lit entry and does nothing with none lit, and Escape closes the menu. The menu's
  own poll of Escape, see Gotchas, is left out while Escape is registered, so one press never
  closes two things.
- **On the NR settings panel** Up and Down light a row, its name drawn in the accent colour, in
  the order Neural Rendering, the style, the intensity, local tone, local structure, skin
  structure, skin structure left to the model, the auto mask, the passes and the quality step.
  Left and Right change the style by one, a slider by 0.05, the passes by one and the quality
  step by one. Enter switches Neural Rendering, skin structure left to the model and the auto
  mask. The passes take one step a press, and a repeat within 0.5 s of a change is ignored, since
  each change of the passes restarts the picture.

F6 is the add-on's and is never registered. Under the ReShade engine the add-on reads it with
GetAsyncKeyState itself, and the lens reads it the same way to follow. The fast engine has no
add-on, so under it F6 does nothing. The first F6 after each start of the picture on the fast
engine writes one line to the log, which names the key that turns Neural Rendering off and on
there, or the lens menu where no key does, and the presses after it write nothing until the
picture starts again. The program in front gets F6 either way, since the lens only reads it. F9
switches Neural Rendering as the menu's entry does, which tells the fast engine directly and on
the ReShade engine goes through `ReShade.ini` and a restart, see Nothing of the lens goes into
another program. F10 shows or hides the on-screen readout, see Fullscreen under Gotchas. Both
are held only while the lens is fullscreen. Two more actions, with no key set to begin with,
raise and lower the fast engine's quality step by one.

## Nothing of the lens goes into another program

The lens is made so that nothing of it reaches the program under it, a game included. It reads
the screen through Windows Graphics Capture, and the keyboard through RegisterHotKey and the state
of a few keys from GetAsyncKeyState. It installs no hook, makes no keystroke, attaches to no other
program's input, opens no other program's process and writes nothing into another program's
folder. The only key messages it sends, Home and F5 for ReShade, are posted to the window of its
own presenter, and the lens checks before each post that the process behind that very handle is
one of its own. A posted message is no input of the system. It changes no key's state, and no
low-level hook or raw input reader sees it, though a hook that runs in the presenter's own
message loop could.

- **Neural Rendering on and off under the ReShade engine.** The add-on reads F6 from the keyboard
  and not from window messages, see Measurement pitfalls, so only a keystroke switches it, and a
  keystroke the lens made would be seen by other programs as well, whatever window was in front.
  So the lens makes none. The menu's entry and F9 write `NeuralUplift` into the add-on's section
  of `ReShade.ini` once the presenter has ended, and start a new one, whose add-on begins in that
  state. A session started with `NeuralUplift=0` ran as a passthrough, an in-to-out difference of
  1.2 of 255 against 2.2 with it on over the same picture. That costs a restart of the picture,
  as a new pass count does. Fullscreen at 6144x2558 on an RTX 5090 the new presenter was ready 1.65
  to 1.74 s after the switch in six of seven switches, and 2.8 s after it in one. Where
  `ReShade.ini` cannot be written, the lens reads the state back
  from the file, shows that state, and says on the notice or the bar that the switch did not
  take. The add-on writes a change made in its overlay to the file about a second later, see
  Passes inside the add-on, and a presenter ended before that loses it. So a switch in tweak mode
  ends tweak mode first, as Done does. A switch in tweak mode, or in the four seconds after it in
  which the lens still follows the file, restarts the picture once 1.5 s have passed and the
  modification time and size of `ReShade.ini` have held still for a second, or 4 s after the
  switch at the latest, and the log says how long it waited. A minimised lens's presenter writes
  nothing, so the wait starts again once the lens is back. A second switch while one waits only
  writes that it waits, and a restart that comes meanwhile, such as one for a new pass count,
  takes the switch with it. F6 pressed by a person still switches at once, and the lens follows
  it.
- **The keyboard for tweak mode.** Tweak mode gives the presenter the keyboard so that the
  ReShade overlay can be used, and attaches the lens's thread to the presenter's input for the
  moment that takes. Afterwards the keyboard goes back to the window that had it, by attaching to
  the presenter's input again, and only while the window in front is the presenter or another
  window of the lens's own. The lens judges that on the very window whose input it joins, and
  checks that the process behind that input is its own or its presenter's before it joins. With
  another program in front by then, the person has moved on, and nothing is done. Up to 0.5.1 the
  lens attached to the input of the window that got the keyboard back.
- **Windows that never take the foreground.** The menu, the NR settings panel, the note, the
  notice and the readout are Tk toplevels made withdrawn, without a frame, topmost and fully
  transparent before Tk first maps them. Tk makes the window that carries the styles at its next
  idle moment, hidden while the toplevel is withdrawn, and `WS_EX_NOACTIVATE`, topmost and
  `WDA_EXCLUDEFROMCAPTURE`, with `WS_EX_LAYERED` and `WS_EX_TRANSPARENT` for a window that lets
  clicks through, go onto it while it is hidden. Tk 8.6's code for Windows then shows a toplevel
  without a frame with `ShowWindow` and `SW_SHOWNOACTIVATE` and with `SetWindowPos` and
  `SWP_NOACTIVATE`, and makes no focus call. The opacity stays at zero until 30 ms after the
  window is shown, when a timer sets it, so that Tk has drawn the window's contents by then. A
  toplevel mapped in view from the start can instead be made active as it appears, before any
  style is on it.
- **The Vulkan layer.** Since 0.6.0 the layer's description carries `enable_environment` with
  `ENABLE_VK_LAYER_reshade_neural_lens=1`, and the presenter sets that variable for itself, so
  Vulkan loads ReShade into the presenter alone, see The installer and the stack setup. A
  description from 0.5.1 or earlier has no `enable_environment`, and an update with the stack
  setup left out keeps it. As it starts, the lens reads the values under
  `HKCU\Software\Khronos\Vulkan\ImplicitLayers` whose data is 0, which are the layers the loader
  takes, opens the description each one names, and looks for `VK_LAYER_reshade_neural_lens`
  without that variable. It writes each path it finds to the log. Where the path is this copy's
  own description, `ReShade\ReShade64.json` in the lens's folder, compared through `normcase` and
  `abspath`, it asks whether to run the stack setup, which writes the description again.
  Declined, the lens starts as before and asks again at its next start. Any other such path
  belongs to another copy of the lens, such as an earlier install in another folder or a copy run
  from source, whose description this copy's setup does not write. For that the lens shows a
  dialog that names the path, says that it belongs to another copy of the lens and loads its
  ReShade into every program that uses Vulkan, and offers to remove that registration, its value
  under `ImplicitLayers`, or to keep it. A path kept goes into `layer_stray_kept` in the ini and
  is not asked about again. Where the ini cannot be written, the path is kept for that session
  alone, the log says so, the lens starts all the same, and it asks again at its next start. The
  setup's self test prints the same finding and names a path of another copy as such. Where both
  are listed, it names this copy's own description by its path as the one the stack setup
  writes. `neural_stack.py --verify` prints the same and exits with 1. Of the registry and the
  descriptions, nothing is written but the removal of a value the person agreed to.
- **A program in exclusive fullscreen.** The shell's `SHQueryUserNotificationState` answers
  `QUNS_RUNNING_D3D_FULL_SCREEN`, 3, while a Direct3D program has the screen in exclusive mode,
  and Windows draws no other window over such a program. The answer is for the whole session and
  names no monitor, so the lens counts it only while the window in front is on the lens's
  monitor, by `MonitorFromWindow` of `GetForegroundWindow` with `MONITOR_DEFAULTTONULL` against
  the monitor of the lens's centre, and is not one of the lens's own. It asks once a second while
  it is fullscreen and in view, and as it starts or goes fullscreen. While the answer counts, the
  lens gives back the four keys of a fullscreen lens and holds none of the keys of its menu,
  panel and note. It closes an open menu, panel or note and shows no note, and it registers its
  keys afresh at each change of that state. The notice's first line says that the lens cannot
  draw over that program and that borderless windowed works. The log has a line each way, and
  one that names what was closed. Nothing is asked of the program itself. Over such a program the
  notice cannot be seen either, so the log is the record. Whether the shell answers 3 for every
  game that asks for exclusive fullscreen, among them the games Windows runs under its fullscreen
  optimisations, was not measured.
- **The foreground in the log.** While the lens is fullscreen and in view, the 200 ms timer writes
  a line each time another window comes to the front, see The lens's log, from
  `GetForegroundWindow` and `GetClassNameW` alone. No process is opened, and no window's title is
  read, since a title can hold private text. The warning that the lens falls behind uses the
  same looks. As each regular summary is written its check asks those two again, and the process
  id of the window in front to tell the lens's own windows, and it opens no process either, see
  The warning under A game in front that keeps the card busy.

## The lens's log

`lens.log` holds everything the lens prints when it runs without a console, see No console under
Gotchas. Each line starts with the local time to the millisecond and a space, as in
`23:14:05.120`, so a line can be put beside what happened on screen and beside the fast engine's
own notes, which start the same way in `presenter-stderr.log`. Python's `print` hands a line over
in two writes, its text and then its newline, and the threads that read the presenters print as
well. So the writer gathers each thread's pieces apart until a line is whole, and writes the whole
line under one lock with the time of its first piece. Run with a console, as `python
neural_lens.py`, the lens prints the same lines without the time. The engine's lines on stdout,
which the lens reads, carry no time.

A lens that writes `lens.log` and is restarted from Settings, for a new stack folder or theme,
carries on in the same `lens.log`. The old lens moves its own output to `restart.log` and closes
`lens.log` before it starts the new one, and gives the new one the path of the `lens.log` it
closed in `NEURAL_LENS_LOG_APPEND`. That has the new one write to `lens.log` with times although
its output is already set. It adds to the file without rolling it only where that path is its own
`lens.log`, compared through `normcase` and `abspath`. After a change of the data folder the new
one's log folder is the new folder's `logs`, so the path differs, and it rolls and starts the
`lens.log` there as any start does. The old folder's `lens.log` then ends at the restart, and its
`restart.log` stays beside it. Either way `restart.log` holds only what was printed in between. A
lens run with a console hands nothing on, and its replacement prints to `restart.log`.

A line that starts with `action ` is something done to the lens, with the way it came in brackets:

```
action menu opened (key F7)
action menu item "Leave fullscreen" (Enter)
action NR settings NRIntensity 0.95 (keyboard)
action NR off (key F9)
action readout hidden (key F10)
action fullscreen off (taskbar list)
action style list item "Natural" (click)
action Settings saved: max_fps 30, fs_readout fps,latency (Save)
action profile "Video" renamed to "Film" (Settings)
action check for a new version (Settings)
action quit (close button)
```

Each action taken through the lens's keys, its menu, the NR settings panel, the buttons of the
title bar, a click on the tab, the note, the taskbar list or Settings has such a line. The lens
menu, and the style list and the profile list of the title bar, each have lines under their own
names for their opening, the entry chosen and their closing. The NR settings panel has lines for
its opening, its closing and each value changed on it, tweak mode for its start and its end, and
the note for its closing and its Don't show this again. Neural Rendering on and off, the quality
step, the passes, fullscreen, screenshots, the A/B split, the on-screen readout shown or hidden,
minimising and bringing the lens back, applying a profile, hiding and showing the title bar,
Ready mode, detaching and quitting each have their line, also where the lens stays as it was,
such as `fullscreen left as it is` for a lens attached to a window. A click on the taskbar
button writes `brought back (taskbar button)` for a minimised lens and
`menu opened (taskbar button)` where it opens the menu, and nothing where it only brings a lens
in view to the front again. Save in Settings writes one line that names
each setting it changed, by its key in the ini and its new value, or says that nothing changed.
On the Profiles page, Rename, Delete and Save the current settings each write a line that names
the profile, and so does Save in the dialog for a new profile. Check now on the Program page
writes `check for a new version`. The plus and minus on the title bar only choose a number, and
Set has the line. Moving the lens by its title bar or its tab, sliding the tab along the edge,
resizing the lens by its edges and dragging the divider write no action line, and neither do
Browse, Cancel and the choices made in Settings before Save. A value changed on the panel gets
one line once it has held still for 0.6 s, or as the panel closes, under its key in
`ReShade.ini`, such as `NRIntensity`, and `NRSkinStructure -1` is skin structure left to the
model. The lines the lens wrote before, such as `Neural Rendering off` and
`fullscreen 6144x2558 at (0,0)`, stay as they were beside them.

While a fullscreen lens on the fast engine is in view, a line every 10 s sums up the engine's
stats lines:

```
fast engine, last N s: N new and N arrived pictures a second, N repeated, N dropped, N skipped, median delay N ms, quality step N NAME, N pass(es), NR on|off, frame rate limit N fps|no frame rate limit
```

The two rates are means over the seconds counted, which are the stats lines that came, ten as a
rule. Repeated, dropped and skipped are totals over those seconds: presents of a picture already
shown, frames replaced by a newer one or left out before the engine took them, and frames equal
to the one before. The delay is the median of the engine's own figure, see The present path and
the delay, not raised to zero as the menu shows it, and reads unknown when no refresh was learned.
The line ends with the frame rate limit in force. Only the stats lines of the engine that runs
now are counted, by its process id. A restart, a new quality step, Neural Rendering switched on
or off, a new pass count, a new frame rate limit, Ready mode switched on or off, fullscreen and
back, a profile and minimising each write a line at once, before they change anything, for the
seconds gathered since the last one, where two or more came. Such a line counts fewer than ten
seconds, and each line covers one engine in one state, which it names, apart from Ready mode.

When two regular summaries in a row find the lens behind the program in front, see The warning
under A game in front that keeps the card busy, a line says so, at most once in ten minutes
unless Settings switches the warning on in between:

```
the lens is running behind the program in front, median delay 51.0 ms, 2 summaries in a row at 25.0 ms or more, and the warning is shown
```

The count is of the summaries behind in a row, and the figure after it is three refreshes of the
lens's monitor. A median up to a tenth of a refresh below that figure counts as well, so at a
rate Windows gives as 119 Hz the figure can read 25.2 ms over medians of 25.0 ms. Where the switch
in Settings is off, the line ends `and the warning is off in Settings`.

While the lens is fullscreen and in view, a line each time another window comes to the front:

```
foreground: Shell_TrayWnd, another program's
foreground: NeuralLensFast, one of the lens's own
foreground: no window
```

The line a lens writes as it attaches to a window names that window's class as well, never its
title, since a title can hold private text.

## Profiles

A profile captures the add-on's section of ReShade.ini whole, apart from ConfigVersion and
EnableHooks, which belong to the install, and applying one replaces the section with the profile's
keys and nothing else, so a setting the profile never held goes back to the add-on's default
rather than lingering from the last look. The add-on reads the section only when its process
starts and writes it back within about a second of a change in its overlay, so a profile saved
after a change in the overlay carries it, and applying one restarts the picture. The name on the
bar compares the pass count, the Cost Scaler rule, ready, the frame rate limit, the motion detail,
the readout, the delay meter and fullscreen against the profile, not the add-on's section, since
reading the file on every tick is not worth it. Verified with a test that saves and switches
profiles through the lens's own methods.

A control on the title bar that answers a click of its own has to be named in the bar's
`nodrag` list, because the bar binds the drag handlers to every other child after it is
built and a later bind on the same event replaces the earlier one. The profile selector and
the style picker both lost their click that way, and the profiles test did not see it
because it called the method. A second test clicks both with real mouse input.

The add-on reads its section when its process starts and not again, for intensity as for
passes. On the test computer with the RTX 5090, over the still with the picture at NRIntensity
1.00, a test wrote 0.05 into the ini. Five seconds later the lens's picture had changed by 0.40
of 255 mean, the noise between two frames of a still, and the same value after a restart changed
it by 1.47 of 255. So a control on the lens can show the Home menu's values live, since the
add-on writes them within a second, but can only set them by restarting the picture. The Home
menu itself is the live path.

## Attached to a window

The lens can attach to another window, or to a region inside it, and follow it. The target's
client area comes from GetClientRect and ClientToScreen, a region is kept as fractions of it,
and the result is clipped to the monitor it is mostly on, since the presenter captures one
monitor. A follower on a 50 ms timer reads that rectangle. A move relays the chrome and the
picture without a restart. A new size restarts the picture once it has held for half a second,
since a resize arrives as many sizes. A minimised target minimises the lens and a restored one
restores it, and a target that is gone closes the lens.

The chrome while attached is the two pixel line around the region, made click-through with
WS_EX_TRANSPARENT since it lies exactly on the target's own edges, and a tab of 28 by 14 on
the top edge, the only part that takes the mouse. A drag slides the tab along the edge and a
click opens the menu. The lens is not topmost while attached. It sits one step above the
target. Each window is inserted after the window above the target, or at HWND_TOP when that
window is itself topmost, since inserting after a topmost window would make the lens topmost
too, and the follower restacks whenever the window above the target is not the picture. So a
window brought over the target covers the lens, and the target brought forward, by a real
click, brings the lens with it. This is verified with two tests of 21 and 9 checks, the follower
through the lens's own methods and the pick through real mouse and keyboard input.
SetForegroundWindow from another process is refused by Windows, which one version of the test
mistook for a stacking failure, and an odd client height loses one row, since the picture keeps
even sizes.

## Capture under the lens's own windows

**Windows Graphics Capture of the monitor composes the desktop beneath an excluded window.** With
a window excluded through `WDA_EXCLUDEFROMCAPTURE` on top of a still, the captured region matched
the bare still exactly, a mean absolute difference of 0.0 before and after moving the cursor
across it. Desktop Duplication shows black there instead, see Dead ends.

An excluded window is invisible to every capture, window capture included, so the lens's output
cannot be captured from outside while it is excluded. The screenshots and the steadiness probe
read the presenter's own swapchain back instead.

Every window the lens owns is excluded. The chrome and the presenter are excluded when they are
created, the menu, the NR settings panel, the note, the notice and the readout while they are
still hidden, before they are first shown, the A/B divider when it opens, and anything else by a
timer that re-applies the exclusion to every visible top-level window of the process every
200 ms, since dialogs and message boxes offer no hook to act on.

## Why the stack is the program's folder

ReShade, loaded as a Vulkan layer, reads `ReShade.ini`, and through it the add-ons and shaders,
from the folder of the executable it attaches to. With `lens-presenter.exe` one folder above the
stack and the stack as its working directory, the layer did not attach, and `ReShade64.dll` 6.8.0
names no environment variable that points it elsewhere. So installed, the program's folder is the
stack, and from source the stack folder holds the interpreter's copy. The setup also writes
`ReShadeApps.ini` beside the layer, naming that one executable, but ReShade does not read it. The
file belongs to ReShade's own setup program, and ReShade 6.8.0 starts in any program that has a
`ReShade.ini` in its own folder.

## Passes inside the add-on

**The v5 line of the add-on runs the passes itself** (renodx-dlss5 5.2.1 from the RHI
repository, and the v5.0 beta before it). It takes the count from `NRPasses` in its
`[RenoDX.DLSS5]` section of ReShade.ini, read only when the process starts. An edit while it
ran had changed nothing twelve seconds later, and a process that is terminated does not write the
file back, so the lens writes the key after the old presenter is gone and before the new one
spawns.

The add-on does write its settings back within about a second of a change made in its overlay.
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

Effect is the mean absolute difference of the after screenshot from the before, out of 255, and
the two two-pass outputs differ from each other by 1.6.

Measured through the presenter, a 1400x1000 lens over a still with the add-on at its defaults,
chained history off and the Anchored codec, as 0.2.0 shipped. The table gives frames a second, the
delay meter's reading, the change to the picture, and the change between consecutive presented
pictures, both out of 255:

```
passes   frame rate   delay   change   consecutive
1          118 fps    10 ms    2.30      0.42
2          107 fps    13 ms    3.58      0.51
3           89 fps    23 ms    4.89      0.65
4           74 fps    29 ms    6.21      0.76
```

**Pulsing at two passes and up.** The add-on's own text says that passes beyond the first are
stateless by default and can flicker, and to try the chained history toggle. With
`NRChainedHistory` off, a model in Blender and a still image under the lens visibly pulsed at two
passes and up, and with it on they did not. So the lens writes `NRChainedHistory=1` where the
add-on's section holds no value for it.

The still the measurements here use is a screenshot of text on a dark window, and on it the
presenter's readback does not show that pulsing. Consecutive presented pictures, mean absolute
difference out of 255, first with `NRIntensity=1.7` and `NRStyle=0`, then at the add-on's
defaults, where the two and three pass pairs were measured twice, in both orders, with the same
result, and four passes once:

```
            NRIntensity 1.7, style 0        the add-on's defaults
passes      chained off     on              chained off     on
1             0.31                            0.42
2             0.46          0.37              0.51          0.59
3             0.60          0.34              0.65          0.66
4                           0.35              0.76          0.68
```

The same still was also read back as 30 pictures over about 30 seconds, at the add-on's defaults
with the Classic codec. Spread is the per-pixel standard deviation over time, averaged over the
picture. Regions is the same over 16x16 pixel block means, and swing is the largest minus the
smallest mean of a whole picture. All are out of 255. The captured input did not change at all,
and one pass, run first and last, gave the same spread, regions and consecutive change both times:

```
passes   chained   frame rate   spread   regions   swing   consecutive
1          off      113.5 fps    0.425    0.116    0.082      0.399
2          off      110.5 fps    0.481    0.143    0.104      0.471
2          on       108.5 fps    0.574    0.153    0.078      0.556
3          off       88.5 fps    0.593    0.175    0.108      0.610
3          on        88.0 fps    0.672    0.184    0.265      0.638
4          off       73.5 fps    0.685    0.199    0.095      0.720
4          on        73.0 fps    0.752    0.214    0.320      0.684
1          off      116.5 fps    0.424    0.116    0.055      0.398
```

The settings set the floor as well. `NRIntensity=1.31` with `NRStyle=1` gave 0.12 consecutive at
one pass.

**Traps.** This add-on line resets its whole section to built-in defaults when `ConfigVersion` is
missing or older than its own, and writes `ConfigVersion=2`, without a log line. Its own working
resolution setting (`NRFollowInputRes`, `NRResolutionScale`) scales against a game's DLSS render
resolution, which the lens has none of. With `NRFollowInputRes=2` and `NRResolutionScale=0.75`
the log still said `NR input 2400x1800`, at the same cost and with the same output.

The newer `renodx-dlss` add-on, with `DirectNeuralRenderingPassCount`, does not inject at all,
see Dead ends.

## The add-on's defaults on a new install

With a section holding only `ConfigVersion=2`, 5.2.1 ran at its defaults, logged as
`intensity=1.000000 color_strength=1.000000 transfer=1.000000 paper_white=2.537500 preset=0
style=0 enabled=ON`, wrote back `EnableHooks=2`, `NeuralUplift=1` and `NREnableUpscaling=0`, and
created and evaluated feature 18 at one pass. So that is all the setup writes into the section,
and a repair keeps whatever the section holds. Before each presenter starts, the lens writes
`NRChainedHistory=1` and `NRCodecMode=0` where the section holds no value for them and leaves a
value that is there, so a choice made in the add-on's overlay, which the add-on writes back to
the section, stays.

The add-on's developer asked, for the v5 line, that the proxy codec be set to Classic,
`NRCodecMode=0`, where the add-on's default is Anchored, `NRCodecMode=1`. Over a still the two
measure alike. Interleaved at the defaults, one pass, twice each, the change between consecutive
presented pictures measured 0.42 with Anchored and 0.40 with Classic, the change to the picture
2.30 and 2.19, and the frame rate 118 fps and 116 fps. Over a model in Blender, Anchored left ghosting
around the model and Classic did not.

## The Cost Scaler

xenmods' DLSSNR-Cost-Scaler is a proxy `nvngx_dlssnr.dll` that runs the model at a fraction of
the frame and composites the delta back onto the native frame. It implements four D3D12 NGX
entry points and forwards the other 51, every Vulkan one included, to `nvngx_dlssnr_real.dll`.
It works in the lens because Neural Rendering there is a **D3D12 NGX session behind the Feed's
Vulkan transport**. `dlss5-feed.log` says `opening D3D12 session (Vulkan transport)`, and neither
add-on carries a single `NVSDK_NGX_VULKAN` symbol. The add-on logs the proxy as
`custom runtime accepted; untested build` and carries on. The proxy logs its settings and its
working size in `nvngx_dlssnr_proxy.log`, switched off included, and reads its ini when it starts
and again within a second of a change.

The setup writes the proxy's own ini with four changes. It sets `EnableProxy = 0`, since the lens
decides, and `EnableHotkeys = 0`, since its hotkeys are polled globally and a desktop program must
not answer Ctrl+Alt+PageUp in every window. It also sets `EnableDepthAwareResolve = 0`, which
works from the depth the Feed synthesises and was off for every measurement below, and
`EnableGovernor = 0`, its default.

The fast engine calls the model through the proxy as well, with the proxy switched off by an ini
of its own, and does the scaling itself, see The fast engine. Everything below is the proxy under
the presenter.

Measured with 0.1.0's pipeline, passes inside the add-on, most frames a second presented:

```
                                     off    0.75    0.50    0.35
fullscreen 6144x2558, 1 pass          30      43      43      44
fullscreen 6144x2558, 2 passes        23      31      43      43
windowed 2400x1800, 1 pass            97      88
windowed 2400x1800, 2 passes          69      86      91
windowed 1400x1000, 1 pass           100     100
```

Measured through the presenter, fullscreen at 6144x2558 over a still, with the add-on at its
defaults and the proxy at the lens's own scale. The one pass pair was measured twice with the same
result. The delay is the meter's reading, the change is from the untouched source out of 255,
and the power is one reading of the card's draw:

```
                         frame rate   delay   change   power
one pass, off              42 fps    47 ms    1.63     557 W
one pass, on at 0.70       58 fps    33 ms    1.22     500 W
two passes, off            26 fps    78 ms    2.98     576 W
two passes, on at 0.50     54 fps    36 ms    2.22     503 W
```

At 2400x1800 with two add-on passes, the effect, the after screenshot against the before as mean
absolute difference out of 255, was 9.95 native, 8.59 at 0.75 and 5.62 at 0.50. Power at a
matched 60 fps with one pass fell from 314 W to 261 W. It pays where the neural pass is the
limit, fullscreen and multi-pass, and costs a little where it is not, which is why the lens turns
it on for fullscreen only. One pass wanted about 0.7 on that panel and two passes 0.5, so up to
0.5.1 the rule was a working area of 8 megapixels over all the passes, re-applied whenever the
pass count changes. The 4 megapixel rule below replaced it.

The windowed switch was measured on a test computer with an RTX 5090 with a 2400x1800 lens at
three passes, 13 megapixels of work a frame, over a square bouncing 60 times a second, by a test
that switched the rule live between always and off the way the Settings dialog does it. With the
scaler on at 0.75, the proxy's log showed the model working at 1800x1350, the GPU read 90 percent
and 438 to 446 W, and the lens showed 58 to 70 new pictures a second. Off, the GPU read 99
percent and 566 W, and the lens showed 53 a second. The proxy took each change within a second,
with no presenter restart.

### The 4 megapixel rule

Measured on an RTX 5090, driver 617.14, fullscreen at 6144x2526 with one pass. The speed was
taken over a white square moving across noise, every captured frame different, two runs a scale
in an interleaved order and two more of off, 0.70 and 0.50 later. The title bar's delay read
54 ms off, 40 ms at 0.70 and 19 to 25 ms at 0.50:

```
       frame rate               power
off    39.5  39.2  39.4  39.3   456 W  467 W  464 W  469 W
0.70   53.3  53.0  53.6  53.5   395 W  398 W  397 W  399 W
0.55   58.4  60.6               348 W  357 W
0.50   63.0  62.8  62.9  62.6   340 W  343 W  344 W  343 W
0.45   64.9  63.8               326 W  324 W
0.40   64.0  64.7               301 W  303 W
0.35   65.7  64.5               292 W  287 W
```

From 0.50 down the frame rate stays at 63 to 66 a second while the power keeps falling, and every
run held its rate. The capture delivered only as many frames as were presented, and with ReShade
off it delivered 116 to 117 a second, so the GPU's load is what holds the rate here. Slower runs
over the flipper are a measurement artifact, see Measurement pitfalls. Power varied by up to 5
percent between runs of the same setting on different occasions, and fullscreen at 0.50 with no
limit read 327 to 344 W.

The picture was measured with `docs/images/blender-before.png` as the backdrop and two pairs a
setting. The change and the difference are mean absolute differences out of 255, and the edge
detail is the variance of the Laplacian, 273 for the untouched picture. The two pairs of each
setting were within 0.19 of each other in mean difference, and their edge detail differed by up
to 22, so the table gives the mean of the two:

```
          change from the original   difference from off   edge detail
off                3.37                     0                  113
1.00               3.37                     0.07               114
0.70               1.88                     1.97               157
0.55               3.61                     0.71               150
0.50               3.23                     0.64               152
0.45               3.32                     0.79               153
```

At 1.00 the proxy passes the frame through. 0.70 made about half the change of every other
setting in both pairs, with the face keeping more of the original's colour, for no reason found.
0.1.0's measurement over a still desktop had 0.70 a quarter below off as well. 0.55 to 0.45 stay
within 0.8 of the model at full size.

The blend was measured at 0.85 over a still picture of a game-style character with the Natural
style, by a test that changes one proxy setting at a time:

```
                          edge detail   change
as shipped                   170         5.92
Sharpness 0                  139         5.92
TransferStrength 1.50        171         8.85
TransferStrength 2.00        174        11.75
ColorStrength 0              170         5.71
EnlargementMode 0             59         6.15
```

The untouched still measures 293 and the model at full size 138. Fullscreen over
the Blender still, in one further run, 0.50 with Sharpness 0 measured 125, the model at full size
121 and 0.50 as shipped 152. So the Matched Residual blend keeps the model's own detail at a lower
scale, where plain enlargement loses most of it, and the extra edge detail over the model alone is
the proxy's sharpening, `Sharpness = 0.20`. It does not put the original's detail back.
TransferStrength scales the model's change, as an intensity would.
The rule is 4 megapixels over all the passes, which gives 0.50 for one pass fullscreen on the
6144x2560 monitor and the floor of 0.35 from two passes, 0.65 and 0.45 for 3840x2160.

## Motion detail

ReshadeMotionEstimation's Motion Estimation Detail, `UI_ME_LAYER_MAX` in the preset's
`[MotionEstimation.fx]` section, 0 Full, 1 Half and 2 Quarter, is the finest layer its block
matching works on. The lens writes it from `motion_detail` before each presenter starts, since
ReShade reads the preset when its process starts. At Full with no section in the preset it writes
nothing, Full being the estimator's default, and with VORT as the provider Settings leaves the
choice out. The ReShade overlay offers the same setting and writes the preset back, so a value
there that differs from the one the lens last wrote is kept, in the lens and its ini, at the next
start of the presenter. At the lens's own start its setting wins. The fast engine gives the model
no motion vectors, so the setting does nothing for it.

Power was measured over the moving square, two runs each, with the frame rates within two frames
a second of each other at each size:

```
                                   Full           Half           Quarter
6144x2526, Cost Scaler 0.50    340 W  340 W   297 W  299 W   286 W  292 W
1400x1000, Cost Scaler off     191 W  187 W   183 W  180 W   179 W  178 W
```

The picture was measured over black text on white scrolling sideways under a 1400x1000 presenter.
At 3 px a frame the three look alike. At 8 px a frame Half and Quarter left a visible double of
the text in every one of eight frames, where Full stayed mostly clean. The partial ink score the
providers were compared with does not see it, since the double is too faint to fall between 40
and 160, and it came out lower for Half and Quarter than for Full. Full stays the default.

## HDR

The lens shows standard range only. windows-capture 2.0.1, the newest release, asks Windows
Graphics Capture for 8-bit BGRA. Its Python binding hard-codes `ColorFormat::Bgra8`, while the
Rust crate under it supports `Rgba16F`. The presenter's swapchain is `B8G8R8A8_UNORM` in
`SRGB_NONLINEAR`. The fast engine captures with its own code, 8-bit BGRA as well, and presents a
`B8G8R8A8_UNORM` flip model swapchain in the standard colour space.

With Windows HDR on, the 8-bit capture is clipped. Measured on a 3840x1200 monitor at 144 Hz on
DisplayPort, with HDR on and standard content at 240 nits, over a pattern drawn in scRGB from 0
to 12.5, where 1.0 is 80 nits. The 8-bit Windows Graphics Capture frame equalled the desktop's
16-bit frame from Desktop Duplication clipped at 1.0 and encoded as sRGB, within 0.1 of 255 on
every patch. Scaled by the standard content level before clipping, the 16-bit frame was 50 of
255 away on average over the patches at or below that level. So in the capture everything from
80 nits up is the same white, and a lens on such a monitor works from a clipped picture. With HDR
off, Desktop Duplication gives that monitor's desktop in 8 bits, so nothing is clipped, and on
the main monitor, with Auto Colour Management on, the 8-bit capture was within 0.06 of 255 of
the 16-bit frame.

What a native HDR path through the presenter and the stack would need, from reading the parts on
2026-09-30. The first three do not apply to the fast engine, whose capture, shaders and swapchain
are its own, and what it would need has not been worked out:

- **A 16-bit capture**, through a rebuilt binding, which needs a Rust toolchain. The binding
  copies and maps the whole monitor for every frame whatever the lens's size. In 16-bit at
  6144x2560 that took 10.8 ms a frame (median, 21 ms at worst) through Desktop Duplication's
  path, the same function. A rebuild could crop on the GPU first.
- **A colour pass in the presenter**, which has no shader today, to scale or encode the frame for
  the swapchain or tone map it back to standard range.
- **The stack on an HDR swapchain.** Nobody upstream has run the Feed and the RenoDX add-on on a
  Vulkan HDR swapchain, and the Feed's HDR runs are D3D11. ReshadeMotionEstimation copies the back
  buffer into 8-bit targets, so it clips scRGB above 1.0, where VORT handles HDR. The add-on
  clamps negative scRGB values, so colours outside BT.709 are lost while Neural Rendering is on,
  and the Feed's HDR10 bridge hands the add-on linear BT.2020 that the add-on treats as BT.709.

## Resize restarts the picture

A resize would recreate the swapchain, and the Neural Rendering add-on responds to a recreated
swapchain by releasing its DLSS feature and crashing with 0xC0000005. Moving the lens is safe,
because that only repositions windows and moves the crop.

So a new size replaces the presenter, the way a new pass count does. `layout_chrome` lays the
title bar and border out again around the new size first, and `restart_presenter` ends the old
presenter and starts one at the lens's size and place. Fullscreen and back go the same way, with
the windowed geometry saved to the state file on the way in and read back on the way out, and so
does a lens that has to shrink to fit its monitor. Up to 0.2.1 every one of these relaunched the
whole process, a habit from mpv, and the taskbar button went with it.

Only the folder settings still relaunch the lens, since they are read at import.

### The handover must not use `os.execv`

On Windows `os.execv` goes through the CRT, which does **not** quote arguments containing
spaces. A script path such as `C:\Some Folder\neural-lens\neural_lens.py` therefore
reaches the replacement process split at the space, and it exits immediately with
`can't open file`.

`execv` does not raise in this case. It starts a broken process successfully while the original
is already gone, so a `try`/`except` around it with a `subprocess` fallback never fires and the
failure is silent, with no window, no console output and no log entry.

`subprocess.Popen` quotes correctly through `list2cmdline`. The replacement's own output goes to
`logs/restart.log`, because the console it was launched from can close along with the outgoing
process, and the replacement of a lens that writes `lens.log` takes that file up again, or after
a change of the data folder starts the one in the new folder, see The lens's log.

The failure only occurs when the script path contains a space, so any test of this path must run
from such a path. This was verified two ways while a resize still relaunched. A lens at 1200x800
at (1800, 700), resized to 960x640 at (1860, 740), came back at exactly that size and position
with capture running, the pass count carried across and nothing left running. The same flow was
also driven from a batch file inside a directory whose name contains a space.

## Dead ends

### A zoom

This was measured on a test computer with an RTX 4070 SUPER, with a 1400x1000 presenter at one
pass over a page of text, taking edge detail as the variance of a Laplacian and the partial
ink fraction as the share of pixels between 40 and 160 of 255. At the page's own size Neural
Rendering took edge detail from 12035 to 2516 and partial ink from 0.034 to 0.066, and over
the page's centre enlarged two times, bilinear, it went from 653 to 402 and 0.083 to 0.091. On
text the model softens, and on enlarged pixels it softens what was already soft. It recovers
nothing. A zoom would enlarge pixels for the model to soften, which Windows Magnifier does
without the GPU, so none is built.

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
  shimmers instead. One stage with 119 frames a second arriving measured 1.637 out of 255 at 120
  declared, 0.220 at 110 and 0.150 at 100, against a floor of 0.146. So 0.1.0 declared five
  sixths of the display rate and governed a playback speed live from the presented rate, the
  brightness out against in, and the output's frame to frame change on still content, with limits
  that expired and retakes of levels already held. A rule calibrated on one GPU did not survive
  another. On an RTX 4070 SUPER two passes at the rule's 50 presented 40 a second and shimmered,
  and a 2000x1400 lens at 100 presented 27 a second and collapsed. The presenter presents the
  captured frame again instead of a stale one, so neither failure can occur, and nothing needs
  governing.
- **Passes.** Before the add-on could run several passes, each extra pass was another mpv
  capturing the one before, stacked on the same rectangle. The cumulative change was 7.71, 14.05
  and 19.45 for one, two and three passes, and 0.24 with Neural Rendering off. Every stage had to
  be on the magnifier's exclude list, or the magnifier rendered it back into the first stage's input
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
Duplication show the desktop behind it. Nothing composites the occluded region into the
duplication buffer, so it stays empty there and only transient dirty rects land in it. The
symptom is a black viewport that accumulates mouse trails and window drag smears. Windows
Graphics Capture of the monitor does compose it, see Capture under the lens's own windows.

Two caveats when testing this. A static window over another static window does capture
correctly, because DWM still holds both buffers, so that case does not generalise. A Vulkan
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

It resynced badly after a restart, with 353 buffering events and frames arriving every few seconds. A
pipe and TCP both measured 60 fps, and nothing restarts mid session, so it bought nothing.

### An in-app NR health indicator

Comparing the frame sent to the host against the frame actually displayed separates NR on from NR
off by only 1.4x. The comparison read 0.58 off and 0.82 on, and 1.7 on in a different scene, so
the scene matters more than the setting. Whole frame averaging at 1/8 stride washes out exactly
the local detail that Neural Rendering changes, so such an indicator raises false alarms. The F6
toggle is unambiguous instead, measuring 12.7/255 on plain text.

## Gotchas

- `windows_capture` dispatches handlers by function `__name__`. They must literally be called
  `on_frame_arrived` and `on_closed`, or it raises ValueError.
- `WindowsCapture(...)` takes a `minimum_update_interval` whose default throttles delivery to
  about 60 frames a second. Setting it to `0` more than doubles delivery on an identical source,
  from 59.4 to 124.6 frames a second.
- `frame.frame_buffer` is row padded and non contiguous (stride 2304 for width 560). Slice
  `[:h, :w, :]` and `np.copyto` it into a reused buffer, since `ascontiguousarray().tobytes()` costs
  two full copies, measured at 2.93 ms per 1400x1000 frame against 0.18 ms.
- The opening frame of a freshly started window capture session is sometimes handed over
  uninitialised and comes back black, measured at roughly one sample in 14. Skip the first
  frames and reject an all zero buffer.
- Passing `HWND_TOPMOST` as Python `-1` through ctypes silently fails on x64, because a 32 bit
  int goes into a pointer parameter. Use `ctypes.c_void_p(-1)`.
- Find a child process's window by its process id rather than its title. A window is visible
  before its title is set, and mpv's showed "mpv" for a second and a half before taking its
  configured title, with a taskbar button all that time.
- A window with `WS_EX_TOOLWINDOW` or `WS_EX_NOACTIVATE` has no taskbar button. Set the styles
  while the window is still hidden, or the button appears while it loads. Windows Graphics
  Capture cannot find a tool window by its handle, which does not matter for a window nobody
  captures.
- `WindowFromPoint` skips click-through windows. To see what is stacked over the lens, walk the
  z-order with `GetWindow(h, GW_HWNDPREV)`.
- **Windows puts a maximised or full screen window that becomes the foreground above every topmost
  window.** Measured with the Photos app maximised over a windowed lens, the app sat above the
  presenter and stayed there, and only a fresh `HWND_TOPMOST` brought the lens back. The lens
  walks the z-order above the presenter every 200 ms and raises itself when a visible window that
  is neither its own nor itself topmost overlaps it.
- `tk_popup` is a native `TrackPopupMenu`. It blocks Tk's main loop until the menu closes, and it
  dismisses on an outside click or Escape only while its owner is the foreground window, which a
  title bar that never activates is not. The menu is a Tk window of the lens's own instead, closed
  by a 30 ms poll of the mouse buttons and Escape through `GetAsyncKeyState`. While a fullscreen
  lens holds Escape as a hotkey for the menu, the poll leaves Escape to the hotkey.
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
- `evaluation succeeded (count=` in `ReShade.log` is a **milestone line**, emitted at counts 1, 60
  and 600 and then not again, with the add-on's `pre-SR` and `inline` evaluations counted apart.
  With renodx-dlss5 5.2.1, a session of 16 minutes that evaluated about 34,800 frames logged
  three, all `inline`, and no more. Two sessions of 23 and 24 September on DLSS5-Feeder
  1.16.0-beta.6 began with `pre-SR` evaluations and went on to `inline` ones during a stall the
  Feed logged, of 156 ms and 247 ms, and each logged six, the `inline` count starting at 1. No
  session in the kept logs went back from `inline` to `pre-SR`, so whether the `pre-SR` count
  would then start again is not known. The number of occurrences is not a measure of how much
  Neural Rendering ran.
- **ReShade rotates its log.** A second instance in the same folder cannot open `ReShade.log`, so
  it writes `ReShade.log1`, and a third writes `ReShade.log2`. Anything that archives or inspects
  logs must cover all of them.

### The clipboard and the update check

The joined screenshot goes onto the clipboard from the presenter, which holds the pixels, as
a 32 bit bottom up CF_DIB in moveable global memory the system owns once SetClipboardData
takes it. The update check reads the releases list rather than the latest release, since
GitHub's latest excludes prereleases and every release so far is one. It runs on a thread and
answers on the Tk thread, and a quiet check records the time in `update-check.txt` in the data
folder so the start check waits a day.

### The taskbar button is the tk root

The title bar is an override redirect window that never activates, so the mouse reaches the
application under the lens, and that combination has no taskbar button. The hidden tk root
stands in, titled, fully transparent and parked minimised. Restoring it from the taskbar fires
`<Map>`. The handler brings a minimised lens back, or else re-asserts topmost on the presenter
and then on the bar, and minimises the root again before it can be seen. `raise_chrome` alone
would not do, since it re-asserts only the bar. Tk toplevels on Windows are not owned by the
root, which was measured rather than assumed. The bar stayed visible with the root minimised, and
restoring fired exactly one `<Map>`. Close window on the button arrives as the root's delete
request and quits the lens. The root is the button in every state, windowed, fullscreen and
minimised. Neither the presenter's window nor the fast engine's has one.

On a fullscreen lens that does not hold its menu key at that moment, because none is set, another
program or another of the lens's actions has it, or a dialog of the lens's own is in front, the
handler opens the menu as well, so a fullscreen lens always has a way to its menu. The root in
front is no dialog, see Global hotkeys, so the keys of a fullscreen lens are not let go for it.

### The taskbar button's list, and a word for the running lens

A right click on the taskbar button lists three tasks of the lens's own, the lens menu, the NR
settings and fullscreen. It is the button's jump list, set at the lens's start through
`ICustomDestinationList`, `IObjectCollection`, `IShellLinkW` and `IPropertyStore`, called through
ctypes by their places in each interface's table. Setting it took 27 to 39 ms and deleting it 1 ms,
and doing either twice is harmless.

- **The entries are tasks under Windows' own heading.** With recently opened items switched off
  in Windows, `Start_TrackDocs` at 0, `AppendCategory` for a heading of the lens's own was refused
  with 0x80070005, and `AddUserTasks` went through.
- **The installed lens sets no AppUserModelID.** The button, a shortcut pinned to the taskbar
  and the list belong together by that id. A pin made from a shortcut without one goes by the id
  Windows gives the exe, and a process that sets an id of its own no longer runs under that pin.
  So installed, the lens, its pin and its list go by Windows' own id for `NeuralLens.exe`, and
  the installer's shortcuts must not be given one. From source the program is Python, whose id
  every Python program shares, so there the lens takes `LeapsBounds.NeuralLens`.
- **Each entry starts the lens's own program with `--do` and a word**, `menu`, `nr` or
  `fullscreen`. When a lens is running, that process opens no window and is handled at the top
  of `neural_lens.py`, before the ini, the stack or the log are touched, since those files are
  the running lens's. Every lens has a window that only takes messages, of the class
  `NeuralLensDo`, on a thread of its own, and the word travels as a registered window message.
  It goes into a queue that the lens's 50 ms timer drains on the Tk thread, so the sender has its
  answer at once, also while the lens is replacing its picture. From source a `--do` process
  took 0.08 to 0.20 s, and a word sent while the picture was being replaced was acted on 1.4 s
  later, when the new picture was up. Its exit code is 0 when a lens took the word, 2 when the
  word is not one of the three, 3 when the lens gave no answer and 4 when a lens is starting or
  closing. With no lens running, which `_send_command` reports as 1, it says so in one line and
  goes on as the lens itself, as starting the program does, fullscreen for `fullscreen`, which
  is how the entries of a list that a lens ended by force left behind still work. From source
  that lens was listening for words 1.0 s after the process started. A lens started fullscreen
  that way writes `fullscreen = 1` to the ini, as going fullscreen any other way does, so a
  restart from Settings or an update brings it back fullscreen.
- **A lens that is starting or closing takes no word, and a `--do` then starts none.** A lens
  listens only once its picture is up, which can take seconds, and a closing lens takes no more
  words. So every lens holds a named mutex, `Local\NeuralLens.alive.LeapsBounds.NeuralLens`,
  from its start until `main` returns. It is let go there and not when the process ends, since a
  test runs `main` in a process that goes on and then starts a lens with `--do`. A `--do` process
  that finds no lens to take the word but finds the mutex there already writes "A Neural Lens is
  starting or closing, so this one does not start." on stderr and ends with code 4. An ordinary
  start ignores the mutex, so several lenses can still run.
- **An entry names the lens's stack with `--stack-dir`** when that lens was started with
  `--stack-dir` or with `NEURAL_LENS_STACK`, so a lens that the entry starts finds the same
  stack. A stack folder chosen in Settings is not named, since the ini has it already and a
  `--stack-dir` would outrank a later change in Settings.
- **A lens attached to a window stays as it is** on `fullscreen`. It has no bar, so the notice
  says why for six seconds.
- **With several lenses running one takes the word.** A lens in view comes before a minimised
  one, then a fullscreen lens before a windowed one, since it has no bar to click, then the lens
  on the monitor the pointer is on, then the one started last.
- **The list is taken away when the last lens closes**, and by `--uninstall-stack`, which the
  uninstaller runs. Windows keeps it as one file named after the id in
  `%APPDATA%\Microsoft\Windows\Recent\CustomDestinations`. A lens that is ended by force leaves
  its list until a lens next closes.

### Minimise

The minimise button withdraws the chrome and hides the presenter's window, so only the taskbar
button is left, and sends the presenter `pause`. Paused, the presenter ends its capture and
presents nothing. ReShade, the Feed and the add-on all run on a present, so nothing runs at all,
which is more than F6 gives. With Neural Rendering off the presenter still presents at the
display's rate and the Feed's motion shader still runs on every frame. The capture is ended
rather than left delivering into a buffer nobody reads, since a monitor capture delivers a frame
for every composition, and copying a whole monitor out of each at the display's rate is real CPU.
`resume` captures afresh and presents the last picture first, so the window is never empty when
it is shown again. Measured with a test that took five second samples of nvidia-smi and
GetProcessTimes, on a test computer with an RTX 5090 at 1400x1000 with one pass. Minimised over a
square bouncing 33 times a second, the GPU read 1 percent and 51 W and the presenter used 0.00 s
of CPU time. In view over the same square it read 21 percent, 114 W and 0.80 s. Frames arrived
again 0.5 s after the taskbar click, with the presenter and the chrome back at exactly their
rects.

The fast engine pauses the same way. Paused for 8.5 s under a minimised fullscreen lens it printed
a stats line of zeros a second and showed 115.8 new pictures a second again after the restore. A
minimised lens also gives back the keys of a fullscreen lens and closes the NR settings panel.

The add-on reads F6 once per presented frame, so a press while minimised changes nothing in it,
and the lens ignores the key then too, to stay in step. Neural Rendering comes back as it was
left. Monitors that changed while the lens was minimised are noticed on restore, which starts the
presenter again as `watch_layout` would have.

windows-capture takes its handlers by their names, `on_frame_arrived` and `on_closed`, so the
close handler is made per capture and carries its generation. A capture that was stopped for a
pause closing later is not a loss.

### The frame, for resizing by the edges

Up to 0.2.1 the chrome's border was a two pixel line, and a two pixel target cannot be dragged,
so resizing went through an outline dialog. The border is now eight pixels. The outer two are
still the line, and the rest are three grips, down each side and along the bottom, with the
resize cursors. `EDGE` is what `inner()` and `fit_rect` count from. A drag previews on the chrome
alone, the presenter untouched, and letting go fits the size to the monitor and replaces the
picture. The top edge is the bar, which moves the lens, so there is no top grip. Nothing asks
first, since a picture restart is what a new pass count does too, with nothing but the note on
the title bar.

The caption buttons are Windows' own glyphs from Segoe Fluent Icons, or Segoe MDL2 Assets before
Windows 11, falling back to plain characters when neither font is there.

### No console

The installed lens is a windowed program, and the launcher starts the lens under pythonw.
`sys.stdout` is None there, so at import everything printed is redirected to `lens.log` in the
log folder, with the previous one first rolled into a stamped copy so the archive's pruning covers
it. Each line gets the time in front, see The lens's log. The replacement Settings starts for such
a lens does the same although its output is set, and adds to `lens.log` without rolling it,
unless a new data folder gave it another log folder, see The lens's log.
`GetConsoleWindow()` returning zero is what turns the messages that used to wait for Enter into
dialogs, including a presenter that never opened its window and an unexpected traceback out of
`main()`. A harness driven from a tool with no console window sees the same, so any test that
reaches a fatal path has to replace `messagebox.showerror` first, or it blocks on a dialog nobody
will dismiss.

The presenter catches any unhandled error itself, prints the traceback to its stderr, which the
lens keeps in `presenter-stderr.log`, and exits. Frozen without a console, an unhandled error
would otherwise stop in a dialog of the bootloader's while the lens waited for a window. From
source, the lens starts the interpreter's copy with `CREATE_NO_WINDOW`, since `python.exe` would
otherwise open a console of its own under a lens that has none.

### Per monitor DPI awareness

On the test computer with the RTX 5090, a 1400x760 lens on its secondary monitor once produced a
1680x912 picture. ReShade created its Neural Rendering resources at 1680x912 and the Feed delivered
frames at 1680x912, while `GetWindowRect` from inside the lens said 1400x760. The ratio, 1.2, is not
a scaling factor but the ratio of two, 150 percent over 125 percent. A system DPI aware process keeps
the DPI the session logged on with and lives in a coordinate space Windows virtualizes against each
monitor, so a window placed on a monitor whose scaling differed from that was rescaled by Windows on
the way. The lens and the presenter are per monitor DPI aware, version 2, so every coordinate either
uses is a physical pixel on whichever monitor it is on.

This was verified on a second test computer, which has an RTX 4070 SUPER, with its primary
monitor switched to 125 percent while the session had logged on at 100 percent. The lens asked
for 1400x760, a per monitor aware probe measured the picture's window at 1400x760 physical,
ReShade created its resources at 1400x760, and the chrome measured 1404x796 with both windows
reporting 120 DPI, so nothing is bitmap stretched either. Fonts follow the monitor's DPI. The bar
is 34 pixels and holds a 10 point label up to 200 percent.

### Fullscreen

- **A fullscreen lens is the picture alone.** It has no title bar, no frame and no tab, on either
  engine, and covers its monitor from the top edge, the taskbar's place included. Up to 0.5.1 the
  picture started below a title bar across the top, 6144x2526 at (0,34) on a 6144x2560 monitor,
  which is the size the older fullscreen figures in this file were measured at.
- **It stops two rows short of the monitor's bottom edge.** Measured on a 6144x2560 monitor with a
  second monitor connected, the fast engine alone over the desktop. With its window covering the
  monitor exactly, at (0,0) and 6144x2560, Windows' notification state went from accepting
  notifications to busy within a quarter second of the window showing, and the taskbar lost its
  topmost bit and went from 4th to 31st of 33 windows in the stacking order. At the taskbar's
  2 pixel edge, which is all that shows of a taskbar that hides itself, `WindowFromPoint` then
  gave another window. Both were undone within a quarter second of the engine leaving. One row
  short, 6144x2559, neither happened. A borderless window of another program
  that covers the monitor and has the foreground does the same by itself. The engine itself ran
  the same whether it covered the monitor exactly or not, 116.0 against 116.2 new pictures a
  second over the moving source, with the same stage times, the power within 2 W, and no composed
  presents to that display either way. The lens keeps its sizes even, so it stops two rows short,
  at 6144x2558.
- **A layered window larger than the screen comes up blank.** The windowed chrome is the picture
  plus a title bar plus a border, so over a whole monitor it was 3844x2194 on a 3840x2160 display.
  It existed, was visible and topmost, and drew nothing.
- **What the title bar would say goes onto a notice.** A restart, a screenshot's result and a
  sentence about the fast engine are shown at the top of the lens's monitor, in a window of the
  lens's own that lets every click through, never takes the keyboard and is out of the capture.
  While a program in exclusive fullscreen is in front on the lens's monitor, its first line says
  so, see Nothing of the lens goes into another program. When the lens has fallen behind the
  program in front, a line says so for 12 s, below the lines for a program in exclusive
  fullscreen and for a sentence the lens keeps up to be read, such as the fast engine giving way
  to the ReShade engine, and above the latest message, see The warning under A game in front that
  keeps the card busy. The readout the bar would show is the second line of the menu, kept
  current while the menu is open.
- **A note as the lens goes fullscreen** says that the lens itself is invisible while it goes on
  applying DLSS 5. With Neural Rendering off that first line says so instead, and names the keys
  and the menu entry that bring it back, such as F9 or Turn NR back on in the lens menu on the
  fast engine, and F6, F9 or Turn NR back on in the lens menu on the ReShade engine. Switching
  Neural Rendering while the note is up changes that line in place. Under it the keys as they
  are set make a list, one line for each with what it does. The key for the lens menu, where
  Leave fullscreen is, comes first, then those for the NR settings, Neural Rendering off and on
  and the on-screen readout, and last one line for the arrow keys, Enter and Escape, which work
  the menu and the NR settings panel while one is open. Each line follows a bullet in a column
  of its own, so a line that wraps goes on under its words. A key that is not set, or that the
  lens does not hold, is left out, and with no key for the menu the list starts with a line
  saying that a click on the taskbar button opens the menu. A sentence on the taskbar button's
  list follows the list. The note is a window of the lens's own over the middle of its monitor,
  out of the capture, kept above the picture on the 200 ms timer, and it never takes the
  keyboard, so a game under the lens keeps it. Its OK takes a click without the window being
  activated, and Enter and Escape close it, which the lens holds while the note is up. Ticking
  Don't show this again writes `fullscreen_note = 0` at once, and unticking it takes that back,
  so the tick counts however the note closes. A switch on the Fullscreen page of Settings
  switches the note on again. With one of its keys held by another program it comes up anyway,
  naming the held keys in the warning colour, since such a key then does nothing. A note that
  comes up only for a held key has no Don't show this again, since the note is switched off
  already. A key that another action of the lens holds is named with that action and does not
  bring the note up, see Global hotkeys. While a program in exclusive fullscreen is in front on
  the lens's monitor the note is not shown, and one that is up closes.
- **The menu opens at the pointer**, or at the top left corner of the lens's monitor when the
  pointer is on another one, since a fullscreen lens has no bar or tab to open it from. The keys
  that work it are under Global hotkeys.
- **The on-screen readout** is one line in a window of the lens's own, 12 px in from the chosen
  corner of the lens's monitor, and at the bottom above the two rows the picture leaves free. It
  lets every click through, never takes the keyboard, is out of the capture and is drawn at 90
  percent opacity. The stats line brings it up to date once a second, and it is drawn again only
  when its text or its place changes. The frame rate and the latency are the ones on the menu's
  second line, with no latency while the picture is idle. The quality step is the fast engine's
  and is left out under the ReShade engine. The passes read NR off while Neural Rendering is off,
  and the style is read from the add-on's section of `ReShade.ini`. It is there only while the
  lens is fullscreen and in view and something in `fs_readout` is switched on. The readout's key,
  F10 to begin with, empties `fs_readout` to hide it and fills it again to show it. What a
  readout showed as it went out, by the key or by every figure switched off in Settings, is kept
  in `fs_readout_last`, and the key brings that back, or the frame rate and the latency where
  nothing is kept. `fs_readout_last` is left out of the ini while it holds the frame rate and the
  latency. The key writes the ini as Settings does, so the next start and a Settings dialog
  opened afterwards show what is on the screen, and the log has `readout shown` or
  `readout hidden` with the key. Save in Settings keeps the figures as they are unless they were
  changed in the dialog, so a change made with the key while the dialog was open stays. A new
  text leaves its place among the topmost windows as it was, and the menu, the NR settings panel
  and the note are raised above it. A panel that would open over a readout at the top of the
  monitor, as it would at the top left, where the panel first opens, opens below it instead.
  The readout does not push the fast engine's pictures through the compositor. Over a picture
  changing 120 times a second on one 120 Hz monitor, the engine's median delay read 0.0 ms in
  both runs with the frame rate and the latency shown at the top right, against medians of 0.0
  and 8.3 ms in the two runs with the readout off, at 117 to 119 new pictures a second either way.
- **The picture's window can climb above the chrome** of a windowed lens. The lens walks the
  z-order above its chrome on the 200 ms timer and raises the chrome again whenever the presenter
  is found there. Menus and dialogs are not the presenter, so they stay above.

The fullscreen lens keeps its pass count in `lens-state-fullscreen.txt`, because the windowed
state file is what the way back restores.

### Tweak mode

Tweak mode makes the presenter interactive, gives it the keyboard and posts Home, so the ReShade
overlay opens in place and takes the lens's clicks and keys. It ends in either of two ways, and both
make the presenter click-through again and, while the presenter or another window of the lens's
own is still in front, give the keyboard back to the window that had it, so a key pressed next goes
where the user expects instead of to ReShade:

- **Done** posts Home again, which closes the overlay, and waits for the key's release before the
  styles change back, since dropping the focus makes ReShade forget a key it holds.
- **Home pressed by the user.** It reaches ReShade only while the presenter is the foreground
  window, so the lens counts a press of the physical key only then, reading it with
  `GetAsyncKeyState` as it does F6, and ends tweak mode once the key is up, without posting Home,
  which would open the overlay again. The presses the lens posts itself never show in that key
  state. Measured over flat grey with Home injected, the presented picture matched the grey again,
  the presenter was click-through, and the window that had the keyboard before had it back. Done
  gave the same.

Neural Rendering switched on or off in tweak mode, from the menu or by F9, ends it the same way as
Done before the presenter is replaced, see Nothing of the lens goes into another program.

Replacing the presenter during tweak mode, as Set does, ends it the same way. Measured with Set to
two passes and back, the new presenter was click-through and the keyboard was back with the window
that had it. Both results on the keyboard were measured with the earlier hand-back, which attached
to the input of the window that got the keyboard back. Since 0.6.0 the lens hands the keyboard back
by attaching to the presenter's input, never to that of the window that gets it, see Nothing of
the lens goes into another program. Measured again with that hand-back, tweak mode ended from the
taskbar list as Done ends it left the keyboard with the window that had it before. After Home and
after Set it has not been measured again.

**The fast engine has no overlay to open**, since no ReShade runs in it. The lens's own NR settings
panel takes its place there, with Neural Rendering on or off, the style, the four strengths, the
auto mask, the passes and the quality step. A change goes into the add-on's section of ReShade.ini
at once, with every other byte of the file kept, and the engine is told `reload`, at most about
ten times a second while a slider moves. Measured, a change of the intensity from 0.97 to 0.3
changed one line of the file, 1038 bytes to 1037 bytes, and with the value put back the file was byte
for byte as before. The engine's shot differed from the capture by 5.06 of 255 at 0.97 and by
1.58 at 0.3, and a slider moved 91 times in a second gave 11 reloads. The panel's ranges, 0.00 to
2.00 and -1 for a skin structure left to the model, are the ones the Cost Scaler's ini gives for
the model's settings. A new pass count restarts the picture, since the engine takes the count
when it starts. The panel works from the keyboard as well, with the keys under Global hotkeys.

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
  element being in frame, and the static half of the same image gave the real figure. Check that the
  source is unchanged across samples before trusting any difference in the output.
- **Measure frame rates over a source whose every frame differs.** The presenter counts a capture
  identical to the one before as nothing new. The flipper flips on Tk's timer, every 15.6 ms, so
  it changes about 64 times a second, and a capture near 60 or 40 a second samples it into runs of
  identical frames. A limit of 30 read 16 fps over it and 31 fps over a moving square, and the
  fullscreen "slow state" of about 44 fps at some Cost Scaler scales never appeared over the
  square. A test backdrop can move a square every 8 ms on a 1 ms timer.
- **Establish a noise floor** by capturing the same state twice before trusting a difference.
- **Compare the add-on's `active settings` lines** in `ReShade.log` before comparing effects
  across runs. A setting changed in the overlay between two runs moves the effect by more than
  most code changes, see Effect parity above.
- **Keep the GPU to the lens.** Another process taking the GPU lowers what the lens presents and
  changes the delay, and it does so unevenly. Beside another program that uses the card has the
  figures for the fast engine.
- **Note which window is in front.** A game that kept the card busy held a fullscreen lens 38.5
  to 58.3 ms behind while it was in front, and 16.7 ms behind with another window in front at the
  same frame rate. While the lens is fullscreen, `lens.log` names the class of each window that
  comes to the front. A load with no window is never in front, see A game in front that keeps the
  card busy.
- **A second monitor changes the figures.** With a second monitor connected at 60 Hz, the moving
  source alone drew 52 W where it drew 46 W with one, and the fast engine's meter read -15.0 ms
  where it read -6.6 ms for the same picture, because the compositor then works two refreshes
  ahead of the display in place of one. With the second monitor at 3840x1200 and 144 Hz on
  DisplayPort the meter read -2.7 ms and the delay about 8.5 ms with no limit and 3 ms at a limit
  of 60, where at 1920x1080 and 60 Hz the delay read -8.3 ms in both. Compare runs only within one
  arrangement of monitors.
- **Power drifts, and the baseline has clocks of its own.** The same arrangement read 254 W and,
  a quarter of an hour later, 245 W, and one run's samples spread over about 6 W, so a difference
  under about 5 W cannot be told. A baseline taken with the card's memory clock at 810 MHz read
  7 W below one taken at 7001 MHz, so each row of a table needs its own settled baseline.
- **F6 belongs to the add-on, which reads it through `GetAsyncKeyState`**, the physical keyboard.
  Posted to the window it did nothing in three runs, with or without focus, while one genuine
  keystroke with no focus at all toggled it, measured as the in-to-out difference over the same
  still going from 1.20 to 2.22. So the lens polls the same key the same way to track the state,
  seeded from `NeuralUplift` in `ReShade.ini`. A keystroke of the lens's own would be seen by
  other programs as well, so the lens makes none and switches the state through `ReShade.ini` and
  a restart, see Nothing of the lens goes into another program. ReShade's own keys, Home for the
  overlay and F5 for its screenshot, are posted to the presenter's message queue and held for
  longer than a frame, since ReShade notices a key only when it polls, once per present. Measure
  absolutely anyway, by capturing the region with the lens absent and then with the lens over it.
- F6 is persisted by the add-on as `NeuralUplift=0` in ReShade.ini, so one toggle turns Neural
  Rendering off for every later launch.
- Neural Rendering's strength scales with local detail, about 4.5x stronger on the most detailed
  tenth of an image than on the flattest half. Flat content changing very little is expected.
- **Never assert an absolute difference for Neural Rendering.** The strength depends on what is
  under the lens, so a threshold calibrated on detailed video fails on flat interface content,
  and it fails by looking exactly like a broken feature. Assert the shape instead, that the change
  concentrates in detailed areas. One pair over flat interface measured 1.29 overall, yet 6.21
  on the most detailed tenth against 0.654 on the flattest half, a ratio of 9.5x.
- **The detail ratio is itself content dependent.** It works where the image has genuinely flat
  areas to contrast against. Dense photographic content has none, and a still frame of film footage
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
`%LOCALAPPDATA%\Programs\NeuralLens` by default. The installer holds the lens, with its fast
engine, and nothing of the stack.
Setup fetches the neural stack during the installation, ticked by default, and `neural_stack.py`
runs the same fetch later from a Start Menu entry or the command line, into the install folder
itself, with the Vulkan layer in `ReShade` beside it and the downloads in `downloads` until the
self test passes. The lens keeps its state, logs and screenshots in `data` there too. So an
install is one folder plus one registry value naming the layer, and the uninstaller runs the
exe's own `--uninstall-stack` for the value and deletes the folder. A DLL the user points the
setup at is copied in after its hash check and only the copy is recorded, so an uninstall never
reaches the original.

Nothing of the stack is bundled, and licences force that rather than taste. NVIDIA's runtimes are
NVIDIA's, the RenoDX add-on has no published licence, and the default motion vector estimator is
CC BY-NC 4.0. NVIDIA's runtimes come from the RHI project's manifest, which carries no hashes, so
the hashes live in `neural_stack.py` and a download matching none is refused. The add-on and the
Cost Scaler are pinned releases whose archives and files are checked the same way. ReShade's DLL
comes straight out of its setup exe, which is a zip, with nothing of ReShade's executed.

Facts measured while building it:

- **The RHI manifest's `310.8.SF-v2` build is not the one many people already hold.** Its zip
  unpacks to a file of 165,830,144 bytes, version 310.8.SF.0, unsigned, hash
  6EB209E7..., and the earlier community build is 165,840,496 bytes, version 310.8.0.0, signed by
  NVIDIA with a hash mismatch, hash 8270B350.... Both run Neural Rendering, so both are accepted.
- **The manifest's version names are labels, and they change.** On 2026-09-24 the manifest
  renamed `310.8.SF-v2` to `310.8.2 (20/30/40/50)` and added the Lecram build as
  `310.8.3 (50xx)`, while the SF-v2 zip stayed at the same release,
  `dlssnr-310.8.SF-v2`. The setup had looked the model up by name, so from that day every new
  install stopped at the NVIDIA step with "the manifest has no dlssnr 310.8.SF-v2", and one
  with the manifest unreachable failed outright. The setup now finds an entry by the release tag
  in its link, then by name, and with neither, or no manifest, fetches the file from its release
  directly. The hash decides what is installed. A test checks the lookup against the current
  names, the old ones, a manifest without the model and an outage.
- **A per user Vulkan layer coexists with a machine wide ReShade only under a different name.**
  The loader loads one implicit layer per name, HKLM before HKCU, so a per user copy named
  `VK_LAYER_reshade` is skipped wherever a machine wide one exists. The layer is registered as
  `VK_LAYER_reshade_neural_lens`. This was verified on a machine with the machine wide layer
  present, where the self test attached, loaded both add-ons and evaluated. The same rule means
  two installs of the lens on one account share one layer, whichever was registered first.
- **ReShade starts where it finds a `ReShade.ini`, not where `ReShadeApps.ini` says.** ReShade
  6.8.0 does not read `ReShadeApps.ini`, which belongs to ReShade's own setup program, and its DLL
  holds no reference to the file. Each ReShade stops at once in a program with no `ReShade.ini` in
  its folder, and where a program has one, the first ReShade to load starts and any other stands
  aside. Up to 0.5.1 the lens's layer was on for every Vulkan process, and on 2026-09-30 a
  throwaway program with a `ReShade.ini` beside it got the lens's copy, the machine wide one
  standing aside. With `DISABLE_VK_LAYER_reshade_neural_lens=1` set it got the machine wide one,
  and without the file it got neither. Since 0.6.0 the layer's manifest carries
  `enable_environment` with `ENABLE_VK_LAYER_reshade_neural_lens=1`, and the presenter sets that
  variable for itself before Vulkan loads, so the layer switches on in the presenter alone.
  Measured with that manifest the same evening, the throwaway program with its own `ReShade.ini`
  got the machine wide ReShade, one that set the variable got the lens's copy, and the presenter
  still created the feature and ran 600 evaluations in 20 s. The lens looks for a description
  without the variable each time it starts, see Nothing of the lens goes into another program.

The card is checked by compute capability from the driver's own `nvidia-smi`, 7.5 or higher
meaning the RTX 20 series and newer, rather than by marketing names, and one model serves every card
that passes. The self test runs the presenter on its pattern source in a 960x540 window at the top
left for nine seconds, and reads `ReShade.log` for `feature 18 created` and `evaluation succeeded`,
the Feed's log for its motion vector provider, and the Cost Scaler's log for its load of the real
model. `0xbad00001` is reported as the model refusing the card.

`install-record.json` lists every file written and the registry value set, and
`--uninstall-stack` removes that, plus any layer value pointing inside the install that the record
did not know about. The Inno uninstaller calls it without asking and then deletes the whole
install folder.

**The fast engine in the build.** The spec builds the engine before anything else, by running
`.\build.cmd all` in `fast_engine` through `cmd.exe`, and stops when that fails. Plain `build.cmd`
was not found there, since cmd does not look in the current folder for a program where
`NoDefaultCurrentDirectoryInExePath` is set. After COLLECT the spec copies `lens-fast.exe` into
the program folder as `fast\lens-fast.exe`, because a file PyInstaller 6 collects lands in
`_internal`, where the lens does not look, and runs the copy once with `--help`. `NeuralLens.iss`
refuses to compile without that file and replaces `{app}\fast` whole on an update. `build.cmd`
finds the compiler through `LENS_FAST_VCVARS`, then `vswhere`, then the default folders of Visual
Studio 2022 and 2026, and refuses a Windows SDK older than 10.0.26100, which the capture's
`MinUpdateInterval` needs. The engine links the C runtime statically and imports only Windows'
own DLLs. Measured, the engine build took 5 to 6 s, and with the exe at 491,008 bytes the
installer grew by 146 KB. The engine writes its copy of the proxy's ini beside its exe. The lens
gives it `data\logs\fast` as a folder for the runtime's logs, and the engine passes that folder to
`Init_Ext` with a null feature description, which asks for no logging. On the test computer with
the RTX 5090, where NVIDIA's NGX logging is not switched on, the runtime has written nothing
there. Every such folder on it is empty, those of sessions that ran Neural Rendering included.
`--uninstall-stack` removes the ini and the folder. The setup's summary and
`neural_stack.py --verify` say in one line whether the engine is there.

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
  exists, which is then laid out in 0.6 seconds from the exe.
- **The install folder showed empty, and typing into it changed nothing.** At the offer, the
  lens's own Tk root already exists and is tkinter's default root, so a `StringVar()` without a
  master lived in that interpreter while the entries lived in the setup window's. Every variable
  in the wizard is made on the window's own Tk.
- **Set it up failed with "main thread is not in main loop".** The install thread read the
  fields with `.get()`, which Tk allows from another thread only while the main thread is in
  `mainloop`, and at the offer it is in `wait_window`. The fields are read on the main thread when
  the button is pressed and the thread gets strings.
- **A relaunch after the setup found the incomplete folder again.** The relaunch reused the
  arguments it was started with, so a folder named on the command line or in the ini that led to
  the offer was found first and the offer came back. The wizard returns the folder it installed
  into and the relaunch names it first.

### VORT's includes, and the measure that agrees with the eye

The self test passed with VORT's shader failing to compile, because a still needs no motion
vectors. Four of its includes were missing from a hand picked list, the Feed logged "no known
VORT shader is installed: motion vectors will be zero", and nothing else said so. The setup
fetches VORT's whole include folder and its blue noise texture, and the self test reads the
Feed's provider line and fails on "none".

Sharpness, the variance of the Laplacian of the output frames, cannot see a ghost, since a
second edge adds high frequencies, and a lower frame to frame change can be the ghost itself, a
blend that lags. The measure that agrees with the eye is the partial ink fraction of the page,
the share of pixels between 40 and 160 out of 255 on a black on white page, where crisp text is
bimodal and a ghost adds mid greys. VORT's own options (its rest mode is for engine vectors)
and the Feed's validation values did not change its result.

Three providers the Feed lists were put through the same page at three scroll speeds, plus a
control with no provider enabled at all, which the Feed answers with zero vectors:

```
                                                    slow    reading   fast    licence
ReshadeMotionEstimation (Jakob Wapenhensch)         0.075   0.096     0.102   CC BY-NC 4.0
VORT (Vortigern)                                    0.099   0.109     0.106   MIT, motion vector code CC BY-NC 4.0
dh_uber_motion (AlucardDH)                          0.112   0.113     0.108   GPL-2.0
no provider, zero vectors                           0.114   0.123     -
```

So the default a new install gets is ReshadeMotionEstimation, DRME, the Feed's provider 0
through the shared `texMotionVectors`. It was crisper than the others on this test, and CC BY-NC
4.0 allows it to be fetched and used with credit in a free tool. Two things to know about it. Its
repository publishes no releases and was last touched in 2023, so the setup pins the commit.
And on ReShade 6.8 its first pass, the frame save, fails to compile with "cannot sample from
texture that is also used as render target". The Feed's header warns that DRME then "silently
writes nothing", but measured here the estimator's remaining passes produce vectors that beat
every alternative, and the zero vector control is far worse, so the warning describes a
different case or an older build. VORT is fetched as well and can be chosen instead.

## Settings

Each setting in the dialog is one short label in a 12 point font, and one helper, `Hints`, shows
what a setting does for the whole dialog. An explanation says what its setting does and no more.
It names no card and gives no watts, milliseconds or frame rates, and the measurements behind the
settings are in the README and in this file. The pointer has to rest on a setting for a second
and a half without moving, measured at 1.50 and 1.51 s. The explanation then comes up in a window of
the dialog's with no frame, wrapped at 320 points, 16 pixels right of the pointer and 22 pixels
below it, or above the pointer where the monitor ends. It is out of the capture, never takes the
keyboard and lets every click through, and it goes when the pointer moves off the setting, a
button or a key is pressed, the wheel turns, the page is turned or the dialog closes. Asked for
at the corners of a 6144x2560 monitor, the window stayed inside the monitor. F1 shows the
explanation of the setting that has the keyboard, below that setting or above it where the
monitor ends, for a person who goes through the dialog with Tab. A click on a switch, a choice,
a button or the slider gives it the keyboard, which Tk on Windows does not do by itself. With no
setting holding the keyboard, F1 explains the one under the pointer, beside the pointer as after
a rest. A bare F1 in a hotkey field shows that row's explanation too, and Ctrl, Alt or Shift
with F1 can still be set there. The window shows the space between a number and its unit, and
the one after RTX, as a space that does not break. Tk on Windows keeps such a pair on one line,
so no line ends with "10" while the next begins with "ms".

The dialog is as high as its tallest page, so the fullscreen settings have a page of their own
and not a third section on the Power page. The Hotkeys page is the tallest. The dialog is 723x689
at 100 percent display scaling, 816x822 at 125 percent and 947x984 at 150 percent, which fits a
1920x1080 screen at all three with nothing cut off on any page.

What Tk does that the dialog depends on:

- A wrap length given in points keeps the same number of letters to a line at every scaling.
- A `tk.Button` asks for one and a half lines of height plus its border, 40 pixels at 10 point
  and 125 percent, and 34 pixels with no border.
- A key event made for a window is dropped unless that window has the keyboard.
- Asked for its text, an `Entry` gives the name of its variable.

## Themes

Every colour the lens draws comes from one table, `THEMES` in neural_lens.py, resolved once at
start into the constants the rest of the file always used, BG, FG, ACCENT, DIM, WARN, CAP and the
four that used to be literals, HOVER, FIELD, TAB_BG and CLOSE. The chosen theme is `theme` in the
ini, and `themes.json` in the data folder is laid over the table, a theme there with a built-in
name replacing it and a theme missing keys taking them from Slate, so a theme can be made without
touching the program. A theme takes effect at the next launch because the colours are baked into
the widgets when they are built, so choosing one in Settings restarts the lens, as the folders do.
The picture is never touched, since the presenter draws nothing but the picture.

## The title bar hidden

Hiding the title bar reuses the attached chrome, the two pixel line and the tab, without the
follower. The picture does not move or restart, since only the chrome changes. The tab drags the
whole lens by running the bar drag handlers, a click without movement opens the menu, and the
right button slides the tab along the edge. The tab has to be re-raised every time the picture
is, since both are topmost and the picture is put back on top whenever something covers it.
`raise_chrome` does that, which the first probe found missing when a real click on the tab
reached the picture instead. A fullscreen lens has no chrome in view, so hiding does nothing
there, and a lens whose bar is hidden goes fullscreen with neither line nor tab and comes back as
it was. In the code this state is called folded. Verified with a test that hides the bar, uses
the tab with real clicks, and goes fullscreen and back.

## Upstream versions and what was measured against them

On 2026-09-21 the projects the stack draws on stood at ReShade 6.8.0, DLSSNR-Cost-Scaler 1.0.6, DLSS5-Feeder v1.16.0-beta.6 and RenoDX DLSS 5 6.5.3, and the RHI manifest still named 310.8.SF-v2 as the newest Neural Rendering model. The Feed at beta.6 is what the 0.4.0 installer fetched, since the stack takes the newest full release and checks the zip against the SHA-256 the maintainer prints, and the whole suite passed on it, 118 of 118. RenoDX 6.5.3, and 6.4.1 before it, carry no release notes. Against 5.2.1 the add-on gains eighteen section keys, per pass colour, intensity and transfer among them, and loses NRAdaptiveExposure and NRDiffuseWhite, with the keys the lens reads unchanged. It also migrates the section from schema v2 to v6 in memory, backing the ini up beside itself. Run in the presenter, 6.5.3 loads, pre-loads the NR runtime, installs its queue completion tracker on the D3D12 command queue, and the process then dies with 0xC0000005 before any feature is created, in twenty seconds of the pattern source, where 5.2.1 in the same stack builds the feature and evaluates it. So the stack stays pinned to 5.2.1 by hash. Measured with a test that takes a before and after pair over the still, and with a presenter run on its own. The crash leaves no Windows error event, but the Feed writes a minidump beside itself, dlss5-feed-crash.dmp. It shows an access violation reading 0xEB9A4188, a 32 bit value where a pointer belongs, inside nvoglv64.dll, the NVIDIA Vulkan driver, on the presenter's main thread, with renodx-dlss5.addon64 and ReShade's Vulkan hooks above it on the stack. So 6.5.3 hands the driver a bad handle from inside ReShade's hook before the feature exists, and no ini setting is involved.

ShortFuse's own renodx-dlss add-on, which the RHI repository also publishes as `renodx-dlss-SF` builds, hooks D3D11 and D3D12 only as of its 2026-09-17 build, so it does nothing on the Vulkan presenter and is not a swap for renodx-dlss5.

On 2026-09-28 the stack's sources stood at ReShade 6.8.0, DLSSNR-Cost-Scaler 1.0.6, DLSS5-Feeder v1.17.0 and RenoDX DLSS 5 8.5.0-rc10, with NVIDIA's DLSS runtime at 310.9.1 and the manifest listing the Lecram model as `310.8.3 (50xx)`. Each was measured against the shipped part with a test that runs both the same way in a copy of the installed stack, with the presenter on its test pattern, a before and after pair over the still, frames per second over the whole monitor, and the harnesses. That was on an RTX 5090 with driver 617.14, where two runs of the same stack give pictures 0.2 to 0.45 of 255 apart.

- **DLSS5-Feeder 1.17.0** is what a new install fetched then. With it the feature is created and evaluated, the picture is 0.26 of 255 from beta.6's, and the harnesses pass 145 of 145.
- **RenoDX DLSS 5 8.5.0-rc10** migrates the section's schema as 6.5.3 does but does not crash. It logs NOT_ENGAGED at each stage of warming up, then ENGAGED, and evaluates 600 times in 20 seconds, with a picture 0.21 of 255 from 5.2.1's. The pin stays at 5.2.1 until an 8.x release is final and the lens's profiles, which rewrite the section, are checked against the new schema.
- **The Lecram model**, hash F95FEB54..., gives the same picture, 0.28 of 255, at 40.6 against 40.0 frames per second fullscreen at one pass, the same in both pairs of runs. It covers RTX 50 only, where SF-v2 covers RTX 20 through 50, so SF-v2 stays.
- **NVIDIA's DLSS runtime 310.9.1** gives the same picture, 0.27 of 255, so 310.8.0 stays.

A newer add-on reads NOT_ENGAGED in the presenter's log until its first evaluation, so its last verdict line is the one to judge by.

On 2026-10-03 a new 0.6.0 install fetched DLSS5-Feeder v1.18.0-beta.1, published on 2026-09-29, beside ReShade 6.8.0, which the stack pins by its version, and DLSSNR-Cost-Scaler 1.0.6 and RenoDX DLSS 5 5.2.1, which it pins by hash. Measured the same way against v1.17.0 on the same computer and driver, the presenter on its own creates the feature once and evaluates 600 times with either, and the picture is 0.27 of 255 from v1.17.0's, the same within noise. Fullscreen at one pass, two runs gave 40.1 and 40.0 frames per second against 40.3 and 40.0 with v1.17.0, 0.2 percent lower on average and within noise. The harnesses all pass. The zip also holds a new `dlss5-feed-helper.addon64`, which the stack does not take, since it takes only `dlss5-feed.addon64` and `DLSS5_Feed.fx`.
