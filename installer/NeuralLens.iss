; Inno Setup script for the DLSS 5 Neural Lens.
;
; Wraps the PyInstaller build (build\dist\NeuralLens) into a per user installer:
; no administrator prompt, a folder of the user's choosing, a Start Menu entry,
; Add or remove programs, and an uninstaller.
;
; The neural stack is NOT bundled, because its parts are published by other
; projects under licences that make redistribution wrong or impossible. It is
; fetched instead, during setup: a page of this installer offers it, ticked by
; default, and the fetch runs after the files are copied with its progress on
; the status line, so the user meets one installer and no second wizard after.
; The stack lands in the install folder itself, beside lens-presenter.exe,
; because ReShade reads its configuration from the folder of the program it
; attaches to.
;
; The fast engine, lens-fast.exe, the lens's own program for a fullscreen lens,
; is part of the program and installed as fast\lens-fast.exe. The spec builds it
; with fast_engine\build.cmd and puts it into the dist folder, and this script
; refuses a dist folder without it.
;
; Build, from the repository root:
;   python -m PyInstaller --noconfirm --clean --distpath build\dist --workpath build\work installer\NeuralLens.spec
;   "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" installer\NeuralLens.iss
; Output: build\installer\NeuralLens-Setup-<version>.exe
;
; A test build that installs beside a real install without touching it takes a
; name and an AppId of its own from the command line, for example:
;   ISCC /DAppName="DLSS 5 Neural Lens Test" /DAppGuid=<another GUID> /FNeuralLens-Setup-test installer\NeuralLens.iss

#ifndef AppName
  #define AppName "DLSS 5 Neural Lens"
#endif
#ifndef AppGuid
  #define AppGuid "6B0B1D6E-4C7A-4D6E-9B7D-2A6C1E9F0A11"
#endif
#define AppVersion "0.8.0"
#define AppExe "NeuralLens.exe"
#define DownloadMB "150"

; a dist folder from a spec without the fast engine would install a lens whose
; fullscreen quietly falls back to the ReShade engine
#if !FileExists(AddBackslash(SourcePath) + "..\build\dist\NeuralLens\fast\lens-fast.exe")
  #error build\dist\NeuralLens\fast\lens-fast.exe is missing. Build with installer\NeuralLens.spec, which builds the fast engine and puts it there.
#endif

