# Contributing

## Reporting a bug

Open an issue. The bug report form asks for the things that actually make a report
diagnosable, so please fill it in rather than opening a blank issue.

The single most useful attachment is the archived `ReShade.log`. Every launch copies the
previous session's logs into `%LOCALAPPDATA%\NeuralLens\logs`, so if something goes wrong,
launch the lens once more and attach the newest archived log.

If the lens never opened at all, there will be no `ReShade.log` to send, because ReShade
never loaded. Attach `mpv-stderr.log` from the same folder instead. It holds whatever mpv
itself printed, and it is the only place the reason survives. `lens.log` beside it is the lens's
own output, with every frame rate decision, and the previous session's copy is stamped next to it.

**A word on screenshots.** A screenshot of the lens contains whatever was behind it, meaning
your desktop. Window titles, notifications, file paths and account names all leak that way.
Crop tightly, or skip the screenshot and send the log instead.

## Building the installer

Two tools, both free: PyInstaller (`pip install pyinstaller`) and Inno Setup 6
(`winget install --id JRSoftware.InnoSetup --scope user`). From the repository root:

```
python assets\make_icon.py
python -m PyInstaller --noconfirm --clean --noconsole --onedir --name NeuralLens ^
    --icon ..\assets\neural-lens.ico --add-data "..\assets\neural-lens.ico;assets" ^
    --collect-all windows_capture --hidden-import neural_stack ^
    --distpath build\dist --workpath build\work --specpath build neural_lens.py
"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" installer\NeuralLens.iss
```

The result is `build\installer\NeuralLens-Setup-<version>.exe`. It contains the lens and
nothing of the neural stack; `neural_stack.py` fetches that at first run. Bump the version in
`neural_lens.py`, `CHANGELOG.md` and `installer\NeuralLens.iss` together.

## Before proposing a change to the capture path

Read [docs/NOTES.md](docs/NOTES.md) first. It records the approaches that were already tried
and rejected, each with the measurement that killed it. Desktop Duplication, gdigrab on the
magnifier window, the deprecated scaling callback and a UDP transport have all been ruled out
with numbers, and the reasons are not obvious from reading the code.

## Measuring changes

Several wrong conclusions during development came from bad measurement rather than bad code,
so if a change claims to improve the image, measure it:

- Use a **static** source. An animated one contaminates any before and after comparison.
- Establish a **noise floor** by capturing the same state twice before trusting a difference.
- Do not infer Neural Rendering's on or off state from the F6 toggle log, because the focus
  step sometimes drops a keypress and inverts the reading. Measure absolutely: capture the
  region with the lens absent, then with the lens over it.
- Remember that Neural Rendering's strength scales with local detail, roughly 4.5x stronger on
  the most detailed tenth of an image than on the flattest half. Flat content barely changing
  is expected.

## What is not in this repository

None of the neural stack is included or redistributed here: ReShade, the DLSS 5 add-ons and
NVIDIA's `nvngx_dlssnr.dll` all come from their own sources. `.gitignore` blocks `*.dll` and
`*.addon64` so they cannot be committed by accident. Please keep it that way.
