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
reads `nr 1|0`, `reload`, `settle 1|0` and `quality N`, and prints `engine quality N work WxH`,
`engine remake failed, shared on|off, preset N, REASON` where a reload asked it to make its
network again and it could not, see Each pass's values, and, as its last line when it fails,
`engine failed REASON`. Its stats line carries the presenter's pairs and then `shared=on|off`
and `network=MS`, the network's GPU time a picture as the mean over the second's runs, `nan`
where it did not run, see The quality steps for what the lens does with it. The lens finds its
window by its process id and its class, `NeuralLensFast`.

No ReShade and no add-on run in it. It loads the stack's `nvngx_dlssnr.dll`, which is the Cost
Scaler's proxy, by its full path, and through it NVIDIA's model, and creates and evaluates NGX
feature 18 on its own D3D12 device with a parameter object of its own. The call order and the
parameter names follow openNR's native adapter, whose MIT notice `nr.cpp` carries. No NVIDIA
header is included, and the runtime's functions are found with `GetProcAddress`. The six settings it
gives the model, the style, the intensity, local tone, local structure, skin structure and the auto
mask, are read from `ReShade.ini` at the start and again on `reload`, for each pass, with the
add-on's UI correction and preset beside them, see Each pass's values. The model's motion vector
and depth inputs are 1x1 textures of zeros. With full-size textures of zeros the output was the
same byte for byte, on 21 MiB more video memory.

One frame goes through five stages:

```
capture     the region under the lens is copied on the card, in the capture's own callback,
            into a texture that the D3D12 device shares
ingest      one compute pass downscales the region to the work size by area and compares
            every texel with the frame before
network     the model runs on the downscaled copy, once for each pass, each at its own values,
            and with the strength above 1 the change the passes made together is scaled on the
            last pass's output, see Each pass's values
composite   one triangle drawn straight into the back buffer:
            original + (bilinear(network output) - bilinear(network input))
present     a flip model swapchain in a click-through window that is out of the capture
```

A frame equal to the last ends at the comparison, and nothing is drawn for it. At the Full step,
and at Quality for a picture within 2560x1440, the work size is the picture's own size, and the
ingest copies the picture as it is. The composite adds only what the network changed, scaled up, to
the original at full size, so the original's own detail is kept at any work size. It is the same
kind of residual blend as the Matched Residual of xenmods' DLSSNR-Cost-Scaler (MIT), which the lens
has used since 0.2.0. The window stays hidden until the first picture has been presented, 0.63 to
0.72 s after the process starts, and the engine is gone 0.09 to 0.12 s after the lens closes it.

What the stages cost without a window, on an RTX 5090 with a 6144x2526 picture and a work size of
2560x1053. These are GPU times from timestamp queries, the medians of 300 frames after the first 120:

```
ingest, the downscale and the comparison     0.09 ms
network, one pass                            3.35 ms
composite                                    0.10 ms
the whole frame                              3.54 ms
a frame equal to the last                    0.07 ms
```

Two passes took 6.69 ms in the network. Creating the network took 255 to 270 ms in the self tests,
and 393 ms for two passes. The engine held 910 MiB of video memory. With the network's strength at 0
on every pass the engine leaves the network out. A run through it at that strength gave the original
byte for byte in 3.34 ms. On screen at the same picture size, the capture's callback took 0.08 to
0.13 ms of processor time a frame and the present call 0.13 to 0.18 ms, and the engine used 0.06 to
0.11 of a core.

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
- **With Windows HDR on, the frames are 16-bit floats.** For a monitor with HDR on, the frame pool
  and the four textures are `R16G16B16A16_FLOAT`, 8 bytes a texel, so at 3840x1198 the four take
  140 MiB where they take 70 MiB in 8 bits. A capture that starts with the other format makes the
  textures again, once the frames on hand have been let go. See HDR.
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

Above 2560x1440, where only the Full step works, the line no longer holds. At the picture's own
size the network took about 0.9 to 1.0 ms a pass for each megapixel. That was measured the same
way, on the Blender picture resized to each size at the test stack's values, and at 6144x2560 on
three frames of a game at the values given under The quality steps. Video memory is the engine's
after the timed frames:

```
work size    megapixels   one pass    two passes           video memory at one and two passes
3840x2160     8.29         7.27 ms    14.72 ms             1395 MiB    2423 MiB
6144x2560    15.73        14.29 ms    27.89 to 28.74 ms    2192 MiB    3877 MiB
7680x4320    33.18        32.42 ms    65.80 ms             4511 MiB    8178 MiB
7680x6144    47.19        48.26 ms                         6212 MiB
```

The ingest took 0.21 ms and the composite 0.11 ms at 6144x2560. The runtime makes no feature
above an area of about 47 megapixels. 7680x6144 was made and ran, and 7680x6272, 48.17
megapixels, was refused with `0xBAD00002` within 1.3 s, as was every larger size tried up to
16384x8192, with 26 GB of video memory free. A side alone is not the limit, since 8256x4320 and
4096x8256 were made. So the engine holds the Full step at Quality for a picture above 7680x6144
texels in area, with a note at the start and on a `quality` line, and its ready line and its
answer name the step in use. No monitor comes near it, a picture at 8K being 33 megapixels.

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
`common.cpp` gives them, on multiples of 128 wherever a side is resampled. The Full step needs
neither, since nothing is resampled there, and nor does Quality for a picture within 2560x1440.
`lens-fast.exe --steps W H` prints the six sizes for a picture.

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
where every step but Full is a downscale and Balanced showed no loss against the picture fitted
into 2560x1440, and Quality for a picture within it, where Quality is the picture's own size.
Full is never the default. The engine applies the rule when it is given no `--quality`, and
names the step in its ready line, before the shared state and the HDR state that end the line.

**5 Full** has the network work on the picture at its own size, however large, with nothing
resampled, see The work size, and what the network costs, for its time and its limit. It is not
in the tables above, which hold each step against the picture fitted into 2560x1440, and for a
picture within 2560x1440 it is the size of Quality. `--quality 5`, `quality 5`, `--switches` and
profiles take it, and its ready line says `quality 5`. Without a window at 6144x2560, on the three
frames of a game below at two passes and on frame 3 at one pass, the Full step's picture was byte
for byte the picture of a run at `--work-size 6144 2560`, and a run that switched from Balanced
to Full, back and to Full again gave each step's picture byte for byte. The one-pass rows of
frames 1 and 2 in the table below are runs at `--work-size 6144 2560`, the size Full works at.

**Against the picture's own size.** Three frames of a game at 6144x2560, taken with nothing
applied, went through the self test with two passes, every pass at style Default, intensity 1,
local tone 1, local structure 1, skin structure 1 and the auto mask on, with a network for each
pass, and each picture after 420 frames on the still. Frames 2 and 3 are one scene a moment
apart. The model the stack installs and NVIDIA's stock 310.8 gave the same pictures byte for
byte. Each picture against the one at Full from the same frame, as the mean absolute RGB
difference of 255 over the whole frame, then the picture's own change from the frame, the
correlation of its change in luma with the change at Full, and the change in mean luma over a
face:

```
frame   work size, passes            from Full   change   correlation   face
1       6144x2560 Full, two            0.00        9.98      1.000         -9.53
        2560x896 Balanced, two         8.80       10.53      0.605        +12.36
        6144x2560 Full, one            4.62        5.54      0.975         -8.62
        the frame, no network          9.98
2       6144x2560 Full, two            0.00       11.72      1.000        -35.45
        2560x896 Balanced, two         9.26       11.46      0.693        -19.59
        6144x2560 Full, one            5.66        6.32      0.976        -24.30
        the frame, no network         11.72
3       6144x2560 Full, two            0.00       12.00      1.000        -36.41
        4608x1920, two                 5.03       11.40      0.914        -30.94
        3072x1280, two                 7.70       11.53      0.797        -25.22
        2560x1024 Quality, two         8.92       11.62      0.728        -23.12
        2560x896 Balanced, two         9.55       11.56      0.685        -19.80
        6144x2560 Full, one            5.73        6.55      0.977        -24.79
        the frame, no network         12.00
```

So on a large screen Balanced makes a change as large as Full's but in other places, and its
picture lands nearly as far from Full's as the frame with no network. The distance falls steadily
as the work size grows. On frames 2 and 3 a face that Full darkened by 35.45 and 36.41 of 255
darkened by 19.59 and 19.80 at Balanced, and on frame 1, where Full darkened it by 9.53, Balanced
brightened it by 12.36. One pass at Full makes about half the change of two.

**Against the network at a game's Present.** Both scenes were also taken in the game with the
network applied at its Present, on its finished frame at its own size of 6144x2560, by the
renodx-dlss add-on, see Upstream versions and what was measured against them, in its build of
2026-10-03. It ran at the values above with two passes, each with a network of its own, and with
the model above. Those pictures were taken moments apart from the frames, with the camera moved
slightly between them, so each of the engine's pictures was moved onto the add-on's by an optical
flow on locally normalised luma before the comparison. The add-on's open panel and the game's
interface were left out, which leaves about 72 percent of the frame. The distance is the mean
absolute RGB difference of 255 over that area without the parts that move, the character among
them, and over all of that area in brackets. The factor is the size of the change at the Present
as a least-squares multiple of the engine's change, 1 being the same size. Against frame 3:

```
the engine's picture                        distance        correlation   factor
the frame, no network                       10.90 (12.61)
6144x2560 Full, two passes                   1.68  (2.22)    0.985         1.00
4608x1920, two passes                        5.04  (5.69)    0.892         0.95
3072x1280, two passes                        7.57  (8.31)    0.759         0.78
2560x1024 Quality, two passes                8.64  (9.42)    0.692         0.70
2560x896 Balanced, two passes                9.22 (10.00)    0.646         0.66
6144x2560 Full, one pass                     5.48  (6.33)    0.960         1.74
6144x2560, two passes through one network   12.33 (13.02)    0.825         0.48
two frames of the game with no network       1.05  (1.61)
```

Against frame 2, a larger move of the camera away, two passes at Full were 2.31 (2.96) of 255
from the picture at the Present and Balanced 9.27 (10.12), where the frame with no network was
10.96 (12.74). Against frame 1, in the other scene, two passes at Full were 1.14 (1.75) with a
factor of 1.03, Balanced 8.24 (8.99), and the frame with no network 9.31 (9.82). So two passes
at the frame's own size come within about the measuring floor of the network at a game's Present,
in tone, in detail, on faces and on the interface alike, and every smaller work size lands
further away. One pass makes a little over half the change, and two passes through one network
about twice it. The engine of 0.6.1 gave the picture of 1 at an intensity of 1.8 or 2.0, byte for
byte, since the network holds its own intensity at 1, see Each pass's values. The add-on had the
game's depth and motion vectors and a 10-bit swapchain, which the engine does not use, and the
frames were near still, so motion was not compared.

`quality N` changes the step while the engine runs. The network for the new size is made beside
the one in use, on a second thread, in 116 to 198 ms at a work size up to 2560x1440, and longer
at Full on a large screen, below, while the loop goes on drawing new pictures with the network's
last change. On screen the first picture at the new size came 132 to 158 ms after the command and
no picture stood longer than 24.8 ms. Made on the loop's own thread, the new network held the
picture for 112 to 157 ms. The stack gives a replaced network up only after the new one has run
between 33 and 64 times, and its video memory comes back about 10 s later, inside the next run.
So a picture at rest after a switch goes through the network 64 times, and once more 14 s later,
unless the settle is switched off. Over 24 switches without a window the engine went from 847 MiB
to 1371 MiB at the most and was back at 847 MiB 10.2 s after the last. A switch from Balanced to
Full at 6144x2560 with two passes was made in 302 to 320 ms, 287 to 307 ms of it the creation,
143 to 154 ms a pass, and while both networks were held the engine had 5763 MiB of video memory,
3877 MiB after. The switch from Full back to Balanced in the same run took 464 ms, 453 ms of it
the creation, the longest switch measured.

