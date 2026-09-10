# DLSS 5 Neural Lens

A floating see-through window for Windows that applies **DLSS 5 Neural Rendering** to whatever
is behind it. Drag it over any window on the desktop and the content underneath is
neural-rendered live inside it, while the mouse passes straight through to the desktop, like
the Windows Magnifier lens.

No renderer, no DLSS integration and no injection into the target app are required. If it can
be drawn on the desktop, it can be neural-rendered.

It also does **multiple neural passes**, adjustable live with plus and minus in the title bar.

## How it works

```
Magnification API host window, UNDER the lens on the same rect,
  with every one of the lens's own windows on its EXCLUDE filter list
      -> asks DWM to render the true desktop content for that rect (what Magnifier does)
Windows.Graphics.Capture captures that host window BY HWND
      -> reads the window's own DWM buffer, so the lens sitting on top is irrelevant
raw BGRA frames straight into mpv's stdin (--demuxer=rawvideo)   no ffmpeg, no codec
      -> mpv's ReShade stack (dlss5-feed + renodx-dlss5) performs Neural Rendering
mpv drawn on top: click-through, always-on-top, no window dragging
```

Moving the lens only moves the windows and re-aims the magnifier every 16 ms. Nothing
restarts, so it stays smooth.

### Multiple passes

The add-on that works in mpv has no pass count of its own, so extra passes are made by running
the whole pipeline again. Stage N captures stage N-1's mpv window with WGC and neural-renders
it a second time. Every stage stacks on the lens rect and only the last one is visible.

Passes accumulate cleanly. Cumulative change from the raw source, measured as mean absolute
difference out of 255:

| passes | cumulative | added by that pass |
|---|---|---|
| 1 | 7.71 | 7.71 |
| 2 | 14.05 | 6.34 |
| 3 | 19.45 | 5.40 |

With Neural Rendering disabled the same chain costs only 0.24, so the round trip is nearly
lossless and what accumulates really is neural work. Each pass is another mpv and another NGX
session: three passes measured about 46 fps against about 52 for one, at 1200x900. The ceiling
is 4, adjustable with `max_passes` in the ini.

Two passes is usually the sweet spot. Three is visibly heavy on most content.

## Requirements

None of the neural stack is included here or redistributed. Get each piece from its own source.

- Windows 11 (for Windows.Graphics.Capture; developed on 25H2) and an RTX GPU with a
  DLSS 5 capable driver
- Python 3 with `numpy` and `windows-capture`
- An **mpv** install carrying a working DLSS 5 Neural Rendering stack: ReShade as the Vulkan
  layer, plus `dlss5-feed.addon64`, `renodx-dlss5.addon64`, `nvngx_dlss.dll` and NVIDIA's
  `nvngx_dlssnr.dll`

## Install

1. Put this folder anywhere you like.
2. `pip install numpy windows-capture`
3. Tell the lens where your mpv install is, using whichever you prefer:
   - `Launch-LensNR.cmd --mpv-dir "D:\path\to\mpv"`
   - `set NEURAL_LENS_MPV_DIR=D:\path\to\mpv`
   - copy `neural-lens.ini.example` to `neural-lens.ini` and set `mpv_dir`
   - or simply put an `mpv` folder beside `neural_lens.py`
4. Run `Launch-LensNR.cmd`.

Window position, pass count and archived logs are kept in `%LOCALAPPDATA%\NeuralLens`, which
you can redirect with `data_dir` in the ini or `NEURAL_LENS_DATA`.

## Using it

- **Move it** by dragging the title bar. The viewport itself is click-through, so clicking
  inside it reaches whatever is underneath.
- **Add or remove a pass** with the plus and minus in the title bar. This is safe to do while
  running, because adding a stage never resizes anything.
- **Close it** with the X. The viewport can never hold keyboard focus, so mpv's `q` will not
  work; that is why the X is there.
- The **menu** on the left has `Tweak NR settings`, which makes the viewport interactive and
  opens the ReShade overlay in place so you can adjust Neural Rendering live, and
  `Done tweaking` to put it back. It also has the pass controls, a one-shot NR toggle (F6,
  applied to every pass in turn) and a screenshot key (F5).

## Limits

- **The size is fixed for the duration of a run.** Resizing recreates mpv's swapchain, which
  makes the NR add-on release the DLSS feature and crash with `0xC0000005`. Pass count is not
  affected by this and can be changed freely. To change size, close the lens, edit the first
  line of `%LOCALAPPDATA%\NeuralLens\lens-state.txt` (`width height x y passes`), and relaunch.
- The Magnification API cannot see exclusive-fullscreen games. Borderless is fine, and such
  games can usually take Neural Rendering directly through the add-on anyway.
- Never add `--untimed` to mpv. It presents the same frame many times over, and Neural
  Rendering then iterates on its own output until the picture collapses.

## Troubleshooting

Neural Rendering's visible strength depends heavily on content. It scales with local detail:
measured 4.5x stronger on the most detailed tenth of an image than on the flattest half. On a
rendered character it is obvious, on flat UI it can be hard to see even while fully active.

To check whether it is working, use the dropdown's **Toggle NR on/off (F6)**. With NR live the
image changes clearly, measured at 12.7/255 on plain text.

Every launch copies the previous session's `ReShade.log` and `dlss5-feed.log` into
`%LOCALAPPDATA%\NeuralLens\logs` (the 40 most recent are kept), so a failed run stays
diagnosable after you relaunch. In an archived `ReShade.log`, look for `feature=18 (DLSSNR`
and `evaluation succeeded (count=`.

## Notes

[docs/NOTES.md](docs/NOTES.md) records the approaches that were tried and rejected, each with
the measurement that killed it, plus the Win32 details that are easy to get wrong. Worth
reading before changing the capture path or the pass chain.
