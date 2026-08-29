; Inno Setup script for the Kairo Windows installer.
;
; Per-user install (no UAC prompt) into %LocalAppData%\Programs\Kairo. The user
; may pick another folder. User data (config.json, credentials, logs) lives in
; %APPDATA%\Kairo and is never written or removed by this installer.
;
; Build locally:  .\packaging\build-installer.ps1
; Build in CI:    iscc /DAppVersion=<x.y.z> packaging\Kairo.iss
; Input:   dist\Kairo\      (the PyInstaller onedir output)
; Output:  packaging\Output\KairoSetup-<version>.exe

#ifndef AppVersion
  #define AppVersion "0.0.0-dev"
#endif

#define AppName "Kairo"
#define AppPublisher "Nightdreams-bat"
#define AppExe "Kairo.exe"
#define AppUrl "https://github.com/Nightdreams-bat/kairo"

[Setup]
AppId={{73247DE8-12BD-4C4B-96A9-774F8AF5EBEE}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppUrl}
AppSupportURL={#AppUrl}/issues
AppUpdatesURL={#AppUrl}/releases
DefaultDirName={localappdata}\Programs\Kairo
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=no
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
OutputDir=Output
OutputBaseFilename=KairoSetup-{#AppVersion}
SetupIconFile=..\assets\kairo.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName} {#AppVersion}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\Kairo\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "START_HERE.txt"; DestDir: "{app}"; DestName: "START HERE.txt"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\_internal"
