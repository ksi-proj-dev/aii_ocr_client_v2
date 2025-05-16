from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem, QHeaderView
from PyQt6.QtCore import Qt
from config_manager import ConfigManager

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
        layout.addWidget(self.table)
        self.setLayout(layout)
        
        # populate_table の前に列幅とソート順を復元する方が自然かもしれない
        # ただし、テーブルにデータがない状態でのソートは意味がないので、populate_table の後で良い
        self.populate_table(self.file_list_data) # 初期データでテーブルを構築
        # self.restore_column_widths() # populate_table 内に移動
        # self.apply_sort_order()      # populate_table 内に移動

    def populate_table(self, files_data):
        self.table.setUpdatesEnabled(False) # <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<< 追加
        try:
            self.file_list_data = files_data
            self.table.setSortingEnabled(False)
            self.table.setRowCount(0) # アイテムをクリアするため先に実行
            self.table.setRowCount(len(self.file_list_data))

            for idx, file_info in enumerate(self.file_list_data):
                no_item = QTableWidgetItem(str(file_info.get("no", idx + 1)))
                no_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(idx, 0, no_item)
                self.table.setItem(idx, 1, QTableWidgetItem(file_info.get("name", "")))
                self.table.setItem(idx, 2, QTableWidgetItem(file_info.get("status", "")))
                self.table.setItem(idx, 3, QTableWidgetItem(file_info.get("ocr_result_summary", "")))
                self.table.setItem(idx, 4, QTableWidgetItem(file_info.get("searchable_pdf_status", "-")))
                size_kb = file_info.get("size", 0) / 1024
                size_item = QTableWidgetItem(f"{size_kb:,.1f} KB")
                size_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(idx, 5, size_item)
            
            # アイテム設定後に列幅調整とソートを行う
            self.table.resizeColumnsToContents() # 一旦内容に合わせる
            self.restore_column_widths()         # 保存された幅があればそれで上書き
            self.apply_sort_order()              # 保存されたソート順を適用
        finally:
            self.table.setSortingEnabled(True)
            self.table.setUpdatesEnabled(True)  # <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<< 追加 (必ず実行されるようにfinally内)

    def update_files(self, files_data):
        self.populate_table(files_data)

    def restore_column_widths(self):
        default_widths = [40, 250, 100, 300, 120, 100]
        widths = self.config.get("column_widths", default_widths)
        if len(widths) != self.table.columnCount(): widths = default_widths
        for i, width in enumerate(widths):
            if i < self.table.columnCount(): self.table.setColumnWidth(i, width)

    def apply_sort_order(self):
        default_sort = {"column": 0, "order": "asc"}
        last_sort = self.config.get("sort_order", default_sort)
        column = last_sort.get("column", default_sort["column"])
        order_str = last_sort.get("order", default_sort["order"])
        sort_order = Qt.SortOrder.AscendingOrder if order_str == "asc" else Qt.SortOrder.DescendingOrder
        if 0 <= column < self.table.columnCount():
            # ここでソートを実行する前にテーブルが描画更新されていないか確認
            # Qtが内部的に行うため直接制御は難しいが、setUpdatesEnabledで抑制できていることを期待
            self.table.sortItems(column, sort_order)

    def get_column_widths(self):
        if hasattr(self, 'table') and self.table.columnCount() > 0:
            return [self.table.columnWidth(i) for i in range(self.table.columnCount())]
        return []

    def get_sort_order(self):
        if hasattr(self, 'table') and self.table.horizontalHeader().isSortIndicatorShown():
            header = self.table.horizontalHeader()
            return {"column": header.sortIndicatorSection(),
                    "order": "asc" if header.sortIndicatorOrder() == Qt.SortOrder.AscendingOrder else "desc"}
        # デフォルトは保存されたものか、さらにそのデフォルト
        return self.config.get("sort_order", {"column": 0, "order": "asc"})