import os
import json
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem, QHeaderView
from PyQt6.QtCore import Qt
from config_manager import ConfigManager # 設定読み込みのために追加

class ListView(QWidget):
    def __init__(self, initial_file_list_data=None): # 引数名変更
        super().__init__()
        # configの読み込みはMainWindow側で行い、必要な設定値(列幅など)は別途渡すか、
        # ここでConfigManagerを使って直接読み込む。今回は直接読み込む。
        self.config = ConfigManager.load()
        self.file_list_data = initial_file_list_data or [] # 内部でデータを保持
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        self.table = QTableWidget()
        self.table.setColumnCount(6) # 列数を6に変更
        self.table.setHorizontalHeaderLabels([
            "No", "ファイル名", "ステータス", "OCR結果概要", "サーチャブルPDF", "サイズ(KB)"
        ])

        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet("""
            QHeaderView::section {
                background-color: #f0f0f0; /* ヘッダー背景色 */
                padding: 4px; /* ヘッダーパディング */
                border: 1px solid #d0d0d0; /* ヘッダー境界線 */
            }
            QTableWidget {
                gridline-color: #e0e0e0; /* グリッド線色 */
                alternate-background-color: #f9f9f9; /* 交互の行の背景色 */
                background-color: white; /* 背景色 */
            }
        """)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive) # サイズ変更をインタラクティブに
        # header.setStretchLastSection(True) # 最後のセクションをストレッチ (任意)

        self.table.setSortingEnabled(True) # 初期状態でソート有効
        layout.addWidget(self.table)
        self.setLayout(layout)

        self.populate_table(self.file_list_data) # 初期データでテーブルを構築
        self.restore_column_widths() # 列幅復元を populate_table の後に移動
        self.apply_sort_order()      # ソート順復元も同様

    def populate_table(self, files_data):
        self.file_list_data = files_data # 内部データを更新
        self.table.setSortingEnabled(False) # 更新中はソートを一時的に無効化
        self.table.setRowCount(0) # テーブルをクリア
        self.table.setRowCount(len(self.file_list_data))

        # ファイルパスから共通の親ディレクトリを取得して表示を短縮 (オプション)
        # common_path = ""
        # if self.file_list_data:
        #     paths = [f_info.get("path", "") for f_info in self.file_list_data if f_info.get("path")]
        #     if paths:
        #         common_path = os.path.commonpath(paths) # 複数ファイルの共通パス

        for idx, file_info in enumerate(self.file_list_data):
            # No
            no_item = QTableWidgetItem(str(file_info.get("no", idx + 1)))
            no_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter) # 中央揃え
            self.table.setItem(idx, 0, no_item)

            # ファイル名
            # display_name = os.path.relpath(file_info.get("path",""), common_path) if common_path and file_info.get("path") else file_info.get("name", "")
            display_name = file_info.get("name", "") # シンプルにファイル名のみ
            self.table.setItem(idx, 1, QTableWidgetItem(display_name))

            # ステータス
            self.table.setItem(idx, 2, QTableWidgetItem(file_info.get("status", "")))

            # OCR結果概要
            summary_item = QTableWidgetItem(file_info.get("ocr_result_summary", ""))
            self.table.setItem(idx, 3, summary_item)

            # サーチャブルPDFステータス
            self.table.setItem(idx, 4, QTableWidgetItem(file_info.get("searchable_pdf_status", "-")))

            # ファイルサイズ (KB)
            size_kb = file_info.get("size", 0) / 1024
            size_item = QTableWidgetItem(f"{size_kb:,.1f} KB") # 3桁区切り、小数点1桁
            size_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter) # 右揃え
            self.table.setItem(idx, 5, size_item)

        self.table.resizeColumnsToContents() # 内容に合わせて列幅を自動調整 (初回)
        self.restore_column_widths() # 保存された列幅があれば適用
        self.apply_sort_order()      # 保存されたソート順があれば適用
        self.table.setSortingEnabled(True) # ソートを再度有効化

    def update_files(self, files_data):
        """外部からファイルリスト全体を更新するためのメソッド"""
        self.populate_table(files_data)

    def restore_column_widths(self):
        # デフォルトの列幅 (No, ファイル名, ステータス, OCR概要, PDFステータス, サイズ)
        default_widths = [40, 250, 100, 300, 120, 100]
        widths = self.config.get("column_widths", default_widths)
        # 保存された列幅の数が現在の列数と異なる場合はデフォルトを使用
        if len(widths) != self.table.columnCount():
            widths = default_widths

        for i, width in enumerate(widths):
            if i < self.table.columnCount(): # 念のため列数が存在するか確認
                self.table.setColumnWidth(i, width)

    def apply_sort_order(self):
        # デフォルトのソート順 (No列、昇順)
        default_sort = {"column": 0, "order": "asc"}
        last_sort = self.config.get("sort_order", default_sort)

        column = last_sort.get("column", default_sort["column"])
        order_str = last_sort.get("order", default_sort["order"])
        sort_order = Qt.SortOrder.AscendingOrder if order_str == "asc" else Qt.SortOrder.DescendingOrder

        if 0 <= column < self.table.columnCount(): # 列インデックスの妥当性チェック
            self.table.sortItems(column, sort_order)

    def get_column_widths(self):
        """現在の列幅をリストで取得する"""
        if hasattr(self, 'table') and self.table.columnCount() > 0:
            return [self.table.columnWidth(i) for i in range(self.table.columnCount())]
        return [] # テーブル未初期化などの場合

    def get_sort_order(self):
        """現在のソート順を辞書で取得する"""
        if hasattr(self, 'table') and self.table.horizontalHeader().isSortIndicatorShown():
            header = self.table.horizontalHeader()
            return {
                "column": header.sortIndicatorSection(),
                "order": "asc" if header.sortIndicatorOrder() == Qt.SortOrder.AscendingOrder else "desc"
            }
        return {"column": 0, "order": "asc"} # デフォルト