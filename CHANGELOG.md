# Changelog

Versions follow semantic versioning. While the major version is 0 the project is beta, and
settings, the state file format and behaviour may change between releases.

## 0.1.0, 2026-09-12

First numbered release. Licensed under the GNU General Public License, version 3 or later.

Features:

- A floating see-through window that applies DLSS Neural Rendering to whatever is behind it.
  The viewport is click-through, so the mouse reaches the application underneath.
- The lens starts at one neural pass. Plus and minus on the title bar change the count while it
  runs, up to three; the Settings dialog sets that ceiling and will allow four.
- Resize from the menu, applied by relaunching at the new size and position.
- Before and after screenshots, saved as three PNGs: the captured source, the neural rendered
  result, and the two joined side by side. Both halves come from the same frame.
- A settings dialog with every setting the lens has: the screenshot folder, fullscreen, the
  automatic frame rate switch, sliders for the lowest rate, the ceiling, the capture refresh
  and the most passes allowed, and the mpv and data folders, each with an explanation. It
  writes `neural-lens.ini`; nothing needs editing by hand.
- Per session log archiving into `data\logs` beside the program, so evidence from a failed
  run survives the next launch.
- A Windows installer, and a stack setup inside the lens. The installer is per user with no
  administrator prompt, installs to a folder you choose, and contains only the lens. Setup
  fetches the neural stack during the installation itself, offered as a checkbox that is already
  ticked, from the projects that publish each part, about 230 MB to download and about 540 MB on
  disk when it is done, into that same folder: mpv, ReShade taken out of its setup without running it, NVIDIA's two
  runtimes with the Neural Rendering model, checked against
  known hashes, the DLSS 5 Feeder, the RenoDX add-on, and motion vectors from
  ReshadeMotionEstimation, chosen by measurement over every estimator that may be fetched, with
  VORT as the alternative from the command line. ReShade is
  registered as a Vulkan layer for the user only, under its own name with its own allow list,
  so an existing ReShade on the machine is neither touched nor doubled. It ends with a self
  test, which opens an mpv window for about nine seconds, and says whether Neural Rendering ran.
  If the box is unticked, or the stack step fails, the install still completes and a Start Menu
  entry runs it later. Everything the lens has is in its one folder,
  the program, the stack, the layer and its data, and the uninstaller removes that folder and
  the layer registration and nothing else; a DLL you pointed the setup at was copied in, so
  the original is not touched. The layer registration is removed even when the install record
  is missing, as after a setup that was interrupted.
  The setup window opens laid out, its folder field is filled in and editable at every
  entry point, and the lens relaunched after a setup points at the new stack ahead of any
  `--mpv-dir` or ini `mpv_dir` that led to the offer.
- The lens is per monitor DPI aware, so a lens on a monitor whose scaling differs from the one
  the session logged on with is the size it says it is. Before, a 1400x760 lens on such a
  monitor ran a 1680x912 chain, rescaled by Windows on the way, and the lens could not tell.
- One Neural Rendering model for every RTX card. The setup used to pick a model by card
  generation and refuse to continue when it could not identify one. The SF-v2 model covers
  RTX 20 through 50, so there is nothing to choose: the installer no longer asks which card
  you have, and the only question left is whether an NVIDIA RTX card is present at all, which
  it answers itself and says plainly when the answer is no.
- The most passes the title bar will go to now defaults to three, and the Settings dialog says
  that going above three is experimental. The lens itself still starts at one pass. Four
  remains available, but how it behaves depends on the card. Measured at four passes over a
  detailed still, over 90 seconds: on an RTX 4070 the rate settled within a spread of 4 fps,
  from 35 to 39, while on an RTX 5090 the rate search hunted across a spread of 40 fps, so the
  frame rate can swing and the picture can wander. Three is the ceiling because it is the
  highest count that behaved consistently on both.
- The window the governor waits after a rate change grows with the pass count. The brightness
  ripple of a change through four stages outlasted the fixed wait and read as a collapse, and a
  retake of a remembered level never steps past that level, which had two rates alternating
  every ten seconds.
- Startup checks for a misconfigured install. A folder without `mpv.exe` is named, with the
  four ways to point the lens elsewhere. An mpv that lacks the Neural Rendering stack warns
  which files are missing, since it would otherwise start and quietly show the screen back
  unchanged. A `data_dir` that cannot be created says so rather than raising. mpv's own stderr
  is kept in `mpv-stderr.log` beside the archived logs, so a stage that never opens a window
  reports the cause instead of only the symptom.
