# ui_dialogs.py (完全なソースコード)

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QTextEdit, QScrollArea, QWidget,
    QHBoxLayout, QPushButton, QDialogButtonBox, QCheckBox,
    QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, QComboBox
)
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import Qt, QTimer
from typing import List, Dict, Optional, Any

# app_constantsから必要な定数をインポート
from app_constants import (
    APP_NAME, APP_VERSION, APP_COPYRIGHT, APP_WEBSITE_URL, APP_ICON_PATH
)
from log_manager import LogManager


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

        self.select_all_checkbox = QCheckBox("すべて選択 / すべて解除")
        self.select_all_checkbox.stateChanged.connect(self.toggle_all_checkboxes)
        main_layout.addWidget(self.select_all_checkbox)

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
        self.all_workflows_cache: List[Dict[str, str]] = []

        main_layout = QVBoxLayout(self)

        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("ワークフロー名 (部分一致):"))
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("検索したいワークフロー名を入力...")
        search_layout.addWidget(self.search_box)
        self.search_button = QPushButton("再検索")
        search_layout.addWidget(self.search_button)
        main_layout.addLayout(search_layout)

        self.results_table = QTableWidget()
        self.results_table.setColumnCount(2)
        self.results_table.setHorizontalHeaderLabels(["ワークフロー名", "ワークフローID"])
        self.results_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.results_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.results_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.results_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.results_table.setAlternatingRowColors(True)
        self.results_table.setStyleSheet("""
            QHeaderView::section { 
                background-color: #f0f0f0;
                padding: 4px;
                border: 1px solid #d0d0d0;
            }
        """)
        main_layout.addWidget(self.results_table)
        
        self.button_box = QDialogButtonBox()
        self.ok_button = self.button_box.addButton("選択", QDialogButtonBox.ButtonRole.AcceptRole)
        self.clear_button = self.button_box.addButton("選択をクリア", QDialogButtonBox.ButtonRole.ResetRole)
        self.button_box.addButton(QDialogButtonBox.StandardButton.Cancel)

        self.ok_button.setEnabled(False)
        self.clear_button.setEnabled(False)
        
        main_layout.addWidget(self.button_box)

        self.search_button.clicked.connect(self.fetch_all_workflows)
        self.search_box.textChanged.connect(self.filter_and_display_workflows)
        self.results_table.itemSelectionChanged.connect(self.on_selection_changed)
        self.results_table.itemDoubleClicked.connect(self.accept_selection)
        self.button_box.accepted.connect(self.accept_selection)
        self.button_box.rejected.connect(self.reject)
        self.clear_button.clicked.connect(self.clear_selection)
        
        QTimer.singleShot(50, self.fetch_all_workflows)

    def fetch_all_workflows(self):
        results, error = self.api_client.search_workflows(workflow_name=None)

        if error:
            QMessageBox.critical(self, "APIエラー", f"ワークフローの全件取得に失敗しました。\n\n{error.get('message', '詳細不明')}")
            self.all_workflows_cache = []
        else:
            self.all_workflows_cache = results.get("workflows", [])
        
        self.filter_and_display_workflows()

    def filter_and_display_workflows(self):
        search_term = self.search_box.text().strip().lower()
        self.results_table.setRowCount(0)
        self.ok_button.setEnabled(False)
        self.clear_button.setEnabled(False)

        if not self.all_workflows_cache:
            return
            
        workflows_to_display = []
        if search_term:
            for wf in self.all_workflows_cache:
                if search_term in wf.get("name", "").lower():
                    workflows_to_display.append(wf)
        else:
            workflows_to_display = self.all_workflows_cache

        if not workflows_to_display and search_term:
            pass
        
        self.results_table.setRowCount(len(workflows_to_display))
        for row, wf in enumerate(workflows_to_display):
            name_item = QTableWidgetItem(wf.get("name", "名前なし"))
            id_item = QTableWidgetItem(wf.get("id", "IDなし"))
            name_item.setData(Qt.ItemDataRole.UserRole, {"id": wf.get("id"), "name": wf.get("name")})
            self.results_table.setItem(row, 0, name_item)
            self.results_table.setItem(row, 1, id_item)

    def on_selection_changed(self):
        is_something_selected = len(self.results_table.selectedItems()) > 0
        self.ok_button.setEnabled(is_something_selected)
        self.clear_button.setEnabled(is_something_selected)

    def accept_selection(self):
        selected_items = self.results_table.selectedItems()
        if not selected_items:
            return
            
        first_item = self.results_table.item(self.results_table.currentRow(), 0)
        self.selected_workflow = first_item.data(Qt.ItemDataRole.UserRole)
        self.accept()
        
    def clear_selection(self):
        self.results_table.clearSelection()
        self.selected_workflow = None

    def get_selected_workflow(self) -> Optional[Dict[str, str]]:
        return self.selected_workflow