The engine answers a step it is told with the step it runs, `engine quality N work WxH`, and
where it could not make the network for the step, it answers the step it had. The lens holds that
answer against the step it told. An answer that differs counts once it has stood for 3 s with no
other after it, since the engine takes only the last of several steps told together and answers
each switch it makes. The lens then goes by the engine's step, keeps it as `fast_quality`, so the
next start does not ask for a step the card could not make, tells the engine that step and says
so on the notice for 8 s, with a line in its log. A step given at the start is held against the
ready line the same way. A fast engine whose pipeline fails at its start at Full on a picture
larger than 2560x1440, where the network for Full is made at the picture's own size, has the lens
go by the default step for the picture, take `fast_quality` out of the ini, say the same words on
the held notice, log a line and start the engine once more. That start asks for the default step,
and a second failure rules the fast engine out for the run as any failed start does. On a picture
within 2560x1440 Full is Quality's size, so a failed start there is not Full's doing and goes
straight to the fallback. Checked without a window with a stand-in engine that prints
`engine failed pipeline: ...` and ends.

The warning that the lens runs behind goes by the network's time on the engine's stats line, see
The fast engine. The lens keeps the median of it over each 10 s span beside the delay's median,
and its summary line ends with it. A picture is shown at a refresh once the network has run on
it, and with the engine by itself over a picture that changed at every refresh, see Frames a
second and power at each step, the median delay came within about 4 ms of the network's time and
one refresh, at Balanced and at Full, with one pass and with two. So at Full, where that median
with one refresh more reaches the three refreshes the warning counts from, less the tenth of a
refresh allowed, the lens would be past the line with no program in front, and the warning names
the step as the cause and a lower step as the way out, since no limit in the program in front
could bring it under. Where the network takes less, the warning is the one of every step, which
puts the delay down to the program in front. For the Full words the network's time has to reach
about 15.8 ms at 120 Hz, 16.0 ms at a rate Windows gives as 119 Hz, 13.2 ms at 144 Hz, 7.9 ms at
240 Hz and 31.7 ms at 60 Hz. At 6144x2526 on screen it took 18.6 ms at Full with one pass and
38.1 ms with two, so both get the Full words there. Without a window it took 7.3 ms a pass at
3840x2160 and 14.7 ms for two passes, and on screen it takes longer than without one, so on such
a screen the words go with the refresh rate and with what else the card does.

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

With the build of 0.7.0 on 2026-10-06, and a second monitor at 3840x1200 and 144 Hz connected in
place of the one above, the engine ran by itself at 6144x2526 over the same scrolling picture,
with no limit, for 60 s after 10 s to warm up. The source alone drew 70 to 78 W, and 72 to 82 W
for the rows at Full, which ran later the same day. Power is the median of the samples a second
apart, and the delay is the engine's own median. Shared is two passes through one network, the
second through the first pass's, see Each pass's values:

```
step, passes                  new a second   network    delay     power
3 Balanced, one pass          120.2          3.48 ms    10.6 ms   226 W
3 Balanced, two passes         75.5          7.51 ms    15.0 ms   261 W
3 Balanced, two, shared        75.0          7.55 ms    15.1 ms   261 W
5 Full, one pass               40.3         18.62 ms    29.2 ms   408 W
5 Full, two passes             24.2         38.11 ms    42.5 ms   472 W
```

Two passes through one network cost what two passes with a network each cost, within the
spread between runs, and the engine held 929 MiB of video memory at its start with them against
1294 MiB with a network each and 920 MiB for one pass.

The rows at Full ran in a series of their own with Balanced beside them again, which showed
120.2 new pictures a second, 3.64 ms, 10.5 ms and 234 W at one pass and 74.6 a second, 7.54 ms,
15.2 ms and 257 W at two. Above the source alone the card drew 156 W and 184 W for those, against
156 W and 187 W in the rows above, so the card's whole draw moves with the source's from one series
to the next. At Full it drew 328 W above the source alone with one pass and 390 W with two, and
the card was 83 and 95 percent busy, against 64 and 71 percent at Balanced. The engine held 2283
MiB of video memory at its start at Full with one pass and 3968 MiB with two. On screen the
network took longer than without a window, 18.6 ms against 14.3 ms for one pass and 38.1 ms
against 27.9 to 28.7 ms for two, while the card also composed the picture that changed at every
refresh, which by itself kept it 20 percent busy. Over a picture that changed 25 times a second
the same two passes took 27.3 ms.

Over a still picture at Full with two passes the engine came to rest as at the other steps. The
settle ran its four runs within a second of the picture's stop, and after that no new picture was
made and the network did not run for the rest of the minute, with 15 repeats a second. The card
drew 52.2 W, 0.9 W above the still picture and the desktop alone, which drew 52.2 W before and
50.4 W after.

### Each pass's values

The engine runs the network once for each pass, and since 0.6.1 each pass at values of its own. The
first pass runs at the six values of the add-on's section, `[RenoDX.DLSS5]`. Every pass from the
second on starts from them and takes a value of its own where `ReShade.ini` holds one:

- **The style, local tone, local structure, skin structure and the auto mask** of a pass from the
  second on come from a section of the lens's own, `[NeuralLens.Passes]`, as `Pass<n>Style`,
  `Pass<n>LocalTone`, `Pass<n>LocalStructure`, `Pass<n>SkinStructure` and `Pass<n>AutoMask`, with n
  the pass's number. The add-on never reads that section, so on the ReShade engine every pass runs
  at the first pass's values for these.
- **The intensity of passes 2 to 4** comes from the add-on's own keys, `NRPass2Intensity`,
  `NRPass3Intensity` and `NRPass4Intensity` in its section, which the add-on keeps for those passes
  and its overlay can change, so that where the section holds them the two engines run those passes
  at the same intensity, see What is not measured. The engine reads the add-on's key ahead of the
  lens's own `Pass<n>Intensity`, which counts only where the add-on's key is missing, and the first
  pass's intensity counts where both are. A pass ticked Same as pass 1 on the panel has
  `Pass<n>IntensityTied` in the lens's section and runs at the first pass's intensity, whatever the
  add-on's key says. For such a pass the lens keeps the add-on's key at the first pass's intensity,
  for the add-on, and the tie holds the value the lens last wrote there. Before each picture starts,
  a tie whose add-on key still holds that value takes the first pass's intensity, which the overlay
  may have moved, and a tie whose key holds another value goes, since the overlay then gave the pass
  an intensity of its own.
- **The intensity of passes 5 to 8**, which the add-on has no key for, comes from `Pass<n>Intensity`
  in the lens's section. The lens runs four passes at most, so only the engine run by hand with more
  passes reads these.

Nothing is taken for a tie because two numbers are equal. A pass with no key of its own for a value
runs at the first pass's. The lens's section also holds `SharedNetwork`, whether the passes after
the first run through the first pass's network, see Passes through pass 1's network below, and
`ScaleChange` with `Strength`, whether and how much the change is scaled, see An intensity above 1,
and the strength below, which the engine reads at any pass count. The section's header stays in
the file once every key in it has gone. `NRPass4Color`, which the add-on also keeps in its
section, belongs to the add-on's own colour stage, which the engine does not have, and is left as
the add-on wrote it. The stack setup keeps the lens's section byte for byte on a repair, and on an
update that runs it, see The add-on's defaults on a new install.

Up to 0.6.0 the engine ran every pass at the first pass's values. So a fullscreen lens at two passes
or more now draws another picture where the add-on's keys for passes 2 to 4 differ from the first
pass's intensity. In the stack the tests ran on they read 0.94, 0.6 and 0.36, with the first pass at
0.97. Ticking Same as pass 1 for a pass's intensity on the panel runs that pass at the first pass's
intensity again, as 0.6.0 did. A new install's section holds none of these keys, see The add-on's
defaults on a new install, and there the engine runs those passes at the first pass's intensity.
Once the first pass's intensity is moved on the panel, the panel writes the add-on's keys for passes
2 to 4 at that intensity, ticked Same as pass 1, so from then on the add-on runs those passes at it
as well, see What is not measured.

The engine reads each section of the file in one read, and only the passes it runs, so at one pass
it does not read the lens's section at all, and one pass draws the same picture byte for byte as
before. On an RTX 5090 a read took 0.034 ms at one pass and 0.056 ms at two and at four passes, the
median of 2000 reads. The network runs when any pass within the count has an intensity above 0, and
a pass at 0 among others hands its input on unchanged. On `reload` the engine's note names the first
pass's values and each value of another pass that differs from them, such as
`pass 2: intensity 0.30`, and so does its note as the network is made, such as
`nr: pass 2 has its own intensity 0.94`.

With `--passes 2` or more the self test draws one picture five ways, each the network's first
picture of the frame: every pass at the first pass's values, the second pass at half the strength,
every pass alike again, the second pass at another style, and the first pass at half the strength
with the second at the values every pass started from. On an RTX 5090 at 2560x1053, the second at
half was 1.372 of 255 from the first picture and the other style 2.285 of 255, the third picture was
the first byte for byte, and the first pass at half was 1.534 of 255 from the first picture and
0.356 of 255 from the second at half, with the network at 6.659 ms for the two passes. The check
would not catch a swap of the two passes' values. Where the strength in the file is 0, a pass at the
values every pass starts from gives its input back, and half the strength is taken as 0.5. The
second pass at another style then draws the first picture again, and the first pass at half draws
what the second at half draws, so the self test does not judge those two comparisons there, and its
line and `timings.json` name them. Over a still at 6144x2558 with two passes, the lens's pictures
with the second pass's intensity at 0.3 of its own and tied to the first pass were 6.975 of 255
apart on average and 46 of 255 at most, and tied again the picture was the same byte for byte.

