# DLSS 5 Neural Lens

A floating see-through window for Windows that applies **DLSS 5 Neural Rendering** to
whatever is behind it. Drag it over any window on the desktop; the content underneath is
neural-rendered live inside it, and the mouse passes straight through to the desktop, like the
Windows Magnifier lens. Also included: a fixed-region screen demo and a phone (scrcpy) variant.

No renderer, no DLSS integration and no injection into the target app are required. If it
can be drawn on the desktop, it can be neural-rendered.

## How it works

Every stage below was measured before it was built; the dead ends are listed further down so
nobody repeats them.

```
Magnification API host window, UNDER the lens on the same rect,
  with the lens's own windows on its EXCLUDE filter list
      -> asks DWM to render the true desktop content for that rect (what Magnifier does)
Windows.Graphics.Capture captures that host window BY HWND
      -> reads the window's own DWM buffer, so the lens sitting on top is irrelevant
raw BGRA frames straight into mpv's stdin (--demuxer=rawvideo)   no ffmpeg, no codec
      -> mpv's ReShade stack (dlss5-feed + renodx-dlss5) performs Neural Rendering
mpv drawn on top: click-through, always-on-top, no window dragging
```

Moving the lens only moves three windows and re-aims the magnifier every 16 ms. Nothing
restarts, so it stays smooth.

## Requirements (not included, not redistributed)

- Windows 11 (Windows.Graphics.Capture; tested on 25H2) and an RTX GPU with a DLSS 5 driver
- Python 3.12 with `numpy` and `windows-capture` (`pip install windows-capture`)
- An **mpv** install at `C:\Games\_mpv` with a working DLSS 5 Neural Rendering stack:
  ReShade (as the Vulkan layer), `dlss5-feed.addon64`, `renodx-dlss5.addon64`,
  `nvngx_dlss.dll`, and NVIDIA's `nvngx_dlssnr.dll`. Get each from its own source.
- For `Launch-PhoneNR.cmd`: scrcpy running first

## Files

| file | what |
|---|---|
| `Launch-LensNR.cmd` + `_screennr-lens3.py` | the see-through lens |
| `Launch-ScreenNR-Demo.cmd` | fixed screen region -> NR window beside it (2x magnify or 1:1) |
| `Launch-PhoneNR.cmd` + `_screennr-findwin.py` | scrcpy window -> NR window beside it |
| `_screennr-resize.py` | Ctrl+Alt+R outline-drag-confirm resize (restart-based) for the two demos |
| `deploy.cmd` | copies the files to `C:\Games`, where the launchers expect them |
| `legacy/` | earlier lens designs kept for reference; they do not work (see below) |

## Limits

- **Size is fixed per run.** Resizing recreates mpv's swapchain, which makes the NR add-on
  release the DLSS feature and crash (`0xC0000005`). Edit the first line of
  `C:\Games\_screennr-lens-state.txt` (`W H X Y`) and relaunch.
- The viewport is click-through, so it never holds keyboard focus and `q` cannot quit mpv.
  Use the X. To reach the ReShade overlay, use the dropdown's **Tweak NR settings**: it makes
  the viewport interactive, focuses it and presses Home; **Done tweaking** reverses it. The
  dropdown also has one-shot NR toggle (F6) and screenshot (F5).
- The Magnification API does not see exclusive-fullscreen games; borderless is fine.
- Never add `--untimed` to mpv: it re-presents the same frame many times and NR then iterates
  on its own output until the image collapses.

## Dead ends, with the measurement that killed each

- **Desktop Duplication (`ddagrab`) under the lens**: it cannot see beneath an occluding
  window, excluded-from-capture or not, even with a magnifier repainting underneath.
  Region under the lens: YAVG 18 (black is 16) vs 46 elsewhere. Only transient dirty rects land
  in it, which produced mouse trails and window-drag smears.
- **`gdigrab`/BitBlt of the magnifier window**: blank even unoccluded; the magnifier
  composites via DWM and BitBlt only sees the empty GDI surface.
- **`MagSetImageScalingCallback`**: deprecated, accepted, deadlocks on the next call from
  ctypes. Replaced entirely by WGC on the host window.
- **UDP transport**: resyncs badly after a restart (353 buffering events, frames every few
  seconds). Moot now that nothing restarts; TCP and a pipe both measured 60 fps.
- **`--untimed`**: the original "runaway neural blob". Presents outnumbered frame arrivals.

## Gotchas

- WGC cannot find a `WS_EX_TOOLWINDOW` window; the magnifier host must be a plain popup.
  Capture by `window_hwnd`, not by name.
- `windows_capture` dispatches handlers by function `__name__`: they must be called
  `on_frame_arrived` / `on_closed`.
- `frame.frame_buffer` is row-padded and non-contiguous: slice `[:h, :w, :]` and use
  `np.ascontiguousarray(...).tobytes()`.
- Passing `HWND_TOPMOST` as Python `-1` through ctypes silently fails on x64
  (use `c_void_p(-1)`), and mpv resets its z-order anyway: use `--ontop`.
