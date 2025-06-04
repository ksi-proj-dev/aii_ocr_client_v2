# option_dialog.py

import json
import re
from PyQt6.QtWidgets import (
    QDialog, QFormLayout, QLineEdit, QComboBox, QCheckBox, QHBoxLayout,
    QPushButton, QMessageBox, QGroupBox, QSpinBox, QRadioButton,
    QVBoxLayout, QLabel,
    QWidget
)

INVALID_FOLDER_NAME_CHARS_PATTERN = r'[\\/:*?"<>|]'

class OptionDialog(QDialog):
    def __init__(self, options_schema: dict, current_option_values: dict, global_config: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("オプション設定")

        self.options_schema = options_schema # 現在アクティブなプロファイルの options_schema
        # current_option_values はアクティブなプロファイルの options_values_by_profile[profile_id] の内容
        # これには、config_manager.py の修正により "api_key": "" が含まれている想定
        self.current_option_values = current_option_values if current_option_values else {}
        self.global_config = global_config # 全体設定（file_actionsなど、プロファイルに依存しない部分）

        self.widgets_map = {}
        self.saved_settings = (None, None) # (updated_profile_specific_options, updated_global_config)

        self.init_ui()
        self.resize(550, 900) # ウィンドウサイズは適宜調整

    def init_ui(self):
        main_layout = QVBoxLayout(self)

        # --- ★変更箇所: APIキー設定グループボックス ---
        api_key_group = QGroupBox("APIキー設定 (現在アクティブなプロファイル用)") # ★タイトル変更
        api_key_form_layout = QFormLayout()
        # self.current_option_values にはアクティブプロファイルの "api_key" が含まれる想定
        current_api_key = self.current_option_values.get("api_key", "")
        self.profile_api_key_edit = QLineEdit(current_api_key) # ★ウィジェット名を変更し、プロファイル固有の値をロード
        self.profile_api_key_edit.setPlaceholderText("このプロファイル用のAPIキーを入力")
        self.profile_api_key_edit.setToolTip("現在選択されているAPIプロファイルにのみ適用されるAPIキーです。")
        api_key_form_layout.addRow("APIキー:", self.profile_api_key_edit) # ★ラベル変更の可能性も（そのままでも可）
        api_key_group.setLayout(api_key_form_layout)
        main_layout.addWidget(api_key_group)
        # --- ★変更箇所ここまで ---

        if self.options_schema:
            dynamic_options_group = QGroupBox("API別 OCRオプション")
            dynamic_form_layout = QFormLayout()

            for key, schema_item in self.options_schema.items():
                # "api_key" は options_schema には含まれない特別なキーなので、ここでは処理しない
                if key == "api_key":
                    continue

                label_text = schema_item.get("label", key) + ":"
                # current_option_values から値を取得。ここには api_key も含まれているが、上のifでスキップ
                current_value = self.current_option_values.get(key, schema_item.get("default"))
                widget = None
                tooltip = schema_item.get("tooltip", "")

                if schema_item.get("type") == "bool":
                    widget = QCheckBox(schema_item.get("label", key))
                    widget.setChecked(bool(current_value))
                    if tooltip: widget.setToolTip(tooltip)
                    dynamic_form_layout.addRow(widget)
                    self.widgets_map[key] = widget

                elif schema_item.get("type") == "int":
                    widget = QSpinBox()
                    if "min" in schema_item: widget.setMinimum(schema_item["min"])
                    if "max" in schema_item: widget.setMaximum(schema_item["max"])
                    widget.setValue(int(current_value) if current_value is not None else schema_item.get("default", 0))
                    if "suffix" in schema_item: widget.setSuffix(schema_item["suffix"])
                    if tooltip: widget.setToolTip(tooltip)
                    dynamic_form_layout.addRow(label_text, widget)
                    self.widgets_map[key] = widget

                elif schema_item.get("type") == "string": # type "string" を使う場合
                    widget = QLineEdit(str(current_value) if current_value is not None else "")
                    if "placeholder" in schema_item: widget.setPlaceholderText(schema_item["placeholder"])
                    if tooltip: widget.setToolTip(tooltip)
                    dynamic_form_layout.addRow(label_text, widget)
                    self.widgets_map[key] = widget
                
                elif schema_item.get("type") == "enum":
                    widget = QComboBox()
                    if "values" in schema_item and isinstance(schema_item["values"], list):
                        widget.addItems(schema_item["values"])

                    if isinstance(current_value, int) and 0 <= current_value < widget.count():
                        widget.setCurrentIndex(current_value)
                    elif isinstance(current_value, str):
                        index = widget.findText(current_value)
                        if index != -1:
                            widget.setCurrentIndex(index)
                        else:
                            default_str_val = str(schema_item.get("default"))
                            index_default = widget.findText(default_str_val)
                            if index_default != -1: widget.setCurrentIndex(index_default)

                    if tooltip: widget.setToolTip(tooltip)
                    dynamic_form_layout.addRow(label_text, widget)
                    self.widgets_map[key] = widget
                
                if key == "split_large_files_enabled" and isinstance(widget, QCheckBox):
                    widget.stateChanged.connect(self.toggle_dynamic_split_options_enabled_state)

            dynamic_options_group.setLayout(dynamic_form_layout)
            main_layout.addWidget(dynamic_options_group)
            self.toggle_dynamic_split_options_enabled_state()

        file_process_group = QGroupBox("ファイル処理後の出力と移動 (共通設定)")
        file_process_form_layout = QFormLayout()
        file_actions_config = self.global_config.get("file_actions", {})

        output_format_label = QLabel("出力形式:")
        self.output_format_json_only_radio = QRadioButton("JSONのみ")
        self.output_format_pdf_only_radio = QRadioButton("サーチャブルPDFのみ")
        self.output_format_both_radio = QRadioButton("JSON と サーチャブルPDF (両方)")
        current_output_format = file_actions_config.get("output_format", "both")
        if current_output_format == "json_only": self.output_format_json_only_radio.setChecked(True)
        elif current_output_format == "pdf_only": self.output_format_pdf_only_radio.setChecked(True)
        else: self.output_format_both_radio.setChecked(True)
        output_format_layout_v = QVBoxLayout()
        output_format_layout_v.addWidget(self.output_format_json_only_radio)
        output_format_layout_v.addWidget(self.output_format_pdf_only_radio)
        output_format_layout_v.addWidget(self.output_format_both_radio)
        file_process_form_layout.addRow(output_format_label, output_format_layout_v)

        self.results_folder_name_edit = QLineEdit(file_actions_config.get("results_folder_name", "OCR結果"))
        file_process_form_layout.addRow("OCR結果サブフォルダ名:", self.results_folder_name_edit)
        self.move_on_success_chk = QCheckBox("OCR成功時にファイルを移動する")
        self.move_on_success_chk.setChecked(file_actions_config.get("move_on_success_enabled", False))
        file_process_form_layout.addRow(self.move_on_success_chk)
        self.success_folder_name_edit = QLineEdit(file_actions_config.get("success_folder_name", "OCR成功"))
        file_process_form_layout.addRow("成功ファイル移動先サブフォルダ名:", self.success_folder_name_edit)
        self.move_on_failure_chk = QCheckBox("OCR失敗時にファイルを移動する")
        self.move_on_failure_chk.setChecked(file_actions_config.get("move_on_failure_enabled", False))
        file_process_form_layout.addRow(self.move_on_failure_chk)
        self.failure_folder_name_edit = QLineEdit(file_actions_config.get("failure_folder_name", "OCR失敗"))
        file_process_form_layout.addRow("失敗ファイル移動先サブフォルダ名:", self.failure_folder_name_edit)

        collision_label = QLabel("ファイル名衝突時の処理 (移動先):")
        self.collision_overwrite_radio = QRadioButton("上書きする")
        self.collision_rename_radio = QRadioButton("リネームする (例: file.pdf -> file (1).pdf)")
        self.collision_skip_radio = QRadioButton("スキップ（移動しない）")
        collision_action = file_actions_config.get("collision_action", "rename")
        if collision_action == "overwrite": self.collision_overwrite_radio.setChecked(True)
        elif collision_action == "skip": self.collision_skip_radio.setChecked(True)
        else: self.collision_rename_radio.setChecked(True)
        collision_layout_v = QVBoxLayout()
        collision_layout_v.addWidget(self.collision_overwrite_radio)
        collision_layout_v.addWidget(self.collision_rename_radio)
        collision_layout_v.addWidget(self.collision_skip_radio)
        file_process_form_layout.addRow(collision_label, collision_layout_v)
        file_process_group.setLayout(file_process_form_layout)
        main_layout.addWidget(file_process_group)

        button_layout = QHBoxLayout()
        self.save_btn = QPushButton("保存"); self.cancel_btn = QPushButton("キャンセル")
        self.save_btn.clicked.connect(self.on_save_settings)
        self.cancel_btn.clicked.connect(self.reject)
        button_layout.addStretch(); button_layout.addWidget(self.save_btn); button_layout.addWidget(self.cancel_btn)
        main_layout.addLayout(button_layout)

        self.setLayout(main_layout)

    def toggle_dynamic_split_options_enabled_state(self):
        split_is_enabled = False
        if "split_large_files_enabled" in self.widgets_map:
            chk_box = self.widgets_map["split_large_files_enabled"]
            if isinstance(chk_box, QCheckBox):
                split_is_enabled = chk_box.isChecked()

        if "split_chunk_size_mb" in self.widgets_map and isinstance(self.widgets_map["split_chunk_size_mb"], QSpinBox):
            self.widgets_map["split_chunk_size_mb"].setEnabled(split_is_enabled)
        if "merge_split_pdf_parts" in self.widgets_map and isinstance(self.widgets_map["merge_split_pdf_parts"], QCheckBox):
            self.widgets_map["merge_split_pdf_parts"].setEnabled(split_is_enabled)


    def is_valid_folder_name(self, folder_name, field_label):
        if not folder_name:
            QMessageBox.warning(self, "入力エラー", f"{field_label}は必須入力です。")
            return False
        if re.search(INVALID_FOLDER_NAME_CHARS_PATTERN, folder_name):
            QMessageBox.warning(self, "入力エラー", f"{field_label}に使用できない文字が含まれています。\n(使用不可: {INVALID_FOLDER_NAME_CHARS_PATTERN})")
            return False
        if folder_name == "." or folder_name == "..":
            QMessageBox.warning(self, "入力エラー", f"{field_label}に '.' や '..' は使用できません。")
            return False
        return True

    def on_save_settings(self):
        # updated_profile_options は、現在アクティブなプロファイルの options_values_by_profile[profile_id] に保存される内容
        updated_profile_options = {}

        # ★変更箇所: プロファイル固有のAPIキーをまず保存
        updated_profile_options["api_key"] = self.profile_api_key_edit.text().strip()
        # --- ★変更箇所ここまで ---

        if self.options_schema:
            for key, schema_item in self.options_schema.items():
                # "api_key" は options_schema には含まれない特別なキーなので、ここでは処理しない
                if key == "api_key":
                    continue

                widget = self.widgets_map.get(key)
                if widget:
                    if schema_item.get("type") == "bool" and isinstance(widget, QCheckBox):
                        updated_profile_options[key] = 1 if widget.isChecked() else 0
                    elif schema_item.get("type") == "int" and isinstance(widget, QSpinBox):
                        updated_profile_options[key] = widget.value()
                    elif schema_item.get("type") == "string" and isinstance(widget, QLineEdit):
                        updated_profile_options[key] = widget.text().strip()
                    elif schema_item.get("type") == "enum" and isinstance(widget, QComboBox):
                        # 'fulltext_output_mode' はインデックスで保存、他はテキストで保存（現状のロジック踏襲）
                        if key == "fulltext_output_mode":
                             updated_profile_options[key] = widget.currentIndex()
                        else:
                             updated_profile_options[key] = widget.currentText().split(" ")[0] # 例: "katsuji (印刷活字)" -> "katsuji"

        upload_max_size = updated_profile_options.get("upload_max_size_mb")
        split_enabled = updated_profile_options.get("split_large_files_enabled")
        split_chunk_size = updated_profile_options.get("split_chunk_size_mb")

        if split_enabled and isinstance(upload_max_size, int) and isinstance(split_chunk_size, int) and split_chunk_size > upload_max_size:
            QMessageBox.warning(self, "入力エラー",
                                "「分割サイズ」は、「アップロード可能な最大ファイルサイズ」以下の値に設定してください。")
            if "split_chunk_size_mb" in self.widgets_map: self.widgets_map["split_chunk_size_mb"].setFocus()
            return

        # updated_global_config は、プロファイルに依存しない共通設定（主に file_actions と window 設定など）
        # self.global_config (MainWindowから渡された config全体) をコピーして変更する
        updated_global_config = json.loads(json.dumps(self.global_config)) # deepcopyの代わりに

        # ★変更箇所: グローバルなAPIキー設定は削除
        # if "api_key" in updated_global_config:
        #     del updated_global_config["api_key"]
        # --- ★変更箇所ここまで ---

        results_folder = self.results_folder_name_edit.text().strip()
        success_folder = self.success_folder_name_edit.text().strip()
        failure_folder = self.failure_folder_name_edit.text().strip()

        if not self.is_valid_folder_name(results_folder, "OCR結果サブフォルダ名"): return
        if not self.is_valid_folder_name(success_folder, "成功ファイル移動先サブフォルダ名"): return
        if not self.is_valid_folder_name(failure_folder, "失敗ファイル移動先サブフォルダ名"): return

        if self.move_on_success_chk.isChecked() and self.move_on_failure_chk.isChecked() and success_folder == failure_folder:
            QMessageBox.warning(self, "入力エラー", "「成功ファイル移動先」と「失敗ファイル移動先」のサブフォルダ名は、互いに異なる名称にしてください。"); return
        if self.move_on_success_chk.isChecked() and results_folder == success_folder:
             QMessageBox.warning(self, "入力エラー", "「OCR結果」と「成功ファイル移動先」のサブフォルダ名は、互いに異なる名称にしてください（移動が有効な場合）。"); return
        if self.move_on_failure_chk.isChecked() and results_folder == failure_folder:
             QMessageBox.warning(self, "入力エラー", "「OCR結果」と「失敗ファイル移動先」のサブフォルダ名は、互いに異なる名称にしてください（移動が有効な場合）。"); return

        file_actions = updated_global_config.setdefault("file_actions", {})
        if self.output_format_json_only_radio.isChecked(): file_actions["output_format"] = "json_only"
        elif self.output_format_pdf_only_radio.isChecked(): file_actions["output_format"] = "pdf_only"
        else: file_actions["output_format"] = "both"
        file_actions["results_folder_name"] = results_folder
        file_actions["move_on_success_enabled"] = self.move_on_success_chk.isChecked()
        file_actions["success_folder_name"] = success_folder
        file_actions["move_on_failure_enabled"] = self.move_on_failure_chk.isChecked()
        file_actions["failure_folder_name"] = failure_folder
        if self.collision_overwrite_radio.isChecked(): file_actions["collision_action"] = "overwrite"
        elif self.collision_skip_radio.isChecked(): file_actions["collision_action"] = "skip"
        else: file_actions["collision_action"] = "rename"

        self.saved_settings = (updated_profile_options, updated_global_config)
        self.accept()

    def get_saved_settings(self):
        return self.saved_settings