**An intensity above 1, and the strength.** The network holds its own intensity at 1. On the game
frames under The quality steps, 1.8 and 2.0 gave the picture of 1 byte for byte, with the model
the stack installs and with NVIDIA's stock 310.8, through the proxy with its scaling off, which by
its source hands the value on as it is, and over the Blender picture at 2560x1053 `NRIntensity=1`
and `NRIntensity=1.6` gave one composite byte for byte. The engine hands the runtime the value as
the file gives it, as 0.6.1 did, so an intensity above 1 draws the picture of 1 on the fast engine.
The add-on holds it at 1 too. Through the lens over a character still at 1400x1000, with style
Default, local tone 1.86, local structure 1.01, skin structure 1, the auto mask off and Denoise
before upscaling on, the ReShade engine's picture at `NRIntensity=1.6` was 1.19 of 255 from its
picture at `NRIntensity=1`, its change 1.006 times as large, where two runs at 1 lay 1.19 of 255
apart. A stronger picture comes from the strength, the lens's own. `ScaleChange=1` in
`[NeuralLens.Passes]`, which the switch Scale the change on the NR settings panel writes, switches
it on, with `Strength` from 1 to 2, which its own slider writes, the slider in view only while
the switch is on. The engine reads both at any pass count, at the start and on `reload`, and
holds a value outside 1 to 2 at the nearer end with a note, `settings: Strength is 3.00, outside 1
to 2, so the strength is held at 2`, and a missing `Strength` at 1 with a note. With the strength
above 1, once the last pass has run, a compute shader, `scale_cs.hlsl`, scales the change the passes
made together in place on the last pass's output, against the network's input, which the first
pass read. The output becomes the input plus the change times the strength, on the 0 to 255 scale,
rounded to a whole level as the composite rounds, a half going up, and held within 0 to 255, and
the composite adds that change. It does so in standard range and in HDR alike, since both
composites read the same two textures, which no run with Windows HDR on has measured, see What
is not measured. At a strength of 1, with the switch off or the keys missing, the shader does not
run and the picture is what it was, byte for byte. A change of the strength alone keeps the
network's history, since the network is given nothing new. The shader reads the output through a
typed unordered access view, which the device has to be able to load `R8G8B8A8_UNORM` through,
and where it cannot, the strength counts as 1 with a note. The settings note on `reload` says
`strength off` or `strength 1.60, the change times it`, and the start's `loop:` line names the
strength where it is above 1. Over the Blender picture at 2560x1053 with the test stack's values,
the self test's reference picture, the change from the picture was 3.418 of 255 at a strength of
1, 5.356 at 1.5 and 6.833 at 2, which is 1.57 and 2.00 times, and with two passes through one
network 6.078, 9.220 and 12.076, which is 1.52 and 1.99 times. The ratios are not the strength
exactly. A change of an odd number of levels times 1.5 ends in a half, which goes up, so a
brightening change grows by half a level more and a darkening one by half a level less, and on
this picture that left both ratios at 1.5 above the strength. At 2 nothing is rounded, and the
hold within 0 to 255, which only shortens a change, left the ratios at 2 a hair under it, 1.999
and 1.987. At each the network's output was the scaling of the output at 1 done on the CPU, byte
for byte, and at 1 again the picture was the first byte for byte. Through the file,
`Strength=1.6` gave the baseline's output scaled by 1.6 byte for byte, `Strength=3` the
baseline's scaled by 2, and `ScaleChange=0` with `Strength=1.6` the baseline's three files byte
for byte. Over that character still at those values, with two passes through one network and the
second at the first pass's values, which is that look on the fast engine, see Passes through pass
1's network below, the fast engine's picture at a strength of 1.6 changed the still by 54.8 of 255
against 35.6 for the ReShade engine's at `NRIntensity=1.6`, 1.54 times as much, and lay 19.3 of
255 from it, where with the switch off the two engines' pictures lay 1.4 of 255 apart. So only
the fast engine draws the stronger picture, as the panel's foot says.

**Passes through pass 1's network.** `SharedNetwork=1` in `[NeuralLens.Passes]`, which the switch
Runs through pass 1's network on the tab of pass 2 of the NR settings panel writes, has every pass
run through the first pass's network feature, each pass at its own values, so one history serves
all the passes. The key is one for every pass after the first, so the tabs of passes 3 and 4 show
the switch greyed at the key's state, with the note `follows pass 2` beside it, and only the tab
of pass 2 changes it. The tab of pass 1 has no row for it, so at one pass the panel shows none,
and the key stays in the file as it was. The engine reads it at the start and on `reload` with two
passes or more. With one pass it changes nothing and the engine says `shared off`. `0`, a word or
no key at all is off, so a profile saved before 0.7.0, whose section lacks the key, loads with it
off. Only the first pass's feature is made while it is on. A `reload` that changes it, or the
preset below, makes the features again at the work size in use, on a second thread as a quality
step does, while the pictures go on with the network's change as it stood, and the history then
starts again. On screen over a 1400x1000 picture the note
`loop: the network was made again at 1400x1000, preset N, shared on|off` came 0.17 to 0.27 s
after the `reload`, the features made in 118 to 247 ms. The engine's ready line says `shared on`
or `shared off` before the HDR state, and its stats line carries `shared=on` or `shared=off`,
each as the features were last made. The lens's readout says shared by those lines, so it follows
the engine and not the file. Where the features cannot be made again, the engine runs on as they
were made and prints `engine remake failed, shared on|off, preset N, REASON`, with the state it
runs in. Where that state is not the one the key gives at the pass count, the lens says so for
the switch on the notice for 8 s, beside the switch until the engine runs as the key has it, in
place of the note on the tabs of passes 3 and 4, and in its log. Where it is the one, as after a
profile with another preset and the same switch, or at one pass, where the key changes nothing,
the switch was not what failed, and the notice and the log say that the network could not be
made again for the new settings and that the engine runs on with the network it had.
`LENS_FAST_ONE_FEATURE=1` forces the passes through one feature as the key does, see Switches for
tests. The ReShade engine never reads the key. The switch leaves each pass's values as they are,
so where the add-on's key for pass 2 holds another intensity than the first pass's, as 0.94
against 0.97 in the stack the tests ran on, the second pass runs at that unless Same as pass 1 is
ticked for it.

On the ReShade engine the add-on's Denoise before upscaling, `NRPreUpscale=1`, runs the network
twice for each picture through one feature, see Passes inside the add-on, and this is that look in
the fast engine. Measured on an RTX 5090 over a character still at 1400x1000, the engine's self
test at the picture's own size against the ReShade engine's picture of the same still through the
lens, with Denoise before upscaling on and off, pre-upscale on and off below, at two sets of
values. The tests' values are style Default, intensity 0.97, local tone 0.99, local structure 0.41,
skin structure 0 and the auto mask off, and a user's own values are style Default, intensity 0.46,
local tone 1.86, local structure 1.01, skin structure 1 and the auto mask off. With two passes the
second ran at the first pass's values, and the distance is the mean absolute RGB difference of 255:

```
values               fast engine                       to pre-upscale on   to pre-upscale off
the tests' values    one pass                          13.20                0.72
                     two passes, a network each         4.15                9.39
                     two passes, shared                 0.91               13.50
a user's own values  one pass                           6.23                0.77
                     two passes, shared                 0.72                6.32
```

The windowed pictures with pre-upscale off and on are 13.26 and 6.21 of 255 apart at the two sets
of values. At the tests' values the shared picture darkens the still by 1.83 in mean luma, where
one pass darkens it by 0.37. At a user's own values it brightens it by 1.35, where one pass
brightens it by 0.62, so the switch's explanation says that the change comes out stronger and no
more. The windowed picture is softer. With pre-upscale on it kept 0.35 of the still's fine detail
at a user's own values, as the variance of the Laplacian against the still's, where the shared
picture kept 0.74 and one pass 0.83. The difference that is left sits on the edges, at a user's
own values 1.42 and 3.59 of 255 in luma on edges and strong edges against 0.27 on flat areas.

Over a page of text scrolling sideways at 3 and 8 pixels a frame under a 1400x1000 engine at the
picture's own size, the shared mode left no trail and no double, the same as one pass and as two
passes with a network each. In eight pairs of the captured frame and the picture for each mode,
lined up, no pixel of the page's white paper came out below 200 of 255, and the share below 235
was 0.2 percent at most, no more than with the page at rest. The ReShade engine's picture over
the same page, with pre-upscale on or off, left a faint double of the text at 8 pixels a frame,
4.2 and 5.2 percent of the paper below 235.

Two passes through one network take the network as long as two passes with a network each,
6.66 ms against 6.69 ms at 2560x1053 without a window, and 7.55 ms against 7.51 ms fullscreen at
Balanced, see Frames a second and power at each step. They hold one feature, 921 MiB of video
memory at 2560x1053 against 910 MiB for one pass. A picture at rest settles more slowly. The
shared reference of the self test went from 1.54 to 0.38 of 255 from its settled picture over the
four runs of the settle, where the one-pass reference goes from 0.45 to 0.18.

**UI correction and the preset.** The engine reads the add-on's `NRUICorrection`, 0 or 1, and
`NRPreset`, 0 to 3, anything else counting as 0, from its section with the six values, and hands
them to the runtime as `DLSSNR.UICorrection` at every evaluation and `DLSSNR.Hint.Render.Preset`
as the features are made, so a new preset makes the features again as a new shared state does.
Over the character still and a page of text at 1400x1000, UI correction 0 and 1 and the presets 0
to 3 gave the same picture byte for byte, though the runtime read the preset. The engine hands the
runtime no texture of a program's interface. So the panel has no control for either, and a
profile carries both with the add-on's section. The add-on's `NRGlobalTone` names nothing that the
model the stack installs reads, and 2 against 0.99 moved the ReShade engine's picture by 0.26 of
255, which is noise, so the Profiles page of Settings no longer lists it.

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
screen until the next refresh, so a render into it waits for that refresh, and the loop, which waits
for the last render before it takes the next frame, see The newest frame, waits with it. Once one
picture is finished a refresh late, every picture after it is late too, for as long as a frame comes
at every refresh, and one refresh without a render ends it. Over the whole picture of noise
scrolling at 120 steps a second with no limit, a loop with no rule for this showed the pictures at
their frames' own refresh in most seconds, with single seconds at -8.3 ms and stretches of 4 to 40 s
at 8.3 ms. So when the pictures of such a run have been late for a quarter of a second, the loop
leaves one frame out. When they are as late again within 2 s of a frame left out, the wait before
the next one doubles, up to 64 s. Over the scrolling picture for 45 s, with the loop made to stand
still for 9 ms every 7 s so that such runs begin, 2311 of 5384 pictures were shown late without the
rule and 166 of 5384 with it, for 5 frames left out. With the rule and no stalls, all 3601 pictures
of 30 s were shown at their frames' own refresh. At a limit of 80 fps the delay was -8.3 ms
throughout. These runs were made before 0.6.1, when the loop took each frame at once and its ingest
waited on the card behind the render.

**Over a source at half the refresh rate** the engine sometimes starts with every draw waiting about
11 ms for its back buffer, and then shows each picture two refreshes later than it can, for as long
as it runs. Under a window of a test's own that held the foreground at 60 fps with frames of 4.7 ms
on the card, on the 120 Hz display with a second monitor at 144 Hz connected, with the compositor
timing the 120 Hz display by the second monitor's refreshes, see Measurement pitfalls, 7 of 21
starts went that way from their first second, with a delay of 19.5 to 20.5 ms and `dwait` at 10.6
to 11.3 ms, where the other 14 read 3.0 to 4.4 ms. It was measured only in that state. The rule
above counts only runs of frames at every refresh, so it never ends this, and the engine has no
rule for it.

### The newest frame

Since 0.6.1 the loop waits for its last draw to be done on the card before it takes a frame from the
capture, so the frame it takes is the newest there is once the card can start on it. A frame that
arrives meanwhile takes the place of the one waiting, which counts as dropped. Up to 0.6.0 the loop
took the waiting frame at once, and its ingest then waited on the card behind the draw before it, so
the picture was made from a frame older by as long as that draw took. The frame rate limit, a frame
the limit keeps back, the settle and the repeats are as they were. The profile's `dwait` is the
wait, see Switches for tests.

Measured on a test computer with an RTX 5090 at 6144x2526 on the 120 Hz display, with nothing else
on the card, at Balanced, a work size of 2560x896, with no limit, over the whole picture of noise
scrolling 8 pixels a step at 120 steps a second, 30 s each, before and after the change. A second
monitor at 3840x1200 and 144 Hz was connected, and in these runs the compositor timed the display
by that monitor's refreshes, with `lead` at 6.9 ms and `grid` at 1.8 to 2.4 ms in each run's median,
see Measurement pitfalls, which adds to every delay below:

