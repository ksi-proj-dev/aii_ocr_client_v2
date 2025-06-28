# AI inside OCR API V2 対応：OCR Client Windows デスクトップ アプリケーション

## Git bash で venv 環境を使う

- $ cd aii_ocr_client_v2
- $ python -m venv .venv
- $ cat /c/Users/{ユーザ名}/.bashrc

```
# bash 起動時、自動的に venv を有効化
if [ -f "./.venv/Scripts/activate" ]; then
    source ./.venv/Scripts/activate
fi
```

- ターミナルで bash を起動すると自動的に venv が有効になり、プロンプトに "(.venv)" が表示される。

```
(.venv)
{作業ディレクトリ}/aii_ocr_client_v2
$
```
