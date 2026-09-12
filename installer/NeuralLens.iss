; Inno Setup script for the DLSS 5 Neural Lens.
;
; Wraps the PyInstaller build (build\dist\NeuralLens) into a per user installer:
; no administrator prompt, a Start Menu entry, Add or remove programs, and an
; uninstaller. The neural stack itself is not in here. The lens fetches it on
; first run, into the user's own folder, from the projects that publish each
; part; see neural_stack.py and docs\NOTES.md for why nothing is bundled.
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
Filename: "{app}\{#AppExe}"; Description: "Start the lens now (it offers to set up the neural stack)"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
// The neural stack lives under %LOCALAPPDATA%\NeuralLens, about 230 MB the user
// downloaded, plus the lens's own state and logs. Ask before removing any of it,
// and do it through the exe's own uninstall so the registry entry goes with it.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  R: Integer;
begin
  if CurUninstallStep = usUninstall then
  begin
    // suppressible, so a silent uninstall never asks and never deletes: it keeps
    if SuppressibleMsgBox('Also remove the Neural Rendering stack the lens downloaded (mpv, ReShade, the NVIDIA runtimes) and the lens''s saved state and logs?' + #13#10 + #13#10 +
              'Choose No to keep them for a later install.', mbConfirmation, MB_YESNO or MB_DEFBUTTON2, IDNO) = IDYES then
    begin
      Exec(ExpandConstant('{app}\{#AppExe}'), '--uninstall-stack', '', SW_HIDE, ewWaitUntilTerminated, R);
      DelTree(ExpandConstant('{localappdata}\NeuralLens'), True, True, True);
    end;
  end;
end;
