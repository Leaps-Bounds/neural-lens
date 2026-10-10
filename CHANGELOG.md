# Changelog

Versions follow semantic versioning. While the major version is 0 the project is beta, and
settings, the state file format and behaviour may change between releases.

## 0.8.0, 2026-10-10

Four themes that each give every window of the lens a look of its own, Settings that you walk
with the keys and that shows what a setting does beside it, Free the mouse, a line on the NR
settings panel that names the arrow keys, a pointer that keeps out of the arrow keys' way while a
game holds the mouse, and shorter explanations on the panel and in Settings.

- **Four themes, each a look of its own.** Slate, the default, Graphite, Paper and Industrial, on
  the Look page of Settings, now change the layout as well as the colours, each as a design draws
  it, Graphite in Slate's layout. Every window of the lens follows the theme, Settings, the NR
  settings panel, the lens menu and its lists, the title bar and the frame, the note on going
  fullscreen, the notices, the on-screen readout, the window that explains a setting, the tab of a
  hidden title bar, the A/B divider, the hint of an attach pick, the sheet of a region pick, the
  lens's dialogs and the stack setup's window. Every setting keeps its words, its key in the ini
  and its keys. Choosing a theme restarts the lens, as before.
- **Settings shows what a setting does beside it.** Its pages are listed down its left side, or as
  tabs along its top in Industrial, and what the setting the pointer is on or the keys have picked
  does shows beside the settings, or under them in Industrial, in place of the window that came up
  after a second and a half. Up and Down pick a setting, Left and Right change it, Enter switches a
  switch or presses a button, Ctrl+Tab, Page Down and Page Up turn the page, and Escape cancels, as
  the dialog's foot shows. Where the screen has no room for the explanation beside the settings, it
  comes up by the pointer as before.
- **The NR settings panel in each theme** has its settings in the order of the theme's design,
  Slate's, Graphite's and Paper's with the passes and the quality step above the pass tabs, shows
  what the setting picked does in a part under its settings, and shows the keys that work it as
  key caps along its foot.
- **The lens's messages are dialogs of its own**, in the theme's colours, where they were Windows'
  own boxes, with the same words, buttons and keys, Windows' sound for each kind of message, and
  Ctrl+C to copy the words. A dialog takes the keyboard only where the lens has it already, so it
  never takes the front from another program, and like the lens's other windows it stays out of
  screenshots. On Windows 11 the frame of each dialog and of the stack setup's window takes the
  theme's colours, and on Windows 10 its dark mode in a dark theme.
- **The fonts of the designs come with the lens.** Paper draws in Source Serif 4 and Source Sans 3,
  Industrial in Barlow, Barlow Semi Condensed and IBM Plex Mono, and Slate and Graphite in a font
  of Windows' own. The fonts are under the SIL Open Font License 1.1, with their licence texts in
  `licenses`, and the lens adds them for itself alone while it runs, so nothing is installed.
- **Paper is warm, and secondary words are easier to read.** Paper takes its design's warm sheet
  and ink where it was grey. The secondary words of Slate, Industrial and Graphite are lighter, and
  Graphite, which has no design of its own, has Slate's layout in its own colours.
- **themes.json.** A theme of your own can name the theme it starts from with `look`, Slate,
  Graphite, Paper or Industrial, and takes that theme's layout and the colours it leaves out. An
  entry that changes some colours of a theme that comes with the lens keeps that theme's other
  colours, where it took Slate's. An entry can also give the colours of the parts a look draws,
  see `docs/NOTES.md`, and `lens.log` says where its colours make some text hard to read.
- **A lens in a window is wider at its narrowest**, since the title bar's drawn controls are
  wider. On a test computer that is 390, 488 and 576 pixels at 100, 125 and 150 percent display
  scaling in Slate and Graphite, 380, 484 and 572 in Paper and 400, 502 and 596 in Industrial,
  where it was 322, 366 and 414. A size saved narrower is widened to it.
- **Free the mouse.** A switch on the NR settings panel, under the switch that loads a profile
  for the program in front, and on the Fullscreen page of Settings, one setting in both places,
  off to begin with. On, the lens brings the panel to the front while it is open, as Alt+Tab
  does, so a game that holds the mouse lets go of it and you can point and click on the panel,
  and closing the panel gives the front back to the game. A window you went to meanwhile keeps
  the front. While the panel is in front, a game may pause, mute its sound or slow down, as it
  does on Alt+Tab, so the switch stays off until you switch it on. Switched in Settings while the
  panel is open, the panel takes the front or gives it back at once. `free_mouse = 1` in the ini
  keeps it on, and `lens.log` says each time whether the front was taken and whether it was given
  back. The lens never moves the pointer, keeps it to a part of the screen, or shows or hides it.
- **A line on the NR settings panel names the arrow keys.** It says how to pick a setting with the
  arrow keys. While the program in front holds the mouse, hiding the pointer, keeping it to a part
  of the screen or putting it back to the middle of its window, and Free the mouse is off, the line
  adds that Free the mouse lets you use the mouse on the panel. The lens tells that the mouse is
  held by whether the pointer is showing, the part of the screen it is kept to and whether it
  stays at the middle of the window in front, which it reads four times a second while the panel
  is open.
- **A held mouse keeps out of the arrow keys' way.** While the program in front holds the mouse,
  the pointer brings up no explanation on the panel, lights nothing on it and lights no entry of
  the lens menu, so a game that keeps putting the pointer back under the panel does not get in the
  way of the arrow keys. Where the panel lights the setting under the pointer, the pointer lights
  one again after an arrow key only once it has moved a little.
- **Shorter explanations, shown whole.** Every explanation on the NR settings panel and in
  Settings fits the part it shows in, in each theme at 100, 125 and 150 percent display scaling,
  so none is cut off or ends in three dots. The quality step's explanation, on the panel and on
  the Power page of Settings, says what the steps do in two short sentences, and the explanations
  of Free the mouse, of profiles, of the global hotkeys, of the Windows HDR warning, of the note
  on going fullscreen and of the two fullscreen engines are as short. The explanation of the
  on-screen readout in Settings is four short sentences, and the explanation of the fullscreen
  keys there lists the keys alone. On a monitor too short for the whole panel, its explanation
  keeps its full height, where it showed two lines. On a screen too short for all of them, Slate's
  list of a page's explanations before a setting is picked shows those that fit whole.
- **The four lines at the NR settings panel's foot are gone**, the foot showing the panel's keys.
  What the ReShade engine makes of the passes and the switches, and how a held key speeds a slider
  up, are in the README and `docs/NOTES.md`. The button beside a slider's number says what it does
  in its own explanation.
- **No profile tied yet.** With the switch Load the profile tied to the program in front on and no
  profile tied to a program, Settings says so beside the switch, and the panel's profile list says
  so above the entry that ties one.

## 0.7.0, 2026-10-09

A switch that scales the network's change, with a strength of its own, a switch that runs the
passes after the first through the first pass's network, an explanation for every setting on the
NR settings panel, and a Full quality step that has the network work on the picture at its own
size.

- **A switch that scales the change, with a strength of its own.** The network itself does no
  more above an intensity of 1, so the NR settings panel's intensity slider above 1, which has run
  to 2.00 since 0.6.0 as the add-on's Home menu does, draws the picture of 1 on either engine, as
  it did, and the intensity's explanation now says so. A stronger picture is the new switch Scale
  the change, under the pass count on the panel, and while it is on, a slider of its own below it,
  Strength, from 1.00 to 2.00. On, the fast engine multiplies the change the passes made together,
  the last pass's output against the first pass's input, by the strength, so the picture is the
  picture at 1 with its change that many times larger. The lens keeps it as `ScaleChange=1` and
  `Strength` in its own section of `ReShade.ini`, which the add-on never reads. The switch is off
  to begin with, an ini or a profile from before 0.7.0 has neither key, and so nothing changes
  until the switch is switched on. The strength stays in the file while the switch is off, so
  switching it on again brings it back. A profile carries both, the star shows once the lens
  differs from its profile in them, the Profiles page of Settings lists them, and the panel's foot
  says that the switch does nothing on the ReShade engine. Measured on a test computer with an RTX
  5090 over the Blender picture at 2560x1053, the change from the picture at a strength of 1.5 and
  of 2 was 1.57 and 2.00 times the change at 1 with one pass, and 1.52 and 1.99 times with two
  passes through one network, the network's output at each being the output at 1 scaled on the
  CPU byte for byte, and at 1 again the picture was the first byte for byte.
