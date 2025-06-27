# app_constants.py (修正版)

import sys
import os

# --- アプリケーション情報 ---
APP_NAME = "AI inside OCR Client for API-V2"
APP_AUTHOR = "KSI"
APP_VERSION = "0.0.17"
APP_COPYRIGHT = f"© 2024 {APP_AUTHOR}. All rights reserved."
APP_WEBSITE_URL = "https://ksin.jp/"

def resource_path(relative_path):
    """ PyInstallerのリソースファイルパス問題を解決するためのヘルパー関数 (修正版) """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    return os.path.join(base_path, relative_path)

APP_ICON_PATH = resource_path("images/dx_suite_client.png")


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