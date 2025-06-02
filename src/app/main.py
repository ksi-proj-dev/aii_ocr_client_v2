# main.py

import sys
import faulthandler
import argparse # argparseをインポート

from PyQt6.QtWidgets import QApplication

from ui_main_window import MainWindow
from config_manager import ConfigManager # MainWindowに渡すため

if __name__ == "__main__":
    faulthandler.enable()

    parser = argparse.ArgumentParser(description="AI inside OCR Client")
    parser.add_argument(
        "--api", 
        type=str, 
        default=None,
        help="Specify the API profile ID to use on startup."
    )
    # 今後、他のオプションをここに追加
    # parser.add_argument("--another-option", ...)

    args = parser.parse_args()

    app = QApplication(sys.argv)
    
    # MainWindow にパースされた引数を渡す
    window = MainWindow(cli_args=args) 
    window.show()
    sys.exit(app.exec())