- **Runs through pass 1's network, a switch on the tab of pass 2.** On the NR settings panel it
  sits on the tab of pass 2, under the values and their Same as pass 1 ticks. On, the second pass
  runs through the first pass's network, with that network's history, instead of a network of its
  own, still at its own values, and the change comes out stronger. Passes 3 and 4 follow pass 2,
  and their tabs show the switch greyed with a note that they follow pass 2. The tab of pass 1
  has no such switch, so a lens at one pass shows none. It is off to begin with. The lens keeps it
  in its own section of `ReShade.ini` as `SharedNetwork=1`, which stays in the file at one pass,
  where the engine does not read it. A profile carries it, one saved before 0.7.0 loads with it
  off, the star shows once the lens differs from its profile in it, and the Profiles page of
  Settings lists it for a profile of two passes or more. The on-screen readout's passes item says
  shared once the engine runs the passes that way. Where the engine could not make its network
  again for the switch, the notice says so for 8 s and the switch's row says that it is not in
  effect, and where it could not for other new settings, such as a profile's preset, the notice
  says that instead. The switch is the fast engine's alone. The ReShade engine never reads the
  key, and the panel's foot says that the switch does nothing there.
- **The windowed look the switch gives fullscreen.** On the ReShade engine, which draws every
  windowed lens, the add-on's Denoise before upscaling, `NRPreUpscale=1`, runs the network twice
  for each picture through one network, the second time on the first run's output. Measured on a
  test computer with an RTX 5090 over a character still at 1400x1000, with two passes and the
  second at the first pass's values, the fast engine's picture with the switch on was 0.91 of 255
  from the ReShade engine's with Denoise before upscaling on at one set of values, and 0.72 of 255
  at another, where one pass was 13.2 and 6.2 of 255 from it, see Each pass's values in
  `docs/NOTES.md`. The windowed picture is the softer one, keeping 0.35 of the still's fine detail
  at the second set of values where the fast engine kept 0.74. Over text scrolling 3 and 8 pixels
  a frame the switch left no trail and no double, the same as one pass. With the engine by itself
  fullscreen at 6144x2526 at Balanced, over a picture that changed at every refresh, two passes
  with the switch on showed 75 new pictures a second on 261 W with a median delay of 15 ms, the
  same as two passes without it, where one pass showed 120 a second on 226 W with 10.6 ms.
- **Every setting on the NR settings panel is explained.** Rest the pointer on a setting for a
  second and a half and a small window beside the pointer says what the setting does, as Settings
  does. F1 says the same for the setting the arrow keys are on, below it, so the panel can be read
  from the keyboard while a game keeps the foreground, and a new line at the panel's foot says how.
  The lens holds F1 only while the panel is open, and not where a hotkey of Settings has F1 on its
  own, where the foot line names the pointer alone. Any key on the panel takes the explanation
  away, and like the panel it never takes the foreground from the program in front.
- **A Full quality step.** Full is the step above Quality. At Full the network works on the
  picture at its own size, however large the screen, where every other step has it work on a
  smaller copy of a picture larger than 2560x1440. For a picture within 2560x1440, Quality works at
  the picture's own size already, so there the two are the same. Full is on the NR settings panel
  and the Power page of Settings, the hotkey that raises the step reaches it, a profile carries it,
  `fast_quality = 5` in the ini keeps it, and the readout says step Full. The default is
  unchanged, Balanced for a picture larger than 2560x1440 and Quality for a smaller one. A lens
  before 0.7.0 takes such an ini or profile as Quality. Measured on a test computer with an RTX
  5090 without a window, the network took 14.3 ms a pass at 6144x2560 and 27.9 to 28.7 ms for two
  passes, against 3.0 ms a pass at Balanced, and 7.3 ms a pass at 3840x2160, and the engine held
  2192 MiB of video memory at one pass and 3877 MiB at two at 6144x2560. With the engine by itself
  fullscreen at 6144x2526, over the picture that changed at every refresh, Full showed 40 new
  pictures a second on 408 W with a median delay of 29 ms at one pass, and 24 a second on 472 W
  with 42 ms at two, where Balanced in the same series showed 120 a second on 234 W with 10.5 ms
  at one pass and 75 a second on 257 W with 15 ms at two. Over a still picture the engine at Full
  comes to rest as at every step, and with two passes the card drew 52 W, 1 W more than with the
  desktop and the picture alone.
- **On a large screen Balanced gives another picture than Full.** On three 6144x2560 frames of a
  game with two passes, measured without a window, the picture at Balanced was 8.8 to 9.5 of 255
  from the picture at Full, where the frame with no network at all was 10.0 to 12.0 of 255 from
  it. The change at Balanced was as large overall but fell in other places, a correlation of 0.61
  to 0.69 with the change at Full, and in two of the frames a face darkened by 19.6 and 19.8 of 255
  in luma at Balanced against 35.5 and 36.4 at Full. Balanced showed no loss against the picture
  fitted into 2560x1440, which is what the steps were measured against before, see The quality
  steps in `docs/NOTES.md`.
- **A step the fast engine cannot take.** A quality step is made beside the network in use, so the
  switch to Full at 6144x2560 with two passes took 0.30 to 0.32 s while the pictures went on, and
  held 5763 MiB of video memory with both networks for that moment, and the switch back to
  Balanced took 0.46 s. Where the engine cannot make the network for a step, as with too little
  video memory for Full on a large screen, it runs on at the step it had, and the lens now goes
  by that step, keeps it in the ini and says on the notice which step runs.
  Where the engine cannot make it at a start at Full on a picture larger than 2560x1440, the lens
  goes by the default step, says so the same way and starts the engine once more, where before a
  failed start ruled the fast engine out for the run. The runtime makes no network for a picture
  above about 47 megapixels, so Full runs such a picture at Quality, where 8K is 33 megapixels.
  The warning that the lens falls behind goes by the network's own time a picture, which the fast
  engine's stats line now carries. The delay stays close to that time and one refresh, so at
  Full, where the two reach the three refreshes the warning counts from, the lens would be behind
  with no program in front, and the warning says that the network's own work on this screen holds
  the lens back by itself and that a lower step lets it keep up, since no frame rate limit in the
  program in front could help then. With the engine by itself at 6144x2526 and 120 Hz the network
  took 18.6 ms a picture at one pass and 38.1 ms at two, so both get those words there. Where the
  network takes less, the warning puts the delay down to the program in front as at any step.
- **Global tone is gone from the Profiles page.** The add-on's `NRGlobalTone` does nothing on the
  model the stack installs, which has no such setting, and a measurement at 2 against 0.99 moved
  the picture by no more than noise, so the page no longer lists it. A profile still carries it
  with the rest of the add-on's section.
- **The fast engine reads the add-on's UI correction and preset.** It reads `NRUICorrection` and
  `NRPreset` from the add-on's section, as it reads the other values, and hands them to the
  network, the preset as the network is made, so a new preset makes the network again. On the
  model the stack installs, over a character still and a page of text, UI correction on and off
  and every preset gave the same picture byte for byte, so the panel has no control for them.
- **From source, the fast engine's self test holds two references.**
  `fast_engine\tools\run_selftest.py` holds the reference run's composite, the network's input and
  output and the runtime's reads against a baseline, byte for byte, and `--shared` does the same
  for a run of two passes through one network. `--both` runs the two, and `--against` and
  `--against-shared` name other baselines. The baselines are kept beside the measuring tools,
  outside the repository, and where one is missing its comparison is skipped and said. Each self
  test now also checks that the strength scales the change, the network's output at 1.5 and at 2
  against the CPU's scaling of the output at 1 byte for byte at any pass count, and that at 1 the
  picture comes back byte for byte, and at two passes or more that switching the passes to one
  network and back takes effect once the network is made again.
- **Smaller changes.** The fast engine's ready line says `shared on` or `shared off` before the
  HDR state, its stats line carries `shared=on` or `shared=off` and ends with `network=MS`, the
  network's GPU time a picture over the second, it prints `engine remake failed` with the state it
  runs in where it could not make its network again for a new preset or for the switch, and
  `--steps` lists six steps. The lens's summary line in its log, every ten seconds fullscreen on
  the fast engine, ends with the network's median time a picture. In Settings, the Passes item of
  the on-screen readout says what shared means, the Profiles page's explanation names the two
  switches among what a profile holds, and on the Hotkeys page the action that raises the quality
  step goes toward Full.

