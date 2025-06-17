# file_model.py

from dataclasses import dataclass
from typing import Optional

@dataclass
class FileInfo:
    no: int
    path: str
    name: str
    size: int
    status: str
    ocr_engine_status: str
    job_id: Optional[str] = None
    ocr_result_summary: str = ""
    json_status: str = "-"
    auto_csv_status: str = "-"
    searchable_pdf_status: str = "-"
    page_count: Optional[int] = None
    is_checked: bool = True
