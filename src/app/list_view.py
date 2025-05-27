from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem, QHeaderView
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor # QColorをインポート
from config_manager import ConfigManager

class NumericTableWidgetItem(QTableWidgetItem):
    def __init__(self, text, sort_key_value):
        super().__init__(text)
        self.sort_key_value = sort_key_value

    def __lt__(self, other):
        if isinstance(other, NumericTableWidgetItem):
            return self.sort_key_value < other.sort_key_value
        return super().__lt__(other)

class ListView(QWidget):
    def __init__(self, initial_file_list_data=None):
        super().__init__()
        self.config = ConfigManager.load()
        self.file_list_data = initial_file_list_data or []
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        # --- ここから変更: 見出し変更 ---
        self.table.setHorizontalHeaderLabels([
            "No", "ファイル名", "ステータス", "OCR結果", # 「OCR結果概要」から変更
            "JSON", "サーチャブルPDF", "サイズ(MB)"  # 「JSON結果」から「JSON」に、「サイズ(KB)」から「サイズ(MB)」に変更
        ])
        # --- ここまで変更 ---
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        # --- ここから変更: パディング変更 ---
        self.table.setStyleSheet("""
            QHeaderView::section {
                background-color: #f0f0f0; padding: 2px; border: 1px solid #d0d0d0; /* padding変更 */
            }
            QTableWidget {
                gridline-color: #e0e0e0; alternate-background-color: #f9f9f9; background-color: white;
            }
            QTableWidget::item { /* データ行のパディングを0に */
                padding: 0px; 
            }
        """)
        # --- ここまで変更 ---
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.setSortingEnabled(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        layout.addWidget(self.table)
        self.setLayout(layout)

        self.populate_table(self.file_list_data)
        self.apply_sort_order()

    def populate_table(self, files_data):
        self.table.setUpdatesEnabled(False)
        current_sorting_enabled_state = self.table.isSortingEnabled()
        self.table.setSortingEnabled(False)
        try:
            self.file_list_data = files_data
            self.table.setRowCount(0)
            self.table.setRowCount(len(self.file_list_data))

            red_color = QColor("red") # エラー表示用の色

            for idx, file_info in enumerate(self.file_list_data):
                # No (変更なし)
                no_value = file_info.get("no", idx + 1)
                no_item = NumericTableWidgetItem(str(no_value), no_value)
                no_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(idx, 0, no_item)

                # ファイル名 (変更なし)
                self.table.setItem(idx, 1, QTableWidgetItem(file_info.get("name", "")))
                
                # ステータス (エラー時赤色)
                status_text = file_info.get("status", "")
                status_item = QTableWidgetItem(status_text)
                if "失敗" in status_text or "エラー" in status_text:
                    status_item.setForeground(red_color)
                self.table.setItem(idx, 2, status_item)
                
                # OCR結果 (変更なし、列名変更はヘッダーで対応済み)
                self.table.setItem(idx, 3, QTableWidgetItem(file_info.get("ocr_result_summary", "")))
                
                # JSON結果 (エラー時赤色)
                json_status_text = file_info.get("json_status", "-")
                json_status_item = QTableWidgetItem(json_status_text)
                if "失敗" in json_status_text or "エラー" in json_status_text:
                    json_status_item.setForeground(red_color)
                self.table.setItem(idx, 4, json_status_item)
                
                # サーチャブルPDF (エラー時赤色)
                pdf_status_text = file_info.get("searchable_pdf_status", "-")
                pdf_status_item = QTableWidgetItem(pdf_status_text)
                if "失敗" in pdf_status_text or "エラー" in pdf_status_text:
                    pdf_status_item.setForeground(red_color)
                self.table.setItem(idx, 5, pdf_status_item)
                
                # --- ここから変更: サイズ(MB)表示 ---
                size_bytes = file_info.get("size", 0)
                size_mb = size_bytes / (1024 * 1024)
                # 小数点以下3桁まで表示、ただし不要な0は表示しないように調整も可能だが、まずは固定桁で
                size_mb_display_text = f"{size_mb:,.3f} MB" 
                size_item = NumericTableWidgetItem(size_mb_display_text, size_bytes) # ソートキーはバイトのまま
                size_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(idx, 6, size_item)
                # --- ここまで変更 ---

            self.restore_column_widths()
        finally:
            self.table.setSortingEnabled(current_sorting_enabled_state)
            self.table.setUpdatesEnabled(True)

    def update_files(self, files_data):
        self.populate_table(files_data)

    def restore_column_widths(self):
        # デフォルト列幅の調整 (「OCR結果」が短くなった分、「ファイル名」や「OCR結果」自体に割り振るなど)
        default_widths = [50, 280, 100, 270, 100, 120, 100] # No, Name, Status, OCR結果, JSON, PDF, Size(MB)
        widths = self.config.get("column_widths", default_widths)
        if len(widths) != self.table.columnCount():
            widths = default_widths
        for i, width in enumerate(widths):
            if 0 <= i < self.table.columnCount():
                self.table.setColumnWidth(i, width)

    def apply_sort_order(self):
        # (変更なし)
        if not (hasattr(self, 'table') and self.table and self.table.rowCount() > 0): return
        default_sort_column = 0; default_sort_order_str = "asc"
        last_sort_config = self.config.get("sort_order", {"column": default_sort_column, "order": default_sort_order_str})
        column_to_sort = last_sort_config.get("column", default_sort_column); order_str = last_sort_config.get("order", default_sort_order_str)
        sort_order_qt = Qt.SortOrder.AscendingOrder if order_str == "asc" else Qt.SortOrder.DescendingOrder
        if 0 <= column_to_sort < self.table.columnCount():
            current_sorting_enabled = self.table.isSortingEnabled(); self.table.setSortingEnabled(True) 
            self.table.sortItems(column_to_sort, sort_order_qt)
            if not current_sorting_enabled : self.table.setSortingEnabled(False)

    def get_column_widths(self):
        # (変更なし、ただしデフォルト値は更新)
        if hasattr(self, 'table') and self.table and self.table.columnCount() > 0:
            return [self.table.columnWidth(i) for i in range(self.table.columnCount())]
        return self.config.get("column_widths", [50, 280, 100, 270, 100, 120, 100])

    def get_sort_order(self):
        # (変更なし)
        if hasattr(self, 'table') and self.table and self.table.horizontalHeader().isSortIndicatorShown():
            header = self.table.horizontalHeader(); return {"column": header.sortIndicatorSection(), "order": "asc" if header.sortIndicatorOrder() == Qt.SortOrder.AscendingOrder else "desc"}
        return self.config.get("sort_order", {"column": 0, "order": "asc"})