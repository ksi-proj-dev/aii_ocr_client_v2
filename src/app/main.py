# main.py

import sys
import faulthandler
import argparse

from PyQt6.QtWidgets import QApplication

from ui_main_window import MainWindow
from config_manager import DEFAULT_API_PROFILES # DEFAULT_API_PROFILES をインポート

if __name__ == "__main__":
    faulthandler.enable()

    # --- ★変更箇所: ヘルプメッセージの生成ロジック ---
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
            "起動時に使用するAPIプロファイルIDを指定します (複数指定可能)。\n" # ★説明を少し分けました
            f"{choosable_ids_display_part}\n"  # ★指定可能なID一覧を改行して表示
            f"{example_str}\n"                 # ★具体例も改行して表示
            "有効なプロファイルID指定がない場合、またはプロファイルIDが0個の場合は選択ダイアログを表示します。"
        )
    except Exception as e: # DEFAULT_API_PROFILES の処理中に万が一エラーが起きた場合のフォールバック
        #print(f"ヘルプメッセージ生成中にエラー: {e}") # ログやコンソールへの出力
        api_help_message = (
            "起動時に使用するAPIプロファイルIDを指定します (複数指定可能)。 "
            "例: --api profile_id1 profile_id2 "
            "有効なプロファイルID指定がない場合、またはプロファイルIDが0個の場合は選択ダイアログを表示します。"
        )
    # --- ★変更箇所ここまで ---

    parser = argparse.ArgumentParser(
        description="AI inside OCR Client",
        formatter_class=argparse.RawTextHelpFormatter # ★ヘルプメッセージの改行を維持するため追加
    )
    parser.add_argument(
        "--api",
        nargs='*',
        type=str,
        default=None,
        help=api_help_message # 更新されたヘルプメッセージを使用
    )
    # 今後、他のオプションをここに追加
    # parser.add_argument("--another-option", ...)

    args = parser.parse_args()

    app = QApplication(sys.argv)

    window = MainWindow(cli_args=args)
    window.show()
    sys.exit(app.exec())