- Half the delay. mpv's readahead is two frames instead of eight, with its latency mode on.
  Measured at one pass and 99 fps, from a change under the lens to the change in its output:
  136 ms before, 68 ms after, with the presented rate and the output floor unchanged.
- A taskbar button. A fullscreen application, or another window that insists on being on top,
  could leave the lens buried with no way back. Clicking the lens on the taskbar brings every
  stage and the title bar back to the top, and the button's Close window closes the lens.
- No console. The launcher starts the lens under pythonw. Everything it prints goes to
  `lens.log` in the log folder, rotated with the archived logs, and anything that stops it
  from starting is shown as a dialog. `python neural_lens.py` still runs it with a console.
- The title bar shows the frame rate the lens is actually presenting, averaged over the last
  few seconds, rather than the capture rate in and the rate asked out, which meant little to
  most people. Settings offers those, or the size alone, as `readout` in the ini.
- The pass controls wait while Neural Rendering is off, since each pass is then only a copy
  of the last: the bar says `NR off`, plus, minus and Set do nothing, and the menu's add and
  remove are greyed. The state is seeded from `NeuralUplift` in `ReShade.ini` and tracked from
  the key itself, because the add-on reads F6 from the physical keyboard, so F6 pressed
  anywhere toggles it. The menu's own toggle, which posted a message the add-on never read,
  now presses the key with the stage briefly focused.
- Over a video, the frame rate no longer collapses. The brightness runaway test compared the
  output against the input's latest brightness, but the output lags the input, so a scene
  change or a bright-dark swing made the two disagree while nothing was wrong, and a one pass
  chain able to hold 100 fps went to 12 in under half a minute and stayed there. The output is
  now judged against the range the input has occupied over the last second and a half. The
  same source that cascaded holds 100 fps; a still pushed past capacity is still caught.
- Plus and minus on the title bar choose a pass count and Set applies it, one rebuild for any
  jump. The menu's add and remove entries still apply at once.
- Keys for ReShade (Home, F6, F5) are posted straight to each stage's message queue instead
  of focusing the stage and synthesising a global key press, which dropped presses and left
  the overlay out of step with the Tweak entry.
- A live A/B split from the menu: a draggable divider with Neural Rendering on its left and the
  raw source on its right. Every stage window is clipped to the left of the divider, so the
  right side is the screen itself.
- Fullscreen, as a checkbox in Settings, and **experimental**: it is the least tested part of
  the lens, included to be tried and reported on rather than relied on. The lens covers the
  whole monitor it is on, with the title bar over the top edge of the picture. It restarts to
  change, like a resize, and keeps the windowed position and size for the way back.
  `fullscreen = 1` in the ini does the same.
- An adaptive frame rate. Every stage is declared at the display rate and presents at a
  playback speed the lens changes live over mpv's IPC pipe, from what the visible stage
  actually presents, the brightness of the output against the input, and the frame to frame
  change of the output while the content is still. A rate that failed is tried again once the
  picture has been clean for a while, on a wait that doubles each time it fails again, so
  something else using the GPU for a while does not cap the lens for the rest of the session.
  A rate the chain has already held is retaken in a few steps a few seconds apart, over moving
  content too, and a limit recorded during a knock down neither gates that return nor survives
  the chain running above it: back at its level 16 seconds after a knock down, where it took
  64 to 94 seconds before. Presenting 87 of 90 is not a shortfall, a mild shortfall backs off
  only a little, and the shimmer test scales with the frame rate rather than reading a slow
  chain as a broken one. The highest rate the chain actually held is saved as a sixth field
  in the state file.
  `adaptive = 0` in the ini keeps the fixed rule; `min_fps` sets the floor.

Known limits:

- Requires an existing mpv install with a working DLSS Neural Rendering stack. None of that
  stack is included or redistributed here.
- Exclusive fullscreen applications are invisible to the Magnification API. Borderless
  windowed works.
- Resizing relaunches the lens, and changing the pass count respawns every stage.
- The visible stage starts at five sixths of the display's refresh rate, divided by the number
  of passes, and is adjusted from there. A slower GPU, a larger
  lens or a busy GPU lands well below those numbers: a 1400x1000 lens at two passes settled at
  34 on an RTX 4070 SUPER, and a 2000x1400 lens at one pass at 41. On an RTX 5090 the same
  1400x1000 lens at one pass held 100, the ceiling for that display, and 62 while the GPU was
  busy with something else. The rate only probes upward
  while the content under the lens is still, so on moving content it stays where it last
  settled. See `docs/NOTES.md`.
