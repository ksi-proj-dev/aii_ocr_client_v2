import json
import re
from PyQt6.QtWidgets import (
    QDialog, QFormLayout, QLineEdit, QComboBox, QCheckBox, QHBoxLayout,
    QPushButton, QMessageBox, QGroupBox, QSpinBox, QRadioButton,
    QVBoxLayout, QLabel
)
from config_manager import ConfigManager

INVALID_FOLDER_NAME_CHARS_PATTERN = r'[\\/:*?"<>|]'

class OptionDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("オプション設定 (AI inside Cube)")
        self.config = ConfigManager.load() 
        self.cube_options_key = self.config.get("api_type", "cube_fullocr")
        self.init_ui()
        self.resize(550, 930) 

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        current_ocr_options = self.config.get("options", {}).get(self.cube_options_key, {})

        # --- 1. 基本設定グループ ---
        basic_group = QGroupBox("基本設定")
        basic_form_layout = QFormLayout()
        self.api_key_edit = QLineEdit(self.config.get("api_key", ""))
        basic_form_layout.addRow("APIキー:", self.api_key_edit)
        default_base_uri = "http://localhost/api/v1/domains/aiinside/endpoints/"
        self.base_uri_edit = QLineEdit(self.config.get("base_uri", default_base_uri))
        basic_form_layout.addRow("ベースURI:", self.base_uri_edit)
        self.api_type_edit = QLineEdit(self.cube_options_key); self.api_type_edit.setReadOnly(True); self.api_type_edit.setStyleSheet("background-color: lightgray;")
        basic_form_layout.addRow("API種別:", self.api_type_edit)
        endpoints_text = json.dumps(self.config.get("endpoints", {}).get(self.cube_options_key, {}), indent=2, ensure_ascii=False)
        self.endpoints_edit = QLineEdit(endpoints_text); self.endpoints_edit.setReadOnly(True); self.endpoints_edit.setStyleSheet("background-color: lightgray;"); self.endpoints_edit.setMinimumHeight(60)
        basic_form_layout.addRow("エンドポイント情報:", self.endpoints_edit)
        basic_group.setLayout(basic_form_layout)
        main_layout.addWidget(basic_group)

        # --- 2. ファイル検索設定グループ ---
        file_search_group = QGroupBox("ファイル検索設定")
        file_search_form_layout = QFormLayout()
        self.max_files_spinbox = QSpinBox(); self.max_files_spinbox.setRange(1, 9999); self.max_files_spinbox.setValue(current_ocr_options.get("max_files_to_process", 100))
        file_search_form_layout.addRow("最大処理ファイル数:", self.max_files_spinbox)
        self.recursion_depth_spinbox = QSpinBox(); self.recursion_depth_spinbox.setRange(1, 10); self.recursion_depth_spinbox.setValue(current_ocr_options.get("recursion_depth", 5))
        file_search_form_layout.addRow("再帰検索の深さ:", self.recursion_depth_spinbox)
        file_search_group.setLayout(file_search_form_layout)
        main_layout.addWidget(file_search_group)
        
        # --- アップロードとファイル分割設定グループ ---
        upload_split_group = QGroupBox("アップロードとファイル分割設定")
        upload_split_form_layout = QFormLayout()

        self.upload_max_size_spinbox = QSpinBox()
        self.upload_max_size_spinbox.setRange(1, 99) # Assuming 99MB is a reasonable practical upper limit for this setting
        self.upload_max_size_spinbox.setValue(current_ocr_options.get("upload_max_size_mb", 50))
        self.upload_max_size_spinbox.setSuffix(" MB")
        self.upload_max_size_spinbox.setToolTip("OCR対象としてアップロードするファイルサイズの上限値。これを超過するファイルは処理対象外となります。")
        upload_split_form_layout.addRow("アップロード可能な最大ファイルサイズ:", self.upload_max_size_spinbox)

        self.split_enabled_chk = QCheckBox("大きなファイルを自動分割する")
        self.split_enabled_chk.setChecked(current_ocr_options.get("split_large_files_enabled", False))
        self.split_enabled_chk.setToolTip("上記「アップロード可能な最大ファイルサイズ」以下のファイルで、\nさらに「分割サイズ」を超える場合に、ファイルを分割してからOCR処理を行います。")
        self.split_enabled_chk.stateChanged.connect(self.toggle_split_options_enabled_state)
        upload_split_form_layout.addRow(self.split_enabled_chk)

        self.split_chunk_size_spinbox = QSpinBox()
        self.split_chunk_size_spinbox.setRange(1, 99) # Should not exceed upload_max_size_mb
        self.split_chunk_size_spinbox.setValue(current_ocr_options.get("split_chunk_size_mb", 10))
        self.split_chunk_size_spinbox.setSuffix(" MB")
        self.split_chunk_size_spinbox.setToolTip("自動分割を有効にした場合の、分割後の各ファイルサイズの上限の目安。\n「アップロード可能な最大ファイルサイズ」を超えない値を指定してください。")
        upload_split_form_layout.addRow("分割サイズ (1ファイルあたり):", self.split_chunk_size_spinbox)
        
        self.merge_pdf_parts_chk = QCheckBox("分割した場合、サーチャブルPDF部品を1つのファイルに結合する")
        self.merge_pdf_parts_chk.setChecked(current_ocr_options.get("merge_split_pdf_parts", True))
        self.merge_pdf_parts_chk.setToolTip("「大きなファイルを自動分割する」が有効な場合のみ適用されます。\nオフの場合、部品ごとのサーチャブルPDFがそれぞれ出力されます。")
        upload_split_form_layout.addRow(self.merge_pdf_parts_chk)
        
        upload_split_group.setLayout(upload_split_form_layout)
        main_layout.addWidget(upload_split_group)

        # --- OCRオプション（Cube API）グループ ---
        cube_ocr_group = QGroupBox("全文OCRオプション (Cube API)")
        cube_ocr_form_layout = QFormLayout()
        self.adjust_rotation_chk = QCheckBox("回転補正を行う"); self.adjust_rotation_chk.setChecked(current_ocr_options.get("adjust_rotation", 0) == 1); cube_ocr_form_layout.addRow(self.adjust_rotation_chk)
        self.character_extraction_chk = QCheckBox("文字ごとの情報を抽出する (文字尤度)"); self.character_extraction_chk.setChecked(current_ocr_options.get("character_extraction", 0) == 1); cube_ocr_form_layout.addRow(self.character_extraction_chk)
        self.concatenate_chk = QCheckBox("強制結合を行う (LLM用途推奨)"); self.concatenate_chk.setChecked(current_ocr_options.get("concatenate", 1) == 1); cube_ocr_form_layout.addRow(self.concatenate_chk)
        self.enable_checkbox_chk = QCheckBox("チェックボックスを認識する"); self.enable_checkbox_chk.setChecked(current_ocr_options.get("enable_checkbox", 0) == 1); cube_ocr_form_layout.addRow(self.enable_checkbox_chk)
        self.fulltext_output_mode_combo = QComboBox(); self.fulltext_output_mode_combo.addItems(["詳細情報を取得 (0)", "全文テキストのみ取得 (1)"]); self.fulltext_output_mode_combo.setCurrentIndex(current_ocr_options.get("fulltext_output_mode", 0)); cube_ocr_form_layout.addRow("テキスト出力モード:", self.fulltext_output_mode_combo)
        self.fulltext_linebreak_char_chk = QCheckBox("全文テキストにグループ区切り文字(\\n)を付加"); self.fulltext_linebreak_char_chk.setChecked(current_ocr_options.get("fulltext_linebreak_char", 0) == 1); cube_ocr_form_layout.addRow(self.fulltext_linebreak_char_chk)
        self.ocr_model_combo = QComboBox(); self.ocr_model_combo.addItems(["katsuji (印刷活字)", "all (手書き含む)", "mix (縦横混合モデル)"]); self.ocr_model_combo.setCurrentText(current_ocr_options.get("ocr_model", "katsuji")); cube_ocr_form_layout.addRow("OCRモデル選択:", self.ocr_model_combo)
        cube_ocr_group.setLayout(cube_ocr_form_layout)
        main_layout.addWidget(cube_ocr_group)

        # --- ファイル処理後サブフォルダ・出力設定グループ ---
        file_process_group = QGroupBox("ファイル処理後の出力と移動")
        file_process_form_layout = QFormLayout()
        file_actions_config = self.config.get("file_actions", {})
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
        ##### MODIFIED START #####
        self.collision_rename_radio = QRadioButton("リネームする (例: file.pdf --> file (1).pdf)")
        ##### MODIFIED END #####
        self.collision_skip_radio = QRadioButton("スキップ（移動しない）")
        collision_action = file_actions_config.get("collision_action", "rename")
        if collision_action == "overwrite": self.collision_overwrite_radio.setChecked(True)
        elif collision_action == "skip": self.collision_skip_radio.setChecked(True)
        else: self.collision_rename_radio.setChecked(True) # Default to rename
        
        collision_layout_v = QVBoxLayout()
        collision_layout_v.addWidget(self.collision_overwrite_radio)
        collision_layout_v.addWidget(self.collision_rename_radio)
        collision_layout_v.addWidget(self.collision_skip_radio)
        file_process_form_layout.addRow(collision_label, collision_layout_v)
        file_process_group.setLayout(file_process_form_layout)
        main_layout.addWidget(file_process_group)

        # --- ボタン ---
        button_layout = QHBoxLayout()
        self.save_btn = QPushButton("保存"); self.cancel_btn = QPushButton("キャンセル")
        self.save_btn.clicked.connect(self.on_save_settings)
        self.cancel_btn.clicked.connect(self.reject)
        button_layout.addStretch(); button_layout.addWidget(self.save_btn); button_layout.addWidget(self.cancel_btn)
        main_layout.addLayout(button_layout)

        self.setLayout(main_layout)
        self.toggle_split_options_enabled_state() # Set initial enabled state of split options

    def toggle_split_options_enabled_state(self):
        split_is_enabled = False
        if hasattr(self, 'split_enabled_chk'): 
            split_is_enabled = self.split_enabled_chk.isChecked()
            
        if hasattr(self, 'split_chunk_size_spinbox'):
            self.split_chunk_size_spinbox.setEnabled(split_is_enabled)
        
        if hasattr(self, 'merge_pdf_parts_chk'): 
            self.merge_pdf_parts_chk.setEnabled(split_is_enabled)


    def is_valid_folder_name(self, folder_name, field_label):
        if not folder_name: # Must not be empty
            QMessageBox.warning(self, "入力エラー", f"{field_label}は必須入力です。")
            return False
        if re.search(INVALID_FOLDER_NAME_CHARS_PATTERN, folder_name):
            QMessageBox.warning(self, "入力エラー", f"{field_label}に使用できない文字が含まれています。\n(使用不可: {INVALID_FOLDER_NAME_CHARS_PATTERN})")
            return False
        if folder_name == "." or folder_name == "..": # Cannot be . or ..
            QMessageBox.warning(self, "入力エラー", f"{field_label}に '.' や '..' は使用できません。")
            return False
        return True

    def on_save_settings(self):
        results_folder = self.results_folder_name_edit.text().strip()
        success_folder = self.success_folder_name_edit.text().strip()
        failure_folder = self.failure_folder_name_edit.text().strip()

        if not self.is_valid_folder_name(results_folder, "OCR結果サブフォルダ名"): return
        if not self.is_valid_folder_name(success_folder, "成功ファイル移動先サブフォルダ名"): return
        if not self.is_valid_folder_name(failure_folder, "失敗ファイル移動先サブフォルダ名"): return
        
        # Check for distinct folder names if moves are enabled
        if self.move_on_success_chk.isChecked() and self.move_on_failure_chk.isChecked() and success_folder == failure_folder:
            QMessageBox.warning(self, "入力エラー", "「成功ファイル移動先」と「失敗ファイル移動先」のサブフォルダ名は、互いに異なる名称にしてください。")
            return
        if self.move_on_success_chk.isChecked() and results_folder == success_folder:
             QMessageBox.warning(self, "入力エラー", "「OCR結果」と「成功ファイル移動先」のサブフォルダ名は、互いに異なる名称にしてください（移動が有効な場合）。")
             return
        if self.move_on_failure_chk.isChecked() and results_folder == failure_folder:
             QMessageBox.warning(self, "入力エラー", "「OCR結果」と「失敗ファイル移動先」のサブフォルダ名は、互いに異なる名称にしてください（移動が有効な場合）。")
             return


        if not self.base_uri_edit.text(): # Base URI is mandatory
            QMessageBox.warning(self, "入力エラー", "ベースURIは必須項目です。")
            return

        upload_max_size = self.upload_max_size_spinbox.value()
        split_enabled = self.split_enabled_chk.isChecked()
        split_chunk_size = self.split_chunk_size_spinbox.value()
        merge_pdf_parts = self.merge_pdf_parts_chk.isChecked()

        if split_enabled and split_chunk_size > upload_max_size:
            QMessageBox.warning(self, "入力エラー", 
                                "「分割サイズ」は、「アップロード可能な最大ファイルサイズ」以下の値に設定してください。")
            return
        
        self.config["api_key"] = self.api_key_edit.text()
        self.config["base_uri"] = self.base_uri_edit.text()
        
        current_api_type_options = self.config.setdefault("options", {}).setdefault(self.cube_options_key, {})
        current_api_type_options["max_files_to_process"] = self.max_files_spinbox.value()
        current_api_type_options["recursion_depth"] = self.recursion_depth_spinbox.value()
        current_api_type_options["adjust_rotation"] = 1 if self.adjust_rotation_chk.isChecked() else 0
        current_api_type_options["character_extraction"] = 1 if self.character_extraction_chk.isChecked() else 0
        current_api_type_options["concatenate"] = 1 if self.concatenate_chk.isChecked() else 0
        current_api_type_options["enable_checkbox"] = 1 if self.enable_checkbox_chk.isChecked() else 0
        current_api_type_options["fulltext_output_mode"] = self.fulltext_output_mode_combo.currentIndex()
        current_api_type_options["fulltext_linebreak_char"] = 1 if self.fulltext_linebreak_char_chk.isChecked() else 0
        current_api_type_options["ocr_model"] = self.ocr_model_combo.currentText().split(" ")[0] # Get the key like 'katsuji'

        current_api_type_options["upload_max_size_mb"] = upload_max_size
        current_api_type_options["split_large_files_enabled"] = split_enabled
        current_api_type_options["split_chunk_size_mb"] = split_chunk_size
        current_api_type_options["merge_split_pdf_parts"] = merge_pdf_parts
        
        file_actions = self.config.setdefault("file_actions", {})
        file_actions["results_folder_name"] = results_folder
        file_actions["move_on_success_enabled"] = self.move_on_success_chk.isChecked()
        file_actions["success_folder_name"] = success_folder
        file_actions["move_on_failure_enabled"] = self.move_on_failure_chk.isChecked()
        file_actions["failure_folder_name"] = failure_folder
        if self.collision_overwrite_radio.isChecked(): file_actions["collision_action"] = "overwrite"
        elif self.collision_skip_radio.isChecked(): file_actions["collision_action"] = "skip"
        else: file_actions["collision_action"] = "rename" # Default
        if self.output_format_json_only_radio.isChecked(): file_actions["output_format"] = "json_only"
        elif self.output_format_pdf_only_radio.isChecked(): file_actions["output_format"] = "pdf_only"
        else: file_actions["output_format"] = "both" # Default

        ConfigManager.save(self.config)
        self.accept() # Close dialog with QDialog.Accepted status