```
                       new a second   delay      ingest call   dwait      power
one pass, before       120.5          16.95 ms    7.52 ms                 225.0 W
one pass, after        119.9          10.45 ms    0.63 ms       4.47 ms   227.6 W
eight passes, before    27.1          71.80 ms   34.69 ms                 320.6 W
eight passes, after     27.1          39.65 ms    0.73 ms      33.44 ms   323.1 W
```

At eight passes the network takes 32 ms a picture, which stands in for a card that the network's
work keeps busy. So where the engine's own work holds it back, the newest frame took 6.5 ms off the
delay at one pass and 32.2 ms at eight, at the same pictures a second, for 2.5 to 2.6 W more, about
the 2.5 W a row is good to. No frame was left out for late pictures in these runs. Over the moving
square, where each picture is done before the next frame comes, `dwait` read 0.01 ms and the engine
drew 218.9 W at 118.1 new pictures a second. Over a demanding game that kept the card fully busy the
newest frame brought no gain, see A game in front that keeps the card busy.

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
six measurements at 2560x896, and two shots a second apart then differed by 0.0000. At Full with
two passes, at 6144x2526 over the same noise, they moved it by 23.9 of 255, where the network's
change from the picture was 18.0 of 255 before them and 21.0 after, and two shots a second apart
then differed by 0.0000 as well. At rest
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

Measured on 2026-10-03 on an RTX 5090, driver 617.14, Windows 11 build 26200 with
hardware-accelerated GPU scheduling on, and one monitor at 6144x2560 and 120 Hz. A demanding game
ran in borderless fullscreen under a fullscreen lens on the fast engine of 0.6.0, 6144x2558 at the
Quality step, a work size of 2560x1024, with one pass. In front means that the game's window had the
foreground. Each row gives the range of the lens's 10 s summaries in that test, see The lens's log,
their new pictures a second, which over the game are the game's own frames, and their median delay.
The first six rows ran on the engine as installed, and the last two on a build of it with the
profile and `LENS_FAST_SPLIT_WAIT=1`, see Switches for tests:

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
wait read 6.4 ms, 3.2 to 15.2 ms, the ingest's own turn after it 23.4 ms, 13.9 to 30.5 ms, and the
flip, which takes in the render's turn on the card, 40.6 ms, 11.9 to 47.5 ms. The delay read
75.0 ms, 50.0 to 91.7 ms, in that run. So each job a new picture gives the card waits for a gap in
the game's work, and there are three: the capture's copy on the capture's D3D11 device, the ingest,
and the network with the composite before the flip. The switch itself makes a list wait longer for
its turn on a busy card, see Switches for tests, and that run's delay was longer than the 58.3 ms of
the runs without it, so these figures say where the time went in that run, and not how long each
wait is without the switch.

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

**Again on 2026-10-04, with the engine of 0.6.1.** The same computer and driver, and the same game
in borderless fullscreen and in front, at another place in it, with the player standing still and
turning the view, at about 16 frames a second with the card fully busy. The 6144x2560 display at
120 Hz was the only monitor, the second one switched off. The lens was fullscreen on the fast engine
at the Quality step with one pass, Neural Rendering on and no frame rate limit. Five separate
sessions of about three minutes followed one another, each with the lens started afresh with the
profile on. A session's delay is the median of its 10 s summaries that had the game in front for
all their seconds, see The lens's log, which are counted beside it with their range. The seconds
with the game in front, and the ingest call by the wall clock as the median of its per second
figures, come from the profile:

```
session                              delay     summaries   their range       seconds   ingest call
LENS_FAST_JOIN=3                     38.0 ms   14          35.0 to 39.2 ms   174        5.6 ms
no switch                            38.0 ms   15          35.3 to 39.5 ms   170       37.0 ms
LENS_FAST_COPY_QUEUE=1               36.5 ms   15          33.2 to 42.8 ms   166       36.5 ms
no switch, again                     38.8 ms   16          35.2 to 39.8 ms   166       36.2 ms
an engine without the newest frame   36.5 ms   15          34.9 to 39.2 ms   164       37.2 ms
```

In every session the per second figures showed 16.0 new pictures a second in the median, the game's
own frames. The two sessions with no switch read 38.0 and 38.8 ms, and all five lay within 36.5 to
38.8 ms, with the copy queue and the engine without the newest frame both at 36.5 ms. So neither
switch brought the delay down beyond the spread between sessions, and both stay off. Nor did the
newest frame bring a gain over this game, see The newest frame. In every session but the joined one
the ingest call waited 36.2 to 37.2 ms for the card, and the joined one, whose ingest call did not
wait, showed the same delay as the session after it. Every session read below the 58.3 ms median of
the 88 summaries of 2026-10-03, the engine without the newest frame included, so that difference is
not the engine's.

A program with no window stands in for this only in part, since it is never in front. The engine
by itself, fullscreen at the Quality step with one pass over a picture changing 40 times a
second, read 0.0 to 8.3 ms alone. Beside one process with no window that blurs a 4K picture
through Vulkan in ffmpeg, the card at 90 percent, it read 16.7 ms with Neural Rendering on and
8.3 ms with it off. Beside four, the card at 100 percent, it read 58.3 ms and 41.7 ms, and showed
22 to 26 of the 40 new pictures a second. The network's span read 3.8 to 4.1 ms alone, 5.9 to
6.2 ms beside one and 13.4 to 14.0 ms beside four. The queue and the class at high, not run as
administrator, changed nothing, apart from one 25 s stretch beside four processes that read
50.0 ms in place of 58.3 ms.

A window of a test's own that holds the foreground stands in closer. It covers the display and draws
one frame of a set cost on the card at a set rate, with vsync, held by a limiter or free running,
and the stand-in figures under Switches for tests come from it. It draws one long draw a frame,
where a game draws many short ones.

**Where the network's list waits.** Under that window held at 30 fps with frames of 23.4 ms on the
card, so that the card stood idle for 10 ms after each, the engine's trace of its draws was set
against the window's own record of its frames, both on the CPU's clock. The lens's frame arrived in
the idle time in 756 of 757 cases, 6.6 ms before the window's next frame in the median, and the
ingest ran on the card 0.8 ms after the arrival. The list with the network, submitted 1.4 ms after
the arrival with 5 ms of idle card left, began on the card only once the window's next frame had
ended, 0.1 ms after its end in 753 of 754 pictures and 28.8 ms after its submission in the median,
and the delay read 41 to 44 ms. With the network left out, the same list began at once and the delay
read 8.0 ms. A plain compute list of the network's length, 3.1 ms, submitted at the arrival, was
done 3.41 ms after it. The ingest and the network joined in one list began 29.2 ms after its
submission. So a list with the network's work in it waits for the window's frame to end, and what
the driver or the scheduler goes by was not found. It does not always wait. Held at 60 fps with
frames of 4.7 ms, 98 percent of the lens's frames arrived in the idle time and the delay read
3.0 ms, and the game above, held at 30 fps by its own limit with room to spare, read 0.0 to 8.3 ms.
Holding the lens's work back to the next idle time where a frame arrives while the window draws
would have shown the pictures 1.9 to 8.6 ms later in the median, and sooner for only 12 to
23 percent of them, so the engine has no such rule. Measured on a test computer with an RTX 5090,
driver 617.14, with hardware-accelerated GPU scheduling on, the engine fullscreen at 6144x2526 at
Balanced with one pass and a second monitor at 144 Hz connected, with the compositor timing the
120 Hz display by the second monitor's refreshes, see Measurement pitfalls, apart from the game's
figures of 2026-10-03. Another driver and the scheduling switched off were not tried.

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
- At the Full step, where the median over the span of the network's own time a picture, from the
  engine's stats line, with one refresh more reaches the line less the tenth of a refresh, the
  warning says instead that at the Full step the network's own work on this screen holds the lens
  back by itself and that a lower step lets it keep up, and its log line ends `, at the Full
  quality step with the network at N ms a picture`. The delay stays close to the network's time
  and one refresh, see The quality steps, so the lens would be past the line then with no program
  in front, and no limit in the program in front could help. At 120 Hz that takes about 15.8 ms
  of the network, which one pass at Full at 6144x2526 took on screen at 18.6 ms and two passes at
  38.1 ms. Where the network takes less, the warning is the one of every step, and on a smaller
  screen which one comes goes with the refresh rate and with what the network takes there.
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

- **Neural Rendering on and off.** No add-on is there to read F6, so under the fast engine F6 does
  nothing. The NR key, F9 to begin with, the menu, the NR settings panel and a profile switch it.
  The lens sends `nr 0` or `nr 1` and writes `NeuralUplift` into ReShade.ini, where the add-on keeps
  it, see Global hotkeys. An engine that starts with Neural Rendering off is told before its first
  picture. With it off the engine's shot equalled the capture exactly.
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

The engine reads these from its environment, and the lens starts it with its own, so a lens started
with one set hands it on. None is set in use. The top of `fast_engine\src\main.cpp` lists them with
the loop's own tests, such as `LENS_FAST_NO_NETWORK`, `LENS_FAST_HEARTBEAT` and `LENS_FAST_STALL`.
These are the ones for finding where a picture's time goes, what changes it and what the HDR path
draws:

- `LENS_PRESENTER_PROFILE=1` adds the profile to each stats line. `meter` and `delay` are as on the
  plain line, the present call and the refresh that showed the picture, each against the frame's
  timestamp. `flip` runs from the present call to that refresh, and `ahead` is how far the timestamp
  lay ahead of the frame's arrival. `grid` is how far the timestamp lies from the display's nearest
  refresh, and `lead` how long before the refresh it was made for the compositor began that frame.
  `ingest`, `nr` and `composite` are the stages' times on the card from timestamp queries, and `nr`,
  the network's span between its two timestamps, stretches while another program has the card.
  `wake` runs from a frame's arrival to the start of its ingest, `iwall` is the ingest call by the
  wall clock, its waits for the card included, `cwait` is the part of that spent waiting on the CPU
  for the capture's copy, 0 unless `LENS_FAST_SPLIT_WAIT` is set, `dwait` is the wait for the last
  draw to finish before the loop takes a frame from the capture, so that the frame taken is the
  newest one, see The newest frame, and `conv` is the time on the card of turning a 16-bit frame
  into an 8-bit one, which the engine does for a monitor with Windows HDR on, 0 with it off.
  `joined` counts the new pictures whose ingest and render went to the card as one list, which the
  engine does under `LENS_FAST_JOIN` below, and `same` those of them that were found the same as the
  frame before once the list was done, each a run of the network for nothing. For a joined picture
  `wake` runs to the start of its list's recording and `iwall` is that recording and its submission,
  with no wait in it. `meter`, `delay`, `flip`, `ahead`, `grid` and `lead` are medians over the
  second, and the other times means.
- `LENS_FAST_JOIN=N` has the ingest and the render of a new frame go to the card as one list,
  presented at once, once N frames in a row were found changed, where otherwise every frame's ingest
  is waited for before its render is submitted. The comparison's answer then comes back a turn
  later. A frame found changed counts as a new picture in the stats line of the second the answer
  came in, and a frame found the same after all is counted as a repeat and a skipped frame and ends
  the run, so the engine cannot feed itself over a still screen. Unset or `0` it is off. The picture
  is the same byte for byte either way. Measured on a test computer with an RTX 5090 under a window
  of a test's own that held the foreground and kept the card busy, with the compositor timing the
  120 Hz display by a second monitor's refreshes, see Measurement pitfalls, the one list saved the
  ingest's wait for the card but took as long to get through the card as the two lists, or longer,
  so the delay was the same at 85 percent of the card and at 60 or 30 fps with gaps, and 2 to 10 ms
  longer under free running frames of 12 to 50 ms. Over a demanding game that kept the card fully
  busy it brought no gain beyond the spread between sessions, see A game in front that keeps the
  card busy, so it stays off.
