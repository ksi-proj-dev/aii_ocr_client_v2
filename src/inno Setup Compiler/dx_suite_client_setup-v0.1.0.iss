; Inno Setup スクリプト AI inside OCR DX Suite Client for API-V2

[Setup]
; --- アプリの基本情報 ---
AppName=AI inside OCR DX Suite Client for API-V2
AppVersion=0.1.0
; {autopf} は Program Files フォルダ (例: C:\Program Files (x86)) を指します
DefaultDirName={autopf}\AI inside OCR DX Suite Client for API-V2
DefaultGroupName=AI inside OCR DX Suite Client for API-V2

; ↓ 以下の2行が重要です
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

; アンインストール情報に表示されるアイコン
UninstallDisplayIcon={app}\dx_suite_client.exe

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
Source: "C:\Users\MP21-06\Desktop\ksi\AI inside OCR Client\aii_ocr_client_v2\src\app\dist\dx_suite_client.exe"; DestDir: "{app}"; Flags: ignoreversion

[Tasks]
Name: "desktopicon_all"; Description: "デスクトップに「DX Suite 全文,標準,非定型 OCR」のショートカットを作成する"; GroupDescription: "デスクトップショートカット:";
Name: "desktopicon_fullocr"; Description: "デスクトップに「DX Suite 全文OCR」のショートカットを作成する"; GroupDescription: "デスクトップショートカット:";
Name: "desktopicon_standard"; Description: "デスクトップに「DX Suite 標準OCR」のショートカットを作成する"; GroupDescription: "デスクトップショートカット:";
Name: "desktopicon_atypical"; Description: "デスクトップに「DX Suite 非定型OCR」のショートカットを作成する"; GroupDescription: "デスクトップショートカット:";

[Icons]
; --- スタートメニューのショートカット (上記のまま) ---
Name: "{group}\DX Suite 全文,標準,非定型 OCR"; Filename: "{app}\dx_suite_client.exe"
Name: "{group}\DX Suite 全文OCR"; Filename: "{app}\dx_suite_client.exe"; Parameters: "--api dx_fullocr_v2"
Name: "{group}\DX Suite 標準OCR"; Filename: "{app}\dx_suite_client.exe"; Parameters: "--api dx_standard_v2"
Name: "{group}\DX Suite 非定型OCR"; Filename: "{app}\dx_suite_client.exe"; Parameters: "--api dx_atypical_v2"

; --- デスクトップのショートカット（ユーザーが選択可能） ---
Name: "{autodesktop}\DX Suite 全文,標準,非定型 OCR"; Filename: "{app}\dx_suite_client.exe"; Tasks: desktopicon_all
Name: "{autodesktop}\DX Suite 全文OCR"; Filename: "{app}\dx_suite_client.exe"; Parameters: "--api dx_fullocr_v2"; Tasks: desktopicon_fullocr
Name: "{autodesktop}\DX Suite 標準OCR"; Filename: "{app}\dx_suite_client.exe"; Parameters: "--api dx_standard_v2"; Tasks: desktopicon_standard
Name: "{autodesktop}\DX Suite 非定型OCR"; Filename: "{app}\dx_suite_client.exe"; Parameters: "--api dx_atypical_v2"; Tasks: desktopicon_atypical

[Run]
; --- インストール完了後にアプリを起動するかのチェックボックス ---
Filename: "{app}\dx_suite_client.exe"; Description: "{cm:LaunchProgram,AI inside OCR DX Suite Client for API-V2}"; Flags: nowait postinstall skipifsilent

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
Type: files; Name: "{userappdata}\KSI\AI inside OCR DX Suite Client for API-V2\config.json"

; LocalフォルダにあるLogsフォルダを、中身ごとすべて削除
Type: filesandordirs; Name: "{localappdata}\KSI\AI inside OCR DX Suite Client for API-V2\Logs"

; 上記の削除後、フォルダが空になった場合に、その親フォルダ自体も削除
Type: dirifempty; Name: "{userappdata}\KSI\AI inside OCR DX Suite Client for API-V2"
Type: dirifempty; Name: "{localappdata}\KSI\AI inside OCR DX Suite Client for API-V2"
