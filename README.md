# AI inside OCR API V2 対応：OCR Client Windows デスクトップ アプリケーション

## Git bash で venv 環境を使う

- $ cd aii_ocr_client_v2
- $ python -m venv .venv
- $ cat /c/Users/{ユーザ名}/.bashrc

```
# Windows環境下で Git bash 起動時、自動的に venv を有効化
# すでに VIRTUAL_ENV が設定されていなければ自動有効化
if [ -z "$VIRTUAL_ENV" ] && [ -f "./.venv/Scripts/activate" ]; then
    source ./.venv/Scripts/activate
fi
```

- ターミナルで Git bash を起動すると自動的に venv が有効になり、プロンプトに "(.venv)" が表示される。

```
(.venv)
{作業ディレクトリ}/aii_ocr_client_v2
$
```

## Python パッケージ一覧

### インストール済みパッケージ一覧を作成

```
- $ cd aii_ocr_client_v2/src
- $ pip freeze > requirements.txt
```

### 一覧を元にパッケージインストール

```
- $ cd aii_ocr_client_v2/src
- $ pip install -r requirements.txt
```