- `LENS_FAST_STATS_NOTE=1` writes each stats line to stderr as well, as a note with its time, so
  `presenter-stderr.log` keeps the profile's figures, which the lens does not log.
- `LENS_FAST_TRACE=FILE`, with the profile on, writes every present, every answer of the
  display's statistics, every compositor frame and every finished draw to that file as a line of
  text. A draw's line carries the frame's stamp and arrival, the list's submission, and the
  ingest's and the draw's timestamps on the card put on the CPU's clock by the queue's clock
  calibration, so a test can see when the network's list began against another program's
  frames. The top of `fast_engine\src\main.cpp` gives the lines' fields.
- `LENS_FAST_SPLIT_WAIT=1` has the ingest wait on the CPU for the capture's copy first, before
  the queue's own turn, where otherwise only the queue waits for it, on the fence the two devices
  share. The profile's `cwait` then gives the copy's wait apart. It gives up the overlap of the
  two waits, and on a busy card a list submitted after a CPU wait takes longer to get its turn
  than one submitted at once behind a fence, so the figures with the switch are not the figures
  without it.
- `LENS_FAST_COPY_QUEUE=1` has the capture copy the crop out of each frame with a D3D12 copy queue,
  which the card's copy engine runs, instead of on the capture's D3D11 context, whose copy runs on
  the 3D engine and waits there for its turn behind a game in the foreground. The frame pool's
  textures are opened on the D3D12 device by shared handle, the copy is ordered behind the frame's
  own work on the D3D11 context, the copy queue signals the slots' fence, and the frame stays open
  until its copy is done. One frame is open at a time. Before the next is kept, the copy of the
  frame before is waited for, 200 ms at most, since two frames held open would hold both of the
  pool's buffers and the system delivers nothing while they do, and the next frame is dropped where
  that copy is still not done. A pool texture that cannot be opened on the D3D12 device hands the
  copy back to the D3D11 context for the rest of the session. The picture is the same. The capture
  test's read of the screen agrees with GDI's texel for texel, and a probe that copied each frame
  both ways compared 7523 frames, most of them under loads that kept the card busy, with none
  differing. Measured on a test computer with an RTX 5090 under a window of a test's own that held
  the foreground, with the compositor timing the 120 Hz display by a second monitor's refreshes, see
  Measurement pitfalls, the time from a frame's arrival to the end of its copy was 2.0 to 7.5 ms in
  the median on the 3D engine under free running frames of 12 to 50 ms, and 0.72 to 0.85 ms on the
  copy engine under every load and on a free card, where the 3D engine takes 0.22 ms. The engine's
  delay was 4 to 7 ms shorter, with 6 percent more pictures a second, under free running frames of
  25 ms, the same under frames of 12 and 50 ms, under frames held at 60 fps and under frames of 1 ms
  at 120 fps, and 2 to 4 ms longer under frames at 120 fps with vsync that nearly filled each
  refresh, where the window then ran 2 percent faster. Over a demanding game that kept the card
  fully busy it read 36.5 ms, 1.5 to 2.3 ms below the two sessions without a switch on the same
  engine and the same as an engine without the newest frame, within the spread between sessions,
  see A game in front that keeps the card busy, so it stays off.
- `LENS_FAST_SHOT_RAW=1` makes a screenshot over a monitor with Windows HDR on also write the
  captured 16-bit frame as it came, before its conversion to 8 bits, as `BASE-raw.npy` beside the
  pictures, a NumPy array of float16, height by width by 4, in scRGB with 1.0 at 80 nits, and the
  picture as drawn into the 16-bit swapchain the same way as `BASE-out.npy`. The PNG pictures are
  8-bit renditions with it or without it, see HDR.
- `LENS_FAST_HDR_ABOVE=pass`, `fade` or `clip` sets what the composite into a 16-bit swapchain does
  with the network's change where the original is brighter than SDR white, where the network saw a
  clipped input. `pass` applies it as at white, where it can only darken, `fade` scales it down to
  nothing at twice white, and `clip` leaves it out. Unset, or with another word, it is `fade`, the
  engine's own, see Above SDR white under HDR. A note names the way whenever the switch is set.
- `LENS_FAST_ONE_FEATURE=1` runs the passes after the first through the first pass's network with
  two passes or more, whatever `SharedNetwork` in `ReShade.ini` says, see Passes through pass 1's
  network under Each pass's values. The engine reads it again on each `reload`. Without it the
  pictures are those of the engine without the switch, byte for byte.
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

**The self test's references.** `fast_engine\tools\run_selftest.py` runs the engine's self test on
`docs\images\blender-before.png` at a work size of 2560x1053 with the test stack, without a
window, and scores it. A reference run, with no other picture, work size or pass count, holds its
`composite.png`, `nr_in.png`, `nr_out.png` and `nr-reads.txt` against a baseline byte for byte and
fails where one differs, the baseline of 2026-10-03 for the run at one pass. `--shared` is the
reference run of two passes through one network, with `SharedNetwork=1` and
`Pass2IntensityTied=1` written into the test stack's `ReShade.ini` for the run and the file put
back byte for byte after it, held against the baseline of 2026-10-06. `--both` runs the two in
turn. `--against DIR` names another baseline, with `--both` for the run at one pass while
`--against-shared DIR` names the shared run's, and `--against none` compares nothing. The
baselines are kept with the measuring tools, outside the repository, and where one is missing the
run says that it compared nothing. On an RTX 5090 the network took 3.36 ms in the reference run
and 6.68 ms for the two passes of the shared one. With two passes or more each self test also
flips the shared state and moves the preset, and checks that the features are made again for
them, that the other shared state draws another picture and that flipped back the picture is the
first byte for byte, where the change of picture is not judged at an intensity of 0. Every self
test draws the picture at a strength of 1, 1.5, 2 and 1 again, with every pass at the values
every pass starts from and the intensity at 1, checks that the last is the first byte for byte
and that the network's output at 1.5 and at 2 is the CPU's scaling of the output at 1 against the
network's input, byte for byte, at any pass count, and writes the changes and their ratios to
`timings.json` as `strength_above_1`. `--quality 5` is a size argument like the others, so such a
run is held against no baseline.

### What is not measured

- **Displays at 60 Hz and at 240 Hz.** The repeats and the burst count refreshes there by rule,
  not by measurement.
- **The power at each step with one monitor.** The steps were measured with a second monitor
  connected. With one monitor, over a picture changing at every refresh, the delay read 0.0 ms in
  10 of 12 summaries and 8.3 and 12.5 ms in the other two, see the on-screen readout under
  Fullscreen in Gotchas.
- **HDR beyond one monitor and test pictures.** HDR ran on a second monitor at 3840x1200 and 144 Hz
  alone, over test patterns, a still scene and the scrolling picture. It was not run on the main
  monitor or at 6144x2560, nor under an HDR game or video, with the A/B split or with a change of
  the quality step. HDR switched off while the engine captured, a change of the SDR white level
  while it ran and the way of reading HDR for Windows before 24H2 were not run at all.
- **A game under the lens, beyond its delay.** One demanding game was measured for the delay and for
  where a picture's time goes, on 2026-10-03 and 2026-10-04, see A game in front that keeps the card
  busy. The power, the steps and the picture were measured over a moving square, a scrolling picture
  and stills, and the tests beside another program used one that has no window and a window of a
  test's own.
- **Passes at their own values beyond two.** The picture with a pass at values of its own was
  measured at two passes, and not at three or four.
- **Passes through pass 1's network beyond two, and with the second pass at values of its own.**
  The look was measured at two passes with the second at the first pass's values, at 1400x1000,
  and the cost at two passes.
- **An intensity above 1 on the ReShade engine beyond one case.** That the add-on holds 1.6 at 1
  was measured over one still at one set of values with Denoise before upscaling on, and not with
  it off, at other values or over a game.
- **The Full step in HDR and in motion.** Its pictures were judged on near-still frames of a game,
  and it was not run with Windows HDR on.
- **The strength in motion, over a game and in HDR.** Scale the change was measured over stills
  alone, the Blender picture in the self test, a character still and a still of noise through the
  lens. Scaling the change also scales how the network's change moves from one picture to the
  next, and how that looks in motion or over a game was not judged. That the composite adds the
  scaled change in HDR as in standard range is from the code, and it was not run with Windows HDR
  on.
- **The add-on's intensities for passes 2 to 4.** That the add-on runs passes 2 to 4 at
  `NRPass2Intensity` to `NRPass4Intensity`, and that its overlay can change them, is taken from the
  key names in the add-on's own file. The ReShade engine's picture at two passes or more was not
  compared with the fast engine's, and what the add-on runs those passes at where its section holds
  no such key was not measured.
- **Motion at the steps.** The pictures the steps were judged on were stills, including stills
  three evaluations into a picture, and near-still frames of a game against the picture's own
  size.
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
  the order the profile, the switch that loads a profile for the program in front, Neural
  Rendering, the pass tabs, the style, the intensity, local tone, local structure, skin
  structure, skin structure left to the model, the auto mask, the passes, the switch Scale the
  change, the strength while that switch is on, and the quality step. On the tab of a pass from
  the second on, each value's Same as pass 1 is a row of its own after the value, and the switch
  Runs through pass 1's network is a row after the auto mask's, greyed on the tabs of passes 3
  and 4. Left and Right load the profile before or after the one in use, show the pass before or
  after, and change the style by one, a slider by 0.01 a press, the passes by one and the
  quality step by one. A key held down moves a slider further with each repeat the longer it
  is held: 0.01 for the first 0.6 s, 0.02 up to 1.5 s and 0.05 after that. A move counts as part
  of the hold when it comes within 0.15 s of the move before, with the key down all the while,
  on the same slider of the same pass and the same way, as a held key's repeats do. Anything
  else starts again at 0.01, a profile loaded or another tab shown meanwhile included. A press
  and a repeat both reach the lens as WM_HOTKEY, so while a hold is under way the lens also reads
  the key with GetAsyncKeyState every 50 ms. Windows does not show every program the keys while
  another program is in front, so a key read as up counts only once the lens has read it down
  with the same window in front, and until then the 0.15 s alone decide. The first repeat comes
  after Windows' repeat delay, half a second by default, and starts the hold, so at the default
  delay and rate a key held from 0 reaches 2 about 2.9 s after the press. Every value lands on a
  hundredth within the slider's range. Enter opens the profile list and switches each switch:
  the one for the program in front, Neural Rendering, a Same as pass 1, skin structure left to
  the model, the auto mask, Runs through pass 1's network on the tab of pass 2 and Scale the
  change. A greyed switch stays as it is. The profile and the passes take one step a press, and
  a repeat within 0.5 s of a change is ignored, since a load can restart the picture and each
  change of the passes does.

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

