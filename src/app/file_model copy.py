# file_model.py

from dataclasses import dataclass, field
from typing import Optional # ★ Optionalをインポート

@dataclass
class FileInfo:
    no: int
    path: str
    name: str
    size: int
    status: str
    ocr_engine_status: str
    ocr_result_summary: str = ""
    json_status: str = "-"
    searchable_pdf_status: str = "-"
    page_count: Optional[int] = None # ★★★ ページ数フィールドを追加 ★★★
    is_checked: bool = True