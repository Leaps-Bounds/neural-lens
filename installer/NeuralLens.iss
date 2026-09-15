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
#define AppVersion "0.3.0"
#define AppExe "NeuralLens.exe"
#define DownloadMB "150"

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

[Files]
Source: "..\build\dist\NeuralLens\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\CHANGELOG.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\neural-lens.ini.example"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\licenses\*"; DestDir: "{app}\licenses"; Flags: ignoreversion

[InstallDelete]
; the program's libraries are replaced whole, so none from an earlier version is left beside the new ones
Type: filesandordirs; Name: "{app}\_internal"

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
// the ReShade layer and its data. The one thing outside is the registry value
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
