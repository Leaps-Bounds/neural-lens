; Inno Setup script for the DLSS 5 Neural Lens.
;
; Wraps the PyInstaller build (build\dist\NeuralLens) into a per user installer:
; no administrator prompt, a folder of the user's choosing, a Start Menu entry,
; Add or remove programs, and an uninstaller.
;
; The neural stack is NOT bundled, because its parts are published by other
; projects under licences that make redistribution wrong or impossible. It is
; fetched instead, and fetched HERE, during setup, on a page of this installer.
; An earlier version left that to the first run of the lens, which met the user
; with a second wizard they had not asked for after setup said it was finished.
;
; Build, from the repository root:
;   python -m PyInstaller --noconfirm --clean --noconsole --onedir --name NeuralLens ^
;       --icon ..\assets\neural-lens.ico --add-data "..\assets\neural-lens.ico;assets" ^
;   (icon and add-data paths are relative to the spec folder, build, hence the ..)
;       --collect-all windows_capture --hidden-import neural_stack ^
;       --distpath build\dist --workpath build\work --specpath build neural_lens.py
;   "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" installer\NeuralLens.iss
; Output: build\installer\NeuralLens-Setup-<version>.exe

#define AppName "DLSS 5 Neural Lens"
#define AppVersion "0.1.0"
#define AppExe "NeuralLens.exe"

[Setup]
AppId={{6B0B1D6E-4C7A-4D6E-9B7D-2A6C1E9F0A11}
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
  CardPage: TInputOptionWizardPage;

procedure InitializeWizard();
begin
  DownloadPage := CreateInputOptionPage(wpSelectTasks,
    'Neural Rendering stack',
    'Setup needs to download about 230 MB.',
    'The lens drives NVIDIA''s DLSS Neural Rendering through mpv and ReShade. None of that is' + #13#10 +
    'included here, because those parts are published by other projects under licences that do' + #13#10 +
    'not allow this installer to carry copies. Setup fetches them from the projects themselves.' + #13#10 + #13#10 +
    'Everything lands inside the folder you chose, is registered for your user only, and is' + #13#10 +
    'removed completely when you uninstall. Nothing asks for administrator rights.' + #13#10 + #13#10 +
    'If you clear this, the lens is installed on its own and you can fetch the stack later from' + #13#10 +
    'the Start Menu entry "' + '{#AppName}' + ' stack setup". The lens cannot render until you do.',
    False, False);
  DownloadPage.Add('Download the Neural Rendering stack now (about 230 MB)');
  DownloadPage.Values[0] := True;

  CardPage := CreateInputOptionPage(DownloadPage.ID,
    'Graphics card',
    'Which NVIDIA card does this computer have?',
    'Neural Rendering uses a different model on each generation, and the wrong one fails to' + #13#10 +
    'start. If you are not sure, leave the last option selected and Setup will identify the' + #13#10 +
    'card itself and choose for you.',
    True, False);
  CardPage.Add('RTX 40 series (Ada)');
  CardPage.Add('RTX 50 series (Blackwell)');
  CardPage.Add('I don''t know: identify the card and choose automatically');
  CardPage.SelectedValueIndex := 2;
end;

{ 'ada', 'blackwell', or '' when the card cannot be identified. Setup runs
  nvidia-smi itself, because the lens is not installed yet when these pages are
  shown. Compute capability is used rather than the marketing name, which
  fragments into "RTX 4090 Laptop GPU" and similar. }
function DetectedGeneration(): String;
var
  Res: Integer;
  Caps: AnsiString;
  Tmp: String;
begin
  { Caps, not Out: "out" is a reserved word in Pascal, and using it here failed
    the whole [Code] section with "'BEGIN' expected" pointing at the var block }
  Result := '';
  Tmp := ExpandConstant('{tmp}\computecap.txt');
  if not FileExists(ExpandConstant('{sys}\nvidia-smi.exe')) then
    Exit;
  if Exec(ExpandConstant('{cmd}'),
          '/c ""' + ExpandConstant('{sys}\nvidia-smi.exe') +
          '" --query-gpu=compute_cap --format=csv,noheader > "' + Tmp + '""',
          '', SW_HIDE, ewWaitUntilTerminated, Res) then
  begin
    if LoadStringFromFile(Tmp, Caps) then
    begin
      if Pos('8.9', Caps) > 0 then
        Result := 'ada'
      else if Pos('12.', Caps) > 0 then
        Result := 'blackwell';
    end;
  end;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  { no card to choose if nothing is being downloaded }
  Result := (PageID = CardPage.ID) and (not DownloadPage.Values[0]);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Detected, Chosen, Human: String;
begin
  Result := True;
  if CurPageID <> CardPage.ID then
    Exit;
  if CardPage.SelectedValueIndex = 2 then
    Exit;
  if CardPage.SelectedValueIndex = 0 then
  begin
    Chosen := 'ada';
    Human := 'RTX 40 series';
  end
  else
  begin
    Chosen := 'blackwell';
    Human := 'RTX 50 series';
  end;
  Detected := DetectedGeneration();
  { warn on a disagreement, but do as asked: the user may be installing for a
    card that is not fitted yet, and it is their machine }
  if (Detected <> '') and (Detected <> Chosen) then
  begin
    Result := MsgBox('You chose ' + Human + ', but this computer looks like a ' +
      'different generation.' + #13#10 + #13#10 +
      'Setup can carry on with your choice. If it turns out to be wrong, Neural ' +
      'Rendering will refuse to start and the lens will show the screen back ' +
      'unchanged. You can rerun the stack setup from the Start Menu at any time ' +
      'to put it right.' + #13#10 + #13#10 +
      'Carry on with ' + Human + '?', mbConfirmation, MB_YESNO) = IDYES;
  end;
end;

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
  install to a dropped connection at 200 MB would be worse than finishing
  without the stack, and the Start Menu entry exists to complete it later. }
procedure RunStackSetup();
var
  Res: Integer;
  LogPath, Args: String;
begin
  LogPath := ExpandConstant('{app}\data\logs\stack-setup.log');
  Args := '--install-stack';
  if CardPage.SelectedValueIndex = 0 then
    Args := Args + ' --gpu ada'
  else if CardPage.SelectedValueIndex = 1 then
    Args := Args + ' --gpu blackwell';

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