## 0.6.1, 2026-10-05

HDR for a fullscreen lens on the fast engine and a warning on the ReShade engine, each pass with
values of its own, profiles on the NR settings panel that can load by themselves for the program
in front, finer steps for its sliders, and a fast engine that takes the newest frame.

- **At two passes or more the fast engine's picture can differ from 0.6.0.** Passes 2 to 4 now run
  at the intensities the add-on keeps for them, `NRPass2Intensity`, `NRPass3Intensity` and
  `NRPass4Intensity` in its section of `ReShade.ini`, wherever the file holds them. The fast
  engine of 0.6.0 ran every pass at the first pass's intensity, so its picture at two passes or
  more changes wherever those keys hold another intensity than the first pass's. On the test
  computer they held 0.94, 0.6 and 0.36. A new install's section holds none of them, and there
  every pass still runs at the first pass's values, as in 0.6.0. The NR settings panel shows such
  an intensity as the pass's own, and ticking Same as pass 1 for it on that pass's tab, see below,
  runs the pass at the first pass's intensity again, as 0.6.0 did. The panel writes the intensity
  of passes 2 to 4 into those same keys, so the add-on of the ReShade engine gets them too.
- **A fullscreen lens on the fast engine shows an HDR monitor in HDR.** When Windows HDR is on for
  the lens's monitor, the fast engine captures the screen in 16-bit floating point, gives the
  network the picture scaled to the SDR white level set in Windows, as Windows shows standard
  range content, and draws its own picture in HDR. So the lens shows standard range content as
  Windows shows it on that monitor, where 0.6.0 showed it washed out, and brighter parts in HDR.
  The network sees nothing brighter than SDR white, so above it the network's change fades out and
  is gone at twice SDR white, and parts at twice SDR white or brighter are left as they are. There
  is nothing to set. The engine reads the monitor's HDR state once a second while it captures, and
  where Windows HDR went on or off it starts its capture again, since Windows went on sending
  8-bit frames when HDR was switched on while the engine captured. Screenshots of such a lens are
  standard range pictures at the SDR white level, so anything brighter is white in them. Measured
  on an RTX 5090 with the engine by itself fullscreen on a monitor at 3840x1200 and 144 Hz,
  Windows HDR on and SDR white at 240 nits, with Neural Rendering off the picture on screen
  equalled the captured one texel for texel, up to the 1000 nits of a test pattern. A test switch
  in `docs/NOTES.md` picks one of two other ways above SDR white, for measurements.
- **A warning when Windows HDR is on while the ReShade engine draws the picture.** That engine
  still captures 8-bit frames, which Windows clips at 80 nits while HDR is on, so its picture
  comes out washed out. A fullscreen lens on the ReShade engine, a lens attached to a window and
  one with its title bar hidden say at the top of the screen that the picture comes out washed
  out, and to switch HDR off for the monitor, or to use fullscreen on the fast engine where the
  lens can offer it. A windowed lens says on its title bar that HDR is on and points to the
  Picture page of Settings, in the longest of three short sentences that fits there, and the bar's
  title gives way while none of them fits beside it. A narrower lens cuts the shortest one short,
  down to none of it at the narrowest a windowed lens can be. The warning shows for about 12 s
  once it applies, and again when the lens goes fullscreen or back to a window, and it goes when
  HDR is switched off. It does not come while the ReShade engine only stands in for the fast
  engine, which comes back once the screen gives pictures again, as after the screen was locked.
  The Picture page of Settings shows the warning when it applies as Settings opens. Its switch
  there, Warn when Windows HDR is on, starts ticked, and its explanation says where the warning
  shows. The ini keeps the switch unticked as `hdr_warn = 0`. `lens.log` has a line when the
  warning applies, also with the switch unticked. Auto Colour Management alone does not count as
  HDR.
- **Each pass can have values of its own on the fast engine.** The NR settings panel has a tab for
  each pass that runs. The first pass's tab holds the values every pass starts from. On the tab of
  a pass from the second on, each value has a tick, Same as pass 1. Ticked, the pass runs at the
  first pass's value, which its control shows greyed. Unticked, the value is the pass's own, and
  the control moves it alone. Every value starts ticked, apart from an intensity of passes 2 to 4
  that the add-on's section holds, see above. The values of the passes from the second on are kept
  in a section of the lens's own in `ReShade.ini`, `[NeuralLens.Passes]`, apart from those
  intensities. The add-on does not read that section, so on the ReShade engine every pass still
  runs at the first pass's values but for the intensity of passes 2 to 4. A pass taken away keeps
  its own values for when it comes back. The stack setup keeps that section as it was, so a repair
  from the Start Menu, and an update with the stack box ticked, keep the passes' own values and
  which of them are ticked Same as pass 1.
- **Profiles on the NR settings panel.** A Profile row at the top of the panel names the profile
  in use, amber with a star once the lens differs from it, as the title bar does. Its list loads a
  profile, saves the current settings as a new profile or into the one in use, ties the one in use
  to the program in front or unties it, see the next point, and opens Settings. On a fullscreen
  lens on the fast engine, a fullscreen profile at the same pass count now loads in place, with no
  restart of the picture, from the panel, the lens menu's Profiles, the Next profile hotkey or the
  program in front alike. Any other profile restarts the picture as before. A profile now also
  holds each pass's own values and the quality step. The star now also shows once a value on the
  panel, of any pass, or the quality step differs from the profile, and the Profiles page of
  Settings lists a profile's quality step, the passes' own values and the program it is tied to. A
  profile saved before 0.6.1 holds neither values per pass nor a quality step. Loaded, its passes
  from the second on run at its first pass's values, apart from the intensity of passes 2 to 4,
  which comes from the add-on's keys saved in it where it has them, and the quality step stays as
  it is. A profile goes into `ReShade.ini` in one write, and where the file cannot be written the
  profile is not loaded and the lens says so.
- **A profile can load by itself for the program in front.** A profile can be tied to a program,
  with Tie to the program in front in the panel's list, or with Tie to the program last in front
  on the Profiles page of Settings, which names that program under the button. Untie takes the tie
  off, and the panel names the program beside a profile tied to it, by its window's title, or by
  its class where the title is empty. The switch Load the profile tied to the program in front,
  on the panel and on the Profiles page, is off to begin with, and the ini
  keeps it on as `auto_profile = 1`. With it on, each time a program with a profile tied to it
  comes to the front from another program, the lens loads that profile, unless it is in use
  already, and says so. It does so too when the window in front takes a title a profile is tied
  to, as a game's window can a moment after it comes up. A window that shows one tied title after
  another, as an emulator or a launcher can for each game it starts, loads each one's profile as
  its title comes, and a title that goes back and forth with untied ones loads nothing again. A
  program is known by its window's title and class, which have to match exactly, so a program
  whose title changes with what it shows matches only while it shows the title it was tied with. A
  program has one profile, so tying another to it unties the first. A window whose class cannot be
  read counts as no program, and a tie without a class, which no window can match, is taken off as
  `profiles.json` loads, with a line in `lens.log`. Coming back to the same program from a window
  of the lens's own, the desktop, the taskbar or the task switcher loads nothing, so a profile
  chosen meanwhile stays. The lens reads the title and the class of the window in front five times
  a second while it is not minimised, also with the switch off, so that the tie entries can name
  the program, and the id of its process to tell the lens's own windows apart. It reads them with
  the plain window calls, which send that window nothing, and opens no handle to its process.
  `profiles.json` keeps the title and class of a tied program, and `lens.log` gives a title only
  in its lines about ties and the profiles loaded for them.
- **Finer steps on the panel's sliders, and a reset for each.** Left and Right move a slider by
  0.01 a press, where they moved it by 0.05, and presses in quick succession move it 0.01 each. A
  key held down moves it further the longer it is held, 0.01 a repeat for the first 0.6 s of the
  hold, 0.02 up to 1.5 s and 0.05 after that. At Windows' default repeat delay and rate, a slider
  held from 0 reached 2 about 2.9 s after the press. A button to the right of each slider's number
  puts the slider at 1.00. It is greyed while its slider is, on a value ticked Same as pass 1 and
  on skin structure left to the model. The panel's own text says that a held key moves a slider
  faster and what the button does. Up and Down now also reach the profile, the switch that loads a
  profile for the program in front, the tabs and each Same as pass 1. On the profile, Left and
  Right load the profile before or after by name, and Enter opens its list. On the tabs they show
  the pass before or after, and on a Same as pass 1 Enter ticks or unticks it.
