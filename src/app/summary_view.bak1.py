from datetime import datetime, timedelta
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar, QFrame
from PyQt6.QtCore import QTimer
import random

class StatusCard(QFrame):
    def __init__(self, title: str, color: str):
        super().__init__()
        self.setFrameShape(QFrame.Shape.Box)
        self.setStyleSheet(f"""
QFrame {{
    border: 2px solid {color};
    border-radius: 8px;
    padding: 10px;
    background-color: #fefefe;
}}
        """)
        layout = QVBoxLayout()
        self.title = QLabel(title)
        self.title.setStyleSheet("font-weight: bold; font-size: 14pt")
        self.count_label = QLabel("件数: 0件")
        self.count_label.setStyleSheet("font-size: 12pt")
        self.progress = QProgressBar()
        self.progress.setMaximum(100)
        self.progress.setValue(0)
        layout.addWidget(self.title)
        layout.addWidget(self.count_label)
        layout.addWidget(self.progress)
        self.setLayout(layout)

    def update_count(self, count: int, total: int):
        self.count_label.setText(f"件数: {count}件")
        self.progress.setMaximum(total)
        self.progress.setValue(count)

class InfoCard(QFrame):
    def __init__(self, label: str, color: str):
        super().__init__()
        self.setFrameShape(QFrame.Shape.Box)
        self.setStyleSheet(f"""
QFrame {{
    border: 2px solid {color};
    border-radius: 8px;
    padding: 10px;
    background-color: #fefefe;
}}
        """)
        layout = QVBoxLayout()
        self.label = QLabel(label)
        self.label.setStyleSheet("font-weight: bold; font-size: 14pt")
        self.value = QLabel("-")
        self.value.setStyleSheet("font-size: 12pt")
        layout.addWidget(self.label)
        layout.addWidget(self.value)
        self.setLayout(layout)

    def update_value(self, text: str):
        self.value.setText(text)

class SummaryView(QWidget):
    def __init__(self):
        super().__init__()
        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout()
        card_layout = QHBoxLayout()
        info_layout = QHBoxLayout()

        self.start_time = datetime.now()
        self.total_files = 100

        self.cards = {
            "unprocessed": StatusCard("🕓 未処理", "#FFA500"),
            "processing": StatusCard("🔄 処理中", "#1E90FF"),
            "completed": StatusCard("✅ 完了", "#32CD32")
        }

        for card in self.cards.values():
            card_layout.addWidget(card)

        self.info_cards = {
            "start": InfoCard("📅 開始時刻　　", "#808080"),
            "eta": InfoCard("⏱ 予想終了時刻", "#808080"),
            "remain": InfoCard("⌛ 残り時間　　", "#808080")
        }

        for info in self.info_cards.values():
            info_layout.addWidget(info)

        self.info_cards["start"].update_value(self.start_time.strftime("%m/%d %H:%M:%S"))

        main_layout.addLayout(card_layout)
        main_layout.addSpacing(10)
        main_layout.addLayout(info_layout)
        self.setLayout(main_layout)

        self.timer = QTimer()
        self.timer.timeout.connect(self.fake_update)
        self.timer.start(3000)

        self.completed = 0
        self.processing = 0

    def fake_update(self):
        self.completed = min(self.completed + random.randint(0, 5), self.total_files)
        self.processing = random.randint(0, self.total_files - self.completed)
        unprocessed = self.total_files - self.completed - self.processing

        self.cards["unprocessed"].update_count(unprocessed, self.total_files)
        self.cards["processing"].update_count(self.processing, self.total_files)
        self.cards["completed"].update_count(self.completed, self.total_files)

        if self.completed > 0:
            elapsed = (datetime.now() - self.start_time).total_seconds()
            avg = elapsed / self.completed
            remaining = self.total_files - self.completed
            eta_time = datetime.now() + timedelta(seconds=avg * remaining)

            self.info_cards["eta"].update_value(eta_time.strftime("%m/%d %H:%M:%S"))
            self.info_cards["remain"].update_value(str(timedelta(seconds=int(avg * remaining))))
        else:
            self.info_cards["eta"].update_value("-")
            self.info_cards["remain"].update_value("-")
