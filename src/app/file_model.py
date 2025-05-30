# file_model.py

from dataclasses import dataclass, field

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
    is_checked: bool = True
    # 必要に応じて他のフィールドも追加できます
    # 例えば、エラーメッセージ専用のフィールドなど
    # error_message: Optional[str] = None # Python 3.9+ なら typing.Optional