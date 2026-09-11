# Changelog

Versions follow semantic versioning. While the major version is 0 the project is beta, and
settings, the state file format and behaviour may change between releases.

## 0.1.0, 2026-09-10

First numbered release.

Features:

- A floating see-through window that applies DLSS Neural Rendering to whatever is behind it.
  The viewport is click-through, so the mouse reaches the application underneath.
- One to four neural passes, changeable while running from the title bar.
- Resize from the menu, applied by relaunching at the new size and position.
- Before and after screenshots, saved as three PNGs: the captured source, the neural rendered
  result, and the two joined side by side. Both halves come from the same frame.
- A settings dialog with every setting the lens has: the screenshot folder, fullscreen, the
  automatic frame rate switch, sliders for the lowest rate, the ceiling, the capture refresh
  and the most passes allowed, and the mpv and data folders, each with an explanation. It
  writes `neural-lens.ini`; nothing needs editing by hand.
- Per session log archiving into `%LOCALAPPDATA%\NeuralLens\logs`, so evidence from a failed
  run survives the next launch.
- A live A/B split from the menu: a draggable divider with Neural Rendering on its left and the
  raw source on its right. Every stage window is clipped to the left of the divider, so the
  right side is the screen itself.
- Fullscreen, as a checkbox in Settings. The lens covers the whole monitor it is on, with the
  title bar over the top edge of the picture. It restarts to change, like a resize, and keeps
  the windowed position and size for the way back. `fullscreen = 1` in the ini does the same.
- An adaptive frame rate. Every stage is declared at the display rate and presents at a
  playback speed the lens changes live over mpv's IPC pipe, from what the visible stage
  actually presents, the brightness of the output against the input, and the frame to frame
  change of the output while the content is still. The settled rate is saved as a sixth field
  in the state file. `adaptive = 0` in the ini keeps the fixed rule; `min_fps` sets the floor.

Known limits:

- Requires an existing mpv install with a working DLSS Neural Rendering stack. None of that
  stack is included or redistributed here.
- Exclusive fullscreen applications are invisible to the Magnification API. Borderless
  windowed works.
- Resizing relaunches the lens, and changing the pass count respawns every stage.
- The visible stage starts at five sixths of the display's refresh rate, divided by the number
  of passes, and is adjusted from there. A slower GPU, a larger
  lens or a busy GPU lands well below those numbers: a 1400x1000 lens at two passes settled at
  34 on an RTX 4070 SUPER, and a 2000x1400 lens at one pass at 41. The rate only probes upward
  while the content under the lens is still, so on moving content it stays where it last
  settled. See `docs/NOTES.md`.
