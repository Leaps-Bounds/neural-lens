# Contributing

## Reporting a bug

Open an issue. The bug report form asks for the things that actually make a report
diagnosable, so please fill it in rather than opening a blank issue.

The single most useful attachment is the archived `ReShade.log`. Every launch copies the
previous session's logs into `data\logs` in the lens folder, so if something goes wrong,
launch the lens once more and attach the newest archived log.

If the lens never opened at all, there may be no `ReShade.log` to send, because ReShade
never loaded. Attach `presenter-stderr.log` from the same folder instead. It holds whatever the
presenter itself printed, and it is the only place the reason survives. `lens.log` beside it is
the lens's own output, and the previous session's copy is stamped next to it.

**A word on screenshots.** A screenshot of the lens contains whatever was behind it, meaning
your desktop. Window titles, notifications, file paths and account names all leak that way.
Crop tightly, or skip the screenshot and send the log instead.

## Building the installer

Two tools, both free: PyInstaller (`pip install pyinstaller`) and Inno Setup 6
(`winget install --id JRSoftware.InnoSetup --scope user`), plus the lens's own requirements
installed where PyInstaller can import them: `pip install numpy windows-capture glfw vulkan`.
`windows-capture` brings in `opencv-python`. From the repository root:

```
python -m PyInstaller --noconfirm --clean --distpath build\dist --workpath build\work installer\NeuralLens.spec
"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" installer\NeuralLens.iss
```

The spec builds two programs into one folder, `NeuralLens.exe` and `lens-presenter.exe`, sharing
their libraries. The result is `build\installer\NeuralLens-Setup-<version>.exe`. It contains the
lens and nothing of the neural stack; setup fetches that during installation, and
`neural_stack.py` runs the same fetch later from the Start Menu entry or the command line. The
icon and its PNG are committed; `assets\make_icon.py` draws both from scratch with Pillow and is
only needed to change them. Bump the version in `neural_lens.py`, `neural_stack.py`,
`README.md`, `CHANGELOG.md` and `installer\NeuralLens.iss` together.

## Before proposing a change to the capture path

Read [docs/NOTES.md](docs/NOTES.md) first. It records the approaches that were already tried
and rejected, each with the measurement that ruled it out. Desktop Duplication, gdigrab on a
magnifier window, the deprecated scaling callback, mpv as the host and a UDP transport have all
been ruled out with numbers, and the reasons are not obvious from reading the code.

## Measuring changes

Several wrong conclusions during development came from bad measurement rather than bad code,
so if a change claims to improve the image, measure it:

- Use a **static** source. An animated one contaminates any before and after comparison.
- Establish a **noise floor** by capturing the same state twice before trusting a difference.
- Compare the add-on's `active settings` line in `ReShade.log` between runs before comparing
  their pictures. A setting changed in the ReShade overlay between two runs moves the result
  more than most code changes do.
- Do not infer Neural Rendering's on or off state from the lens's own toggle log. F6 is a real
  keystroke that the add-on reads from the keyboard, so the state can change without the lens
  having sent anything. Measure absolutely: capture the region with the lens absent, then with
  the lens over it.
- Keep the GPU to the lens. A game or a video running at the same time lowers the frame rate
  and changes the delay, and it does so unevenly.
- Remember that Neural Rendering's strength scales with local detail, roughly 4.5x stronger on
  the most detailed tenth of an image than on the flattest half. Flat content barely changing
  is expected.

## What is not in this repository

None of the neural stack is included or redistributed here: ReShade, the DLSS 5 add-ons, the
Cost Scaler and NVIDIA's `nvngx_dlssnr.dll` all come from their own sources. `.gitignore` blocks
`*.dll` and `*.addon64` so they cannot be committed by accident. Please keep it that way.