- **The fast engine takes the newest frame.** The engine now waits until it has finished drawing
  its last picture before it takes a frame from the capture, so the frame it takes is the newest
  one. In 0.6.0 it could take a frame while a picture was still being drawn, and that frame then
  waited behind the drawing. There is no switch. Measured on an RTX 5090 with the engine by itself
  at 6144x2526 on a 6144x2560 display at 120 Hz, at Balanced with one pass, over a picture that
  scrolled 8 pixels a step at 120 steps a second with nothing else keeping the card busy, the
  median delay fell from 16.95 ms to 10.45 ms, at about 120 new pictures a second either way. A
  second monitor at 3840x1200 and 144 Hz was connected, and in these runs the compositor timed the
  120 Hz display by that monitor's 144 Hz refreshes, which adds to the delay, see Measurement
  pitfalls in `docs/NOTES.md`. A game that keeps the card fully busy showed no gain, since there
  the wait is for the game's own work on the card. On a test computer with an RTX 5090 and that
  display alone at 120 Hz, a demanding game in borderless fullscreen and in front kept the card
  fully busy at about 16 frames a second, under a fullscreen lens on the fast engine at the
  Quality step with one pass and Neural Rendering on. In five separate sessions of about three
  minutes, the median of the lens's 10 s summaries that had the game in front for all of their
  10 s read 38.0 ms and 38.8 ms in the two sessions with this change and neither test switch, and
  36.5 ms in the session without the change, where the four sessions with it read 36.5 to 38.8 ms.
  These sessions ran at another place in the game than the figures of 0.6.0, so the two do not
  compare.
- **Two switches for tests of the delay under a game**, off unless set, are described under
  Switches for tests in `docs/NOTES.md`. Over a demanding game that kept the card fully busy
  neither brought a gain beyond the spread between sessions, so both stay off.
- **A windowed lens is never narrower than the controls on its title bar**, which on a test
  computer with Windows 11 came to 322 px at 100 percent scaling, 366 px at 125 percent and 414 px
  at 150 percent, where a drag could make any lens 240 px wide. A drag on its frame stops at that
  width, and a narrower size from a profile, from the way back from fullscreen or from the last
  time the lens ran is widened to it. The title bar now gives its buttons their room first, so a
  narrow lens cuts its title, readout and profile selector short, and never a button.
- **Smaller changes.** On the ReShade engine, after a profile with Neural Rendering in the other
  state, the title bar and the menu now show the state the profile set, where they went on showing
  the one from before. `profiles.json` is now written in one step, so a write cut short leaves the
  old file whole, and one that cannot be read is kept as `profiles.json.bad`, where the next save
  wrote over it. The fast engine's notes in `presenter-stderr.log` give the video memory budget
  beside the memory in use, and whether Windows HDR is on for its monitor and at which SDR white
  level. From source, the fast engine's self test at two passes or more also checks that each pass
  runs at values of its own, and with an intensity of 0 in `ReShade.ini` it judges only what that
  intensity can show.

## 0.6.0, 2026-10-04

A fast engine for a fullscreen lens, fullscreen as the picture alone with keys that work over a
game, quality steps, a frame rate limit, Settings with short labels, logs with times, and a new
licence.

- **The licence is now the PolyForm Strict License 1.0.0.** Releases up to 0.5.1 remain under
  GPL-3.0-or-later.
- **A fast engine draws a fullscreen lens.** It is a program of the lens's own, `lens-fast.exe`,
  which the lens starts in place of the presenter when it goes fullscreen. It captures the
  monitor on the graphics card, runs the neural network on a copy of the picture by calling the
  stack's runtime directly, and shows the original plus what the network changed, so the
  original's own detail is kept. The copy is downscaled where the picture is larger than
  2560x1440, and at the lower quality steps. The presenter with ReShade and the two add-ons still
  draws every windowed lens, and the lens now calls it the ReShade engine. Measured on an RTX 5090
  with a 6144x2560 display at 120 Hz and a second monitor connected, fullscreen at 6144x2558 with
  one pass over a white square moving across noise, the fast engine at Balanced, the step it
  starts at for that size, showed 115 new pictures a second on 218 W, and 60 a second on 131 W
  with the frame rate limit at 60. The ReShade engine showed 62 a second on 330 W over the same
  picture. The fast engine has no ReShade in it, so with it there is no Home menu, no ReShade
  effect and no ReShade screenshot key, and F6, the add-on's key, does nothing. The lens's own
  screenshots, the A/B split, the passes, Ready mode and minimise work as before, and F9 turns
  Neural Rendering off and on, see below. The new Fullscreen page of Settings, or
  `fullscreen_engine = stack` in the ini, puts fullscreen back on the ReShade engine. Where the
  fast engine fails, the ReShade engine takes over until the lens is started again, and the lens
  says so on screen. Where it is not installed, fullscreen runs on the ReShade engine and the
  Fullscreen page says why. A fast engine that gets no picture from the screen is not counted as
  failed. The ReShade engine stands in for it until the screen gives pictures again.
- **Fullscreen is the picture alone.** A fullscreen lens covers its monitor from the top edge to
  two rows of pixels above the bottom edge, 6144x2558 on a 6144x2560 monitor, with no title bar,
  frame or tab, on either engine. The two rows keep Windows from treating the lens as a
  fullscreen program. Measured with a window that covered the monitor exactly, Windows set its
  notification state to busy and the taskbar lost its place on top of other windows. One row
  short neither happened, and the lens keeps its sizes even, so it stops two rows short. What
  the title bar would have said, such as a restart, a screenshot's result or a failure of the
  fast engine, shows for a few seconds on a notice at the top of the monitor, which takes no
  click and is out of the picture. Back in a window the title bar is as it was.
- **Four keys for a fullscreen lens**, which has no title bar to click. F7 opens and closes the
  lens menu, F8 the NR settings, F9 turns Neural Rendering off and on, and F10 shows or hides
  the on-screen readout. The lens holds them only while it is fullscreen and in view, so from a
  windowed or minimised lens they reach the program that has the keyboard. It also lets them go
  while Settings or another dialog of its own is in front, and while a program in exclusive
  fullscreen is in front on its monitor. They are single keys because Windows takes only the
  last key of a combination away from the program in front, so a game still gets the Ctrl of a
  combination such as Ctrl+Home, and many games use it. The Hotkeys page of Settings changes or
  clears them, and the ini keeps them as `hotkey_lens_menu`, `hotkey_nr_panel`,
  `hotkey_nr_toggle` and `hotkey_readout_toggle`. An action that already has one of these keys
  in the ini, as 0.5.1 allowed, keeps it, and the new action then starts without a key, which
  its row on the Hotkeys page says. Once Settings has given the other action another key, the
  new action gets its own. Whenever the lens does not hold the menu's key, such as when it has
  none, or another program or another of its actions has it, a click on the lens's taskbar
  button opens the menu.
- **A note as the lens goes fullscreen.** A small window over the middle of the screen says that
  the lens itself is now invisible while it goes on applying DLSS 5. Under that it lists the keys
  as they are set, one to a line with what each does. The lens menu comes first, then the NR
  settings, Neural Rendering off and on, the on-screen readout, and last the arrow keys, Enter
  and Escape, which work the menu and the NR settings panel while one is open. A line after the
  list says what a right click on the taskbar button lists. With Neural Rendering off the first
  line says so instead, and names the keys and the menu entry that bring it back. OK, Enter or
  Escape closes it. Ticking its Don't show this again switches it off at once, a switch on the
  Fullscreen page of Settings switches it on again, and the ini keeps it as `fullscreen_note`.
  It comes up all the same when another program holds one of the keys, and then has no Don't
  show this again if it was switched off. Like every window of the lens it is out of the
  picture, and it never takes the keyboard, so a game under the lens keeps it.
