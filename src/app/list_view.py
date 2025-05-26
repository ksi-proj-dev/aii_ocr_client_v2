from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem, QHeaderView
from PyQt6.QtCore import Qt
from config_manager import ConfigManager

class NumericTableWidgetItem(QTableWidgetItem):
    """数値を正しくソートするためのカスタムQTableWidgetItem"""
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
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels([
            "No", "ファイル名", "ステータス", "OCR結果概要", "サーチャブルPDF", "サイズ(KB)"
        ])
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet("""
            QHeaderView::section {
                background-color: #f0f0f0; padding: 4px; border: 1px solid #d0d0d0;
            }
            QTableWidget {
                gridline-color: #e0e0e0; alternate-background-color: #f9f9f9; background-color: white;
            }
        """)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.setSortingEnabled(True)

        # --- ここから変更 ---
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers) # 編集を無効化
        # --- ここまで変更 ---

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

            for idx, file_info in enumerate(self.file_list_data):
                no_value = file_info.get("no", idx + 1)
                no_item = NumericTableWidgetItem(str(no_value), no_value)
                no_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(idx, 0, no_item)

                self.table.setItem(idx, 1, QTableWidgetItem(file_info.get("name", "")))
                
                status_item = QTableWidgetItem(file_info.get("status", ""))
                self.table.setItem(idx, 2, status_item)
                
                self.table.setItem(idx, 3, QTableWidgetItem(file_info.get("ocr_result_summary", "")))
                self.table.setItem(idx, 4, QTableWidgetItem(file_info.get("searchable_pdf_status", "-")))
                
                size_bytes = file_info.get("size", 0)
                size_kb_display_text = f"{size_bytes / 1024:,.1f} KB"
                size_item = NumericTableWidgetItem(size_kb_display_text, size_bytes)
                size_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(idx, 5, size_item)
            self.restore_column_widths()
        finally:
            self.table.setSortingEnabled(current_sorting_enabled_state)
            self.table.setUpdatesEnabled(True)

    def update_files(self, files_data):
        self.populate_table(files_data)

    def restore_column_widths(self):
        default_widths = [50, 300, 120, 350, 120, 100]
        widths = self.config.get("column_widths", default_widths)
        if len(widths) != self.table.columnCount():
            widths = default_widths
        for i, width in enumerate(widths):
            if 0 <= i < self.table.columnCount():
                self.table.setColumnWidth(i, width)

    def apply_sort_order(self):
        if not (hasattr(self, 'table') and self.table and self.table.rowCount() > 0):
            return
        default_sort_column = 0 
        default_sort_order_str = "asc"
        last_sort_config = self.config.get("sort_order", 
                                    {"column": default_sort_column, "order": default_sort_order_str})
        column_to_sort = last_sort_config.get("column", default_sort_column)
        order_str = last_sort_config.get("order", default_sort_order_str)
        sort_order_qt = Qt.SortOrder.AscendingOrder if order_str == "asc" else Qt.SortOrder.DescendingOrder
        if 0 <= column_to_sort < self.table.columnCount():
            current_sorting_enabled = self.table.isSortingEnabled()
            self.table.setSortingEnabled(True) 
            self.table.sortItems(column_to_sort, sort_order_qt)
            if not current_sorting_enabled : self.table.setSortingEnabled(False)

    def get_column_widths(self):
        if hasattr(self, 'table') and self.table and self.table.columnCount() > 0:
            return [self.table.columnWidth(i) for i in range(self.table.columnCount())]
        return self.config.get("column_widths", [50, 300, 120, 350, 120, 100])

    def get_sort_order(self):
        if hasattr(self, 'table') and self.table and self.table.horizontalHeader().isSortIndicatorShown():
            header = self.table.horizontalHeader()
            return {"column": header.sortIndicatorSection(),
                    "order": "asc" if header.sortIndicatorOrder() == Qt.SortOrder.AscendingOrder else "desc"}
        return self.config.get("sort_order", {"column": 0, "order": "asc"})