The lens is made so that nothing of it reaches the program under it, a game included. It reads the
screen through Windows Graphics Capture, the keyboard through RegisterHotKey and the state of a few
keys from GetAsyncKeyState, and the title and the class of the window in front, see The program in
front below. It installs no hook, makes no keystroke, attaches to no other program's input, opens no
other program's process and writes nothing into another program's folder. The only key messages it
sends, Home and F5 for ReShade, are posted to the window of its own presenter, and the lens checks
before each post that the process behind that very handle is one of its own. A posted message is no
input of the system. It changes no key's state, and no low-level hook or raw input reader sees it,
though a hook that runs in the presenter's own message loop could.

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
- **The foreground in the log.** While the lens is fullscreen and in view, the 200 ms timer writes a
  line each time another window comes to the front, see The lens's log, from `GetForegroundWindow`
  and `GetClassNameW` alone. No process is opened, and the line names no title, since a title can
  hold private text. The warning that the lens falls behind uses the same looks. As each regular
  summary is written its check asks those two again, and the process id of the window in front to
  tell the lens's own windows, and it opens no process either, see The warning under A game in front
  that keeps the card busy.
- **The program in front.** In a window and fullscreen alike, at each of its looks, five times a
  second, the 200 ms timer reads the title of the window in front with `GetWindowTextW` and its
  class with `GetClassNameW`, for a profile tied to that program, see Tied to a program under
  Profiles. For a window of another program `GetWindowTextW` reads the caption Windows keeps for it
  and sends that window nothing. The process id from `GetWindowThreadProcessId` tells the lens's own
  windows apart, and no process is opened. The lens keeps in memory the title and the class of the
  program last in front and the last tied title its window showed, and no list of the titles it
  reads, whether profiles load by themselves or not. A title is written only for a program the
  person tied a profile to, into `profiles.json` and the log.

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
action NR settings show pass 2 (click)
action NR settings Pass2LocalTone same as pass 1 (mouse)
action NR settings NRLocalTone 1 (reset button)
action NR settings SharedNetwork 1 (keyboard)
action NR settings ScaleChange 1 (mouse)
action NR settings Strength 1.6 (mouse)
action NR off (key F9)
action readout hidden (key F10)
action fullscreen off (taskbar list)
action style list item "Natural" (click)
action Settings saved: max_fps 30, fs_readout fps,latency (Save)
action profile "Video" renamed to "Film" (Settings)
action profile "Game" tied to "Window title" (panel)
action profile "Game" loaded for the program in front, "Window title" (auto)
action auto profile on (keyboard)
action check for a new version (Settings)
action quit (close button)
```

Each action taken through the lens's keys, its menu, the NR settings panel, the buttons of the title
bar, a click on the tab, the note, the taskbar list or Settings has such a line. The lens menu, and
the style list and the profile list of the title bar and of the NR settings panel, each have lines
under their own names for their opening, the entry chosen and their closing. The NR settings panel
has lines for its opening, its closing, each tab chosen and each value changed on it, tweak mode for
its start and its end, and the note for its closing and its Don't show this again. Neural Rendering
on and off, the quality step, the passes, fullscreen, screenshots, the A/B split, the on-screen
readout shown or hidden, minimising and bringing the lens back, applying a profile, tying one to a
program and untying it, the switch that loads profiles by themselves, hiding and showing the title
bar, Ready mode, detaching and quitting each have their line, also where the lens stays as it was,
such as `fullscreen left as it is` for a lens attached to a window. A click on the taskbar button
writes `brought back (taskbar button)` for a minimised lens and `menu opened (taskbar button)` where
it opens the menu, and nothing where it only brings a lens in view to the front again. Save in
Settings writes one line that names each setting it changed, by its key in the ini and its new
value, or says that nothing changed. On the Profiles page, Rename, Delete, Save the current
settings, the tie to the program last in front and Untie each write a line that names the profile,
and so does Save in the dialog for a new profile. Check now on the Program page writes
`check for a new version`. The plus and minus on the title bar only choose a number, and Set has the
line. Moving the lens by its title bar or its tab, sliding the tab along the edge, resizing the lens
by its edges and dragging the divider write no action line, and neither do Browse, Cancel and the
choices made in Settings before Save. A value changed on the panel gets one line once it has held
still for 0.6 s, or as the panel closes, under its key in `ReShade.ini` for the first pass, such as
`NRIntensity`, and for a pass from the second on under `Pass` with the pass's number and the value's
name, such as `Pass2LocalTone`, which is the name for the intensity of passes 2 to 4 as well.
The switch Runs through pass 1's network has its line under `SharedNetwork`, with 1 or 0, the
switch Scale the change under `ScaleChange` the same way, and its strength under `Strength`.
`same as pass 1` is a value ticked to follow the first pass, `NRSkinStructure -1` is skin structure
left to the model, and `(reset button)` is the button beside a slider. A profile the lens loads by
itself for the program in front has its line with `(auto)`. The lines the lens wrote before, such as
`Neural Rendering off` and `fullscreen 6144x2558 at (0,0)`, stay as they were beside them.

Lines for a profile tied to a program, untied from one or loaded for one name the program by its
window's title, or by its class where the title is empty, and so does the entry of the panel's
profile list that ties one, once chosen. No other line names a window's title, and these name only a
program the person tied a profile to. A tie saved without a class, which no window can match, is
taken off as `profiles.json` loads, with a line for each profile that loses one.

While a fullscreen lens on the fast engine is in view, a line every 10 s sums up the engine's
stats lines:

```
fast engine, last N s: N new and N arrived pictures a second, N repeated, N dropped, N skipped, median delay N ms, quality step N NAME, N pass(es), NR on|off, frame rate limit N fps|no frame rate limit, network N ms
```

The two rates are means over the seconds counted, which are the stats lines that came, ten as a
rule. Repeated, dropped and skipped are totals over those seconds: presents of a picture already
shown, frames replaced by a newer one or left out before the engine took them, and frames equal
to the one before. The delay is the median of the engine's own figure, see The present path and
the delay, not raised to zero as the menu shows it, and reads unknown when no refresh was learned.
Then come the frame rate limit in force and the network's time a picture, the median over the
seconds it ran in of the engine's `network=` figure, see The fast engine, which reads unknown
where it ran in none. Only the stats lines of the engine that runs
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
in Settings is off, the line ends `and the warning is off in Settings`. At the Full step, where
the warning names that step because the network's own time with one refresh more reaches the
line, see The quality steps, the line ends `, at the Full quality step with the network at N ms a
picture` after either.

While Windows HDR is on for the lens's monitor and the ReShade engine draws the picture, see The
warning under HDR, a line says so each time the warning would be said, with the monitor's SDR white
level:

```
Windows HDR is on for the lens's monitor, SDR white 240 nits, and the ReShade engine draws the picture, so it comes out washed out, and the warning is shown
```

Where the switch in Settings is off, the line ends `and the warning is off in Settings`. When HDR
goes off for that monitor while the warning applies, the log has
`Windows HDR is off for the lens's monitor again`. Save in Settings names `hdr_warn 0` or
`hdr_warn 1` where that switch changed, as it names `fs_behind_warn 0` or `fs_behind_warn 1` for the
warning that the lens falls behind.

Where the fast engine did not take a quality step it was told, see The quality steps, and where
it could not make its network again for the switch Runs through pass 1's network, or for other
new settings such as a profile's preset, see Each pass's values, a line says so, beside the
notice:

```
the fast engine did not take quality step 5 Full and runs at 3 Balanced, so the lens goes by that step
the fast engine could not make its network again for "Runs through pass 1's network", saying "REASON", so the passes run as they did before the switch
the fast engine could not make its network again for the new settings, saying "REASON", so it runs on with the network it had
```

While the lens is fullscreen and in view, a line each time another window comes to the front:

```
foreground: Shell_TrayWnd, another program's
foreground: NeuralLensFast, one of the lens's own
foreground: no window
```

The line a lens writes as it attaches to a window names that window's class as well, never its
title, since a title can hold private text.

## Profiles

A profile holds everything that makes the picture under a name: the lens's place and size,
fullscreen, the pass count, the Cost Scaler rule, the motion detail, Ready mode, the frame rate
limit, what the title bar shows, the add-on's section of ReShade.ini whole, apart from ConfigVersion
and EnableHooks, which belong to the install, and since 0.6.1 the lens's own section
`[NeuralLens.Passes]` whole, the quality step in force and the program it is tied to, kept in
`profiles.json` as `per_pass`, `quality` and `program`. Applying one writes both sections of the
file in one write, each made the profile's whole, so a setting the profile never held goes back to
its default rather than lingering from the last look, and each pass ticked Same as pass 1 stays at
the first pass's intensity, see Each pass's values. Where Windows refuses the write for a moment, as
while the engine reads the file, it is tried again up to ten times, 30 ms apart. Where the file
still does not take it, nothing of the profile is loaded, the log says
`ReShade.ini could not be written, so profile 'Game' was not loaded`, and the notice or the bar says
that the profile was not loaded. Neural Rendering goes on or off as the profile's section has it.

A profile saved before 0.6.1 holds neither `per_pass` nor `quality`. Applying one empties the lens's
section, so each pass from the second on runs at the first pass's values, apart from the intensity
of passes 2 to 4, which comes from the add-on's keys saved with the profile's section, and it leaves
the quality step as it is, as a profile without a frame rate limit leaves the limit.

The add-on reads its section only when its process starts and writes it back within about a second
of a change in its overlay, so a profile saved after a change in the overlay carries it, and on the
ReShade engine applying one restarts the picture. A fullscreen lens on the fast engine takes a
fullscreen profile at its own pass count as it runs. The lens tells the engine to read the file
again, the profile's frame rate limit and Ready mode, and the quality step and Neural Rendering
where they change, and the picture goes on in the same engine process, which the log calls
`loaded in place`. Every other profile restarts the picture.

The name on the bar and on the NR settings panel's picker gets a star, in amber, once the lens no
longer matches its profile. It compares the pass count, the Cost Scaler rule, ready, the frame rate
limit, the motion detail, the readout, the delay meter, what the title bar shows and fullscreen, the
quality step where the profile holds one, the six values of every pass the lens can run as
`ReShade.ini` has them against the profile's, number by number, whether the passes after the
first run through the first pass's network, `SharedNetwork` in the lens's section, whether the
change is scaled, `ScaleChange`, and while it is the strength, `Strength`, to a hundredth. A
profile saved before 0.7.0 has none of those keys, so it loads with each pass on a network of its
own and the change not scaled, since applying it empties the lens's section of the keys it lacks.
Verified with a test that saves and switches profiles through the lens's own methods.
`profiles.json` is written beside itself and put in its place in one step, and a file that is
there but cannot be read as profiles is kept as `profiles.json.bad`, with a line in the log, so
the next save cannot write over it.

The Profiles page of Settings lists for a profile the lens's own settings and the Home menu's,
whether its passes run through pass 1's network, under the panel's label for the switch, for a
profile of two passes or more, since at one pass the switch does nothing and the panel shows
none, and whether its change is scaled, with the strength, among the first, and no longer the
add-on's `NRGlobalTone`, which the model the stack installs does not read, see UI correction and
the preset under Each pass's values. A profile at the Full step shows Full as its quality step,
and a lens before 0.7.0 takes a profile's step 5 as Quality, the highest it has.

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

### Tied to a program

A profile can be tied to a program by the title and the class of the program's window, and the two
must match exactly, so a program whose title changes with what it shows matches only under the title
it was tied with. The panel's profile list ties the profile in use to the program in front, which
over a fullscreen lens is the program under it, since the panel never takes the front. The Profiles
page of Settings ties the profile chosen in its list to the program whose window was last in front
before the dialog, which it names under its button, and greys the button where no other program has
been in front. Each also unties. A program has one profile, so tying a profile unties any other tied
to the same title and class, with a line in the log.

