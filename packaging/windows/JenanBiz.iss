#ifndef MyAppName
	#define MyAppName "Jenan Biz Platform"
#endif
#ifndef MyAppVersion
	#define MyAppVersion "1.0.1"
#endif
#ifndef MyAppPublisher
	#define MyAppPublisher "Jenan Biz Platform"
#endif
#ifndef MyAppExeName
	#define MyAppExeName "JenanBiz.exe"
#endif

[Setup]
AppId={{FA9A8C64-B611-4D9D-9D01-DA3F70DEAF32}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\Jenan Biz Platform
DefaultGroupName=Jenan Biz Platform
OutputDir=..\..\dist\setup
OutputBaseFilename=JenanBiz-Setup-{#MyAppVersion}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=..\..\static\icons\app_icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
AppPublisherURL=https://github.com/khalid20210/mohassaba
AppSupportURL=https://github.com/khalid20210/mohassaba

[Languages]
Name: "arabic"; MessagesFile: "compiler:Languages\Arabic.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\..\dist\installer\JenanBiz.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\dist\installer\INSTALL_README.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Jenan Biz Platform"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\Jenan Biz Platform"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "تشغيل Jenan Biz الآن"; Flags: nowait postinstall skipifsilent
