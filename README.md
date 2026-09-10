# DLSS 5 Neural Lens

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
None of it is included here, none of it is redistributed here, and this README cannot walk you
through it. You need an mpv install that already contains:

| component | what it does | comes from |
|---|---|---|
| ReShade, installed as its Vulkan layer | hosts the two add-ons below | reshade.me |
| `dlss5-feed.addon64` | synthesises the inputs DLSS expects, such as depth and motion vectors, for content that has none of its own | its own project |
| `renodx-dlss5.addon64` | performs the neural rendering pass | its own project |
| `nvngx_dlss.dll` | NVIDIA's DLSS runtime | NVIDIA |
| `nvngx_dlssnr.dll` | NVIDIA's Neural Rendering model | NVIDIA |

The test is simple: if you can open a video in that mpv and see Neural Rendering applied to it,
you have everything you need. If you cannot, fix that first.

You also need:

- Windows 11. The capture path uses Windows.Graphics.Capture. Developed on 25H2.
- An NVIDIA RTX GPU with a driver new enough for DLSS Neural Rendering.
- Python 3 with `numpy` and `windows-capture`.

## Install

1. Put this folder anywhere you like. It runs in place.
2. `pip install numpy windows-capture`
3. Tell it where your mpv install is, whichever way suits you:
   - `Launch-LensNR.cmd --mpv-dir "D:\path\to\mpv"`
   - `set NEURAL_LENS_MPV_DIR=D:\path\to\mpv`
   - copy `neural-lens.ini.example` to `neural-lens.ini` and set `mpv_dir`
   - or put an `mpv` folder beside `neural_lens.py`
4. Run `Launch-LensNR.cmd`.

Window position, pass count, screenshots and archived logs live in `%LOCALAPPDATA%\NeuralLens`.
Redirect all of it with `data_dir` in the ini, or the `NEURAL_LENS_DATA` variable. Screenshots
can also be pointed somewhere else on their own, from the menu's Settings.

## Using it

- **Move it** by dragging the title bar. The viewport is click-through, so clicking inside it
  reaches whatever is underneath rather than the lens.
- **Add or remove a pass** with plus and minus in the title bar, while it runs.
- **Close it** with the X. Because the viewport can never take keyboard focus, mpv's usual `q`
  will not reach it, which is why the X is there.
- The **menu** at the left opens the ReShade overlay in place so you can adjust Neural
  Rendering settings live, and also holds the pass controls and a Neural Rendering on and off
  toggle.
- **Save a before and after screenshot** from the menu. It writes three PNGs: the untouched
  content the lens captured, the neural rendered result, and the two joined side by side. Both
  halves come from the same moment and the same pixels, so it is a fair comparison rather than
  two shots taken seconds apart.
- **Resize it** from the menu. A translucent outline appears over the lens showing its live
  size. Drag any edge, let go, and confirm. See [Limits](#limits) for why this restarts.
- **Settings** in the menu chooses where screenshots are saved, and remembers the choice in
  `neural-lens.ini`.

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

Two passes is usually the sweet spot. Three is visibly heavy on most content.

### Frame rate

At 1400x1000 on an RTX 5090 driving a 120 Hz display, one pass runs at about **111 fps**, near
the panel's refresh rate.

Adding passes costs GPU time: roughly 32 percent utilisation at one pass, 57 at two, 80 at
three. Be aware that the fps figure in the title bar counts frames arriving from capture into
the first stage, not frames presented by the last one, so at higher pass counts it reports the
input side rather than what you are looking at. Measured that way two and three passes both
land around 85 to 90, and the difference between them is inside the noise.

The single biggest factor here was a library default rather than anything expensive: the
capture binding's `minimum_update_interval` throttles delivery to about 60 fps unless it is set
to 0. See [docs/NOTES.md](docs/NOTES.md).

## Limits

- **Resizing restarts the lens.** It cannot resize in place, because that recreates mpv's
  swapchain, which makes the Neural Rendering add-on release its DLSS feature and crash. The
  menu's resize therefore takes the size you drag out, saves it, and relaunches at that size and
  position with the same number of passes. It takes a second or two. Pass count is unaffected by
  any of this and still changes live.
- **Exclusive fullscreen games are invisible to it**, because the Magnification API cannot see
  them. Borderless windowed works. Games with real DLSS support can usually take Neural
  Rendering directly through the add-on anyway, without this.
- **Never add `--untimed` to mpv.** It makes mpv present the same frame repeatedly, and Neural
  Rendering then processes its own output over and over until the picture collapses.

## Troubleshooting

**Neural Rendering looks like it is doing nothing.** Its strength depends heavily on the
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
`ReShade.log` and `dlss5-feed.log` into `%LOCALAPPDATA%\NeuralLens\logs`, keeping the 40 most
recent, so evidence from a failed run survives restarting. In an archived `ReShade.log`, the
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