With Load the profile tied to the program in front ticked, on the panel or on the Profiles page,
which the ini keeps as `auto_profile = 1`, the lens loads the profile tied to a program each time
that program comes to the front from another program, unless it is the profile in use, and says so
on the notice of a fullscreen lens for 5 s, and on the bar of a lens in a window. Ticking it looks
at the program in front at once, or, with a dialog of the lens's own in front, at the next program
to come to the front. It starts unticked.

In a window and fullscreen alike, the 200 ms timer looks at the window in front five times a second,
and reads its title with `GetWindowTextW` and its class with `GetClassNameW` at each look, also with
the switch off, to know the program last in front for the tie entries. The program counts, not the
window. A window that stays in front and takes another title is the program of that title from then
on, so with the switch on a window that takes a tied title a moment after it comes up, as a game's
window can, loads that profile then. A tied title counts when the window shows it first or after
another tied title, so a title that goes back and forth with untied ones loads nothing again, and a
window that shows one tied title after another, as an emulator or a launcher can for each game it
starts, loads each one's profile as its title comes. No list of the titles shown is kept, so a title
that never settles, such as one with a counter in it, costs nothing. Once the switch is on, a tied
title the window in front showed while it was off loads its profile when the window shows it again.

No window, a window of the lens's own, which the windows of its stages and the process id from
`GetWindowThreadProcessId` tell apart, the desktop, the taskbar and the task switcher are no
program, the last three by their classes `Progman`, `WorkerW`, `Shell_TrayWnd`,
`Shell_SecondaryTrayWnd`, `XamlExplorerHostIslandWindow`, `MultitaskingViewFrame`, `TaskSwitcherWnd`
and `ForegroundStaging`. So a program that comes back from a dialog of the lens's own or from the
desktop has not come to the front anew, and a profile chosen meanwhile stays. A window whose class
cannot be read, as one that is gone by the time it is read, is no program either. The title is read
first, so a window that goes between the two reads counts for nothing too. A window with a class and
an empty title is a program, matched by its class and the empty title, and the panel and Settings
name it by its class. A tie without a class would match no window, so none is made, and one found in
`profiles.json` is taken off as the file loads, with a line in the log for each profile. A line that
cannot be written, as on a full disk, is left out, and the profiles load all the same. A lens that
is minimised or replacing its picture looks at nothing, and judges the window in front against the
program before once it is back. A title is shown cut to 40 letters with three dots, and kept whole
in the profile and the match.

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

**Denoise before upscaling.** The add-on's `NRPreUpscale=1`, Denoise before upscaling in its Home
menu, runs the network on the colour that goes into a DLSS evaluate instead of on what comes out
of it. In the presenter that evaluate is the Feed's DLAA, and it reaches two hooked copies of the
NGX module, the driver's and the stack's `nvngx_dlss.dll`, the one forwarding into the other. On
this path each copy runs the network, the second on the first one's output, through the same
network feature and so with the same history. The add-on's log shows a second workset with the
feature made once, and 208 evaluations a second against the Feed's 104 frames a second, where
with the setting off it runs once a frame. Both 5.2.1, the add-on the stack installs, and
8.5.0-rc10 do so. The Feed's DLAA then works on the result. Over a character still at 1400x1000 with
5.2.1, at style Default, intensity 0.97, local tone 0.99, local structure 0.41, skin structure 0
and the auto mask off, with one pass, the picture changed by 22.6 of 255 from the still with the
setting on against 9.5 with it off, darkened it by 1.85 in mean luma against 0.40, and kept 0.24
of the still's fine detail, as the variance of the Laplacian, against 0.37, where the Feed's DLAA
alone keeps 0.46. The fast engine gives that look with the switch Runs through pass 1's network
on the tab of pass 2, see Each pass's values.

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
and a repair keeps whatever the section holds. Since 0.6.1 the setup also keeps the lens's own
section, `[NeuralLens.Passes]`, on a repair and on an update that runs it, see Each pass's values.
It writes the file anew from its template and puts that section after it byte for byte, finding it
by its name as Windows reads it, whatever its case and with spaces or a comment on its name line,
and its log says so. A file without the section comes out as before.

Before each presenter starts, the lens writes `NRChainedHistory=1` and `NRCodecMode=0` where the
add-on's section holds no value for them and leaves a value that is there, so a choice made in the
add-on's overlay, which the add-on writes back to the section, stays.

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

Since 0.6.1 a fullscreen lens on the fast engine draws in HDR on a monitor that has Windows HDR on.
The ReShade engine still works in 8 bits, so on such a monitor every lens it draws comes out washed
out: every lens in a window, a lens attached to a window and a fullscreen lens on that engine. The
lens says so, see The warning below.

### Telling HDR from Auto Colour Management

The lens and the fast engine read a monitor's state the same way, through DisplayConfig, from the
active path whose source is that monitor. From Windows 11 24H2,
`DISPLAYCONFIG_DEVICE_INFO_GET_ADVANCED_COLOR_INFO_2` gives the active colour mode, which is HDR
only with Windows HDR on. Auto Colour Management gives the wide colour mode, which does not count.
Before 24H2 the older `DISPLAYCONFIG_DEVICE_INFO_GET_ADVANCED_COLOR_INFO` counts as HDR where
advanced colour is on and wide colour is not enforced. The SDR white level, the brightness Windows
gives standard content on that monitor, comes from `DISPLAYCONFIG_DEVICE_INFO_GET_SDR_WHITE_LEVEL`,
in thousandths of 80 nits. On Windows 11 build 26200, a 3840x1200 monitor at 144 Hz on DisplayPort
with HDR on read as HDR at 240 nits, and the 6144x2560 display at 120 Hz with Auto Colour Management
on read as not HDR, at 80 nits. The older way, for Windows before 24H2, was not run. The engine
reads the state when its window is made, whenever its capture starts and once a second while it
captures, and the lens reads it once a second on its 200 ms timer.

### The fast engine in HDR

With HDR on for its monitor the engine captures, works and draws like this:

- **The capture takes 16-bit floats**, `R16G16B16A16_FLOAT` in scRGB, linear light with 1.0 at
  80 nits, for the frame pool and the four textures it copies into.
- **A compute pass makes the 8-bit frame the network works on.** Each texel's level is
  `round(255 * sRGB(clamp(scRGB / white, 0, 1)))`, where white is the SDR white level in units of
  80 nits, so standard content comes out as it would with HDR off and everything above SDR white is
  white. It goes into one of two `R8G8B8A8` textures, and the downscale and the network work on it
  as on an 8-bit capture. Whether a frame is new is decided on the two 16-bit frames, compared bit
  for bit, so a change that lies only above SDR white counts too.
- **The swapchain is in 16-bit floats in scRGB**, `R16G16B16A16_FLOAT` with the colour space
  `RGB_FULL_G10_NONE_P709`, on both ways of making it. The ready line then gives the format as 10,
  where it is 87 in 8 bits.
- **The composite is drawn in linear light.** It draws
  `native + white * (decode(v / 255) - decode(l / 255))` with `v = clamp(l + d, 0, 255)`, where
  native is the captured 16-bit value, l the level the network saw at the pixel, d the change in
  levels that the standard range composite draws there, and decode the sRGB transfer function. At or
  below SDR white that is the standard range picture in linear light, with the original's own 16-bit
  value under it, so nothing is lost to 8 bits there, and above SDR white the change fades out, see
  Above SDR white.

A composite of the network's own output against its input in linear light,
`white * (decode(out) - decode(in))` scaled up, was not taken, since it applies the change at the
brightness of the work texel and not of the pixel. A pixel at level 50 beside a work texel at 150,
with a change of 10 levels, would get 0.0465 of SDR white in linear light where the standard range
picture gives it 0.0133 of SDR white, 3.5 times as much, a halo the standard range picture does not
have. Where the swapchain does not take scRGB it stays in 8 bits and shows the standard range
picture at SDR white, as Windows shows a standard program, and the engine says so in its note and
does not ask again in that run. The engine's note `hdr: on, sdr white 240 nits, the capture takes
16-bit floats, the network sees them scaled to that white, and the picture is drawn in 16-bit
floats`, or `hdr: off`, comes when the capture first starts and whenever it changes, and the ready
line ends with `hdr on` or `hdr off`.

**Switched on or off while the engine runs.** Windows did not end a capture when HDR was switched on
for its monitor. Measured, with HDR switched on while the engine captured, no loss of the capture
came in 8 s, and the session went on in 8 bits, whose pictures of the HDR desktop were 45.6 of 255
from the right ones on average. So the engine reads the monitor's state once a second while it
captures, in a few hundred microseconds, and where HDR went on or off it starts the capture again,
which takes the format, the swapchain and the white level with it, with a note such as
`hdr: Windows HDR went on for the monitor while the capture ran, so the capture starts again`. A
new SDR white level alone is taken without a restart, with the note
`hdr: the SDR white level is now N nits`, and the picture on screen is drawn again. In one run on
each of the two ways of making the swapchain, with HDR switched on once while the engine captured
and then off, on and off again while it was paused, the swapchain followed every change, and after
each change to HDR the drawn picture matched the pattern to a hundredth of a nit at twice SDR white
and above. HDR switched off while the engine captured was not run, the time from the switch to the
new picture was not measured, and a change of the SDR white level while the engine ran was not run.

**Screenshots.** Under HDR the lens's before and after pictures, the side by side picture, the
clipboard's copy and the probe are 8-bit pictures made the way Windows shows standard content, by
scaling the 16-bit picture by one over the SDR white level, clipping it, encoding it as sRGB and
rounding it, so anything above SDR white is white in them. The before picture is the 8-bit frame the
network saw. Measured, the after picture equalled such a picture made on the CPU from the drawn
16-bit picture byte for byte, and at 3840x1198 the engine answered a screenshot in 0.151 s in the
median. `LENS_FAST_SHOT_RAW` keeps the two 16-bit pictures as well, see Switches for tests.

Measured on a test computer with an RTX 5090, driver 617.14 and Windows 11 build 26200, with HDR on
for a second monitor at 3840x1200 and 144 Hz alone, at an SDR white of 240 nits, and the engine
fullscreen on it at Balanced, a work size of 2560x640, over a pattern drawn in scRGB from 0 to
1000 nits and over a photo-like scene:

- The 8-bit frame the network saw was within 0.04 of 255 on average, and 0.52 of 255 at most, of the
  pattern's own picture at SDR white, at or below white. The same conversion made on the CPU from
  the captured 16-bit frame equalled it in all of its 4.6 million texels. A grey of 20 nits came out
  at level 82 where an 8-bit capture gives level 137, and one of 80 nits at level 156 where the
  capture gives level 255.
- With Neural Rendering off the drawn 16-bit picture equalled the captured frame texel for texel up
  to 1000 nits, and the desktop's 16-bit frame from Desktop Duplication equalled the drawn picture
  texel for texel with Neural Rendering off and on.
- With Neural Rendering on, the change at or below SDR white was within 0.18 nits on average of the
  standard range picture's change over the pattern, 1.41 nits at the 99th percentile and 2.09 nits
  at most, where half a level at white is 1.07 nits, and within 0.04 nits on average over the scene,
  0.38 nits at the 99th percentile.
- Over a still screen the 16-bit swapchain was shown directly, as the 8-bit one is, with
  17.7 repeats a second and no frames of the compositor's own. Over a picture scrolling at 120 steps
  a second the delay read 0.00 ms on that monitor's own grid. The swapchain made for
  DirectComposition gave the same.
- A square at 800 nits moving at 120 steps a second over a field at 400 nits, both above SDR white,
  gave 120 new pictures a second at a median delay of 0.0 ms. Over a still HDR screen 0.1 new
  pictures a second came.

### Above SDR white

Above SDR white the network saw a clipped input, a level of 255, and not the original's value. The
engine fades its change out there. Per channel and by the original's own value, the change is scaled
by a weight of 1 at or below SDR white that falls to 0 at twice SDR white, from where the original
is shown as it is. `LENS_FAST_HDR_ABOVE` sets the two other ways for tests, see Switches for tests.
`pass` applies the change as at white, where it can only darken, and `clip` leaves out the change
wherever a channel is above white.

Measured as above, at an SDR white of 240 nits, over the Blender picture with a disc at 480 nits, a
soft glow up to 400 nits, a framed rectangle at 400 nits, a ramp from 120 to 360 nits through white
and highlights of its own at 300 to 430 nits, 3.8 percent of its pixels above white. The change
against the original, in nits, a mean over each part, with the glow by the original's value in units
of SDR white:

```
                                     pass      fade      clip