- **The menu of a fullscreen lens** opens at the pointer, or at the top left corner of the
  lens's monitor when the pointer is on another one. Its second line is the readout the title
  bar would show, and it has Leave fullscreen, Minimise to the taskbar and Profiles.
- **Quit Neural Lens in place of Close.** The last entry of the lens menu, in a window and
  fullscreen, was Close, which could be read as closing only the menu or a dialog. It is now
  Quit Neural Lens. The offer to install a new version and the message when the picture cannot
  be started now say that Neural Lens quits, where they said that the lens closes.
- **NR settings on a panel of the lens's own.** With the fast engine, the menu's NR settings
  entry and F8 open a panel with Neural Rendering on or off, the style, the intensity, local
  tone, local structure, skin structure, the auto mask, the passes and the quality step. The
  picture follows a value while it moves. The values are the add-on's own, kept in its section
  of `ReShade.ini`, so the ReShade engine uses them too. A new pass count restarts the picture.
  With the ReShade engine the entry and the key open ReShade's overlay.
- **The menu and the NR settings panel work from the keyboard.** While either is open over a
  fullscreen lens, the lens holds the arrow keys, Enter and Escape as well, and lets them go when
  it closes. In the menu, Up and Down move through the entries, Enter chooses one and Escape
  closes it. On the panel, Up and Down move between the settings, Left and Right change the one
  that is lit, Enter switches a switch and Escape closes it. The note on going fullscreen closes
  with Enter or Escape. The menu, the panel and the note never take the foreground from the
  program in front, so a game under the lens keeps the keyboard.
- **F6 does nothing on the fast engine.** F6 is the add-on's key, and the fast engine has no
  add-on. A fullscreen lens on it turns Neural Rendering off and on with its NR key, F9 unless
  the Hotkeys page of Settings gives it another, or with its menu, and F6 pressed for a game
  under the lens leaves the lens as it is. The add-on of the ReShade engine, which draws every
  windowed lens, reads F6 itself, so in a window F6 switches Neural Rendering as before. The
  program in front gets F6 either way, since the add-on and the lens only read it.
- **Neural Rendering on and off presses no key.** On the ReShade engine the menu's Turn NR off
  and Turn NR back on pressed F6 for the add-on as a real keystroke, which other programs could
  see as well, with the presenter given the keyboard for a moment. Now they and the new F9 write
  the new state into `ReShade.ini`, where the add-on reads it as it starts, and restart the
  picture, as a new pass count does. F6 pressed on the keyboard still switches at once, since
  the add-on reads it itself. With the overlay open they end tweak mode first, as Done tweaking
  does. While the overlay is open or has just closed, the restart waits a second and a half at
  least, and until `ReShade.ini` has held still for a second, four seconds at most, since the
  add-on writes a change made in the overlay to the file about a second later. Giving the
  keyboard back after the lens's own F6 and after tweak mode attached the lens to the input of
  the window that got it back. Now only tweak mode hands the keyboard back, and for that the lens
  attaches only to the presenter's input, while the presenter or another window of the lens's own
  is in front, so it never attaches to another program's input.
- **An on-screen readout for a fullscreen lens.** The Fullscreen page of Settings can put a line
  of figures in a corner of the screen while the lens is fullscreen, with a switch each for the
  frame rate, the latency, the quality step, the passes and the style, all off to begin with,
  and a choice of corner, the top right unless another is chosen. It lets every click through,
  never takes the keyboard, is out of the picture and is updated once a second. The quality step
  shows only on the fast engine. F10 hides the readout and shows it again. Hidden, by F10 or by
  switching every figure off in Settings, it keeps the figures it showed, and F10 brings those
  back, or the frame rate and the latency where none are kept. The ini keeps the choices as
  `fs_readout` and `fs_readout_at`, and the figures F10 brings back as `fs_readout_last`. F10
  writes `fs_readout` as Settings does, so the readout is as it was left at the next start.
- **A fullscreen lens notices a program in exclusive fullscreen**, which nothing else is drawn
  over, the lens included. While Windows reports one and the window in front is another
  program's on the lens's monitor, the lens gives F7 to F10 back and closes its note, menu
  and NR settings panel, so that program gets those keys and the arrow keys, Enter and Escape.
  The notice at the top of the screen says that the lens cannot draw over that program and that
  borderless windowed works, and the log has a line when it starts and when it ends.
- **A warning when the lens falls behind.** A fullscreen lens on the fast engine looks at its
  median delay every 10 s while no program is in exclusive fullscreen on its monitor. When the
  median delay of each of two 10 s spans in a row is three refreshes of its monitor or more,
  25 ms at 120 Hz with a small margin for rates such as 119.88 Hz, and one window of another
  program was in front all that time, a warning at the top of the screen says about how far
  behind the program in front the lens is, that this program most likely keeps the card fully
  busy, and that a frame rate limit in that program, set a little below the rate it reaches, lets
  the lens keep up. Its last sentence says where in Settings it can be switched off. The desktop
  or the taskbar in front brings no warning. It goes after about 12 s and does not come back for
  ten minutes, and `lens.log` has a line whenever it comes, or would come with the switch off.
  The switch is Warn when the lens falls behind, on the Fullscreen page of Settings and on to
  begin with, and the ini keeps it off as `fs_behind_warn = 0`. Switched on again, the warning
  comes at the next two spans behind in a row, with no wait of ten minutes. On a test computer
  with an RTX 5090 and one monitor at 120 Hz, a demanding game that kept the card fully busy while
  it was in front held the lens 38.5 to 58.3 ms behind in most 10 s spans, up to 100 ms in a few,
  with Neural Rendering and G-SYNC on or off, and 0 to 8.3 ms once the game's own frame rate limit
  at 30 fps left the card room to spare. The README has the figures and what did not help.
- **Five quality steps for the fast engine.** Quality, Balanced, Performance, Low power and
  Lowest power are on the Power page of Settings and on the NR settings panel, and
  `fast_quality` in the ini takes 4 down to 0. A lower step has the network work on a smaller
  copy of the picture, which costs less power and loses some of the fine detail the network
  adds. A picture larger than 2560x1440 starts at Balanced, where no loss was seen in the test
  pictures, and a smaller one at Quality, where the network works at the picture's own size. A
  change takes effect while the picture runs. Measured in the same setup with the engine by
  itself at 6144x2526, over the same moving square at about 116 new pictures a second at every
  step, the card drew 240 W at Quality, 220 W at Balanced, 202 W at Performance, 186 W at Low
  power and 154 W at Lowest power. Two actions on the Hotkeys page raise and lower the step,
  with no key set to begin with.
- **A frame rate limit.** The new Power page of Settings, where Ready mode moved too, offers no
  limit, 60 or 30 frames a second, and `max_fps` in the ini takes any rate from 10 to 240 frames
  a second. The neural pass runs only for the pictures the limit lets through. On an RTX 5090
  with a 1400x1000 lens over a moving picture at 120 Hz, the card drew 183 W with no limit,
  129 W at 60 frames a second and 83 W at 30 frames a second. Fullscreen at 6144x2558 on the
  fast engine, with a second monitor connected, it drew 218 W with no limit and 131 W with the
  limit at 60. The ReShade engine runs fullscreen at about 63 frames a second with the card fully
  busy, so there only a limit of 30 saves power, 327 W down to 202 W at 6144x2526. The ReShade
  engine holds a picture until its turn comes, up to one period, so with it a limit adds delay.
  The fast engine takes or leaves each frame as it arrives and does not hold one for its turn, so
  with it a limit adds none. A limit applies straight away and is part of a profile.
- **The latency a fullscreen lens shows on the fast engine is the engine's own measure**, from a
  captured frame's timestamp to the refresh that showed its picture, never below zero. With a
  second monitor at 60 Hz connected it read 0 ms over the moving square, the picture being on
  screen one refresh before the one its frame was composed for. A fullscreen lens shows the
  latency on the second line of its menu.
- **A still screen under the fast engine.** Over a picture that does not change the fast engine
  repeats its picture fifteen times a second without running the network, and thirty times with
  Ready mode. A picture that has come to rest after a large change goes through the network up
  to four more times, since the network's first run on a picture that has just stopped moving is
  not yet its settled one. With the engine by itself at 6144x2526, those runs changed a picture
  that had just stopped scrolling by 1.7 to 2.0 out of 255 on average, and it then stood still.
