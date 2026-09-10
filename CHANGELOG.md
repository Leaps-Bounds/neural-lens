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
- A settings dialog for the screenshot folder.
- Per session log archiving into `%LOCALAPPDATA%\NeuralLens\logs`, so evidence from a failed
  run survives the next launch.

Known limits:

- Requires an existing mpv install with a working DLSS Neural Rendering stack. None of that
  stack is included or redistributed here.
- Exclusive fullscreen applications are invisible to the Magnification API. Borderless
  windowed works.
- Resizing relaunches the lens, and changing the pass count respawns every stage.
- The frame rate declared to mpv is the display rate divided by the number of passes, so more
  passes means a lower presented rate. See `docs/NOTES.md` for the measurements behind this.