the disc at 480 nits                -11.5      0.00      0
the glow at 0.95 to 1               -11.0    -11.3     -11.3
            1 to 1.05               -10.0    -10.1      -0.1
            1.05 to 1.2              -4.4     -4.0      0
            1.2 to 1.5               -3.0     -2.1      0
            1.5 to 1.7               -6.9     -3.2      0
the rectangle at 400 nits            -0.08    -0.03     0
the scene's own highlights          -43.2    -34.4     -7.2
```

In each of the three ways the network's own dark ring 2 to 20 px outside the disc read -5 to
-7 nits, as it does with HDR off, the largest step between neighbouring columns of the ramp near
white was 1.15 to 1.17 nits, and the change at or below white was within 0.04 nits on average of the
standard range picture's. `clip` steps by 11 nits along the line where the glow crosses white, a
ring the original does not have. Over the pattern a red patch at 320 nits changed by -31 nits with
`pass`, -24 nits with `fade` and not at all with `clip`. Looked at on that monitor with the lens
fullscreen over the scene, `fade` looked right, with only a slight change to the soft glow, `pass`
darkened the disc slightly, and `clip` drew a hard outline on the glow where it crosses white. So
`fade` is the engine's way, and the other two stay switches for tests.

### What HDR costs

Measured as above, at 3840x1166 on that monitor over a picture scrolling as a whole at 120 steps a
second, so that every pixel changes at every step, at Balanced with a work size of 2560x640 and a
frame rate limit of 60 fps, 30 s each. The power is the card's whole draw less that of the source
alone in the same state:

```
          new a second   power above the source   card busy
HDR off   60.0           56.5 W                   26 percent
HDR on    60.0           58.1 W and 59.0 W        30 and 31 percent
```

So the HDR path drew 1.6 to 2.5 W more at 60 new pictures a second, within the 2.5 W a row is good
to. With the 16-bit capture and the conversion alone, and an 8-bit swapchain, the same row read
56.5 W, as with HDR off. On the card the conversion took 0.02 ms a frame and the composite 0.04 ms
against 0.03 ms, and the delay read 0.00 ms either way. Without a limit the compositor delivered 114
to 135 frames a second from run to run with HDR on, so those runs do not compare row by row. They
drew about 1 W for each new picture a second, with HDR on or off. In video memory at 3840x1198, the
four textures of the capture take 140 MiB in place of 70 MiB, the two 8-bit frames 35 MiB and the
swapchain's two buffers 70 MiB in place of 35 MiB. The engine held 600 MiB at its start with HDR on
against 487 MiB with it off. With HDR off the engine draws the same picture byte for byte and costs
what it did. Neither the conversion's time at 6144x2526 nor HDR on the main monitor was measured.

### The ReShade engine under HDR

The ReShade engine shows standard range only. windows-capture 2.0.1, which the presenter uses, asks
Windows Graphics Capture for 8-bit BGRA. Its Python binding hard-codes `ColorFormat::Bgra8`, while
the Rust crate under it supports `Rgba16F`. The presenter's swapchain is `B8G8R8A8_UNORM` in
`SRGB_NONLINEAR`.

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

**The warning.** While Windows HDR is on for the lens's monitor and the ReShade engine draws the
picture, the lens warns that the picture comes out washed out. That is a lens in a window, a lens
attached to a window or with its title bar hidden, and a fullscreen lens on the ReShade engine,
whether the Fullscreen page of Settings chose that engine or the fast engine is not installed or has
failed. A fullscreen lens on the fast engine gets no warning, and nor does one while the ReShade
engine stands in for a fast engine that got no picture from the screen, as after an unlock, since
the fast engine comes back by itself, see An engine that gets no picture has not failed.

- The lens reads its monitor's state once a second, see Telling HDR from Auto Colour Management, so
  the warning follows HDR switched on or off, and a move of the lens to another monitor, within
  about a second.
- A fullscreen lens, a lens attached to a window and a lens with its title bar hidden show the whole
  warning on the notice for 12 s in the warning colour, as a line of its own after those for a
  program in exclusive fullscreen and for a sentence the lens keeps up to be read, and before the
  latest message. It says that the picture comes out washed out because Windows HDR is on for this
  monitor, to switch HDR off for the monitor or, where the lens can offer it, to use fullscreen on
  the fast engine, and that the warning can be switched off in Settings, Picture. The lens cannot
  offer the fast engine where its exe or the Cost Scaler's files are missing, or where it has failed
  in this run of the lens.
- A lens in a window has a bar narrower than that, so for 12 s the bar carries the longest of three
  short sentences that fits there, `Windows HDR is on for this monitor. See Settings, Picture.`,
  `Windows HDR is on. See Settings, Picture.` or `HDR is on. See Settings, Picture.`, chosen again
  when the lens is resized. Where none fits beside the bar's title, the title gives way until the
  sentence goes, and a lens too narrow for the shortest beside its controls cuts it short at its
  end, down to none of it at the narrowest. On a test computer with Windows 11 the shortest was
  whole from 566, 640 and 750 px at a display scale of 100, 125 and 150 percent. The Picture page of
  Settings shows the whole warning in the warning colour when it applies as Settings opens.
- It comes each time it begins to apply, and once more when the lens goes fullscreen or comes back
  to a window, and not when the picture only restarts, as for a new pass count. It goes at once when
  HDR goes off, when the fast engine draws the picture, and while the lens is minimised.
- The Picture page of Settings has a switch for it, Warn when Windows HDR is on, which starts
  ticked. Unticked, the ini holds `hdr_warn = 0`, and ticked, the key is left out. Unticking it
  takes a warning that is up away at once, ticking it says it again at the next reading where it
  still applies, and Save names `hdr_warn 0` or `hdr_warn 1` in its one line. The log has a line
  either way, see The lens's log.

What an HDR path through the presenter and the stack would need for the ReShade engine, from reading
the parts on 2026-09-30:

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

Since 0.6.1 a lens in a window, with its title bar shown or hidden, is never narrower than the
controls on its bar, with the pass count at its widest, and never under 240 px, the narrowest a drag
could make it before. Worked out with the bar's own widgets and fonts on a test computer with
Windows 11, that is 322, 366 and 414 px at a display scale of 100, 125 and 150 percent. A drag on
the frame stops there, and a resize, the way back from fullscreen and a start at a size saved
narrower widen the lens to it. Tk's packer hands out the bar's room in the order things went onto
it, so the bar takes its buttons first and its words after them, and a narrow lens cuts its title,
its readout and the profile selector short before any button.

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
  keeps the card busy. The warning that Windows HDR is on, for a fullscreen lens on the ReShade
  engine, shows in the same way, see The warning under HDR. The readout the bar would show is the
  second line of the menu, kept current while the menu is open.
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
panel takes its place there. From the top it holds the profile picker, the switch that loads a
profile for the program in front, see Profiles, Neural Rendering on or off, a tab for each pass that
runs, the style, the four strengths, the auto mask, the passes, the switch Scale the change with
the strength's own slider while it is on, and the quality step. On the tab of a pass from the
second on each value has a tick, Same as pass 1. Ticked, the pass runs at the first pass's value,
and the control shows that value greyed. Unticked, the value is the pass's own, and the control
moves it alone. Under the values the tab of pass 2 has the switch Runs through pass 1's network,
see Each pass's values, which the tabs of passes 3 and 4 show greyed with the note
`follows pass 2`, and the tab of pass 1 does not show. A pass fewer keeps that pass's own values
in the file for when it comes back. A change goes into `ReShade.ini` at once, into the add-on's
section for the first pass and for the intensity of passes 2 to 4, and into the lens's own
section for the other values of a pass from the second on and for the two switches, see Each
pass's values, in one write that keeps every other byte of the file. The
file is written beside itself and put in its place in one step, so the engine never reads it cut
short, and the engine is told `reload`, at most about ten times a second while a slider moves.
Measured, a change of the intensity from 0.97 to 0.3 changed one line of the file, 1038 bytes to
1037 bytes, and with the value put back the file was byte for byte as before. The engine's shot
differed from the capture by 5.06 of 255 at 0.97 and by 1.58 at 0.3, and a slider moved 91 times in
a second gave 11 reloads. The panel's ranges, 0.00 to 2.00 and -1 for a skin structure left to the
model, are the ones the Cost Scaler's ini gives for the model's settings, and every value lands on a
hundredth. To the right of each slider's number a button with an anticlockwise arrow puts the slider
at 1.00 for the pass shown, as the arrow keys set a value. It is greyed, and does nothing, while its
slider is greyed, for a value ticked Same as pass 1 or for skin structure left to the model, and it
has no key. A new pass count restarts the picture, since the engine takes the count when it starts.
The panel works from the keyboard as well, with the keys under Global hotkeys. A line at its foot
says that the arrow keys pick a setting and change it, that a slider moves faster the longer Left
or Right is held and that the button beside a number puts its slider at 1.00, and the last line
says how a setting's explanation comes up. The add-on of the ReShade engine reads only its own
section, so there every pass from the second on runs at the first pass's values apart from the
intensity of passes 2 to 4, and neither switch does anything.

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
- **The compositor can time the display by another monitor's refreshes.** With a second monitor at
  3840x1200 and 144 Hz connected, the compositor at times timed the 120 Hz display's frames by the
  second monitor's refreshes, for hours on end, and the fast engine's delay over the moving source
  then read 7 to 11 ms, where it read 0.0 ms with the compositor on the display's own refreshes. An
  earlier build of the engine read the same, so the state is not the engine's. The profile's `grid`
  and `lead` tell the two apart, 0.00 ms and 8.3 ms on the display's own refreshes against about
  2 to 3 ms and 3 to 7 ms on the other monitor's. Whether a restart of Windows ends it was not
  tried. Say with each delay figure which state it was taken in.
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

The NR settings panel explains each of its settings the same way, with a text of its own for each,
`PANEL_WHY` in neural_lens.py, after the pointer has rested on it for a second and a half. The
panel is a window of the lens's own that never takes the keyboard, so its explanation is one too.
It is shown as the lens's own windows are, out of the capture and never taking the foreground, a
click gives nothing the keyboard, and the panel's own keys take it away, since they never reach
Tk. F1 is held as a hotkey while the panel is open, beside the arrow keys, Enter and Escape, and
not for the menu or the note. It shows the explanation of the setting the arrow keys are on,
below it, or with none picked the one under the pointer. Where a hotkey of Settings is F1 on its
own, the panel leaves F1 to it, and the line at the panel's foot says only to rest the pointer.

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