- **The taskbar button's right-click list** has three entries of the lens's own, Open the lens
  menu, Open or close the NR settings, and Enter or leave fullscreen. They work with a windowed,
  a fullscreen and a minimised lens, which comes back first. Enter or leave fullscreen leaves a
  lens attached to a window as it is and says why on the notice. `NeuralLens.exe --do menu`,
  `--do nr` and `--do fullscreen` hand the same three commands to the lens that is running, for
  a shortcut or a script, and with no lens running they start one, fullscreen for
  `--do fullscreen`. The list is taken away when the last lens closes and when the lens is
  uninstalled, and the entries of a list that a lens ended by force left behind start the lens.
- **Settings shows each setting as one short label**, in a larger font. What a setting does comes
  up in a small window beside the pointer once the pointer has rested on the setting for a
  second and a half. F1 brings it up for the setting that has the keyboard, or for the one under
  the pointer when no setting has it, and a line at the foot of the dialog says how. A click on a
  switch, a choice, a button or the slider gives that setting the keyboard. There are nine pages,
  Picture, Power, Fullscreen, Title bar, Profiles, Hotkeys, Screenshots, Look and Program. An
  explanation says only what its setting does, in a few plain sentences, and the figures
  measured for the settings are in the README and in `docs/NOTES.md`. The Profiles page has a
  Name field with Rename, Delete and Save the current settings beside the list, and a switch that
  another switch holds on says so beside it. The Hotkeys page refuses a combination that another
  action already has, and names that action.
- **The Cost Scaler works to about 4 megapixels over all the passes, down from 8.** It serves the
  ReShade engine, since the fast engine scales the picture itself. With the ReShade engine
  fullscreen at 6144x2526 and one pass that is a scale of 0.50 instead of 0.70, which on an RTX
  5090 ran 63 frames a second on 343 W instead of 53 a second on 397 W, and the picture kept the
  model's full change, where 0.70 made about half of it. A `cost_scaler_mpx` already in the ini
  still applies.
- **Motion detail.** The Picture page of Settings sets how finely the default motion estimator
  works out movement between frames, on the full picture or on half or a quarter of it on each
  side. Half and Quarter cost the card less, and text that moves fast then shows a faint double.
  With the ReShade engine fullscreen at 6144x2526 on an RTX 5090, Half drew 42 W less than Full
  and Quarter 51 W less, at the same frame rate, and a 1400x1000 lens saved 8 W and 11 W. Full
  stays the default. A change restarts the picture, and the choice is part of a profile. The
  fast engine does not use this setting.
- **The lens's ReShade no longer starts in other programs.** Up to 0.5.1 its Vulkan layer was on
  for every Vulkan program, and ReShade starts in any program that has a `ReShade.ini` in its own
  folder, so in another program that has its own ReShade set up for Vulkan the lens's copy could
  start in place of that program's own. The README said a list of allowed programs kept it out,
  which ReShade does not read. The layer now switches on only in the lens's presenter, which sets
  the variable that enables it for itself. The stack setup writes the new layer description each
  time it runs, which the installer does unless its box is unticked. The lens checks the
  registrations of its layer each time it starts. Where an update with the box unticked kept its
  own old one, which Vulkan loads into every program that uses Vulkan, it says so and offers the
  stack setup. Where the old one belongs to another copy of the lens, it names the file and
  offers to remove that registration or to keep it, and does not ask again about one kept. The
  setup's self test and `neural_stack.py --verify` say which registration is in place, and
  `--verify` fails on the old one.
- **The installer carries the fast engine**, as `fast\lens-fast.exe` in the program's folder,
  with the licence texts of openNR and C++/WinRT in `licenses`. An update replaces that folder
  whole, and uninstalling also removes the ini and the engine's log folder.
- **From source the fast engine has to be built.** `fast_engine\build.cmd` builds it into
  `fast_engine\bin`, where the lens finds it. That needs MSVC from Visual Studio 2022 or later,
  or from its Build Tools, with the workload "Desktop development with C++", and Windows SDK
  10.0.26100 or later. Without the engine a fullscreen lens runs on the ReShade engine, and the
  stack setup's summary and `neural_stack.py --verify` say whether the engine is there. The
  release build builds the engine first and stops when that fails.
- **VORT's motion vector code is CC BY-NC 4.0, not MIT.** The README, the stack setup and its log
  said MIT for all of VORT. Most of its files are MIT, but `vort_MotionVectors.fxh` builds on
  ReshadeMotionEstimation and carries the same non-commercial licence, so choosing VORT does not
  lift the setup's non-commercial limit.
- **Logs with times, and a line for each action.** Each line of `lens.log` starts with the local
  time to the millisecond, and so does each note the fast engine writes to
  `presenter-stderr.log`. Each action taken through the lens's keys, its menu, the NR settings
  panel, the title bar's buttons, the taskbar list or Settings has a line with the way it came.
  Save in Settings names each setting it changed, and the Profiles page's Rename, Delete and Save
  the current settings and the Program page's Check now have lines of their own. While a
  fullscreen lens runs on the fast engine, a line every 10 s gives the engine's new and arrived
  pictures a second, the repeated, dropped and skipped ones, its median delay, the quality step,
  the passes, whether Neural Rendering is on and the frame rate limit. A restart, a new quality
  step, pass count or frame rate limit, Neural Rendering or Ready mode switched, fullscreen and
  back, a profile and minimising write that line at once, for the seconds before. While the lens
  is fullscreen, a line names the class of each window that comes to the front, and never its
  title. A lens relaunched by Settings for a new stack folder or theme writes on in the same
  `lens.log`, where its output went to `restart.log` before. One relaunched for a new data folder
  starts a `lens.log` in that folder's `logs`, and `restart.log` stays in the old folder's.
- **Smaller changes.** A lens whose picture cannot be started again says so and quits. Going
  fullscreen or back goes through when `neural-lens.ini` cannot be written. A fullscreen lens
  whose monitors change says "the monitors changed, starting again ...". A screenshot that
  failed says "screenshot failed" and the reason, once. While the ReShade overlay is open the
  title bar says "Tweak mode is on. Press Home when done." Run from source, the lens now starts
  again after the stack setup it offers, where before it did not come back. Tab and Shift+Tab now
  move on through the hotkey fields in Settings, where before a field took Tab and could take
  Shift+Tab as a hotkey. When ReShade does not start in the stack's self test, the setup now says
  what to check, the layer's registration, its switch and `ReShade.ini` beside the presenter, and
  says instead when the cause is that the setup runs as administrator. The bug report form asks
  which engine drew the lens and at which quality step, and names the logs a fast engine writes.
  The README's Limits now say that with Windows HDR on, the lens works from a capture clipped at
  80 nits.

## 0.5.1, 2026-09-28

- **The stack setup finds the Neural Rendering model again.** Since 2026-09-24 the RHI
  manifest lists the 310.8.SF-v2 build as "310.8.2 (20/30/40/50)", and the setup looked the
  model up by its old name, so a new install stopped at the NVIDIA step with "the manifest has
  no dlssnr 310.8.SF-v2". The file itself never moved. The setup now finds each NVIDIA file by
  the release it is published under, then by its name, and when the manifest names neither or
  cannot be reached it fetches the file from that release directly. The hash check still
  decides what is installed. Installs made before 2026-09-24 hold the file already and are not
  affected.
- **The self test's report reads right.** At the end of setup it printed "motion vectors: 2)."
  where it meant the estimator in use, and counted the add-on's log lines as evaluations. It now
  names the estimator, says that the compile failure the Feed logs for it on ReShade 6.8 is
  expected, since it still delivers vectors once something moves, and gives the evaluation count
  the add-on logged.
- **New installs get DLSS5-Feeder 1.17.0**, which the setup fetches as the newest full release.
  It was tested with the lens and changes nothing in the picture.

## 0.5.0, 2026-09-21

- **Themes.** The Look page of Settings picks the colours of the title bar, the menus and the
  dialog. Slate is the lens as it always looked, and Graphite, Paper and Industrial come with
  it. A themes.json in the data folder adds themes of your own, one per name, with the same
  keys as the built-in ones. The picture is never touched. A theme takes effect at the next
  launch, so choosing one restarts the lens.
