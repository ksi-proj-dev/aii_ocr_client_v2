import json
from PyQt6.QtWidgets import (
    QDialog, QFormLayout, QLineEdit, QComboBox, QCheckBox, QHBoxLayout,
    QPushButton, QMessageBox, QGroupBox # QGroupBox を追加
)
from config_manager import ConfigManager

class OptionDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("オプション設定 (AI inside Cube)") # ウィンドウタイトルを変更
        self.config = ConfigManager().load()
        # Cube API用のオプションキーを特定 (config_manager.pyのapi_typeに依存)
        self.cube_options_key = self.config.get("api_type", "cube_fullocr") # デフォルトをcube_fullocrに
        self.init_ui()
        self.resize(450, 400) # ウィンドウサイズを調整

    def init_ui(self):
        layout = QFormLayout()

        # --- 基本設定 ---
        basic_group = QGroupBox("基本設定")
        basic_layout = QFormLayout()

        self.api_key_edit = QLineEdit(self.config.get("api_key", ""))
        basic_layout.addRow("APIキー（必須）", self.api_key_edit)

        # base_uriのデフォルト値をCube用に変更
        default_base_uri = "http://localhost/api/v1/domains/aiinside/endpoints/"
        self.base_uri_edit = QLineEdit(self.config.get("base_uri", default_base_uri))
        basic_layout.addRow("ベースURI（必須）", self.base_uri_edit)

        self.api_type_edit = QLineEdit(self.config.get("api_type", "cube_fullocr")) # load時に設定されるはず
        self.api_type_edit.setReadOnly(True)
        self.api_type_edit.setStyleSheet("background-color: lightgray;")
        basic_layout.addRow("API種別", self.api_type_edit)

        self.endpoints_edit = QLineEdit()
        # configから読み込まれたエンドポイント情報を表示
        endpoints_text = json.dumps(self.config.get("endpoints", {}).get(self.cube_options_key, {}), indent=2, ensure_ascii=False)
        self.endpoints_edit.setText(endpoints_text)
        self.endpoints_edit.setReadOnly(True)
        self.endpoints_edit.setStyleSheet("background-color: lightgray;")
        self.endpoints_edit.setMinimumHeight(60) # 表示エリアを少し広げる
        basic_layout.addRow("エンドポイント情報", self.endpoints_edit)
        basic_group.setLayout(basic_layout)
        layout.addRow(basic_group)

        # --- Cube API OCRオプション ---
        cube_ocr_group = QGroupBox("全文OCRオプション (Cube API)")
        cube_ocr_layout = QFormLayout()

        # config.jsonのoptions.<api_type>から設定を読み込む
        current_options = self.config.get("options", {}).get(self.cube_options_key, {})

        self.adjust_rotation_chk = QCheckBox("回転補正を行う")
        self.adjust_rotation_chk.setChecked(current_options.get("adjust_rotation", 0) == 1)
        self.adjust_rotation_chk.setToolTip("0=OFF, 1=ON (補正可能範囲は90度単位, ±5度程度まで)")
        cube_ocr_layout.addRow(self.adjust_rotation_chk)

        self.character_extraction_chk = QCheckBox("文字ごとの情報を抽出する (文字尤度)")
        self.character_extraction_chk.setChecked(current_options.get("character_extraction", 0) == 1)
        self.character_extraction_chk.setToolTip("0=OFF, 1=ON (ONにすると1文字ずつの情報が追加)")
        cube_ocr_layout.addRow(self.character_extraction_chk)

        self.concatenate_chk = QCheckBox("強制結合を行う (LLM用途推奨)")
        self.concatenate_chk.setChecked(current_options.get("concatenate", 1) == 1) # Cube APIデフォルトは1
        self.concatenate_chk.setToolTip("0=OFF (単語で区切る), 1=ON (できるだけ文章として扱う)")
        cube_ocr_layout.addRow(self.concatenate_chk)

        self.enable_checkbox_chk = QCheckBox("チェックボックスを認識する")
        self.enable_checkbox_chk.setChecked(current_options.get("enable_checkbox", 0) == 1)
        self.enable_checkbox_chk.setToolTip("0=OFF, 1=ON (ONにすると処理時間が増大する可能性)")
        cube_ocr_layout.addRow(self.enable_checkbox_chk)

        self.fulltext_output_mode_combo = QComboBox()
        self.fulltext_output_mode_combo.addItems(["詳細情報を取得 (0)", "全文テキストのみ取得 (1)"])
        self.fulltext_output_mode_combo.setCurrentIndex(current_options.get("fulltext_output_mode", 0))
        self.fulltext_output_mode_combo.setToolTip("Cube API 'fulltext' パラメータ: 0=詳細, 1=fulltextのみ")
        cube_ocr_layout.addRow("テキスト出力モード:", self.fulltext_output_mode_combo)

        self.fulltext_linebreak_char_chk = QCheckBox("全文テキストにグループ区切り文字(\\n)を付加する")
        self.fulltext_linebreak_char_chk.setChecked(current_options.get("fulltext_linebreak_char", 0) == 1)
        self.fulltext_linebreak_char_chk.setToolTip("Cube API 'fulltext_linebreak' パラメータ: 0=区切り文字なし, 1=\\nを付加")
        cube_ocr_layout.addRow(self.fulltext_linebreak_char_chk)

        self.ocr_model_combo = QComboBox()
        self.ocr_model_combo.addItems(["katsuji (印刷活字)", "all (手書き含む)", "mix (縦横混合モデル)"])
        self.ocr_model_combo.setCurrentText(current_options.get("ocr_model", "katsuji"))
        self.ocr_model_combo.setToolTip("Cube API 'horizontal_ocr_model' パラメータ")
        cube_ocr_layout.addRow("OCRモデル選択:", self.ocr_model_combo)

        cube_ocr_group.setLayout(cube_ocr_layout)
        layout.addRow(cube_ocr_group)


        # --- ボタン ---
        button_layout = QHBoxLayout()
        save_btn = QPushButton("保存")
        cancel_btn = QPushButton("キャンセル")
        save_btn.clicked.connect(self.save)
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(save_btn)
        button_layout.addWidget(cancel_btn)
        layout.addRow(button_layout)

        self.setLayout(layout)

    def save(self):
        if not self.api_key_edit.text() or not self.base_uri_edit.text():
            QMessageBox.warning(self, "入力エラー", "APIキーとベースURIは必須項目です。")
            return

        self.config["api_key"] = self.api_key_edit.text()
        self.config["base_uri"] = self.base_uri_edit.text()

        # optionsセクションがなければ作成
        self.config.setdefault("options", {})
        # API種別に応じたオプションキー (例: "cube_fullocr") で設定を保存
        self.config["options"].setdefault(self.cube_options_key, {})
        cube_opts = self.config["options"][self.cube_options_key]

        cube_opts["adjust_rotation"] = 1 if self.adjust_rotation_chk.isChecked() else 0
        cube_opts["character_extraction"] = 1 if self.character_extraction_chk.isChecked() else 0
        cube_opts["concatenate"] = 1 if self.concatenate_chk.isChecked() else 0
        cube_opts["enable_checkbox"] = 1 if self.enable_checkbox_chk.isChecked() else 0
        cube_opts["fulltext_output_mode"] = self.fulltext_output_mode_combo.currentIndex() # 0 or 1
        cube_opts["fulltext_linebreak_char"] = 1 if self.fulltext_linebreak_char_chk.isChecked() else 0
        cube_opts["ocr_model"] = self.ocr_model_combo.currentText().split(" ")[0] # "katsuji", "all", "mix" を取得

        ConfigManager().save(self.config)
        QMessageBox.information(self, "保存完了", "設定を保存しました。") # 保存完了メッセージ
        self.accept()