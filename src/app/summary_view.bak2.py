from datetime import datetime, timedelta
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar, QFrame
from PyQt6.QtCore import QTimer # QTimerはETAのリアルタイム更新などに使えるが、今回はイベント駆動

class StatusCard(QFrame):
    def __init__(self, title: str, color: str):
        super().__init__()
        self.setFrameShape(QFrame.Shape.StyledPanel) # BoxからStyledPanelへ変更 (見栄え)
        self.setFrameShadow(QFrame.Shadow.Raised)   # 影を追加
        self.setStyleSheet(f"""
            QFrame {{
                border: 1px solid {color};
                border-radius: 5px; /* 少し丸みを小さく */
                padding: 8px;      /* パディング調整 */
                background-color: #ffffff; /* 背景白 */
            }}
        """)
        layout = QVBoxLayout()
        self.title_label = QLabel(title) # 変数名を変更 (titleだとQWidgetのプロパティと衝突の可能性)
        self.title_label.setStyleSheet("font-weight: bold; font-size: 13pt; color: #333;") # フォントサイズ調整
        self.count_label = QLabel("0件") # 初期値は件数のみ
        self.count_label.setStyleSheet("font-size: 16pt; font-weight: bold; color: #555; qproperty-alignment: 'AlignCenter';")
        self.progress = QProgressBar()
        self.progress.setMaximum(100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False) # パーセンテージ非表示 (件数表示と重複するため)
        self.progress.setFixedHeight(8)    # プログレスバーの高さ調整

        layout.addWidget(self.title_label)
        layout.addWidget(self.count_label)
        layout.addWidget(self.progress)
        self.setLayout(layout)

    def update_data(self, count: int, total: int):
        self.count_label.setText(f"{count}件")
        if total > 0:
            self.progress.setMaximum(total)
            self.progress.setValue(count)
            self.progress.setVisible(True)
        else:
            self.progress.setMaximum(100) # totalが0の場合のデフォルト
            self.progress.setValue(0)
            self.progress.setVisible(False) # totalが0ならプログレスバー非表示

class InfoCard(QFrame):
    def __init__(self, label_text: str, color: str): # 引数名変更
        super().__init__()
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFrameShadow(QFrame.Shadow.Raised)
        self.setStyleSheet(f"""
            QFrame {{
                border: 1px solid {color};
                border-radius: 5px;
                padding: 8px;
                background-color: #ffffff;
            }}
        """)
        layout = QVBoxLayout()
        self.label_widget = QLabel(label_text) # 変数名変更
        self.label_widget.setStyleSheet("font-weight: bold; font-size: 10pt; color: #444;") # フォントサイズ調整
        self.value_label = QLabel("-") # 変数名変更
        self.value_label.setStyleSheet("font-size: 11pt; color: #666; qproperty-alignment: 'AlignRight';") # 右寄せ
        layout.addWidget(self.label_widget)
        layout.addWidget(self.value_label)
        self.setLayout(layout)

    def update_value(self, text: str):
        self.value_label.setText(text)

