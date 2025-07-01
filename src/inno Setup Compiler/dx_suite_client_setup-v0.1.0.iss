; Inno Setup スクリプト AI inside OCR DX Suite Client for API-V2

; カレントディレクトリは .iss の設置場所

#define MyAppName "AI inside OCR DX Suite Client for API-V2"
#define MyAppExeName "dx_suite_client.exe"
#define SrcDir "../../src"


[Setup]
; --- アプリの基本情報 ---

AppName={#MyAppName}
AppVersion=0.1.0

; {autopf} は Program Files フォルダ (例: C:\Program Files (x86)) を指します
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}

; ↓ 以下の2行が重要です
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

; アンインストール情報に表示されるアイコン
UninstallDisplayIcon={app}\{#MyAppExeName}

; インストーラーの出力先とファイル名
OutputDir=.\Installer
OutputBaseFilename=dx_suite_client-Setup-0.1.0

; 圧縮設定
Compression=lzma
SolidCompression=yes
WizardStyle=modern

[Languages]
; インストーラーを日本語で表示します
Name: "japanese"; MessagesFile: "compiler:Default.isl"

[Files]
; --- インストールするファイル ---
; pyinstallerで作成した .exe ファイルを指定します
; Source: "配布したいファイルのパス"; DestDir: "インストール先のフォルダ"
Source: "{#SrcDir}\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Tasks]
Name: "desktopicon_all"; Description: "デスクトップに「DX Suite 全文,標準,非定型 OCR」のショートカットを作成する"; GroupDescription: "デスクトップショートカット:";
Name: "desktopicon_fulltext"; Description: "デスクトップに「DX Suite 全文OCR」のショートカットを作成する"; GroupDescription: "デスクトップショートカット:";
Name: "desktopicon_standard"; Description: "デスクトップに「DX Suite 標準OCR」のショートカットを作成する"; GroupDescription: "デスクトップショートカット:";
Name: "desktopicon_atypical"; Description: "デスクトップに「DX Suite 非定型OCR」のショートカットを作成する"; GroupDescription: "デスクトップショートカット:";

[Icons]
; --- スタートメニューのショートカット (上記のまま) ---
Name: "{group}\DX Suite 全文,標準,非定型 OCR"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\DX Suite 全文OCR"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--api dx_fulltext_v2"
Name: "{group}\DX Suite 標準OCR"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--api dx_standard_v2"
Name: "{group}\DX Suite 非定型OCR"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--api dx_atypical_v2"

; --- デスクトップのショートカット（ユーザーが選択可能） ---
Name: "{autodesktop}\DX Suite 全文,標準,非定型 OCR"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon_all
Name: "{autodesktop}\DX Suite 全文OCR"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--api dx_fulltext_v2"; Tasks: desktopicon_fulltext
Name: "{autodesktop}\DX Suite 標準OCR"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--api dx_standard_v2"; Tasks: desktopicon_standard
Name: "{autodesktop}\DX Suite 非定型OCR"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--api dx_atypical_v2"; Tasks: desktopicon_atypical

[Run]
; --- インストール完了後にアプリを起動するかのチェックボックス ---
; Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,AI inside OCR DX Suite Client for API-V2}"; Flags: nowait postinstall skipifsilent
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,アプリケーション}"; Flags: nowait postinstall skipifsilent

; =================================================================
; ★ アンインストール時に特定のファイルを削除する設定
; =================================================================
[UninstallDelete]
; Type: files;             -> 指定したファイルを削除
; Type: filesandordirs;    -> 指定したフォルダと中身のファイルをすべて削除
; Type: dirifempty;        -> 指定したフォルダが空の場合に削除

; {userappdata} は Roaming フォルダ (C:\Users\<ユーザー名>\AppData\Roaming)
; {localappdata} は Local フォルダ (C:\Users\<ユーザー名>\AppData\Local)

; Roamingフォルダにある設定ファイル(config.json)を削除
; "DX Suite" を含んだ正しいパスを指定します
Type: files; Name: "{userappdata}\KSI\{#MyAppName}\config.json"

; LocalフォルダにあるLogsフォルダを、中身ごとすべて削除
Type: filesandordirs; Name: "{localappdata}\KSI\{#MyAppName}\Logs"

; 上記の削除後、フォルダが空になった場合に、その親フォルダ自体も削除
Type: dirifempty; Name: "{userappdata}\KSI\{#MyAppName}"
Type: dirifempty; Name: "{localappdata}\KSI\{#MyAppName}"
