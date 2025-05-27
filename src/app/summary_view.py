from datetime import datetime, timedelta
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar, QFrame
from PyQt6.QtCore import Qt

class StatusCard(QFrame):
    def __init__(self, title: str, color: str):
        super().__init__()
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFrameShadow(QFrame.Shadow.Raised)
        self.setStyleSheet(f"""
            QFrame {{ border: 1px solid {color}; border-radius: 5px; padding: 8px; background-color: #ffffff; }}
        """)
        layout = QVBoxLayout()
        self.title_label = QLabel(title)
        self.title_label.setStyleSheet("font-weight: bold; font-size: 13pt; color: #333;")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.count_label = QLabel("0件")
        self.count_label.setStyleSheet("font-size: 16pt; font-weight: bold; color: #555; qproperty-alignment: 'AlignCenter';")
        self.progress = QProgressBar()
        self.progress.setMaximum(100); self.progress.setValue(0); self.progress.setTextVisible(False); self.progress.setFixedHeight(8)
        layout.addWidget(self.title_label); layout.addWidget(self.count_label); layout.addWidget(self.progress)
        self.setLayout(layout)

    def update_data(self, count: int, total: int):
        self.count_label.setText(f"{count}件")
        if total > 0:
            self.progress.setMaximum(total); self.progress.setValue(count); self.progress.setVisible(True)
        else:
            self.progress.setMaximum(100); self.progress.setValue(0); self.progress.setVisible(False)

class InfoCard(QFrame):
    def __init__(self, label_text: str, color: str):
        super().__init__()
        self.setFrameShape(QFrame.Shape.StyledPanel); self.setFrameShadow(QFrame.Shadow.Raised)
        self.setStyleSheet(f"""
            QFrame {{ border: 1px solid {color}; border-radius: 5px; padding: 8px; background-color: #ffffff; }}
        """)
        layout = QVBoxLayout(); self.label_widget = QLabel(label_text)
        self.label_widget.setStyleSheet("font-weight: bold; font-size: 10pt; color: #444; qproperty-alignment: 'AlignCenter';")
        self.value_label = QLabel("-")
        self.value_label.setStyleSheet("font-size: 11pt; color: #666; qproperty-alignment: 'AlignCenter';")
        layout.addWidget(self.label_widget); layout.addWidget(self.value_label)
        self.setLayout(layout)

    def update_value(self, text: str):
        self.value_label.setText(text)

class SummaryView(QWidget):
    def __init__(self):
        super().__init__()
        self.total_files = 0
        self.processed_count = 0
        self.ocr_completed_count = 0
        self.ocr_error_count = 0
        self.start_time = None
        self.init_ui()

    def init_ui(self):
        # (UI要素の初期化は変更なし)
        main_layout = QVBoxLayout(); main_layout.setContentsMargins(10, 10, 10, 10); main_layout.setSpacing(15)
        status_card_layout = QHBoxLayout(); status_card_layout.setSpacing(10)
        self.cards = {"pending": StatusCard("処理待ち", "#AAAAAA"), "completed": StatusCard("OCR成功", "#32CD32"), "error": StatusCard("OCRエラー", "#FF6347")}
        status_card_layout.addWidget(self.cards["pending"]); status_card_layout.addWidget(self.cards["completed"]); status_card_layout.addWidget(self.cards["error"])
        info_layout = QHBoxLayout(); info_layout.setSpacing(10)
        self.info_cards = {"total": InfoCard("総ファイル数", "#808080"), "start_time": InfoCard("処理開始時刻", "#808080"), "elapsed_time": InfoCard("経過時間", "#808080"), "avg_time": InfoCard("平均処理時間/件", "#808080")}
        info_layout.addWidget(self.info_cards["total"]); info_layout.addWidget(self.info_cards["start_time"]); info_layout.addWidget(self.info_cards["elapsed_time"]); info_layout.addWidget(self.info_cards["avg_time"])
        main_layout.addLayout(status_card_layout); main_layout.addLayout(info_layout)
        self.setLayout(main_layout)
        self.reset_summary()

    def reset_summary(self):
        self.total_files = 0; self.processed_count = 0; self.ocr_completed_count = 0; self.ocr_error_count = 0
        self.start_time = None
        self.update_display()

    def start_processing(self, total_files_count):
        self.total_files = total_files_count; self.processed_count = 0; self.ocr_completed_count = 0; self.ocr_error_count = 0
        self.start_time = datetime.now()
        self.update_display()

    # --- ここから変更: 新しいメソッドの追加と既存メソッドの修正 ---
    def update_for_processed_file(self, is_success: bool):
        """ファイル1件の処理結果に応じてサマリーを更新する"""
        self.processed_count = min(self.processed_count + 1, self.total_files)
        if is_success:
            self.ocr_completed_count += 1
        else:
            self.ocr_error_count += 1
        self.update_display()

    def increment_processed_count(self): # このメソッドは直接使われなくなる可能性がある
        self.processed_count = min(self.processed_count + 1, self.total_files)
        # self.update_display() # update_for_processed_file でまとめて行う

    def increment_completed_count(self): # このメソッドは直接使われなくなる可能性がある
        self.ocr_completed_count += 1
        # self.update_display() # update_for_processed_file でまとめて行う

    def increment_error_count(self): # このメソッドは直接使われなくなる可能性がある
        self.ocr_error_count += 1
        # self.update_display() # update_for_processed_file でまとめて行う
    # --- ここまで変更 ---

    def update_display(self):
        pending_count = self.total_files - self.processed_count
        self.cards["pending"].update_data(pending_count, self.total_files)
        self.cards["completed"].update_data(self.ocr_completed_count, self.total_files)
        self.cards["error"].update_data(self.ocr_error_count, self.total_files)
        self.info_cards["total"].update_value(f"{self.total_files} 件")
        if self.start_time:
            self.info_cards["start_time"].update_value(self.start_time.strftime("%H:%M:%S"))
            elapsed_delta = datetime.now() - self.start_time
            self.info_cards["elapsed_time"].update_value(str(elapsed_delta).split('.')[0])
            if self.processed_count > 0:
                avg_time_sec = elapsed_delta.total_seconds() / self.processed_count
                self.info_cards["avg_time"].update_value(f"{avg_time_sec:.2f} 秒")
            else: self.info_cards["avg_time"].update_value("-")
        else:
            self.info_cards["start_time"].update_value("-"); self.info_cards["elapsed_time"].update_value("-"); self.info_cards["avg_time"].update_value("-")