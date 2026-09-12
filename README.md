# DLSS 5 Neural Lens

**Beta, version 0.1.0.** See [CHANGELOG.md](CHANGELOG.md). While the version starts with 0,
settings, the state file format and behaviour may change between releases.

A floating see-through window for Windows. Drag it over anything on your desktop and the
content underneath appears inside it with **NVIDIA DLSS Neural Rendering** applied, live. The
mouse passes straight through the viewport, so you can keep using whatever is beneath it, much
like the Windows Magnifier lens.

The point of it is that Neural Rendering normally exists only inside a game that integrates
DLSS. This puts it on anything that can be drawn on your screen: a browser, a video, an
emulator, a photo, a remote desktop session. Nothing is injected into the target application,
and the target does not need to know anything about DLSS.

It can also apply **several neural passes**, adjustable while it runs with plus and minus in
the title bar.

## Before you start, the honest prerequisite

**This project is the window, not the neural rendering.** It drives an existing mpv install
that already has a working DLSS Neural Rendering setup, and it does nothing without one.

That setup is an experimental community stack, and assembling it is genuinely the hard part.
None of it is included or redistributed here. The installer's setup can fetch and assemble it
for you, see Install below, or you can bring an mpv install of your own that already contains:

| component | what it does | comes from |
|---|---|---|
| ReShade, installed as its Vulkan layer | hosts the two add-ons below | reshade.me |
| `dlss5-feed.addon64` | synthesises the inputs DLSS expects, such as depth and motion vectors, for content that has none of its own | its own project |
| `renodx-dlss5.addon64` | performs the neural rendering pass | its own project |
| `nvngx_dlss.dll` | NVIDIA's DLSS runtime | NVIDIA |
| `nvngx_dlssnr.dll` | NVIDIA's Neural Rendering model | NVIDIA |

### Which Neural Rendering model, by card generation

`nvngx_dlssnr.dll` is NVIDIA's model, and the version this was built against is **310.8**. Which
build of it you need depends on your card:

| card | model |
|---|---|
| RTX 50 series (Blackwell) | NVIDIA's stock 310.8 model, unmodified |
| RTX 40 series (Ada) | a community modified build of the same 310.8 model |

All carry the same `NVIDIA DLSSNR - DVS PRODUCTION` description, so identify them by hash. Three
builds are known to run:

```
stock, RTX 50          E16BCF15E16E13F527491CDF7845B2FE6521A738D8F7C9C721866A8496E1FC8E   165,840,496 bytes, version 310.8.0.0
40 series, current     6EB209E764F39872625DEBD6ABAF45E2BB6322F6F270F781F70C059AE30B3927   165,830,144 bytes, version 310.8.SF.0
40 series, earlier     8270B350CD82DE5CE89806872CDD6B6A9249B80836B91BBEB3573470744CC206   165,840,496 bytes, version 310.8.0.0
```

None is included or redistributed here. The setup fetches the one for your card from the RHI
project's repository and refuses it unless it matches one of these hashes. If Neural Rendering
never engages on a 40 series card with the stock model, this is the first thing to check.

The test is simple: if you can open a video in that mpv and see Neural Rendering applied to it,
you have everything you need. If you cannot, fix that first.

You also need:

- Windows 11. The capture path uses Windows.Graphics.Capture. Developed on 25H2.
- An NVIDIA RTX GPU with a driver new enough for DLSS Neural Rendering.
- Python 3 with `numpy` and `windows-capture`.

## Install

**The installer.** Run `NeuralLens-Setup-<version>.exe` from the releases page. It needs no
administrator prompt: it puts the lens under your own user folder, adds a Start Menu entry and
an uninstaller, and that is all it contains. On first start the lens offers to set up the
neural stack. Nothing of the stack is bundled; about 230 MB is downloaded from the projects
that publish each part into a folder of your own, and ReShade is registered as a Vulkan layer
for your user only, under its own name, so an existing ReShade on the machine is left alone.

What it fetches, and from where:

