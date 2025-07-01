# option_dialog.py (修正版)

import json
import re
from PyQt6.QtWidgets import (
    QDialog, QFormLayout, QLineEdit, QComboBox, QCheckBox, QHBoxLayout,
    QPushButton, QMessageBox, QGroupBox, QSpinBox, QRadioButton,
    QVBoxLayout, QLabel, QWidget, QTabWidget
)
from config_manager import ConfigManager
from ui_dialogs import ClassSelectionDialog, WorkflowSearchDialog
from typing import Optional, Dict, Any

INVALID_FOLDER_NAME_CHARS_PATTERN = r'[\\/:*?"<>|]'

class OptionDialog(QDialog):
    def __init__(self, options_schema: dict, current_option_values: dict, global_config: dict, api_profile: Optional[Dict[str, Any]], api_client: Any, parent=None):
        super().__init__(parent)
        self.setWindowTitle("オプション設定")

        self.options_schema = options_schema
        self.current_option_values = current_option_values if current_option_values else {}
        self.global_config = global_config
        self.api_profile = api_profile
        self.api_client = api_client

        self.widgets_map = {}
        self.saved_settings = (None, None)

        self.init_ui()

        is_dx_standard_v2 = self.api_profile and self.api_profile.get("id") == "dx_standard_v2"
        is_dx_atypical = self.api_profile and self.api_profile.get("id") == "dx_atypical_v2"

        self.output_format_widget.setVisible(not is_dx_standard_v2)
        self.dx_standard_output_widget.setVisible(is_dx_standard_v2)

        if is_dx_atypical:
            self.output_format_json_only_radio.setChecked(True)
            self.output_format_widget.setEnabled(False)
            self.output_format_widget.setToolTip("このプロファイルはJSON出力のみをサポートしています。")
        elif is_dx_standard_v2:
            self.output_format_widget.setEnabled(False)
            self.dx_standard_csv_check.stateChanged.connect(self._update_standard_delete_option_state)
            self._update_standard_delete_option_state()
        else: 
            self.output_format_widget.setEnabled(True)
            self.output_format_widget.setToolTip("")

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        self.setLayout(main_layout)

        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)

        api_options_tab = QWidget()
        common_settings_tab = QWidget()
        
        api_layout = QVBoxLayout(api_options_tab)
        api_layout.setContentsMargins(5, 10, 5, 10)
        common_layout = QVBoxLayout(common_settings_tab)
        common_layout.setContentsMargins(5, 10, 5, 10)

        group_box_style = """
            QGroupBox {
                background-color: #f0f0f0;
                border: 1px solid #d0d0d0;
                border-radius: 5px;
                margin-top: 1ex;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 3px;
                background-color: transparent;
            }
        """

        # ===================================================================
        #  「API別オプション」タブの中身を作成
        # ===================================================================
        api_connection_group = QGroupBox("API接続設定 (現在アクティブなプロファイル用)")
        api_connection_group.setStyleSheet(group_box_style)
        api_connection_form_layout = QFormLayout()
        current_base_uri = self.current_option_values.get("base_uri", "")
        self.profile_base_uri_edit = QLineEdit(current_base_uri)
        self.profile_base_uri_edit.setPlaceholderText("このプロファイル用のベースURIを入力 (例: https://xxx.dx-suite.com/wf/api/fullocr/v2/)")
        self.profile_base_uri_edit.setToolTip("APIの接続先となる基本URLです。末尾のスラッシュは任意です。")
        api_connection_form_layout.addRow("ベースURI:", self.profile_base_uri_edit)
        current_api_key = self.current_option_values.get("api_key", "")
        self.profile_api_key_edit = QLineEdit(current_api_key)
        self.profile_api_key_edit.setPlaceholderText("このプロファイル用のAPIキーを入力")
        self.profile_api_key_edit.setToolTip("現在選択されているAPIプロファイルにのみ適用されるAPIキーです。")
        api_connection_form_layout.addRow("APIキー:", self.profile_api_key_edit)
        api_connection_group.setLayout(api_connection_form_layout)
        api_layout.addWidget(api_connection_group)

        output_format_group = QGroupBox("出力形式")
        output_format_group.setStyleSheet(group_box_style)
        output_format_form_layout = QFormLayout()
        
        file_actions_config = self.global_config.get("file_actions", {})
        
        self.output_format_widget = QWidget()
        output_format_label = QLabel("出力形式:")
        self.output_format_json_only_radio = QRadioButton("JSONのみ")
        self.output_format_pdf_only_radio = QRadioButton("サーチャブルPDFのみ")
        self.output_format_both_radio = QRadioButton("JSON と サーチャブルPDF (両方)")
        current_output_format = file_actions_config.get("output_format", "both")
        if current_output_format == "json_only": self.output_format_json_only_radio.setChecked(True)
        elif current_output_format == "pdf_only": self.output_format_pdf_only_radio.setChecked(True)
        else: self.output_format_both_radio.setChecked(True)
        output_format_layout_v = QVBoxLayout(self.output_format_widget)
        output_format_layout_v.setContentsMargins(0,0,0,0)
        output_format_layout_v.addWidget(self.output_format_json_only_radio)
        output_format_layout_v.addWidget(self.output_format_pdf_only_radio)
        output_format_layout_v.addWidget(self.output_format_both_radio)
        output_format_form_layout.addRow(output_format_label, self.output_format_widget)

        self.dx_standard_output_widget = QWidget()
        dx_standard_output_label = QLabel("出力形式 (dx standard):")
        self.dx_standard_json_check = QCheckBox("OCR結果をJSONファイルとして出力する")
        self.dx_standard_json_check.setChecked(file_actions_config.get("dx_standard_output_json", True))
        self.dx_standard_csv_check = QCheckBox("OCR完了時にCSVファイルを自動でダウンロードする")
        self.dx_standard_csv_check.setChecked(file_actions_config.get("dx_standard_auto_download_csv", True))
        dx_standard_layout_v = QVBoxLayout(self.dx_standard_output_widget)
        dx_standard_layout_v.setContentsMargins(0,0,0,0)
        dx_standard_layout_v.addWidget(self.dx_standard_json_check)
        dx_standard_layout_v.addWidget(self.dx_standard_csv_check)
        output_format_form_layout.addRow(dx_standard_output_label, self.dx_standard_output_widget)

        output_format_group.setLayout(output_format_form_layout)
        api_layout.addWidget(output_format_group)
        
        # === 修正箇所 START ===
        # 3. API別オプションのグループを生成（OCR用と仕分け用に分離）
        if self.options_schema:
            is_dx_standard_v2 = self.api_profile and self.api_profile.get("id") == "dx_standard_v2"

            # グループボックスとレイアウトを準備
            ocr_options_group = QGroupBox("OCRオプション")
            ocr_options_group.setStyleSheet(group_box_style)
            ocr_form_layout = QFormLayout()

            sort_options_group = QGroupBox("仕分けオプション (Elastic Sorter)")
            sort_options_group.setStyleSheet(group_box_style)
            sort_form_layout = QFormLayout()
            
            # 全オプションをループし、適切なグループに振り分け
            for key, schema_item in self.options_schema.items():
                if key in ["api_key", "base_uri"]: continue
                
                # QFormLayoutがコロンを自動付加するため、手動での追加をやめる
                label_text = schema_item.get("label", key)
                current_value = self.current_option_values.get(key, schema_item.get("default"))
                widget = None
                tooltip = schema_item.get("tooltip", "")
                
                # ターゲットとなるレイアウトを決定
                target_layout = sort_form_layout if key == "sortConfigId" else ocr_form_layout

                # ウィジェット生成ロジック（従来通り）
                if schema_item.get("type") == "bool":
                    widget = QCheckBox(schema_item.get("label", key)); widget.setChecked(bool(current_value));
                    if tooltip: widget.setToolTip(tooltip);
                    target_layout.addRow(widget); self.widgets_map[key] = widget
                elif schema_item.get("type") == "int":
                    widget = QSpinBox();
                    if "min" in schema_item: widget.setMinimum(schema_item["min"]);
                    if "max" in schema_item: widget.setMaximum(schema_item["max"]);
                    widget.setValue(int(current_value) if current_value is not None else schema_item.get("default", 0));
                    if "suffix" in schema_item: widget.setSuffix(schema_item["suffix"]);
                    if tooltip: widget.setToolTip(tooltip);
                    target_layout.addRow(label_text, widget); self.widgets_map[key] = widget
                elif key == "classes":
                    h_layout = QHBoxLayout(); line_edit = QLineEdit(str(current_value) if current_value is not None else ""); line_edit.setReadOnly(True); line_edit.setToolTip(tooltip);
                    select_button = QPushButton("クラスを選択..."); select_button.clicked.connect(self.open_class_selection_dialog);
                    h_layout.addWidget(line_edit); h_layout.addWidget(select_button);
                    target_layout.addRow(label_text, h_layout); self.widgets_map[key] = line_edit
                elif schema_item.get("type") == "string":
                    if key == "workflowId":
                        h_layout = QHBoxLayout(); line_edit = QLineEdit(str(current_value) if current_value is not None else "");
                        if "placeholder" in schema_item: line_edit.setPlaceholderText(schema_item["placeholder"]);
                        if tooltip: line_edit.setToolTip(tooltip);
                        search_button = QPushButton("検索..."); search_button.setToolTip("利用可能なワークフローを検索してIDを設定します。"); search_button.clicked.connect(self.open_workflow_search_dialog);
                        h_layout.addWidget(line_edit); h_layout.addWidget(search_button);
                        target_layout.addRow(label_text, h_layout); self.widgets_map[key] = line_edit
                    else:
                        widget = QLineEdit(str(current_value) if current_value is not None else "");
                        if "placeholder" in schema_item: widget.setPlaceholderText(schema_item["placeholder"]);
                        if tooltip: widget.setToolTip(tooltip);
                        target_layout.addRow(label_text, widget); self.widgets_map[key] = widget
                elif schema_item.get("type") == "enum":
                    widget = QComboBox()
                    if "values" in schema_item and isinstance(schema_item["values"], list) and schema_item["values"]:
                        if isinstance(schema_item["values"][0], dict):
                            for item_dict in schema_item["values"]:
                                widget.addItem(item_dict.get("display", ""), item_dict.get("value", ""))
                            index = widget.findData(current_value)
                            if index != -1:
                                widget.setCurrentIndex(index)
                            else:
                                default_val = schema_item.get("default")
                                default_idx = widget.findData(default_val)
                                if default_idx != -1:
                                    widget.setCurrentIndex(default_idx)
                    if tooltip: widget.setToolTip(tooltip)
                    if key == "model": widget.currentIndexChanged.connect(self.on_model_changed)
                    target_layout.addRow(label_text, widget)
                    self.widgets_map[key] = widget

                if key in ["split_large_files_enabled", "split_by_page_count_enabled"]:
                    if isinstance(widget, QCheckBox): widget.stateChanged.connect(self.toggle_dynamic_split_options_enabled_state)
            
            # 作成したグループボックスをレイアウトに追加
            # 標準V2プロファイルの場合のみ、両方のボックスを表示する可能性あり
            if is_dx_standard_v2:
                if sort_form_layout.rowCount() > 0:
                    sort_options_group.setLayout(sort_form_layout)
                    api_layout.addWidget(sort_options_group)
                if ocr_form_layout.rowCount() > 0:
                    ocr_options_group.setLayout(ocr_form_layout)
                    api_layout.addWidget(ocr_options_group)
            else: # その他のプロファイル
                if ocr_form_layout.rowCount() > 0:
                    # グループボックスのタイトルを汎用的に変更
                    ocr_options_group.setTitle("API別 OCRオプション")
                    ocr_options_group.setLayout(ocr_form_layout)
                    api_layout.addWidget(ocr_options_group)
            
            self.toggle_dynamic_split_options_enabled_state()
        # === 修正箇所 END ===

        api_layout.addStretch(1)

        # ===================================================================
        #  「共通設定」タブの中身を作成
        # ===================================================================
        file_move_group = QGroupBox("ファイル移動と結果フォルダ (共通設定)")
        file_move_group.setStyleSheet(group_box_style)
        file_move_form_layout = QFormLayout()
        
        self.results_folder_name_edit = QLineEdit(file_actions_config.get("results_folder_name", "OCR結果"))
        file_move_form_layout.addRow("OCR結果サブフォルダ名:", self.results_folder_name_edit)
        self.move_on_success_chk = QCheckBox("OCR成功時にファイルを移動する")
        self.move_on_success_chk.setChecked(file_actions_config.get("move_on_success_enabled", False))
        file_move_form_layout.addRow(self.move_on_success_chk)
        self.success_folder_name_edit = QLineEdit(file_actions_config.get("success_folder_name", "OCR成功"))
        file_move_form_layout.addRow("成功ファイル移動先サブフォルダ名:", self.success_folder_name_edit)
        self.move_on_failure_chk = QCheckBox("OCR失敗時にファイルを移動する")
        self.move_on_failure_chk.setChecked(file_actions_config.get("move_on_failure_enabled", False))
        file_move_form_layout.addRow(self.move_on_failure_chk)
        self.failure_folder_name_edit = QLineEdit(file_actions_config.get("failure_folder_name", "OCR失敗"))
        file_move_form_layout.addRow("失敗ファイル移動先サブフォルダ名:", self.failure_folder_name_edit)
        
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
        file_move_form_layout.addRow(collision_label, collision_layout_v)
        file_move_group.setLayout(file_move_form_layout)
        common_layout.addWidget(file_move_group)

        log_settings_group = QGroupBox("ログ表示設定 (共通設定)")
        log_settings_group.setStyleSheet(group_box_style)
        log_settings_config = self.global_config.get("log_settings", {})
        log_checkbox_layout = QHBoxLayout()
        self.log_level_info_chk = QCheckBox("INFO"); self.log_level_info_chk.setChecked(log_settings_config.get("log_level_info_enabled", True)); self.log_level_info_chk.setToolTip("アプリケーションの通常動作に関する情報ログを表示します。"); log_checkbox_layout.addWidget(self.log_level_info_chk)
        self.log_level_warning_chk = QCheckBox("WARNING"); self.log_level_warning_chk.setChecked(log_settings_config.get("log_level_warning_enabled", True)); self.log_level_warning_chk.setToolTip("軽微な問題や注意喚起に関する警告ログを表示します。"); log_checkbox_layout.addWidget(self.log_level_warning_chk)
        self.log_level_debug_chk = QCheckBox("DEBUG"); self.log_level_debug_chk.setChecked(log_settings_config.get("log_level_debug_enabled", False)); self.log_level_debug_chk.setToolTip("開発者向けの詳細なデバッグ情報を表示します。"); log_checkbox_layout.addWidget(self.log_level_debug_chk)
        log_checkbox_layout.addStretch(1); log_settings_group.setLayout(log_checkbox_layout)
        common_layout.addWidget(log_settings_group)
        error_label = QLabel("注: ERRORレベルのログは常に表示されます。"); error_label.setStyleSheet("font-style: italic; color: #555; margin-left: 5px;"); common_layout.addWidget(error_label)
        
        common_layout.addStretch(1)

        self.tabs.addTab(api_options_tab, "API別オプション")
        self.tabs.addTab(common_settings_tab, "共通設定")

        button_layout = QHBoxLayout()
        self.save_btn = QPushButton("保存")
        self.cancel_btn = QPushButton("キャンセル")
        self.save_btn.clicked.connect(self.on_save_settings)
        self.cancel_btn.clicked.connect(self.reject)
        button_layout.addStretch()
        button_layout.addWidget(self.save_btn)
        button_layout.addWidget(self.cancel_btn)
        main_layout.addLayout(button_layout)

        self.setMinimumWidth(550)

    def _update_standard_delete_option_state(self):
        """標準OCRプロファイルにて、CSV自動ダウンロードとユニット削除オプションを連動させる"""
        if not (self.api_profile and self.api_profile.get("id") == "dx_standard_v2"):
            return

        delete_widget = self.widgets_map.get("delete_job_after_processing")
        if not isinstance(delete_widget, QCheckBox):
            return
            
        is_auto_download_enabled = self.dx_standard_csv_check.isChecked()
        
        delete_widget.setEnabled(is_auto_download_enabled)
        delete_widget.setToolTip(
            "サーバーからユニットを削除するには、先に「CSVファイルを自動でダウンロードする」を有効にしてください。" if not is_auto_download_enabled else 
            "有効な場合、各ファイルのOCR処理完了後、関連する読取ユニットをDX Suiteサーバーから削除します。"
        )
        
        if not is_auto_download_enabled:
            delete_widget.setChecked(False)

    def on_model_changed(self):
        if "classes" in self.widgets_map:
            classes_widget = self.widgets_map["classes"]
            if isinstance(classes_widget, QLineEdit):
                classes_widget.setText("")

    def open_class_selection_dialog(self):
        model_widget = self.widgets_map.get("model")
        classes_widget = self.widgets_map.get("classes")

        if not isinstance(model_widget, QComboBox) or not isinstance(classes_widget, QLineEdit):
            return

        selected_model_id = model_widget.currentData()
        if not selected_model_id:
            QMessageBox.warning(self, "モデル未選択", "先に帳票モデルを選択してください。")
            return

        available_classes = ConfigManager.get_class_definitions_for_model(selected_model_id)
        if not available_classes:
            QMessageBox.information(self, "クラス定義なし", f"モデル '{selected_model_id}' には、選択可能なクラス定義がありません。")
            return

        current_classes = [c.strip() for c in classes_widget.text().split(',') if c.strip()]
        
        dialog = ClassSelectionDialog(available_classes, current_classes, self)
        if dialog.exec():
            new_classes_str = dialog.get_selected_classes_str()
            classes_widget.setText(new_classes_str)

    def toggle_dynamic_split_options_enabled_state(self):
        size_split_is_enabled = False
        if "split_large_files_enabled" in self.widgets_map:
            chk_box = self.widgets_map.get("split_large_files_enabled")
            if isinstance(chk_box, QCheckBox):
                size_split_is_enabled = chk_box.isChecked()
        
        page_split_is_enabled = False
        if "split_by_page_count_enabled" in self.widgets_map:
            chk_box_page = self.widgets_map.get("split_by_page_count_enabled")
            if isinstance(chk_box_page, QCheckBox):
                page_split_is_enabled = chk_box_page.isChecked()

        widget_chunk_size = self.widgets_map.get("split_chunk_size_mb")
        if widget_chunk_size and isinstance(widget_chunk_size, QSpinBox):
            widget_chunk_size.setEnabled(size_split_is_enabled)

        widget_page_split_enable = self.widgets_map.get("split_by_page_count_enabled")
        if widget_page_split_enable and isinstance(widget_page_split_enable, QCheckBox):
            widget_page_split_enable.setEnabled(size_split_is_enabled)

        widget_max_pages = self.widgets_map.get("split_max_pages_per_part")
        if widget_max_pages and isinstance(widget_max_pages, QSpinBox):
            widget_max_pages.setEnabled(size_split_is_enabled and page_split_is_enabled)

        widget_merge_parts = self.widgets_map.get("merge_split_pdf_parts")
        if widget_merge_parts and isinstance(widget_merge_parts, QCheckBox):
            widget_merge_parts.setEnabled(size_split_is_enabled)

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
        updated_profile_options = {}

        updated_profile_options["api_key"] = self.profile_api_key_edit.text().strip()
        updated_profile_options["base_uri"] = self.profile_base_uri_edit.text().strip()
        
        if self.options_schema:
            for key, schema_item in self.options_schema.items():
                if key in ["api_key", "base_uri"]: 
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
                        if schema_item.get("values") and isinstance(schema_item["values"][0], dict):
                            updated_profile_options[key] = widget.currentData()
                        else:
                            updated_profile_options[key] = widget.currentText()
        
        upload_max_size = updated_profile_options.get("upload_max_size_mb")
        split_enabled = updated_profile_options.get("split_large_files_enabled")
        split_chunk_size = updated_profile_options.get("split_chunk_size_mb")

        if isinstance(upload_max_size, (int, float)) and \
            split_enabled and \
            isinstance(split_chunk_size, (int, float)) and \
            split_chunk_size > upload_max_size:
            QMessageBox.warning(self, "入力エラー", 
                                "「分割サイズ」は、「アップロード可能な最大ファイルサイズ」以下の値に設定してください。")
            if "split_chunk_size_mb" in self.widgets_map: self.widgets_map["split_chunk_size_mb"].setFocus()
            return

        updated_global_config = json.loads(json.dumps(self.global_config))
        
        results_folder = self.results_folder_name_edit.text().strip()
        success_folder = self.success_folder_name_edit.text().strip()
        failure_folder = self.failure_folder_name_edit.text().strip()

        if not self.is_valid_folder_name(results_folder, "OCR結果サブフォルダ名"): return
        if not self.is_valid_folder_name(success_folder, "成功ファイル移動先サブフォルダ名"): return
        if not self.is_valid_folder_name(failure_folder, "失敗ファイル移動先サブフォルダ名"): return
        
        if self.move_on_success_chk.isChecked() and self.move_on_failure_chk.isChecked() and success_folder == failure_folder:
            QMessageBox.warning(self, "入力エラー", "「成功ファイル移動先」と「失敗ファイル移動先」のサブフォルダ名は、互いに異なる名称にしてください。")
            return
        if self.move_on_success_chk.isChecked() and results_folder == success_folder:
            QMessageBox.warning(self, "入力エラー", "「OCR結果」と「成功ファイル移動先」のサブフォルダ名は、互いに異なる名称にしてください（移動が有効な場合）。")
            return
        if self.move_on_failure_chk.isChecked() and results_folder == failure_folder:
            QMessageBox.warning(self, "入力エラー", "「OCR結果」と「失敗ファイル移動先」のサブフォルダ名は、互いに異なる名称にしてください（移動が有効な場合）。")
            return

        file_actions = updated_global_config.setdefault("file_actions", {})
        
        is_dx_standard = self.api_profile and self.api_profile.get("id") == "dx_standard_v2"
        if is_dx_standard:
            file_actions["dx_standard_output_json"] = self.dx_standard_json_check.isChecked()
            file_actions["dx_standard_auto_download_csv"] = self.dx_standard_csv_check.isChecked()
        else:
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

        log_settings = updated_global_config.setdefault("log_settings", {})
        log_settings["log_level_info_enabled"] = self.log_level_info_chk.isChecked()
        log_settings["log_level_warning_enabled"] = self.log_level_warning_chk.isChecked()
        log_settings["log_level_debug_enabled"] = self.log_level_debug_chk.isChecked()

        self.saved_settings = (updated_profile_options, updated_global_config)
        self.accept()

    def get_saved_settings(self):
        return self.saved_settings
    
    def open_workflow_search_dialog(self):
        if not self.api_client:
            QMessageBox.critical(self, "エラー", "APIクライアントが利用できません。")
            return

        dialog = WorkflowSearchDialog(self.api_client, self)
        if dialog.exec():
            selected_wf = dialog.get_selected_workflow()
            if selected_wf and "id" in selected_wf:
                workflow_id_widget = self.widgets_map.get("workflowId")
                if isinstance(workflow_id_widget, QLineEdit):
                    workflow_id_widget.setText(selected_wf["id"])
