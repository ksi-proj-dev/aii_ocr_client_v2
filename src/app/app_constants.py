# app_constants.py

# --- アプリケーション情報 ---
APP_NAME = "AI inside OCR DX Suite Client for API-V2"
APP_AUTHOR = "KSI"
APP_VERSION = "0.0.17"

# --- OCRエンジン処理状態の定数 ---
OCR_STATUS_NOT_PROCESSED = "未処理"
OCR_STATUS_PROCESSING = "処理中"
OCR_STATUS_COMPLETED = "完了"
OCR_STATUS_FAILED = "失敗"
OCR_STATUS_SKIPPED_SIZE_LIMIT = "対象外(サイズ上限)"
OCR_STATUS_SPLITTING = "分割中"
OCR_STATUS_PART_PROCESSING = "部品処理中"
OCR_STATUS_MERGING = "結合中"

# --- UI更新関連の定数 ---
LISTVIEW_UPDATE_INTERVAL_MS = 300