- **Hide the title bar.** From the menu, or with a hotkey, the title bar and frame give way
  to the small tab on the picture's top edge, the one an attached lens has. The picture stays
  exactly where it is and nothing restarts. The tab drags the lens with the left button,
  slides along the edge with the right button, and opens the menu, where Show is.
  Fullscreen, hiding leaves only the tab, so a fullscreen video behind the lens is covered to
  the top edge as well.

## 0.4.0, 2026-09-15

Attach the lens to a window, profiles, global hotkeys, Settings on pages, and a quicker
first frame after a pause.

- **Attach the lens to a window, or to a region inside one.** Pick the entry from the menu
  and click the window, or drag a rectangle over the part of it you want. The lens then
  follows that window. It moves with it, restarts its picture when the window's size settles,
  minimises and comes back with it, and closes when it closes. A region is kept as a share of
  the window, so it scales with it. While attached, the lens is a thin click-through line
  around the region with a small tab on its top edge that opens the menu, where Detach is,
  and it sits one step above its window in the stacking order rather than above everything.
- **Profiles.** A profile is everything that makes the picture, saved under a name. That is
  the window's place and size, fullscreen, the pass count, the Cost Scaler rule, the ready
  switch, what the title bar shows, and the add-on's whole section of ReShade.ini, which is
  the Home menu. A selector on the title bar saves the current settings as a profile and
  switches between them, and marks the name with a star once the lens no longer matches it.
  Settings renames and deletes them. Applying a profile rewrites the add-on's section whole
  and restarts the picture.
- **Global hotkeys** are off until you set them on the Hotkeys page of Settings. Each action
  can have a key combination that works from anywhere, for a screenshot, a pass more or
  fewer, the A/B split, minimise, fullscreen, the next profile, the ready switch and
  detaching. Home, F5 and F6 on their own are refused, since ReShade and the add-on read them
  from the keyboard.
- **Settings is six pages** rather than one column. They are Picture, Title bar, Profiles,
  Hotkeys, Screenshots and Program, and on each page the explanation comes before the
  controls it explains. The dialog opens over the middle of the lens. On the Profiles page,
  choosing a profile shows what it holds, the lens's own settings and the Home menu's.
- **The title bar's size can be turned off** like the rest of what it shows, and the delay
  meter is now called what it measures, latency, with its floor on a 120 Hz screen stated in
  Settings, about 8 to 11 ms. The frames-in-and-out readout leaves Settings and stays in the
  ini as `readout = detail`, for anyone debugging a capture.
- **The Home menu's NR style and overall intensity can sit on the title bar**, each with its
  own switch on the Title bar page, off by default. Both follow the Home menu within a second
  of a change there. The style is picked from the bar and restarts the picture, since the
  add-on reads its settings only when it starts. The intensity is shown and not moved from
  the bar, because a value worth adjusting needs the picture to follow it live, and only the
  Home menu can do that today.
- **The first frame after a pause.** Over a still the neural pass rests and the card drops to
  its lowest clocks. Measured at 120 Hz with a 1400x1000 lens at one pass, an RTX 4070 SUPER
  took 62 ms for the first frame after 12 seconds still, and up to 151 ms, against 17 ms
  while moving. The lens now keeps presenting thirty times a second for ten seconds after any
  new picture and then drops to four, so a pause in the middle of working costs nothing and a
  longer one costs one late frame. Ready mode, on the Picture page of Settings, keeps
  thirty a second throughout. On that card it brought the first frame after any pause to
  about 21 ms and took a still from 40 W to 58 W. On an RTX 5090 the first frame after a 12
  or 30 second pause took 10 ms with the switch off, so there is nothing for it to buy there.
- **Screenshots to the clipboard.** A switch on the Screenshots page copies the joined before
  and after to the clipboard each time a screenshot is saved.
- **Check for updates** is on the Program page and off by default. With it on, the lens asks
  GitHub for the newest release when it starts, at most once a day, and only says something
  when there is a newer one, with the release page a click away. A second switch offers to
  download that release's installer and run it over this install, and the lens comes back on
  the new version. Nothing is downloaded or installed without a yes.
- **The window buttons have a shade of their own** on the title bar, with a line between them
  and the pass controls, so the minimise glyph no longer reads as the minus of the pass count.
- **Fullscreen covers the whole monitor**, the taskbar's place included, where 0.3.0 stopped at
  the taskbar's edge. A fullscreen video behind the lens is now covered to the bottom of the
  screen.
- **The Feed's download is checked.** Fake copies of DLSS5-Feeder are circulating, so the stack
  setup now compares the zip it fetched with the SHA-256 the Feed's maintainer prints in each
  release's notes, or with a hash verified by hand, and refuses anything that matches neither.
  The other parts of the stack were already checked this way.

## 0.3.0, 2026-09-14

Minimise and maximise buttons, resizing by the edges, and a picture that restarts in place.

- **Minimise, to the taskbar.** The title bar has the three buttons every window has: minimise,
  maximise and close. Minimise hides the lens and pauses the presenter: it ends its capture and
  presents nothing, so no neural pass runs and the lens costs the GPU nothing while it is away.
  Clicking its taskbar button brings it back as it was, with Neural Rendering as it was left.
  Measured on an RTX 5090, a 1400x1000 lens minimised over a square bouncing 33 times a second:
  the GPU read 1 percent and 51 W and the presenter used no CPU time in five seconds, where in
  view over the same square it read 21 percent and 114 W; frames were arriving again half a
  second after the click, with every window back in its place.
- **Maximise, and back**: fullscreen, and back to the last windowed position and size. It
  replaces the Fullscreen checkbox in Settings; `fullscreen` in the ini stays, written by the
  button, so the lens opens the way it was left.
- **Resize by dragging the edges.** The border is now an 8 pixel frame to drag by its sides and
  bottom corners, with the cursors any window shows and the size on the title bar as you go.
  Letting go replaces the picture at the new size. It replaces the menu's resize outline and its
  confirmation.
- **A new size, and fullscreen or back, no longer restart the lens.** The picture restarts in
  place, the way a new pass count does: the presenter is replaced at the new size and the title
  bar and frame laid out again around it, so the taskbar button stays and it takes a second or
  two rather than several. A lens that has to shrink to fit its monitor does the same, and only
  the folder settings still relaunch the lens.
- **Nothing runs when nothing changes.** A captured frame the same as the last is not presented,
  so over content that is not changing the neural pass rests and the title bar says idle. Up to
  0.2.1 the lens ran the model at the display's rate over a still, because its own presents came
  back to it as captures. A present every quarter second keeps ReShade's keys and the capture
  alive, and the overlay, a key press, a screenshot and a probe get the display's rate. The frame
  rate on the title bar is now the rate of new pictures: a video's own rate over a video.
  Measured on an RTX 5090, a 1400x1000 lens at one pass over a still: 0 percent of the GPU and
  53 W idling, against 57 percent and 222 W presenting at the display's rate; over a square
  bouncing 33 times a second, 21 percent and 114 W with 34 new pictures a second, and at 60
  times a second, 36 percent and 166 W with 59. A fresh presenter presents at the display's rate
  for its first twelve seconds whatever arrives, since the add-on builds its neural feature on
  the first frames it is shown.
- **The Cost Scaler in Settings**: a switch for a fullscreen lens, on to begin with, and one for
  a windowed lens too, which keeps the first on. They write `cost_scaler` in the ini, whose
  `manual` value disables them, and a change applies straight away. Measured on an RTX 5090,
  windowed at 2400x1800 with three passes over a source changing 60 times a second: with the
  scaler at 0.75 the GPU read 90 percent and 440 W, without it 99 percent and 566 W, and the
  lens showed 58 to 70 new pictures a second against 53.
- **The title bar shows the delay from capture to display by default**, and the frame rate on
  request, in Settings under Title bar, where it used to be the other way round. The frame rate
  is the rate of new pictures the content under the lens hands it, which the lens never limits,
  and read as the lens's own rate it misled. `readout` in the ini now defaults to `size` and
  `latency` to on.
- The title bar's close, maximise and minimise buttons use Windows' own caption glyphs, from
  the Segoe icon fonts.

## 0.2.1, 2026-09-14

The lens switches on two of the add-on's settings: chained temporal history and the Classic codec.

- **Chained temporal history is on.** The RenoDX DLSS 5 add-on resets its passes beyond the first
  every frame unless its chained temporal history is on, and with it off the picture pulsed at two
  passes and up, over a model in Blender and over a still image. Before the presenter starts, the
  lens now writes `NRChainedHistory=1` into the add-on's section of ReShade.ini where the section
  holds no value for it, so a choice made in the ReShade overlay stays.
