# main.py

import sys
import faulthandler
import argparse

from PyQt6.QtWidgets import QApplication

from ui_main_window import MainWindow
# from config_manager import ConfigManager # MainWindowに渡すわけではないので直接は不要

if __name__ == "__main__":
    faulthandler.enable()

    parser = argparse.ArgumentParser(description="AI inside OCR Client")
    parser.add_argument(
        "--api",
        nargs='*',  # ★変更: 0個以上の引数を受け付けるようにする
        type=str,
        default=None, # ★変更: オプションが指定されなかった場合のデフォルトはNone
        help="起動時に使用するAPIプロファイルIDを指定します (複数指定可能)。指定がない場合、またはプロファイルIDが0個の場合は選択ダイアログを表示します。"
    )
    # 今後、他のオプションをここに追加
    # parser.add_argument("--another-option", ...)

    args = parser.parse_args()

    app = QApplication(sys.argv)

    # MainWindow にパースされた引数を渡す
    window = MainWindow(cli_args=args)
    window.show()
    sys.exit(app.exec())