| part | from |
|---|---|
| mpv | shinchiro's mpv-winbuild-cmake, the current release |
| ReShade 6.8.0 with add-on support | reshade.me, the DLL taken out of the setup without running it |
| `nvngx_dlss.dll` 310.8.0 and the Neural Rendering model for your card | the RHI project's manifest, hash checked against this README |
| `dlss5-feed.addon64` and `DLSS5_Feed.fx` | DLSS5-Feeder, the current release |
| `renodx-dlss5.addon64` | the RHI repository |
| ReshadeMotionEstimation (CC BY-NC 4.0), VORT (MIT) and ReShade's two shader headers | their repositories |

If you already have NVIDIA's two DLLs, point the setup at them and it uses those instead, once
their hashes check out. Motion vectors come from ReshadeMotionEstimation by Jakob Wapenhensch,
CC BY-NC 4.0, which measured crisper on scrolling text than every other estimator that may be
fetched, and a little crisper than LumeniteFX. VORT (MIT) is fetched too and can be chosen
instead. If you already have LumeniteFX and prefer it, point the setup at its folder and your
copy is used; it cannot be downloaded for you. The setup is for personal, non-commercial use,
which is what that licence allows. The setup ends with a self test that opens an mpv window for a few
seconds and reads ReShade's log, and says plainly whether Neural Rendering ran. The Start Menu
also has a "stack setup" entry to fetch or repair it later.

**From source**, if you would rather:

1. Put this folder anywhere you like. It runs in place.
2. `pip install numpy windows-capture`
3. Tell it where your mpv install is, whichever way suits you:
   - `Launch-LensNR.cmd --mpv-dir "D:\path\to\mpv"`
   - `set NEURAL_LENS_MPV_DIR=D:\path\to\mpv`
   - copy `neural-lens.ini.example` to `neural-lens.ini` and set `mpv_dir`
   - or put an `mpv` folder beside `neural_lens.py`
4. Run `Launch-LensNR.cmd`. No console window opens. Everything the lens prints goes to
   `%LOCALAPPDATA%\NeuralLens\logs\lens.log`, and anything that stops it from starting is shown
   as a dialog. To watch it live instead, run `python neural_lens.py`.

Window position, pass count, screenshots and archived logs live in `%LOCALAPPDATA%\NeuralLens`.
Redirect all of it with `data_dir` in the ini, or the `NEURAL_LENS_DATA` variable. Screenshots
can also be pointed somewhere else on their own, from the menu's Settings.

## Using it

- **Move it** by dragging the title bar. The viewport is click-through, so clicking inside it
  reaches whatever is underneath rather than the lens.
- **Close it** with the X. Because the viewport can never take keyboard focus, mpv's usual `q`
  will not reach it, which is why the X is there.
- The **menu** at the left opens the ReShade overlay in place so you can adjust Neural
  Rendering settings live, and also holds the pass controls and a Neural Rendering on and off
  toggle.
- **Save a before and after screenshot** from the menu. It writes three PNGs: the untouched
  content the lens captured, the neural rendered result, and the two joined side by side. Both
  halves come from the same live pipeline a fraction of a second apart, so on still content they
  line up pixel for pixel. It pauses briefly first, so the menu you just used is not in the shot.
