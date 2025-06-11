# ui_dialogs.py

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QTextEdit, QScrollArea, QWidget,
    QHBoxLayout, QPushButton, QDialogButtonBox, QCheckBox,
    QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox
)
from PyQt6.QtCore import Qt
from typing import List, Dict, Optional, Any

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

class WorkflowSearchDialog(QDialog):
    def __init__(self, api_client: Any, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ワークフローを検索")
        self.setMinimumSize(600, 400)
        
        self.api_client = api_client
        self.selected_workflow: Optional[Dict[str, str]] = None

        # --- UI要素の作成 ---
        main_layout = QVBoxLayout(self)

        # 検索ボックス
        search_layout = QHBoxLayout()
        # ★★★ 修正箇所 ★★★
        search_layout.addWidget(QLabel("ワークフロー名 (完全一致):"))
        self.search_box = QLineEdit()
        # ★★★ ここまで修正 ★★★
        self.search_box.setPlaceholderText("検索したいワークフロー名を入力...")
        search_layout.addWidget(self.search_box)
        self.search_button = QPushButton("検索")
        search_layout.addWidget(self.search_button)
        main_layout.addLayout(search_layout)

        # 結果表示テーブル
        self.results_table = QTableWidget()
        self.results_table.setColumnCount(2)
        self.results_table.setHorizontalHeaderLabels(["ワークフロー名", "ワークフローID"])
        self.results_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.results_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.results_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.results_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.results_table.setAlternatingRowColors(True)
        main_layout.addWidget(self.results_table)
        
        # OK/キャンセルボタン
        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.ok_button = self.button_box.button(QDialogButtonBox.StandardButton.Ok)
        self.ok_button.setText("選択")
        self.ok_button.setEnabled(False) # 初期状態では無効
        main_layout.addWidget(self.button_box)

        # --- シグナル接続 ---
        self.search_button.clicked.connect(self.perform_search)
        self.search_box.returnPressed.connect(self.perform_search)
        self.results_table.itemSelectionChanged.connect(self.on_selection_changed)
        self.results_table.itemDoubleClicked.connect(self.accept_selection)
        self.button_box.accepted.connect(self.accept_selection)
        self.button_box.rejected.connect(self.reject)

    def perform_search(self):
        """検索ボタンが押されたときの処理"""
        search_term = self.search_box.text().strip()
        self.results_table.setRowCount(0)
        self.ok_button.setEnabled(False)
        
        # APIクライアントを使ってワークフローを検索
        results, error = self.api_client.search_workflows(workflow_name=search_term if search_term else None)

        if error:
            QMessageBox.critical(self, "APIエラー", f"ワークフローの検索に失敗しました。\n\n{error.get('message', '詳細不明')}")
            return
        
        # API仕様書P.11のレスポンス形式 `{"workflows": [...]}` を想定 
        workflows = results.get("workflows", [])
        if not workflows:
            QMessageBox.information(self, "検索結果", "該当するワークフローが見つかりませんでした。")
            return
            
        self.results_table.setRowCount(len(workflows))
        for row, wf in enumerate(workflows):
            # ★★★ 修正箇所１ ★★★
            # API仕様書P.11の表に従い、IDのキーを "workflowId" から "id" に変更
            name_item = QTableWidgetItem(wf.get("name", "名前なし"))
            id_item = QTableWidgetItem(wf.get("id", "IDなし"))
            
            # ★★★ 修正箇所２ ★★★
            # テーブルアイテムに保持するデータも "id" を使用
            name_item.setData(Qt.ItemDataRole.UserRole, {"id": wf.get("id"), "name": wf.get("name")})
            
            self.results_table.setItem(row, 0, name_item)
            self.results_table.setItem(row, 1, id_item)

    def on_selection_changed(self):
        """テーブルの選択状態が変わったときの処理"""
        self.ok_button.setEnabled(len(self.results_table.selectedItems()) > 0)

    def accept_selection(self):
        """OKボタンが押された、またはダブルクリックされたときの処理"""
        selected_items = self.results_table.selectedItems()
        if not selected_items:
            return
            
        # 選択された行の最初のアイテムからデータを取得
        first_item = selected_items[0]
        self.selected_workflow = first_item.data(Qt.ItemDataRole.UserRole)
        self.accept()

    def get_selected_workflow(self) -> Optional[Dict[str, str]]:
        """選択されたワークフロー情報を返す"""
        return self.selected_workflow
