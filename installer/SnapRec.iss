; Installationsprogramm für SnapRec (Inno Setup 6)
; Wird von GitHub Actions gebaut:  iscc /DAppVersion=1.2.0 installer\SnapRec.iss
; Installiert ohne Admin-Rechte in %LOCALAPPDATA%\Programs\SnapRec

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{8C1B8E3A-6F1D-4B8A-9E5C-5A7D2C4B9F10}
AppName=SnapRec
AppVersion={#AppVersion}
AppVerName=SnapRec {#AppVersion}
AppPublisher=Alex Studios
AppPublisherURL=https://github.com/anonym239/SnapRec
AppSupportURL=https://github.com/anonym239/SnapRec/issues
AppUpdatesURL=https://github.com/anonym239/SnapRec/releases
DefaultDirName={localappdata}\Programs\SnapRec
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=SnapRec-Setup
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\SnapRec.exe
UninstallDisplayName=SnapRec
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
VersionInfoCompany=Alex Studios
VersionInfoCopyright=© Alex Studios · MIT-Lizenz
VersionInfoDescription=SnapRec Setup
VersionInfoProductName=SnapRec
VersionInfoVersion={#AppVersion}

[Languages]
Name: "german"; MessagesFile: "compiler:Languages\German.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
german.WelcomeLabel2=Dieses Programm installiert [name/ver] auf deinem Computer.%n%nAlles Nötige ist schon enthalten – Python muss NICHT installiert sein und Admin-Rechte sind nicht nötig. Ideal auch für Schul- und Arbeits-PCs.
english.WelcomeLabel2=This will install [name/ver] on your computer.%n%nEverything is included – Python is NOT required and no admin rights are needed.

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\SnapRec\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\SnapRec"; Filename: "{app}\SnapRec.exe"
Name: "{autodesktop}\SnapRec"; Filename: "{app}\SnapRec.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\SnapRec.exe"; Description: "{cm:LaunchProgram,SnapRec}"; Flags: nowait postinstall skipifsilent
