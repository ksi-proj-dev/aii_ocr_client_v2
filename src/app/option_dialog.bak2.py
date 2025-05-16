import json
import os # os.path.join を使う可能性のため (今回は未使用)
from PyQt6.QtWidgets import (
    QDialog, QFormLayout, QLineEdit, QComboBox, QCheckBox, QHBoxLayout,
    QPushButton, QMessageBox, QGroupBox, QSpinBox, QRadioButton, QVBoxLayout, QLabel, # 追加
    QFileDialog # フォルダ選択ダイアログ用
)
from config_manager import ConfigManager

class OptionDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("オプション設定 (AI inside Cube)")
        self.config = ConfigManager().load()
        self.cube_options_key = self.config.get("api_type", "cube_fullocr")
        self.init_ui()
        self.resize(500, 600) # ウィンドウサイズを調整 (縦長に)

    def init_ui(self):
        main_layout = QVBoxLayout(self) # QVBoxLayout をメインレイアウトに

        # --- 1. 基本設定グループ ---
        basic_group = QGroupBox("基本設定")
        basic_form_layout = QFormLayout() # QFormLayoutをグループ内で使用

        self.api_key_edit = QLineEdit(self.config.get("api_key", ""))
        basic_form_layout.addRow("APIキー:", self.api_key_edit)

        default_base_uri = "http://localhost/api/v1/domains/aiinside/endpoints/"
        self.base_uri_edit = QLineEdit(self.config.get("base_uri", default_base_uri))
        basic_form_layout.addRow("ベースURI:", self.base_uri_edit)

        self.api_type_edit = QLineEdit(self.cube_options_key)
        self.api_type_edit.setReadOnly(True)
        self.api_type_edit.setStyleSheet("background-color: lightgray;")
        basic_form_layout.addRow("API種別:", self.api_type_edit)

        self.endpoints_edit = QLineEdit()
        endpoints_text = json.dumps(self.config.get("endpoints", {}).get(self.cube_options_key, {}), indent=2, ensure_ascii=False)
        self.endpoints_edit.setText(endpoints_text)
        self.endpoints_edit.setReadOnly(True)
        self.endpoints_edit.setStyleSheet("background-color: lightgray;")
        self.endpoints_edit.setMinimumHeight(60)
        basic_form_layout.addRow("エンドポイント情報:", self.endpoints_edit)
        basic_group.setLayout(basic_form_layout)
        main_layout.addWidget(basic_group)

        # --- 2. ファイル検索設定グループ ---
        file_search_group = QGroupBox("ファイル検索設定")
        file_search_form_layout = QFormLayout()

        self.max_files_spinbox = QSpinBox()
        self.max_files_spinbox.setRange(1, 999) # 1-999
        self.max_files_spinbox.setValue(self.config.get("options", {}).get(self.cube_options_key, {}).get("max_files_to_process", 100))
        self.max_files_spinbox.setToolTip("一度に処理する最大ファイル数 (1-999)")
        file_search_form_layout.addRow("最大処理ファイル数:", self.max_files_spinbox)

        self.recursion_depth_spinbox = QSpinBox()
        self.recursion_depth_spinbox.setRange(1, 10) # 1-10
        self.recursion_depth_spinbox.setValue(self.config.get("options", {}).get(self.cube_options_key, {}).get("recursion_depth", 5))
        self.recursion_depth_spinbox.setToolTip("入力フォルダの再帰検索の深さ (1でカレントのみ, 最大10)")
        file_search_form_layout.addRow("再帰検索の深さ:", self.recursion_depth_spinbox)
        file_search_group.setLayout(file_search_form_layout)
        main_layout.addWidget(file_search_group)

        # --- 3. OCRオプション（Cube API）グループ ---
        cube_ocr_group = QGroupBox("全文OCRオプション (Cube API)")
        cube_ocr_form_layout = QFormLayout() # QFormLayoutを使用

        current_ocr_options = self.config.get("options", {}).get(self.cube_options_key, {})

        self.adjust_rotation_chk = QCheckBox("回転補正を行う")
        self.adjust_rotation_chk.setChecked(current_ocr_options.get("adjust_rotation", 0) == 1)
        cube_ocr_form_layout.addRow(self.adjust_rotation_chk)

        self.character_extraction_chk = QCheckBox("文字ごとの情報を抽出する (文字尤度)")
        self.character_extraction_chk.setChecked(current_ocr_options.get("character_extraction", 0) == 1)
        cube_ocr_form_layout.addRow(self.character_extraction_chk)

        self.concatenate_chk = QCheckBox("強制結合を行う (LLM用途推奨)")
        self.concatenate_chk.setChecked(current_ocr_options.get("concatenate", 1) == 1)
        cube_ocr_form_layout.addRow(self.concatenate_chk)

        self.enable_checkbox_chk = QCheckBox("チェックボックスを認識する")
        self.enable_checkbox_chk.setChecked(current_ocr_options.get("enable_checkbox", 0) == 1)
        cube_ocr_form_layout.addRow(self.enable_checkbox_chk)

        self.fulltext_output_mode_combo = QComboBox()
        self.fulltext_output_mode_combo.addItems(["詳細情報を取得 (0)", "全文テキストのみ取得 (1)"])
        self.fulltext_output_mode_combo.setCurrentIndex(current_ocr_options.get("fulltext_output_mode", 0))
        cube_ocr_form_layout.addRow("テキスト出力モード:", self.fulltext_output_mode_combo)

        self.fulltext_linebreak_char_chk = QCheckBox("全文テキストにグループ区切り文字(\\n)を付加")
        self.fulltext_linebreak_char_chk.setChecked(current_ocr_options.get("fulltext_linebreak_char", 0) == 1)
        cube_ocr_form_layout.addRow(self.fulltext_linebreak_char_chk)

        self.ocr_model_combo = QComboBox()
        self.ocr_model_combo.addItems(["katsuji (印刷活字)", "all (手書き含む)", "mix (縦横混合モデル)"])
        self.ocr_model_combo.setCurrentText(current_ocr_options.get("ocr_model", "katsuji"))
        cube_ocr_form_layout.addRow("OCRモデル選択:", self.ocr_model_combo)
        cube_ocr_group.setLayout(cube_ocr_form_layout)
        main_layout.addWidget(cube_ocr_group)

        # --- 4. ファイル移動設定グループ ---
        file_move_group = QGroupBox("ファイル移動設定")
        file_move_form_layout = QFormLayout()

        # OCR成功時のファイル移動
        self.move_on_success_chk = QCheckBox("OCR成功時にファイルを移動する")
        self.move_on_success_chk.setChecked(self.config.get("file_actions", {}).get("move_on_success_enabled", False))
        file_move_form_layout.addRow(self.move_on_success_chk)

        self.success_folder_edit = QLineEdit(self.config.get("file_actions", {}).get("success_folder", "OCR成功"))
        success_folder_button = QPushButton("選択...")
        success_folder_button.clicked.connect(lambda: self.select_folder_for_edit(self.success_folder_edit, "成功ファイル移動先フォルダを選択"))
        success_folder_layout = QHBoxLayout()
        success_folder_layout.addWidget(self.success_folder_edit)
        success_folder_layout.addWidget(success_folder_button)
        file_move_form_layout.addRow("成功ファイル移動先:", success_folder_layout)

        # OCR失敗時のファイル移動
        self.move_on_failure_chk = QCheckBox("OCR失敗時にファイルを移動する")
        self.move_on_failure_chk.setChecked(self.config.get("file_actions", {}).get("move_on_failure_enabled", False))
        file_move_form_layout.addRow(self.move_on_failure_chk)

        self.failure_folder_edit = QLineEdit(self.config.get("file_actions", {}).get("failure_folder", "OCR失敗"))
        failure_folder_button = QPushButton("選択...")
        failure_folder_button.clicked.connect(lambda: self.select_folder_for_edit(self.failure_folder_edit, "失敗ファイル移動先フォルダを選択"))
        failure_folder_layout = QHBoxLayout()
        failure_folder_layout.addWidget(self.failure_folder_edit)
        failure_folder_layout.addWidget(failure_folder_button)
        file_move_form_layout.addRow("失敗ファイル移動先:", failure_folder_layout)

        # ファイル名衝突時の処理
        collision_label = QLabel("ファイル名衝突時の処理:")
        self.collision_overwrite_radio = QRadioButton("上書きする")
        self.collision_rename_radio = QRadioButton("リネームする (例: file (1).txt)")
        self.collision_skip_radio = QRadioButton("スキップ（移動しない）")

        collision_action = self.config.get("file_actions", {}).get("collision_action", "rename") # デフォルトはリネーム
        if collision_action == "overwrite":
            self.collision_overwrite_radio.setChecked(True)
        elif collision_action == "skip":
            self.collision_skip_radio.setChecked(True)
        else: # "rename" または不明な値の場合
            self.collision_rename_radio.setChecked(True)

        collision_layout = QVBoxLayout() # ラジオボタンを縦に並べる
        collision_layout.addWidget(self.collision_overwrite_radio)
        collision_layout.addWidget(self.collision_rename_radio)
        collision_layout.addWidget(self.collision_skip_radio)
        file_move_form_layout.addRow(collision_label, collision_layout)
        file_move_group.setLayout(file_move_form_layout)
        main_layout.addWidget(file_move_group)

        # --- ボタン ---
        button_layout = QHBoxLayout()
        save_btn = QPushButton("保存")
        cancel_btn = QPushButton("キャンセル")
        save_btn.clicked.connect(self.save_settings) # メソッド名変更
        cancel_btn.clicked.connect(self.reject)
        button_layout.addStretch() # ボタンを右寄せ
        button_layout.addWidget(save_btn)
        button_layout.addWidget(cancel_btn)
        main_layout.addLayout(button_layout)

        self.setLayout(main_layout)

    def select_folder_for_edit(self, line_edit_widget, dialog_title):
        """指定されたラインエディットウィジェットにフォルダ選択ダイアログの結果を設定する"""
        current_path = line_edit_widget.text()
        # QFileDialogに渡す初期パスは既存のパスか、なければユーザーのホームディレクトリ
        # ただし、デフォルトの "OCR成功" などはパスではないので、その場合はホームディレクトリ
        if not os.path.isdir(current_path) and not os.path.isabs(current_path) : # 相対パスや単なる名前の場合
            initial_dir = self.config.get("last_result_dir", os.path.expanduser("~")) # 結果フォルダを基準に
        else:
            initial_dir = current_path or os.path.expanduser("~")

        folder = QFileDialog.getExistingDirectory(self, dialog_title, initial_dir)
        if folder:
            line_edit_widget.setText(folder)


    def save_settings(self): # メソッド名変更 save -> save_settings
        # 基本設定のバリデーション
        if not self.api_key_edit.text() and not self.api_client.dummy_mode: # ダミーモードでない場合のみAPIキー必須
             # ダミーモードの場合はAPIキーがなくても動作するようにするため、このチェックは条件付きにする
             # self.api_client は MainWindow から渡す必要がある、またはここでインスタンス化？
             # → OptionDialogは独立してConfigを扱うので、ここではAPIキーの有無だけチェックする
            pass # APIキーの必須チェックは実際のAPIコール前に行うのが適切かもしれない

        if not self.base_uri_edit.text():
            QMessageBox.warning(self, "入力エラー", "ベースURIは必須項目です。")
            return

        # 設定を self.config に保存
        self.config["api_key"] = self.api_key_edit.text()
        self.config["base_uri"] = self.base_uri_edit.text()

        # optionsセクションがなければ作成し、API種別キーもなければ作成
        self.config.setdefault("options", {}).setdefault(self.cube_options_key, {})
        cube_opts = self.config["options"][self.cube_options_key]

        # ファイル検索設定
        cube_opts["max_files_to_process"] = self.max_files_spinbox.value()
        cube_opts["recursion_depth"] = self.recursion_depth_spinbox.value()

        # OCRオプション
        cube_opts["adjust_rotation"] = 1 if self.adjust_rotation_chk.isChecked() else 0
        cube_opts["character_extraction"] = 1 if self.character_extraction_chk.isChecked() else 0
        cube_opts["concatenate"] = 1 if self.concatenate_chk.isChecked() else 0
        cube_opts["enable_checkbox"] = 1 if self.enable_checkbox_chk.isChecked() else 0
        cube_opts["fulltext_output_mode"] = self.fulltext_output_mode_combo.currentIndex()
        cube_opts["fulltext_linebreak_char"] = 1 if self.fulltext_linebreak_char_chk.isChecked() else 0
        cube_opts["ocr_model"] = self.ocr_model_combo.currentText().split(" ")[0]

        # ファイル移動設定
        self.config.setdefault("file_actions", {})
        file_actions = self.config["file_actions"]
        file_actions["move_on_success_enabled"] = self.move_on_success_chk.isChecked()
        file_actions["success_folder"] = self.success_folder_edit.text()
        file_actions["move_on_failure_enabled"] = self.move_on_failure_chk.isChecked()
        file_actions["failure_folder"] = self.failure_folder_edit.text()

        if self.collision_overwrite_radio.isChecked():
            file_actions["collision_action"] = "overwrite"
        elif self.collision_skip_radio.isChecked():
            file_actions["collision_action"] = "skip"
        else: # リネームがデフォルト
            file_actions["collision_action"] = "rename"

        ConfigManager().save(self.config)
        QMessageBox.information(self, "保存完了", "設定を保存しました。")
        self.accept()