# main.py

import sys
import faulthandler

from PyQt6.QtWidgets import QApplication

# アプリケーションのメインウィンドウをインポート
from ui_main_window import MainWindow

if __name__ == "__main__":
    faulthandler.enable() # クラッシュ時のトレースバック取得を有効化
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())