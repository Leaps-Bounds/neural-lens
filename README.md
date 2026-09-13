# DLSS 5 Neural Lens

**Beta, version 0.1.0.** See [CHANGELOG.md](CHANGELOG.md). While the version starts with 0,
settings, the state file format and behaviour may change between releases.

A floating see-through window for Windows. Drag it over anything on your desktop and the
content underneath appears inside it with **NVIDIA DLSS Neural Rendering** applied, live. The
mouse passes straight through the viewport, so you can keep using whatever is beneath it, much
like the Windows Magnifier lens.

The point of it is that Neural Rendering normally exists only inside an application that
integrates DLSS. This puts it on anything that can be drawn on your screen: a browser, a video,
an emulator, a photo, a remote desktop session. Nothing is injected into the target application,
and the target does not need to know anything about DLSS.

It can also apply **several neural passes**, chosen with plus and minus in the title bar and
applied with Set, while it runs.

## Requirements

- Windows 10 build 19041 or later, 64 bit, which is what the installer requires. The capture
  path uses Windows.Graphics.Capture. It has only ever been tested here on Windows 11 25H2.
- An NVIDIA RTX card with a driver new enough for DLSS Neural Rendering. The setup reads the
  compute capability from `nvidia-smi` and stops below 7.5, which is the RTX 20 series and newer.
- Room on disk for about 540 MB once the stack is in place, of which about 230 MB is downloaded
  during installation.

The installed lens does not need Python. That is only for running from source, below.

## Install