class SummaryView(QWidget):
    def __init__(self):
        super().__init__()
        self.total_files = 0
        self.processed_count = 0 # 処理が試みられたファイル数 (成功・エラー問わず)
        self.ocr_completed_count = 0  # OCRが成功したファイル数
        self.ocr_error_count = 0      # OCRが失敗したファイル数
        self.start_time = None
        self.init_ui()
        # self.eta_timer = QTimer(self) # ETAの定期更新用 (任意)
        # self.eta_timer.timeout.connect(self.update_eta_display)

    def init_ui(self):
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(10, 10, 10, 10) # マージン設定
        main_layout.setSpacing(15) # ウィジェット間のスペーシング

        # --- ステータスカードのレイアウト ---
        status_card_layout = QHBoxLayout()
        status_card_layout.setSpacing(10)

        self.cards = {
            "pending": StatusCard("処理待ち", "#AAAAAA"),
            "completed": StatusCard("OCR成功", "#32CD32"),
            "error": StatusCard("OCRエラー", "#FF6347")
        }
        status_card_layout.addWidget(self.cards["pending"])
        status_card_layout.addWidget(self.cards["completed"])
        status_card_layout.addWidget(self.cards["error"])

        # --- 情報カードのレイアウト ---
        info_layout = QHBoxLayout()
        info_layout.setSpacing(10)

        self.info_cards = {
            "total": InfoCard("総ファイル数", "#808080"),
            "start_time": InfoCard("処理開始時刻", "#808080"),
            "elapsed_time": InfoCard("経過時間", "#808080"), # 「残り時間」を「経過時間」に変更
            "avg_time": InfoCard("平均処理時間/件", "#808080") # 「予想終了」を「平均時間」に変更
        }
        info_layout.addWidget(self.info_cards["total"])
        info_layout.addWidget(self.info_cards["start_time"])
        info_layout.addWidget(self.info_cards["elapsed_time"])
        info_layout.addWidget(self.info_cards["avg_time"])

        main_layout.addLayout(status_card_layout)
        main_layout.addLayout(info_layout)
        self.setLayout(main_layout)

        self.reset_summary() # 初期表示をリセット状態に

    def reset_summary(self):
        self.total_files = 0
        self.processed_count = 0
        self.ocr_completed_count = 0
        self.ocr_error_count = 0
        self.start_time = None
        # if self.eta_timer.isActive():
        #     self.eta_timer.stop()
        self.update_display()

    def start_processing(self, total_files_count):
        self.total_files = total_files_count
        self.processed_count = 0
        self.ocr_completed_count = 0
        self.ocr_error_count = 0
        self.start_time = datetime.now()
        # if self.total_files > 0 and not self.eta_timer.isActive():
        #     self.eta_timer.start(1000) # 1秒ごとにETA更新
        self.update_display()

    def increment_processed_count(self):
        self.processed_count = min(self.processed_count + 1, self.total_files)
        self.update_display()

    def increment_completed_count(self):
        self.ocr_completed_count += 1
        # self.increment_processed_count() # processed_countは別途呼び出される想定
        self.update_display()

    def increment_error_count(self):
        self.ocr_error_count += 1
        # self.increment_processed_count() # processed_countは別途呼び出される想定
        self.update_display()

    def update_display(self):
        pending_count = self.total_files - self.processed_count
        self.cards["pending"].update_data(pending_count, self.total_files)
        self.cards["completed"].update_data(self.ocr_completed_count, self.total_files)
        self.cards["error"].update_data(self.ocr_error_count, self.total_files)

        self.info_cards["total"].update_value(f"{self.total_files} 件")

        if self.start_time:
            self.info_cards["start_time"].update_value(self.start_time.strftime("%H:%M:%S"))
            elapsed_delta = datetime.now() - self.start_time
            self.info_cards["elapsed_time"].update_value(str(elapsed_delta).split('.')[0]) # 秒まで表示

            if self.processed_count > 0:
                avg_time_per_file_seconds = elapsed_delta.total_seconds() / self.processed_count
                self.info_cards["avg_time"].update_value(f"{avg_time_per_file_seconds:.2f} 秒")
            else:
                self.info_cards["avg_time"].update_value("-")
        else:
            self.info_cards["start_time"].update_value("-")
            self.info_cards["elapsed_time"].update_value("-")
            self.info_cards["avg_time"].update_value("-")

    # def update_eta_display(self): # ETAタイマーで呼ばれる場合
    #     if self.start_time and self.processed_count > 0 and self.processed_count < self.total_files:
    #         # update_display 内のロジックと同様の計算
    #         elapsed_seconds = (datetime.now() - self.start_time).total_seconds()
    #         avg_time_per_file = elapsed_seconds / self.processed_count
    #         remaining_files = self.total_files - self.processed_count
    #         eta_seconds = avg_time_per_file * remaining_files
    #         # self.info_cards["remain"].update_value(str(timedelta(seconds=int(eta_seconds))))
    #         # self.info_cards["eta"].update_value((datetime.now() + timedelta(seconds=eta_seconds)).strftime("%H:%M:%S"))
    #     elif self.processed_count == self.total_files and self.start_time:
    #         # self.info_cards["remain"].update_value("完了")
    #         # self.info_cards["eta"].update_value(self.start_time.strftime("%H:%M:%S")) # 完了時刻でも良い
    #         if self.eta_timer.isActive():
    #             self.eta_timer.stop()
    #     else: # 処理前または完了後
    #         # self.info_cards["remain"].update_value("-")
    #         # self.info_cards["eta"].update_value("-")
    #         if self.eta_timer.isActive():
    #             self.eta_timer.stop()