[Setup]
AppId={{{#AppGuid}}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion} beta
AppPublisher=Leaps-Bounds
AppPublisherURL=https://github.com/Leaps-Bounds/neural-lens
AppSupportURL=https://github.com/Leaps-Bounds/neural-lens/issues
DefaultDirName={localappdata}\Programs\NeuralLens
DisableProgramGroupPage=yes
DisableDirPage=no
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=
OutputDir=..\build\installer
OutputBaseFilename=NeuralLens-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.19041
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
SetupIconFile=..\assets\neural-lens.ico
WizardStyle=modern
SetupLogging=yes

LicenseFile=..\LICENSE

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"

; From the dist folder only the four parts the spec builds go into the installer: NeuralLens.exe,
; lens-presenter.exe, the _internal folder the two share, and fast\lens-fast.exe. A lens run from the dist
; folder keeps its stack there beside the program, NVIDIA's runtimes included, with its settings, data and
; logs. ReShade, the add-ons, the Cost Scaler and the fast engine write their own settings, logs,
; screenshots and crash dumps there too. Naming the parts keeps all of that out of an installer that ISCC
; builds on its own after such a run. The stack is fetched, never shipped. _internal holds only what the
; spec collected, since a run writes nothing there, not even Python bytecode. A part the spec gains has to
; be named here as well.
[Files]
Source: "..\build\dist\NeuralLens\{#AppExe}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\build\dist\NeuralLens\lens-presenter.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\build\dist\NeuralLens\_internal\*"; DestDir: "{app}\_internal"; Flags: recursesubdirs ignoreversion
Source: "..\build\dist\NeuralLens\fast\lens-fast.exe"; DestDir: "{app}\fast"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\CHANGELOG.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\neural-lens.ini.example"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\licenses\*"; DestDir: "{app}\licenses"; Flags: ignoreversion

[InstallDelete]
; the program's libraries are replaced whole, so none from an earlier version is left beside the new ones
Type: filesandordirs; Name: "{app}\_internal"
; and so is the fast engine's folder, with the copy of the proxy's ini the engine wrote there,
; which it writes again from the stack's at its next start
Type: filesandordirs; Name: "{app}\fast"

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autoprograms}\{#AppName} stack setup"; Filename: "{app}\{#AppExe}"; Parameters: "--setup-stack"; Comment: "Fetch or repair the Neural Rendering stack"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Start the lens now"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
var
  DownloadPage: TInputOptionWizardPage;

procedure InitializeWizard();
begin
  DownloadPage := CreateInputOptionPage(wpSelectTasks,
    'Neural Rendering stack',
    'Setup can download about {#DownloadMB} MB now.',
    'The lens drives NVIDIA''s DLSS Neural Rendering through ReShade and two community add-ons.' + #13#10 +
    'None of that is included here, because those parts are published by other projects under' + #13#10 +
    'licences that do not allow this installer to carry copies. Setup fetches them from the' + #13#10 +
    'projects themselves.' + #13#10 + #13#10 +
    'Everything lands inside the folder you chose, is registered for your user only, and is' + #13#10 +
    'removed completely when you uninstall. Nothing asks for administrator rights.' + #13#10 + #13#10 +
    'If you clear this, the lens is installed on its own and you can fetch the stack later from' + #13#10 +
    'the Start Menu entry "' + '{#AppName}' + ' stack setup". The lens cannot render until you do.',
    False, False);
  DownloadPage.Add('Download the Neural Rendering stack now (about {#DownloadMB} MB)');
  DownloadPage.Values[0] := True;
end;

{ There is no card page. One Neural Rendering model serves every RTX card, so
  there is nothing to choose and nothing to get wrong. The stack setup checks
  for an RTX card itself and says so plainly if there is not one. }

{ ExecAndLogOutput calls this once per line the stack setup prints, and pumps
  the message queue itself, so the wizard stays alive without a busy wait. }
procedure StackLogLine(const S: String; const Error, FirstLine: Boolean);
var
  Line: String;
begin
  { the sentinel terminates the log file; it is not for the user to read }
  if Pos('__STACK_SETUP_EXIT__', S) > 0 then
    Exit;
  Line := Trim(S);
  if Line <> '' then
    WizardForm.StatusLabel.Caption := Line;
end;

{ Fetch the stack while Setup is still on screen, so the user meets one
  installer and not a second wizard afterwards. ExecAndLogOutput blocks until
  the child exits, pumping messages and calling StackLogLine per output line,
  and hands the exit code back directly.

  A failure warns and lets Setup finish rather than rolling back: losing a whole
  install to a dropped connection near the end of the download would be worse
  than finishing without the stack, and the Start Menu entry exists to complete
  it later. }
procedure RunStackSetup();
var
  Res: Integer;
  LogPath, Args: String;
begin
  LogPath := ExpandConstant('{app}\data\logs\stack-setup.log');
  Args := '--install-stack';

  WizardForm.StatusLabel.Caption := 'Starting the Neural Rendering stack download...';
  Res := -1;
  if not ExecAndLogOutput(ExpandConstant('{app}\{#AppExe}'), Args,
                          ExpandConstant('{app}'), SW_HIDE,
                          ewWaitUntilTerminated, Res, @StackLogLine) then
  begin
    MsgBox('Setup could not start the stack download. The lens is installed; use the' + #13#10 +
           'Start Menu entry "{#AppName} stack setup" to fetch it.', mbInformation, MB_OK);
    Exit;
  end;

  if Res = 0 then
    WizardForm.StatusLabel.Caption := 'The Neural Rendering stack is installed and working.'
  else
    MsgBox('The lens is installed, but the Neural Rendering stack did not finish.' + #13#10 + #13#10 +
           'The details are in:' + #13#10 + LogPath + #13#10 + #13#10 +
           'Use the Start Menu entry "{#AppName} stack setup" to try again. Until then the' + #13#10 +
           'lens will start but show the screen back unchanged.', mbInformation, MB_OK);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and DownloadPage.Values[0] then
    RunStackSetup();
end;

// Everything the lens has is inside {app}: the program, the stack it downloaded,
// the ReShade layer and its data. The fast engine's copy of the proxy's ini in
// {app}\fast and the folder the lens gives it for the runtime's logs,
// {app}\data\logs\fast, are inside too, and the exe's
// own uninstall removes both first. The one thing outside is the registry value
// that names the layer, which the exe's own uninstall removes; the folder itself
// goes with [UninstallDelete]. A DLL the user pointed the setup at was copied in,
// so nothing outside {app} is touched.
//
// These have to be // comments rather than a { } block. Inno ends a brace
// comment at the first }, which {app} supplies, so the rest of the sentence
// becomes code and the section fails to compile.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  R: Integer;
begin
  if CurUninstallStep = usUninstall then
    Exec(ExpandConstant('{app}\{#AppExe}'), '--uninstall-stack', '', SW_HIDE, ewWaitUntilTerminated, R);
end;
