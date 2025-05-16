import os
import json

CONFIG_PATH = os.path.join('config', 'config.json') # 保存先は変更なし

# Cube API用の内部設定
INTERNAL_CONFIG = {
    "api_type": "cube_fullocr",  # アプリケーションが使用するAPIの種別を明示
    "endpoints": {
        "cube_fullocr": {  # api_typeとキーを合わせる
            "read_document": "/fullocr-read-document",         # 全文OCR実行（JSON結果）
            "make_searchable_pdf": "/make-searchable-pdf"  # サーチャブルPDF作成
        }
        # DX Suite API V2用の "fullocr", "atypical", "standard" は削除
    }
}

class ConfigManager:
    @staticmethod
    def load():
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                try:
                    user_config = json.load(f)
                except json.JSONDecodeError:
                    # JSONデコードエラーの場合、空の辞書として扱い、後でINTERNAL_CONFIGで上書き
                    user_config = {}
                    print(f"警告: {CONFIG_PATH} の読み込みに失敗しました。JSON形式が無効です。") # ログやprintで通知
        else:
            user_config = {}

        # INTERNAL_CONFIG の api_type と endpoints は外部設定では変更不可。
        # これにより、アプリケーションが意図するAPI種別とエンドポイント定義を強制適用。
        user_config["api_type"] = INTERNAL_CONFIG["api_type"]
        user_config["endpoints"] = INTERNAL_CONFIG["endpoints"]

        # Cube API用のデフォルトオプションをuser_configに設定 (config.jsonにoptions.<api_type>がない場合など)
        # option_dialog.pyでの読み込みと重複する可能性があるため、どちらで主導権を持つか注意
        # ここでは、config.jsonに存在しない場合に限り、基本的な構造だけ用意する形も考えられる
        # 今回はoption_dialog.pyでデフォルト値を扱っているので、ここでは特に追加しない
        # ただし、options.<api_type> のキーが存在しない場合の初期化はあっても良いかもしれない
        if "options" not in user_config:
            user_config["options"] = {}
        if INTERNAL_CONFIG["api_type"] not in user_config["options"]:
             # option_dialog.pyで設定されるデフォルト値に任せるため、ここでは空の辞書または
             # config.jsonの提案で示したような最低限のデフォルト構造を用意してもよい
            user_config["options"][INTERNAL_CONFIG["api_type"]] = {
                "adjust_rotation": 0,
                "character_extraction": 0,
                "concatenate": 1,
                "enable_checkbox": 0,
                "fulltext_output_mode": 0,
                "fulltext_linebreak_char": 0,
                "ocr_model": "katsuji"
            }


        return user_config

    @staticmethod
    def save(config):
        # 保存前に、api_type と endpoints が INTERNAL_CONFIG の値で上書きされていることを保証
        # (通常、load時に上書きされているが、念のため)
        config["api_type"] = INTERNAL_CONFIG["api_type"]
        config["endpoints"] = INTERNAL_CONFIG["endpoints"]

        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)