class ProfileSelectionDialog(QDialog):
    def __init__(self, api_profiles: list[dict], current_profile_id: Optional[str], parent=None, initial_selection_filter: Optional[List[str]] = None):
        super().__init__(parent)
        self.setWindowTitle("APIプロファイル選択")
        self.selected_profile_id: Optional[str] = None
        self.log_manager = LogManager()

        layout = QVBoxLayout(self)
        label = QLabel("使用するAPIプロファイルを選択してください:")
        layout.addWidget(label)

        self.combo_box = QComboBox()

        profiles_to_display = []
        if initial_selection_filter:
            temp_ids_in_dialog = set()
            for profile_id_to_filter in initial_selection_filter:
                if profile_id_to_filter in temp_ids_in_dialog:
                    continue
                profile = next((p for p in api_profiles if p.get("id") == profile_id_to_filter), None)
                if profile:
                    profiles_to_display.append(profile)
                    temp_ids_in_dialog.add(profile_id_to_filter)
            
            if not profiles_to_display:
                self.log_manager.warning(f"ProfileSelectionDialog: initial_selection_filterで有効なプロファイルが見つかりませんでした。全プロファイルを表示します。Filter: {initial_selection_filter}", context="UI_DIALOG_WARN")
                profiles_to_display = api_profiles
        else:
            profiles_to_display = api_profiles

        selected_text_to_set = None
        if initial_selection_filter and profiles_to_display:
            selected_text_to_set = profiles_to_display[0].get("name", profiles_to_display[0].get("id"))
        elif not initial_selection_filter and current_profile_id:
            profile = next((p for p in profiles_to_display if p.get("id") == current_profile_id), None)
            if profile:
                selected_text_to_set = profile.get("name", profile.get("id"))

        for profile in profiles_to_display:
            profile_id = profile.get("id")
            profile_name = profile.get("name", profile_id)
            if profile_id:
                self.combo_box.addItem(profile_name, userData=profile_id)
        
        if selected_text_to_set:
            self.combo_box.setCurrentText(selected_text_to_set)
        elif self.combo_box.count() > 0 :
            self.combo_box.setCurrentIndex(0)

        layout.addWidget(self.combo_box)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def accept(self):
        self.selected_profile_id = self.combo_box.currentData()
        super().accept()

def show_about_dialog(parent=None):
    """
    アプリケーションのバージョン情報を表示するダイアログを作成して表示します。
    """
    dialog = QMessageBox(parent)
    dialog.setWindowTitle(f"{APP_NAME} のバージョン情報")
    
    # アプリケーションアイコンを設定
    icon_pixmap = QPixmap(APP_ICON_PATH)
    if not icon_pixmap.isNull():
        dialog.setIconPixmap(icon_pixmap.scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    # 表示するテキストをHTML形式で作成
    about_text = f"""
    <p style='font-size: 16px;'><b>{APP_NAME}</b></p>
    <p>バージョン: {APP_VERSION}</p>
    <p>AI inside社のOCRエンジン「DX Suite」をより便利に利用するための<br>Windowsデスクトップアプリケーションです。</p>
    <p><a href='{APP_WEBSITE_URL}'>{APP_WEBSITE_URL}</a></p>
    <p>{APP_COPYRIGHT}</p>
    """
    
    dialog.setText(about_text)
    dialog.setTextFormat(Qt.TextFormat.RichText)
    dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
    dialog.exec()
