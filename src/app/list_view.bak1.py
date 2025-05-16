
import os
import json
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem, QHeaderView
from PyQt6.QtCore import Qt

CONFIG_FILE = os.path.join('config', 'config.json')
COLUMN_WIDTH_KEY = "column_widths"
SORT_ORDER_KEY = "sort_order"

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

CONFIG = load_config()

class ListView(QWidget):
    def __init__(self, file_list=None):
        super().__init__()
        self.file_list = file_list or []
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["No", "ファイル名", "ファイルサイズ", "ステータス"])

        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet("""
            QHeaderView::section {
                background-color: #f0f0f0;
                padding: 0px;
            }
            alternate-background-color: #f0f0f0;
            background-color: white;
        """)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)

        self.table.setSortingEnabled(False)
        layout.addWidget(self.table)
        self.setLayout(layout)

        self.populate_table(self.file_list)
        self.restore_column_widths()
        self.apply_sort_order()

    def populate_table(self, files):
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(files))
        common_path = os.path.commonpath([f["path"] for f in files]) if files else ""

        for idx, file in enumerate(files):
            short_path = os.path.relpath(file["path"], common_path) if common_path else file["path"]
            self.table.setItem(idx, 0, QTableWidgetItem(str(idx + 1)))
            self.table.setItem(idx, 1, QTableWidgetItem(short_path))
            self.table.setItem(idx, 2, QTableWidgetItem(f"{file.get('size', 0)} bytes"))
            self.table.setItem(idx, 3, QTableWidgetItem(file.get("status", "")))

        self.restore_column_widths()
        self.apply_sort_order()
        self.table.setSortingEnabled(True)

    def restore_column_widths(self):
        widths = CONFIG.get(COLUMN_WIDTH_KEY, [50, 400, 150, 250])
        for i, width in enumerate(widths):
            self.table.setColumnWidth(i, width)

    def apply_sort_order(self):
        last_sort = CONFIG.get(SORT_ORDER_KEY, {"column": 0, "order": "asc"})
        self.table.sortItems(
            last_sort["column"],
            Qt.SortOrder.AscendingOrder if last_sort["order"] == "asc" else Qt.SortOrder.DescendingOrder
        )

    def get_column_widths(self):
        return [self.table.columnWidth(i) for i in range(self.table.columnCount())]

    def get_sort_order(self):
        header = self.table.horizontalHeader()
        return {
            "column": header.sortIndicatorSection(),
            "order": "asc" if header.sortIndicatorOrder() == Qt.SortOrder.AscendingOrder else "desc"
        }

    def update_files(self, files):
        self.file_list = files
        self.populate_table(files)