- **The codec is Classic.** The lens writes `NRCodecMode=0` the same way, the codec the add-on's
  developer asks for on its v5 line. With the add-on's default, Anchored, a model in Blender showed
  ghosting around it, and with Classic it did not.
- An install made by 0.2.0 gets both at the lens's next start, unless they were set in the overlay.

## 0.2.0, 2026-09-13

The lens draws its picture with a presenter of its own, and mpv is gone.

- **The presenter.** `lens-presenter.exe` is a Vulkan window of the lens's own that captures the
  monitor with Windows.Graphics.Capture, cropped to the lens, with every window of the lens
  excluded from capture, and presents each frame the moment it arrives. Between arrivals it
  presents the last frame again at the display's rate, copied in afresh, so Neural Rendering
  never runs on its own output. ReShade, the Feed and the add-on attach to it as they did to mpv.
  Measured on an RTX 5090 with a 120 Hz display, a window flipping between black and white took
  8 ms to show the change in the presenter's output, where 0.1.0's pipeline took 70 ms at 99 fps.
  A 1400x1000 lens shows 118 frames a second. Fullscreen at 6144x2560 it shows 42 with the delay
  meter at 47 ms, and 58 at 33 ms with the Cost Scaler on, where 0.1.0 measured 183 ms at 33 fps.
  The change Neural Rendering makes to the image is the same.
- Gone with mpv: the Magnification API host, the adaptive frame rate and its Settings controls,
  and the ini's `fps`, `pump_hz`, `adaptive`, `min_fps`, `max_passes`, `passes_mode` and `host`.
  Nothing buffers, so there is no rate to govern. The state file no longer carries a rate, and
  one written by 0.1.0 still loads.
- **Passes run inside the add-on, up to four.** The setup fetches RenoDX DLSS 5 5.2.1, which
  applies several neural passes in one process from `NRPasses` in ReShade.ini. Set writes the
  count and restarts the presenter, and a count chosen in the ReShade overlay's own control
  reaches the title bar within about two seconds while the overlay is open. The add-on's chained
  temporal history, a toggle in its overlay, is left as the add-on has it: at the add-on's
  defaults it made two passes less steady and four steadier, and with other settings it steadied
  two and three, so whether to switch it on is a setting like any other.
- **A new install starts the add-on at its own defaults.** The setup writes nothing into the
  add-on's section of ReShade.ini but its config version, where 0.1.0 wrote tuned values. A
  repair keeps whatever that section holds.
- **The Cost Scaler is part of the stack.** The setup fetches DLSSNR-Cost-Scaler 1.0.6 and puts it
  in front of NVIDIA's model, off, with its global hotkeys off. The lens switches it on for a
  fullscreen lens, scaled so the model's work over all the passes comes to about 8 megapixels,
  and off for a windowed one. `cost_scaler` and `cost_scaler_mpx` in the ini change the rule.
  Fullscreen at 6144x2560 with the add-on at its defaults, it took one pass from 42 frames a
  second to 58 and two passes from 26 to 54, with the change to the picture about a quarter
  smaller.
- The add-on and the Cost Scaler are pinned releases, each archive and the file taken from it
  checked against a hash, as NVIDIA's runtimes already were.
- **The stack sits in the install folder itself**, beside `lens-presenter.exe`, because ReShade
  reads its configuration from the folder of the program it attaches to. The download is about
  150 MB, where it was 230, and the install comes to about 400 MB, where it came to 540.
  Installing over 0.1.0 removes the stack it assembled in `stack`, keeping NVIDIA's runtimes and
  ReShade's DLL when their hashes and version check out, so they are not downloaded again.
- The self test runs the presenter on a still for about nine seconds, and reports whether the
  Cost Scaler loaded as well as whether Neural Rendering ran.
- The title bar menu is drawn by the lens itself. The menu button opens it and closes it, a
  click anywhere else closes it, so does Escape, and it never takes the focus from the
  application under the lens.
- A delay meter on the title bar, switched on in Settings under Title bar or with `latency = 1`
  in the ini: the presenter's own measure from capture to present, plus a refresh and a half for
  composition and scanout. Against a window flipping black and white it read
  8 ms where the flip measured 8 at 120 Hz.
- Fullscreen, the lens fills its monitor apart from the taskbar, with the title bar across the top
  and the picture below it, so the ReShade overlay, which opens at the picture's top left, is never
  under the bar. Fullscreen is no longer marked experimental.
- Home, pressed to close the ReShade overlay, ends tweak mode as Done does, and leaving tweak mode
  gives the keyboard back to the window that had it.
- The lens climbs back on top by itself within a fifth of a second when a maximised or full
  screen window has been stacked over it. Windows puts such a window above every topmost window
  when it becomes the foreground; windows that are themselves topmost are left alone.
- No taskbar button flashes while the presenter starts.
- The lens stays on one monitor, since the presenter captures one. It opens fitted to its
  monitor, centred on the main monitor the first time, a resize is kept within the monitor, and a
  lens let go over an edge slides back onto it. Let go on another monitor, it starts again there.
- Switching a monitor on or off, or rearranging monitors, starts the lens's picture again within a
  couple of seconds. Windows ends a monitor capture when the displays change, so the lens starts
  a new presenter once the monitor layout has held still for a second. The presenter also
  reports a capture that has stopped delivering, and the lens then starts a new one after a wait
  that begins at a second and doubles up to a minute, since a screen that is off or locked stops
  delivering too.
- `stack_dir` in the ini, `--stack-dir` and `NEURAL_LENS_STACK` name the stack folder. The names
  0.1.0 used, `mpv_dir`, `--mpv-dir` and `NEURAL_LENS_MPV_DIR`, still work.
- From source, the presenter needs `glfw` and `vulkan` besides `numpy` and `windows-capture`, and
  `neural_stack.py` puts a copy of the Python running it in the stack folder as
  `lens-presenter.exe`, which the layer's allow list names.

Known limits:

- The neural stack is fetched, not included. None of it is redistributed here, so setup needs
  the network to assemble it, and the lens does nothing until it has.
- The lens stays on one monitor at a time. While it is dragged across a monitor's edge, its
  picture does not line up with what is under it.
- Resizing and changing the pass count restart the presenter, which takes a second or two.
- Applications in exclusive fullscreen cannot be under the lens: nothing else is drawn over them.
  Borderless windowed works.

## 0.1.0, 2026-09-12

First numbered release. Licensed under the GNU General Public License, version 3 or later.

Features:

- A floating see-through window that applies DLSS Neural Rendering to whatever is behind it.
  The viewport is click-through, so the mouse reaches the application underneath.
- The lens starts at one neural pass. Plus and minus on the title bar change the count while it
  runs, up to three; the Settings dialog sets that ceiling and will allow four.
- Resize from the menu, applied by relaunching at the new size and position.
- Before and after screenshots, saved as three PNGs: the captured source, the neural rendered
  result, and the two joined side by side. Both halves come from the same live pipeline a
  fraction of a second apart, so on still content they line up pixel for pixel.
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
  disk when it is done, into that same folder: mpv, ReShade taken out of its setup without
  running it, NVIDIA's two runtimes, the DLSS runtime and the Neural Rendering model, checked
  against known hashes, the DLSS 5 Feeder, the RenoDX add-on, and motion vectors from
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

- The neural stack is fetched, not included. None of it is redistributed here, so setup needs
  the network to assemble it, and the lens does nothing until it has.
- Exclusive fullscreen applications are invisible to the Magnification API. Borderless
  windowed works.
- Resizing relaunches the lens, and changing the pass count respawns every stage.
- The visible stage starts at five sixths of the display's refresh rate, divided by the number
  of passes, and is adjusted from there. A slower GPU, a larger
  lens or a busy GPU lands well below those numbers: a 1400x1000 lens at two passes settled at
  about 35 on an RTX 4070 SUPER, and a 2000x1400 lens at one pass at 41. On an RTX 5090 the same
  1400x1000 lens at one pass held 100, the ceiling for that display, and 62 while the GPU was
  busy with something else. The rate only probes upward
  while the content under the lens is still, so on moving content it stays where it last
  settled. See `docs/NOTES.md`.
