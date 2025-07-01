# main.py (修正版)

import sys
import argparse

from PyQt6.QtWidgets import QApplication

from log_manager import LogManager
from ui_main_window import MainWindow
from config_manager import DEFAULT_API_PROFILES
# === 修正箇所 START ===
# APP_NAME定数をインポート
from app_constants import APP_NAME
# === 修正箇所 END ===

if __name__ == "__main__":
    
    log_manager = LogManager()

    try:
        available_profile_ids = [p.get("id") for p in DEFAULT_API_PROFILES if p.get("id")]
        
        choosable_ids_display_part = ""
        if available_profile_ids:
            choosable_ids_str = ", ".join(available_profile_ids)
            choosable_ids_display_part = f"指定可能なID: {choosable_ids_str}。"
        else:
            choosable_ids_display_part = "指定可能なIDはありません（設定を確認してください）。"

        example_str = ""
        if len(available_profile_ids) >= 2:
            example_str = f"例: --api {available_profile_ids[0]} {available_profile_ids[1]}"
        elif len(available_profile_ids) == 1:
            example_str = f"例: --api {available_profile_ids[0]}"
        else:
            example_str = "例: --api profile_id1 profile_id2"

        api_help_message = (
            "起動時に使用するAPIプロファイルIDを指定します (複数指定可能)。\n"
            f"{choosable_ids_display_part}\n"
            f"{example_str}\n"
            "有効なプロファイルID指定がない場合、またはプロファイルIDが0個の場合は選択ダイアログを表示します。"
        )
    except Exception as e:
        log_manager.error(f"ヘルプメッセージ生成中にエラー: {e}", context="SYSTEM_INIT")
        api_help_message = (
            "起動時に使用するAPIプロファイルIDを指定します (複数指定可能)。 "
            "例: --api profile_id1 profile_id2 "
            "有効なプロファイルID指定がない場合、またはプロファイルIDが0個の場合は選択ダイアログを表示します。"
        )

    # === 修正箇所 START ===
    # descriptionにAPP_NAME定数を使用
    parser = argparse.ArgumentParser(
        description=APP_NAME,
        formatter_class=argparse.RawTextHelpFormatter
    )
    # === 修正箇所 END ===
    
    parser.add_argument(
        "--api",
        nargs='*',
        type=str,
        default=None,
        help=api_help_message
    )

    args = parser.parse_args()

    app = QApplication(sys.argv)
    
    window = MainWindow(cli_args=args)
    window.show()
    sys.exit(app.exec())