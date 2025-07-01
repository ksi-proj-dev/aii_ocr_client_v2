# main.py (修正版)

import sys
import argparse

from PyQt6.QtWidgets import QApplication

# --- 修正箇所 ---
# LogManagerをインポートします
from log_manager import LogManager
# --- 修正箇所 ---

from ui_main_window import MainWindow
from config_manager import DEFAULT_API_PROFILES

if __name__ == "__main__":
    # faulthandler.enable()
    
    # --- 修正箇所 ---
    # LogManagerのインスタンスを作成します
    log_manager = LogManager()
    # --- 修正箇所 ---

    try:
        # 利用可能なプロファイルIDのリストを取得
        available_profile_ids = [p.get("id") for p in DEFAULT_API_PROFILES if p.get("id")]
        
        choosable_ids_display_part = ""
        if available_profile_ids:
            choosable_ids_str = ", ".join(available_profile_ids)
            choosable_ids_display_part = f"指定可能なID: {choosable_ids_str}。"
        else:
            choosable_ids_display_part = "指定可能なIDはありません（設定を確認してください）。"

        # ヘルプメッセージ用の具体例を生成
        example_str = ""
        if len(available_profile_ids) >= 2:
            example_str = f"例: --api {available_profile_ids[0]} {available_profile_ids[1]}"
        elif len(available_profile_ids) == 1:
            example_str = f"例: --api {available_profile_ids[0]}"
        else:
            # DEFAULT_API_PROFILES が空か、IDがない場合のフォールバック例
            example_str = "例: --api profile_id1 profile_id2"

        api_help_message = (
            "起動時に使用するAPIプロファイルIDを指定します (複数指定可能)。\n"
            f"{choosable_ids_display_part}\n"
            f"{example_str}\n"
            "有効なプロファイルID指定がない場合、またはプロファイルIDが0個の場合は選択ダイアログを表示します。"
        )
    except Exception as e:
        # --- 修正箇所 ---
        # printをlog_manager.errorに置き換えます
        log_manager.error(f"ヘルプメッセージ生成中にエラー: {e}", context="SYSTEM_INIT")
        # --- 修正箇所 ---
        api_help_message = (
            "起動時に使用するAPIプロファイルIDを指定します (複数指定可能)。 "
            "例: --api profile_id1 profile_id2 "
            "有効なプロファイルID指定がない場合、またはプロファイルIDが0個の場合は選択ダイアログを表示します。"
        )

    parser = argparse.ArgumentParser(
        description="AI inside OCR API V2対応：OCR Client",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "--api",
        nargs='*',
        type=str,
        default=None,
        help=api_help_message
    )

    args = parser.parse_args()

    app = QApplication(sys.argv)

    # MainWindowにはlog_managerを渡す必要はありません。
    # MainWindow自身が新しいインスタンスを生成するためです。
    window = MainWindow(cli_args=args)
    window.show()
    sys.exit(app.exec())