**The installer.** Download `NeuralLens-Setup-<version>.exe` from
[the releases page](https://github.com/Leaps-Bounds/neural-lens/releases) and run it.

**Windows will warn you before it runs.** The installer is not code-signed, so Microsoft Defender
SmartScreen shows "Windows protected your PC" and gives the publisher as Unknown. Click More info
if it is offered, then Run anyway. Every release publishes the installer's sha256; check the file
you downloaded against it first, with `Get-FileHash NeuralLens-Setup-<version>.exe` in
PowerShell, rather than taking the warning's word in either direction.

It needs no administrator prompt: it installs for your user alone, into a folder you choose, and
adds two Start Menu entries, the lens and its stack setup, an uninstaller, and a desktop shortcut
if you tick that. The installer itself contains only the lens.

Setup offers to fetch the neural stack as part of the installation, as a checkbox that is
already ticked. Left ticked, it downloads about 230 MB and assembles the stack before setup
finishes, reporting each step as it goes. **A small mpv window opens for about nine seconds
near the end**: that is the self test checking that Neural Rendering really ran, and it closes
itself. If that step fails, setup still completes and tells you which log to read, and you can
run it again afterwards from the Start Menu's stack setup entry. Untick the box and nothing is
downloaded, and that same entry is how you set it up later.

Everything the lens has lives in its one folder: the program, the stack in `stack`, the layer in
`ReShade`, and its state, logs and screenshots in `data`. ReShade is registered as a Vulkan layer
for your user only, under its own name with its own allow list, so an existing ReShade on the
machine is neither touched nor doubled. Uninstalling removes that folder and that one registry
value, and nothing else: a DLL you pointed the setup at was copied in, so the original stays
where it was, and a `data_dir` you moved outside the install is left alone.

What it fetches, and from where:

| part | from |
|---|---|
| mpv | shinchiro's mpv-winbuild-cmake, the current release |
| ReShade 6.8.0 with add-on support | reshade.me, the DLL taken out of the setup without running it |
| `nvngx_dlss.dll` 310.8.0 and the `310.8.SF-v2` Neural Rendering model | the RHI project's manifest, sha256 checked against the hashes held in `neural_stack.py`; the model's are listed below |
| `dlss5-feed.addon64` and `DLSS5_Feed.fx` | DLSS5-Feeder, the current release |
| `renodx-dlss5.addon64` | the RHI repository |
| ReshadeMotionEstimation (CC BY-NC 4.0), VORT (MIT) and ReShade's two shader headers | their repositories |

Only NVIDIA's two runtimes are verified against a published hash, the ones listed above. The
rest are taken from the current release each project publishes, with the RenoDX add-on pinned to
a version and ReshadeMotionEstimation pinned to a commit.

If you already have NVIDIA's two DLLs, the Start Menu's stack setup entry has a field for each,
and `neural_stack.py` takes `--dlssnr` and `--dlss` on the command line; the installer's own page
does not ask. A DLL you point at is hash checked and copied in, and only the two `310.8.SF-v2`
builds listed under [The Neural Rendering model](#the-neural-rendering-model) are accepted.

Motion vectors come from ReshadeMotionEstimation by Jakob Wapenhensch, CC BY-NC 4.0, which
measured crisper on scrolling text than every other estimator that may be fetched. With it, the
setup is for personal, non-commercial use, which is what that licence allows. VORT (MIT) is fetched too and carries no such limit; it can be chosen only
from the command line, with `NeuralLens.exe --install-stack --provider vort` from an install or
`python neural_stack.py --provider vort` from source, since the Start Menu entry always uses the
default. The setup ends with a self test that opens an mpv window for about nine seconds and
reads ReShade's log, and says plainly whether Neural Rendering ran. The Start Menu also has a
"stack setup" entry to fetch or repair the stack later.

### From source

If you would rather run it from the repository:

1. Put this folder anywhere you like. It runs in place.
2. Python 3 with tkinter, then `pip install numpy windows-capture`.
3. Get a stack. `python neural_stack.py` fetches and assembles one into a `stack` folder beside
   the script, the same as the installer does, and the lens finds it there. Or point the lens at
   an mpv install of your own that already carries the stack, whichever way suits you:
   - `Launch-LensNR.cmd --mpv-dir "D:\path\to\mpv"`
   - `set NEURAL_LENS_MPV_DIR=D:\path\to\mpv`
   - copy `neural-lens.ini.example` to `neural-lens.ini` and set `mpv_dir`
   - or put an `mpv` folder beside `neural_lens.py`
4. Run `Launch-LensNR.cmd`. No console window opens. Everything the lens prints goes to
   `data\logs\lens.log` beside the script, and anything that stops it from starting is shown
   as a dialog. To watch it live instead, run `python neural_lens.py`.

Window position, pass count, screenshots and archived logs live in the `data` folder beside
the program. Redirect all of it with `data_dir` in the ini, or the `NEURAL_LENS_DATA` variable.
Screenshots can also be pointed somewhere else on their own, from the menu's Settings.

## What makes the picture

**The lens is the window. It does not do the neural rendering itself.** That is done by an
experimental community stack, and none of it is included or redistributed here. The installer
fetches each piece from the project that publishes it, see [Install](#install), and from source
`neural_stack.py` does the same. What has to be present is:

| component | what it does | comes from |
|---|---|---|
| ReShade, installed as its Vulkan layer | hosts the two add-ons below | reshade.me |
| `dlss5-feed.addon64` | synthesises the inputs DLSS expects, such as depth and motion vectors, for content that has none of its own | its own project |
| `renodx-dlss5.addon64` | performs the neural rendering pass | its own project |
| `nvngx_dlss.dll` | NVIDIA's DLSS runtime | NVIDIA |
| `nvngx_dlssnr.dll` | NVIDIA's Neural Rendering model | NVIDIA |

### The Neural Rendering model

`nvngx_dlssnr.dll` is NVIDIA's model, and the version this was built against is **310.8**. One
build covers every RTX card, so there is nothing to choose and the setup does not ask. It checks
only that an NVIDIA RTX card is present, meaning compute capability 7.5 or higher, which is the
RTX 20 series and newer, and says so plainly when there is not one.

The build used is `310.8.SF-v2`. It was published for the RTX 40 series and its author states it
also covers RTX 20 and 30 and runs identically on RTX 50. It was measured here creating and
evaluating Neural Rendering on an RTX 5090, matching the stock model's effect on the image to
within 0.01 at two pinned rates.

All these builds carry the same `NVIDIA DLSSNR - DVS PRODUCTION` description, so identify them by
hash rather than by version string. Three are known to run:

```
310.8.SF-v2, what the setup fetches
                       6EB209E764F39872625DEBD6ABAF45E2BB6322F6F270F781F70C059AE30B3927   165,830,144 bytes, version 310.8.SF.0
NVIDIA's stock 310.8   E16BCF15E16E13F527491CDF7845B2FE6521A738D8F7C9C721866A8496E1FC8E   165,840,496 bytes, version 310.8.0.0
an earlier community build
                       8270B350CD82DE5CE89806872CDD6B6A9249B80836B91BBEB3573470744CC206   165,840,496 bytes, version 310.8.0.0
```

None is included or redistributed here. The setup fetches the `310.8.SF-v2` model from the RHI
project's repository and refuses a download that matches neither of its two hashes, the first
and the last above. A DLL you point the setup at is checked the same way, so NVIDIA's stock
310.8 is listed here so you can identify it, and is not accepted: the SF-v2 build is what runs on
every card.

If you are bringing an mpv install of your own, the test is simple: open a video in it and see
whether Neural Rendering is applied. If it is not, fix that first.

## Using it

- **Move it** by dragging the title bar. The viewport is click-through, so clicking inside it
  reaches whatever is underneath rather than the lens.
- **Close it** with the X. Because the viewport can never take keyboard focus, mpv's usual `q`
  will not reach it, which is why the X is there.
- The **menu** at the left opens the ReShade overlay in place so you can adjust Neural
  Rendering settings live, and also holds the pass controls and a Neural Rendering on and off
  toggle. The menu button opens and closes it; so does a click anywhere else, or Escape.
- **Save a before and after screenshot** from the menu. It writes three PNGs: the untouched
  content the lens captured, the neural rendered result, and the two joined side by side. Both
  halves come from the same live pipeline a fraction of a second apart, so on still content they
  line up pixel for pixel. It pauses briefly first, so the menu you just used is not in the shot.
- **Passes** are chosen with the plus and minus on the title bar and applied with **Set**, so
  going from one pass to three is one rebuild rather than two. The number turns amber while
  it differs from what is running. The menu's add and remove entries apply at once.
- **Live A/B split** from the menu puts a draggable divider across the lens, with Neural
  Rendering on the left of it and the untouched source on the right, both live. It costs
  nothing: the lens is see-through, so the right side is simply the screen underneath. Works
  at any pass count and in fullscreen. Pick the menu entry again to end it.
- **Resize it** from the menu. A translucent outline appears over the lens showing its live
  size. Drag any edge, let go, and confirm. See [Limits](#limits) for why this restarts.
- **Settings** in the menu chooses where screenshots are saved, and remembers the choice in
  `neural-lens.ini`.
- **F6 turns Neural Rendering off and on** in every pass at once, from the menu or the key
  itself. The add-on reads the physical key, so F6 pressed anywhere toggles it. While it is off
  the title bar says `NR off` and the pass controls wait, because a pass with Neural Rendering
  off is only a copy of the last one.
- **It has a taskbar button.** A fullscreen application, or another window that insists on
  being on top, can leave the lens buried underneath it. Click the lens on the taskbar and it
  comes back to the front and stays on top again. The button's Close window closes the lens.
- **Fullscreen** is a checkbox in Settings, and is **experimental**: it is the least tested
  part of the lens, included to be tried and reported on rather than relied on. The lens
  covers the whole monitor it is on, with the title bar over the top edge of the picture, as a
  short bar in the bottom right corner instead while the ReShade overlay is open from the menu,
  and cannot be dragged. Changing it restarts the lens, like a resize, and the windowed position
  and size are kept for the way back. A whole monitor is a lot of pixels: expect the frame
  rate to settle well below the windowed one, and see [Frame rate](#frame-rate) for what it
  does about that. If the Cost Scaler proxy is in the stack, fullscreen is where the lens
  switches it on; see [The Cost Scaler proxy](#the-cost-scaler-proxy).

## How it works

The obstacle this works around is that you cannot simply capture the screen area underneath a
window. Windows does not draw the desktop behind an opaque window, so ordinary screen capture
of that region comes back empty.

```
A Magnification API host window sits UNDER the lens, on the same rectangle, with all of the
lens's own windows on its exclude list
      -> Windows renders the true desktop content for that rectangle, the same mechanism the
         built-in Magnifier uses. This is a render request, not a screen capture.
Windows.Graphics.Capture captures that host window by its handle
      -> window capture reads a window's own buffer, so the lens sitting on top of it and
         hiding it makes no difference
raw BGRA frames go straight into mpv's standard input
      -> no encoder, no codec, no intermediate file
mpv's ReShade stack applies Neural Rendering, and mpv is drawn on top: click-through,
always on top, and never moved by clicks
```

Moving the lens only repositions those windows and re-aims the magnifier. Nothing restarts.

### Multiple passes

How the extra passes are made depends on the add-on in the stack.

The RenoDX DLSS 5 add-on from its v5 line runs the passes itself, inside the one mpv, and
takes the count from `NRPasses` in its section of ReShade.ini when its process starts. The lens
recognises such an add-on, writes the count there, and restarts its single stage whenever the
count is applied with Set. Measured against chaining on an RTX 5090, a 2400x1800 lens over a
still image: two passes inside the add-on presented up to 69 frames a second where two chained
stages presented 51, three passes 53 where three stages presented 33, and the change to the image
was the same within 2 out of 255. The add-on's own limit is four passes. `passes_mode` in the ini
forces either way. The stack the setup fetches still carries the 4.70 add-on, which chains, so an
installed lens runs the passes inside the add-on only once the add-on in its stack is replaced
by a v5 build.

Add-ons before that line offer no setting for running the pass more than once, so with those the
extra passes are produced by running the whole pipeline again: a second stage captures the first
stage's mpv window and neural renders that already neural rendered image, and so on. The stages
stack on the same rectangle, and only the last one is visible.

The passes genuinely accumulate rather than merely looking different. Cumulative change from
the untouched source, as mean absolute difference out of 255:

| passes | cumulative | added by that pass |
|---|---|---|
| 1 | 7.71 | 7.71 |
| 2 | 14.05 | 6.34 |
| 3 | 19.45 | 5.40 |

Running the same chain with Neural Rendering switched off changes the image by only 0.24, so
the round trip through capture and mpv is very nearly lossless, and what accumulates really is
neural work. With the passes inside the add-on the title bar goes up to four, the add-on's own
limit, and a count chosen in the ReShade overlay's own control reaches the title bar within about
two seconds while the overlay is open. Chained, three is the ceiling and the highest that is
tested; `max_passes` in the ini raises it, and going above three that way is experimental: at four
chained stages the rate search has been measured hunting across a 40 fps spread on a still image,
so the frame rate can swing and the picture can wander.

**Each pass lowers the frame rate on purpose.** Every pass is another full capture and present
stage, so the chain delivers fewer frames per second, and each stage is asked for a little less
than the stage feeding it. The visible stage starts at five sixths of your display's refresh
rate at one pass, and at that divided by the pass count beyond, and the rate is then adjusted to
what the machine actually manages (see Frame rate below). With the passes inside the add-on there
is one stage, so only the neural work grows with the count; the rate starts by the same rule and
the adjustment finds the rest.

Asking a stage for more than it can deliver makes it present frames that have not arrived yet,
and Neural Rendering then re-runs over its own output. A large mismatch crushes the picture
toward black or white and recovers, over and over. A small one makes it shimmer instead.

Two passes is usually the sweet spot. Three is visibly heavy on most content.

### Frame rate

The rate the lens asks for is adjusted while it runs, because what a chain can deliver depends
on the GPU, the size of the lens, the number of passes and whatever else the GPU is doing at the
time. Measured on an RTX 4070 SUPER, a 1400x1000 lens at one pass held 100 with the GPU idle and
about 60 with a video playing beside it; the same lens at two passes held about 35; a 2000x1400
lens held 41. On an RTX 5090 the same 1400x1000 lens held 100 at one pass.

Once a second the lens compares three things: the frames the visible stage presents against the
rate it was asked for, the brightness of what comes out against the range of brightness that has
gone in over the last second and a half, and, while the content under the lens is still, how
much the output changes from frame to frame. A shortfall, a brightness runaway or a shimmer
lowers the rate. The brightness test uses a range rather than the latest value because the
output lags the input slightly, and over a video with scene changes the two would otherwise
disagree while nothing is wrong: that false alarm alone took a lens from 100 to 12 fps. When
the picture has been stable for a while and the content is still, the rate probes upward again
in small steps, never above five sixths of the display rate. A rate the lens has already held
is retaken much faster, in a few steps a few seconds apart and over moving content too, since
it is known to work: after a fifteen second knock down, a 4070 was back at its level in 16
seconds.

A rate that failed is not held against the lens for ever. Something else using the GPU, a video
or another application, lowers what the chain can carry for as long as it runs, and a limit
learned then is wrong once it stops. So a limit is tried again after the picture has been clean for a while, on
a wait that doubles each time the limit turns out to be real. Measured on an RTX 5090 at one
pass: 100 with the GPU to itself, 62 under load, and back to 99 about half a minute after the
load stopped. The highest rate the chain actually held is saved with the window position, so
the next launch starts from that rather than from whatever it happened to be running when it
closed.

The picture in the lens runs a little behind what is under it, since every frame is captured,
handed to mpv, neural rendered and presented again. Measured at one pass and 99 fps with a
window flipping between black and white under the lens, from the flip on screen to the flip in
the output: 68 ms. It was 136 ms until mpv's readahead was cut from eight frames to two; the
lens plays slower than frames arrive, so that buffer was always full and every frame in it was
delay. Over a video this is the gap between the sound and the lens's picture, and it grows at
lower frame rates, because each buffered frame lasts longer.

The title bar can show that delay: **Show the delay from capture to display** in Settings, under
Title bar. The lens logs every frame it sends with the time Windows composed it, asks mpv four
times a second which frame it is showing, and takes the difference, plus an allowance for the
steps that cannot see: the magnifier's repaint and composition before the capture, and the
present, composition and scanout after. Calibrated against the flip measurement above on an
RTX 5090 with a 120 Hz display, it read 70 ms where the flip measured 70 at 99 fps, and 181
where the flip measured 183 at 33 fps; the measured part alone was 34 and 137. The bar marks
it with a tilde because the allowance is an estimate.

The title bar shows the frame rate the lens is actually showing you, averaged over the last few
seconds, with a word beside it when the adjustment has just acted. Settings can change that to
the input and output sides instead, where `120 in  33 out` means capture delivers 120 frames a
second into the first stage and the visible stage is asked for 33, or to the size alone. It
also has a switch to turn the adjustment off and keep the fixed rule, a slider for the lowest rate it may
go to, and sliders for the frame rate ceiling and the capture refresh, each with an explanation
of what it does. Everything the lens can be told lives in that dialog; the ini file is only
where it writes the answers.

The single biggest factor in the input rate was a library default rather than anything
expensive: the capture binding's `minimum_update_interval` throttles delivery to about 60 fps
unless it is set to 0. See [docs/NOTES.md](docs/NOTES.md).

### The presenter

The lens can host its stage in a presenter of its own instead of mpv: `host = presenter` in the
ini, or `--presenter` on the command line. The presenter, `lens_presenter.py`, is a Vulkan
window that captures the monitor itself, cropped to the lens with the lens's own windows
excluded from capture, and presents each frame the moment it arrives; between arrivals it
presents the last frame again at the display's rate, copied in afresh each time so Neural
Rendering never works on its own output. Nothing buffers, so there is no rate to govern and no
magnifier to drive, and the delay meter reads the presenter's own figure. ReShade, the Feed and
the add-on attach to it as they do to mpv, because it runs as the stack folder's own
`lens-presenter.exe`, which the layer's allow list names.

Measured on an RTX 5090 with a 120 Hz display, from a change on screen to the change in the
output, both read through the compositor:

| | mpv | presenter |
|---|---|---|
| 1400x1000, one pass | 70 ms at 99 fps | 8 ms at 118 fps |
| fullscreen 6144x2560, one pass | 183 ms at 33 fps | 33 ms at 58 fps |

The change Neural Rendering makes to the image is the same through either host on the same
still, with the same settings. The presenter cannot chain stages, since a chained stage would
have to capture a window it excludes from capture, so with an add-on before the v5 line it
runs one pass; with a v5 add-on the passes run inside the add-on as usual. Screenshots come
from the presenter: the frame it captured, and the picture it presented last, read back from
its swapchain.

Until the setup does it, the presenter is put in place by hand: `pip install glfw vulkan` for
the Python the lens runs with, a copy of that Python's `python.exe` in the stack folder named
`lens-presenter.exe` beside a `pyvenv.cfg` holding `home = <that Python's folder>` and
`include-system-site-packages = true`, and the copy's full path added to `Apps=` in the
`ReShade\ReShadeApps.ini` of the install, comma separated after mpv's.

### The Cost Scaler proxy

DLSSNR-Cost-Scaler, by xenmods, MIT, is a proxy `nvngx_dlssnr.dll` that runs the neural model
at a fraction of the frame's resolution and composites the result back onto the full frame. The
setup does not fetch it. To put it in the stack by hand, rename `nvngx_dlssnr.dll` in the stack
folder to `nvngx_dlssnr_real.dll`, then copy the proxy's `nvngx_dlssnr.dll` and `nvngx_dlssnr.ini`
from its release zip beside it. Neural Rendering in mpv runs as a D3D12 NGX session behind the
Feed's Vulkan transport, which is what the proxy hooks, so it works here as it does in a game.

When it is there, the lens switches it on for a fullscreen lens and off for a windowed one,
writing its ini before the stage starts and again whenever the pass count changes. The scale is
chosen so the model's work over all the passes comes to about 8 megapixels: 6144x2560 gets 0.70
at one pass and 0.50 at two, 3840x2160 stays at native for one pass and gets 0.65 at two, and
2560x1440 stays at native up to two passes, since below a saving of about a fifth the proxy's
own cost is all that is left. `cost_scaler_mpx` in the ini changes that budget;
`cost_scaler` set to `always` applies the rule to a windowed lens as well, `off` keeps the proxy
off, and `manual` leaves the proxy's ini alone. Anamorphic scaling is switched off with the scale,
and the proxy's other settings are left as they are.

Measured on an RTX 5090 with the passes inside the add-on, as the most frames a second the visible
stage presented:

| | off | 0.75 | 0.50 | 0.35 |
|---|---|---|---|---|
| fullscreen 6144x2560, one pass | 30 | 43 | 43 | 44 |
| fullscreen 6144x2560, two passes | 23 | 31 | 43 | 43 |
| windowed 2400x1800, one pass | 97 | 88 | | |
| windowed 2400x1800, two passes | 69 | 86 | 91 | |

The price is detail: the change the neural pass makes to the image is about a fifth smaller at
0.75 and almost half at 0.50, because the model sees fewer pixels of what, under a lens, is all
detail. That is why it stays off windowed, where the neural pass is rarely what limits the frame
rate; the one pass windowed row shows the proxy's own per frame cost when it is not.

## Limits

- **Resizing restarts the lens.** It cannot resize in place, because that recreates mpv's
  swapchain, which makes the Neural Rendering add-on release its DLSS feature and crash. The
  menu's resize therefore takes the size you drag out, saves it, and relaunches at that size and
  position with the same number of passes. It takes a second or two. Pass count is unaffected by
  any of this and still changes live.
- **Over fast moving content the picture can wash out at a rate the chain cannot carry**, going
  pale for a few seconds and recovering, without the automatic frame rate noticing, because the
  brightness stays inside the margin it watches. Seen once at 85 fps over a scrolling page on a
  4070; at 30 it did not happen. Lowering the frame rate ceiling in Settings avoids it.
- **Applications in exclusive fullscreen are invisible to it**, because the Magnification API
  cannot see them. Borderless windowed works. An application with real DLSS support can usually
  take Neural Rendering directly through the add-on anyway, without this.
- **Never add `--untimed` to mpv.** It makes mpv present the same frame repeatedly, and Neural
  Rendering then processes its own output over and over until the picture collapses.

## Troubleshooting

**The lens warned at startup that Neural Rendering will probably not run.** It checks the mpv
folder for `dlss5-feed.addon64`, `renodx-dlss5.addon64`, `nvngx_dlss.dll` and
`nvngx_dlssnr.dll`, and names any that are missing. Finding the folder only proves `mpv.exe` is in it, so an ordinary mpv install
is accepted and the lens opens normally: it simply shows the screen back to you unchanged, which
looks like the app doing nothing rather than an install that is incomplete. See
[What makes the picture](#what-makes-the-picture) for what the mpv install has to carry. None of
it is included or redistributed here.

**Neural Rendering looks like it is doing nothing.** If the startup check above said nothing,
the install is fine and this is almost certainly the content. Its strength depends heavily on the
content. It scales with local detail, measured about 4.5 times stronger on the most detailed
tenth of an image than on the flattest half. On a rendered character it is obvious; on flat
interface elements it can be hard to see even while fully active. The menu's before and after
screenshot is the easiest way to settle it: put the lens over something detailed, save the pair,
and compare them. For scale, over a desktop of flat interface the average difference measured
1.3 out of 255 while Neural Rendering was fully live, and almost all of that change sat in the
detailed areas of the image.

**The lens disappeared after you confirmed a resize.** Resizing relaunches the lens, so a
relaunch that fails looks exactly like the app closing on its own. Nothing is lost: the size you
chose was saved before the restart, so starting it again with the launcher brings it back at
that size. If it happens repeatedly, `data\logs\restart.log` in the lens folder holds whatever
the replacement printed before it gave up.

**Something went wrong and you want to know why.** Every launch copies the previous session's
`ReShade.log` and `dlss5-feed.log` into `data\logs` in the lens folder, keeping the 80 most
recent files, so evidence from a failed run survives restarting. Anything mpv itself wrote to
its error stream is in `mpv-stderr.log` in the same folder, which is where to look when a stage
never opened a window. The lens's own output, including every frame rate decision, is in
`lens.log` there, with the previous session's copy stamped beside it. In an archived
`ReShade.log`, the
line that confirms Neural Rendering was really running is `feature=18 (DLSSNR`, which means the
feature was created. Do not judge it by counting `evaluation succeeded (count=` lines: that is a
milestone message, emitted at the first evaluation and the sixtieth and then not again, so a
healthy session that ran for several minutes still shows only two of them.

Bug reports are welcome as GitHub issues. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Notes

[docs/NOTES.md](docs/NOTES.md) is the engineering record: approaches that were tried and
abandoned, each with the measurement that ruled it out, and the Windows API details that are
easy to get wrong. Worth reading before changing how capture or the pass chain works, because
several of the discarded approaches look perfectly reasonable until measured.

## Credits

The lens is the window. Everything that makes the picture is someone else's work, fetched at
setup time from the project that publishes it, and the lens itself is built on libraries that
ship inside the installer. Each keeps its own licence:

| what | by | licence |
|---|---|---|
| ReShade, whose add-on build hosts the two add-ons and whose Vulkan layer hooks mpv | crosire | BSD 3-Clause |
| DLSS5-Feeder, the add-on that builds the inputs DLSS expects, and `DLSS5_Feed.fx` | Jean-Laurent Rouzies | MIT |
| the `renodx-dlss5` add-on that runs the neural pass, built on RenoDX | the RenoDX community; RenoDX itself by Carlos Lopez Jr. | the add-on has no published licence; RenoDX is MIT |
| RHI and its repository, which publish the DLSS manifest and host the add-on and runtimes | RankFTW | GPL-3.0 |
| mpv, and the Windows builds the setup fetches | the mpv project; builds by shinchiro | GPL |
| ReshadeMotionEstimation, the default motion vector estimator | Jakob Wapenhensch | CC BY-NC 4.0 |
| vort_Shaders, the alternative estimator | Vortigern | MIT |
| DLSS, the DLSS runtime and the Neural Rendering model | NVIDIA | NVIDIA's terms |
| windows-capture, the screen capture binding | NiiightmareXD | MIT |
| OpenCV, which windows-capture requires, and which is most of the installer's size | the OpenCV team | Apache 2.0 |
| NumPy | the NumPy developers | BSD 3-Clause |
| Python 3.12, with the libffi and Tcl/Tk libraries its Windows build carries, bundled by PyInstaller; its licence text is installed as `licenses\PYTHON-LICENSE.txt` | the Python Software Foundation; the Tcl core team | PSF; Tcl/Tk licence |
| OpenSSL, the `libcrypto` and `libssl` libraries Python's build carries; its licence text is installed as `licenses\OPENSSL-LICENSE.txt` | the OpenSSL Project | Apache 2.0 |
| zlib, the `zlib1.dll` Python's build carries; its licence text is installed as `licenses\ZLIB-LICENSE.txt` | Jean-loup Gailly and Mark Adler | zlib licence |
| 7-Zip's `7zr`, fetched to unpack mpv | Igor Pavlov | LGPL |
| PyInstaller and Inno Setup, which build the installer | their authors | GPL with exception; Inno Setup licence |

The installer's shape, one small program that bundles nothing and fetches every part from
upstream, follows FeedKit by ntqueryinformation (MIT).

This project is not affiliated with, endorsed by or supported by NVIDIA. DLSS is NVIDIA's
trademark, and the name here says what the lens applies, not who made it.

## License

The lens itself, meaning everything in this repository, is free software under the GNU General
Public License, version 3 or, at your option, any later version. See [LICENSE](LICENSE). The
parts the setup fetches are not part of this repository and keep the licences above. Because
the default motion vector estimator is licensed for non-commercial use only, the stack the
setup assembles is for personal, non-commercial use.
