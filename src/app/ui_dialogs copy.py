# ui_dialogs.py

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QTextEdit, QScrollArea, QWidget,
    QHBoxLayout, QPushButton, QDialogButtonBox, QCheckBox
)
from PyQt6.QtCore import Qt
from typing import List, Dict

class OcrConfirmationDialog(QDialog):
    def __init__(self, settings_summary, parent=None):
        super().__init__(parent)
        self.setWindowTitle("OCR実行内容の確認")
        self.setMinimumWidth(500)
        self.setMinimumHeight(400)
        layout = QVBoxLayout(self)
        label = QLabel("以下の内容でOCR処理を開始します。よろしいですか？")
        layout.addWidget(label)
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setHtml(settings_summary)
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(self.text_edit)
        layout.addWidget(scroll_area)
        button_layout = QHBoxLayout()
        self.ok_button = QPushButton("実行")
        self.ok_button.clicked.connect(self.accept)
        self.cancel_button = QPushButton("キャンセル")
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addStretch()
        button_layout.addWidget(self.ok_button)
        button_layout.addWidget(self.cancel_button)
        layout.addLayout(button_layout)
        self.setLayout(layout)

class ClassSelectionDialog(QDialog):
    def __init__(self, available_classes: List[Dict[str, str]], selected_classes: List[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("読取クラスの選択")
        self.setMinimumWidth(400)
        self.setMinimumHeight(500)

        self.available_classes = available_classes
        self.selected_classes_str = ""
        self.checkboxes: List[QCheckBox] = []

        main_layout = QVBoxLayout(self)

        # 全選択/全解除チェックボックス
        self.select_all_checkbox = QCheckBox("すべて選択 / すべて解除")
        self.select_all_checkbox.stateChanged.connect(self.toggle_all_checkboxes)
        main_layout.addWidget(self.select_all_checkbox)

        # クラス一覧のスクロールエリア
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        container_widget = QWidget()
        self.class_layout = QVBoxLayout(container_widget)

        selected_set = set(selected_classes)
        for class_def in self.available_classes:
            checkbox = QCheckBox(f"{class_def['display']} ({class_def['value']})")
            checkbox.setProperty("class_value", class_def['value'])
            if class_def['value'] in selected_set:
                checkbox.setChecked(True)
            self.checkboxes.append(checkbox)
            self.class_layout.addWidget(checkbox)
        
        self.class_layout.addStretch()
        scroll_area.setWidget(container_widget)
        main_layout.addWidget(scroll_area)

        # OK/キャンセルボタン
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self.accept_selection)
        button_box.rejected.connect(self.reject)
        main_layout.addWidget(button_box)

        self.setLayout(main_layout)

    def toggle_all_checkboxes(self, state):
        is_checked = (state == Qt.CheckState.Checked.value)
        for checkbox in self.checkboxes:
            checkbox.setChecked(is_checked)

    def accept_selection(self):
        selected = []
        for checkbox in self.checkboxes:
            if checkbox.isChecked():
                selected.append(checkbox.property("class_value"))
        
        self.selected_classes_str = ",".join(selected)
        self.accept()

    def get_selected_classes_str(self) -> str:
        return self.selected_classes_str