- **Passes** are chosen with the plus and minus on the title bar and applied with **Set**, so
  going from one pass to four is one rebuild rather than three. The number turns amber while
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
  covers the whole monitor it is on, with the title bar over the top edge of the picture, and
  cannot be dragged. Changing it restarts the lens, like a resize, and the windowed position
  and size are kept for the way back. A whole monitor is a lot of pixels: expect the frame
  rate to settle well below the windowed one, and see [Frame rate](#frame-rate) for what it
  does about that.

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

Neural Rendering here is applied by a ReShade add-on, and that add-on offers no setting for
running its pass more than once. So extra passes are produced by running the whole pipeline
again: a second stage captures the first stage's mpv window and neural renders that already
neural rendered image, and so on. The stages stack on the same rectangle, and only the last one
is visible.

The passes genuinely accumulate rather than merely looking different. Cumulative change from
the untouched source, as mean absolute difference out of 255:

| passes | cumulative | added by that pass |
|---|---|---|
| 1 | 7.71 | 7.71 |
| 2 | 14.05 | 6.34 |
| 3 | 19.45 | 5.40 |

Running the same chain with Neural Rendering switched off changes the image by only 0.24, so
the round trip through capture and mpv is very nearly lossless, and what accumulates really is
neural work. The maximum is 4, changeable with `max_passes` in the ini.

**Each pass lowers the frame rate on purpose.** Every pass is another full capture and present
stage, so the chain delivers fewer frames per second, and each stage is asked for a little less
than the stage feeding it. The visible stage starts at five sixths of your display's refresh
rate at one pass, and at that divided by the pass count beyond, and the rate is then adjusted to
what the machine actually manages (see Frame rate below).

Asking a stage for more than it can deliver makes it present frames that have not arrived yet,
and Neural Rendering then re-runs over its own output. A large mismatch crushes the picture
toward black or white and recovers, over and over. A small one makes it shimmer instead.

Two passes is usually the sweet spot. Three is visibly heavy on most content.

### Frame rate

The rate the lens asks for is adjusted while it runs, because what a chain can deliver depends
on the GPU, the size of the lens, the number of passes and whatever else the GPU is doing at the
time. Measured on an RTX 4070 SUPER, a 1400x1000 lens at one pass held 100 with the GPU idle and
about 60 with a video playing beside it; the same lens at two passes held 35; a 2000x1400 lens
held 41. On an RTX 5090 the same 1400x1000 lens held 100 at one pass.

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

A rate that failed is not held against the lens for ever. Something else using the GPU, a game
or a video, lowers what the chain can carry for as long as it runs, and a limit learned then is
wrong once it stops. So a limit is tried again after the picture has been clean for a while, on
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
- **Exclusive fullscreen games are invisible to it**, because the Magnification API cannot see
  them. Borderless windowed works. Games with real DLSS support can usually take Neural
  Rendering directly through the add-on anyway, without this.
- **Never add `--untimed` to mpv.** It makes mpv present the same frame repeatedly, and Neural
  Rendering then processes its own output over and over until the picture collapses.

## Troubleshooting

**The lens warned at startup that Neural Rendering will probably not run.** It checks the mpv
folder for `dlss5-feed.addon64`, `renodx-dlss5.addon64` and `nvngx_dlssnr.dll`, and names any
that are missing. Finding the folder only proves `mpv.exe` is in it, so an ordinary mpv install
is accepted and the lens opens normally: it simply shows the screen back to you unchanged, which
looks like the app doing nothing rather than an install that is incomplete. See
[Before you start, the honest prerequisite](#before-you-start-the-honest-prerequisite) for what
the mpv install has to carry. None of it is included or redistributed here.

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
that size. If it happens repeatedly, `%LOCALAPPDATA%\NeuralLens\logs\restart.log` holds whatever
the replacement printed before it gave up.

**Something went wrong and you want to know why.** Every launch copies the previous session's
`ReShade.log` and `dlss5-feed.log` into `%LOCALAPPDATA%\NeuralLens\logs`, keeping the 80 most
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
setup time from the project that publishes it, and each keeps its own licence:

| what | by | licence |
|---|---|---|
| ReShade, whose add-on build hosts the two add-ons and whose Vulkan layer hooks mpv | crosire | BSD 3-Clause |
| DLSS5-Feeder, the add-on that builds the inputs DLSS expects, and `DLSS5_Feed.fx` | Jean-Laurent Rouzies | MIT |
| the `renodx-dlss5` add-on that runs the neural pass, built on RenoDX | the RenoDX community; RenoDX itself by Carlos Lopez Jr. | the add-on has no published licence; RenoDX is MIT |
| RHI and its repository, which publish the DLSS manifest and host the add-on and runtimes | RankFTW | GPL-3.0 |
| mpv, and the Windows builds the setup fetches | the mpv project; builds by shinchiro | GPL |
| ReshadeMotionEstimation, the default motion vector estimator | Jakob Wapenhensch | CC BY-NC 4.0 |
| vort_Shaders, the alternative estimator | Vortigern | MIT |
| LumeniteFX, used only from a copy you already have | Afzaal | no licence published |
| DLSS, the DLSS runtime and the Neural Rendering model | NVIDIA | NVIDIA's terms |
| windows-capture, the screen capture binding | NiiightmareXD | MIT |
| NumPy | the NumPy developers | BSD 3-Clause |
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
