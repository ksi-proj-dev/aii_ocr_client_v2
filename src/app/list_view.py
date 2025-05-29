# list_view.py

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QApplication
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer # QTimer をインポート
from PyQt6.QtGui import QColor, QFont, QPalette

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
    item_check_state_changed = pyqtSignal(int, bool)

    def __init__(self, initial_file_list_data=None):
        super().__init__()
        self.config = ConfigManager.load()
        self.file_list_data = initial_file_list_data if initial_file_list_data is not None else []
        self._suspend_item_changed_signal = False
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels(["☑", "No", "ファイル名", "ステータス", "OCR結果", "JSON", "サーチャブルPDF", "サイズ(MB)"])
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        
        ##### MODIFIED START #####
        # 現在のアプリケーションのパレットを取得
        current_palette = self.palette() # QWidget の palette() を使用
        base_color = current_palette.color(QPalette.ColorRole.Base).name() # 通常の背景色 (例: white)
        alternate_base_color = current_palette.color(QPalette.ColorRole.AlternateBase).name() # 交互背景色 (例: #f9f9f9)
        highlight_color = current_palette.color(QPalette.ColorRole.Highlight).name() # 選択時の背景色

        self.table.setStyleSheet(f"""
            QHeaderView::section {{ 
                background-color: #f0f0f0; 
                padding: 4px; 
                border: 1px solid #d0d0d0; 
            }}
            QTableWidget {{ 
                gridline-color: #e0e0e0; 
                alternate-background-color: {alternate_base_color}; 
                background-color: {base_color}; 
            }}
            QTableWidget::item {{ 
                padding: 3px; 
                border: 1px solid transparent; /* 通常時は枠なし */
            }}
            QTableWidget::item:focus {{
                /* フォーカス枠の色を通常の背景色と同じにする。
                    ただし、交互の行色があるため、どちらか一方の色に固定すると、
                    もう一方の色の行で枠が見えてしまう可能性がある。
                    最も目立たないのは、完全に透明にすることだが、それが効かない場合がある。
                    ここでは、主要な背景色(base_color)に合わせる。
                */
                border: 1px solid {base_color}; 
                outline: none;
            }}
            QTableWidget::item:selected {{
                background-color: {highlight_color};
                color: {current_palette.color(QPalette.ColorRole.HighlightedText).name()};
                border: 1px solid {highlight_color}; /* 選択時は選択色に合わせた枠 */
            }}
            QTableWidget::item:selected:focus {{
                border: 1px solid {highlight_color}; /* 選択時のフォーカス枠も選択色に */
                outline: none;
            }}
        """)
        ##### MODIFIED END #####

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(0, 35) # 少し幅を広げてみる
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionsClickable(True)
        header.sectionClicked.connect(self.on_header_section_clicked)
        
        col0_header_item_text = "☑"
        actual_header_item_col0 = QTableWidgetItem(col0_header_item_text)
        font = self.table.horizontalHeader().font()
        font.setBold(True)
        # font.setPointSize(font.pointSize() + 1) # アイコンが小さい場合はフォントサイズ調整も有効
        actual_header_item_col0.setFont(font)
        actual_header_item_col0.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setHorizontalHeaderItem(0, actual_header_item_col0)

        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().sortIndicatorChanged.connect(self.handle_sort_indicator_changed)

        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.itemChanged.connect(self.on_item_changed)

        layout.addWidget(self.table)
        self.setLayout(layout)

        self.populate_table(self.file_list_data)
        self.restore_column_widths()
        self.apply_sort_order(default_to_skip_col0=True)

    def handle_sort_indicator_changed(self, logical_index, order):
        if logical_index == 0:
            # QTimerを使って非同期にインジケータをクリア
            # これにより、ヘッダー描画の更新サイクル後に確実にクリアされることを期待
            QTimer.singleShot(0, lambda: self.table.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.AscendingOrder))

    def on_header_section_clicked(self, logical_index):
        if logical_index == 0:
            self.toggle_all_checkboxes()
            # 0列目がクリックされた場合、ソートインジケータは handle_sort_indicator_changed でクリアされる

    def toggle_all_checkboxes(self):
        is_currently_all_checked = True
        found_editable_checkbox = False
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.flags() & Qt.ItemFlag.ItemIsUserCheckable and item.flags() & Qt.ItemFlag.ItemIsEnabled:
                found_editable_checkbox = True
                if item.checkState() == Qt.CheckState.Unchecked:
                    is_currently_all_checked = False
                    break
        
        if not found_editable_checkbox:
            return

        new_check_state = Qt.CheckState.Unchecked if is_currently_all_checked else Qt.CheckState.Checked
        
        self._suspend_item_changed_signal = True
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.flags() & Qt.ItemFlag.ItemIsUserCheckable and item.flags() & Qt.ItemFlag.ItemIsEnabled:
                item.setCheckState(new_check_state)
                self.item_check_state_changed.emit(row, new_check_state == Qt.CheckState.Checked)
        self._suspend_item_changed_signal = False

    def on_item_changed(self, item):
        if self._suspend_item_changed_signal:
            return
        if item.column() == 0:
            row = item.row()
            is_checked = item.checkState() == Qt.CheckState.Checked
            self.item_check_state_changed.emit(row, is_checked)

    def populate_table(self, files_data):
        self._suspend_item_changed_signal = True
        self.table.setUpdatesEnabled(False)
        current_sorting_enabled_state = self.table.isSortingEnabled() 
        self.table.setSortingEnabled(False) 
        try:
            self.file_list_data = files_data
            self.table.setRowCount(0)
            self.table.setRowCount(len(self.file_list_data))
            
            error_color = QColor("red")

            for idx, file_info in enumerate(self.file_list_data):
                # 0. チェックボックス列
                check_item = QTableWidgetItem()
                flags = Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled
                # ItemIsSelectable を外すとフォーカス枠が抑制されることが多い
                # flags &= ~Qt.ItemFlag.ItemIsSelectable # これで点線枠が消えるか確認
                check_item.setFlags(flags)
                
                is_checked_val = file_info.get("is_checked", True)
                check_item.setCheckState(Qt.CheckState.Checked if is_checked_val else Qt.CheckState.Unchecked)
                check_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter) # チェックボックスを中央に
                
                if file_info.get("ocr_engine_status") == "対象外(サイズ上限)": 
                    check_item.setFlags(check_item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                    check_item.setToolTip("サイズ上限のため処理対象外です")
                self.table.setItem(idx, 0, check_item)

                # 1. No 列
                no_value = file_info.get("no", idx + 1)
                no_item = NumericTableWidgetItem(str(no_value), no_value)
                no_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(idx, 1, no_item)

                # Other columns
                self.table.setItem(idx, 2, QTableWidgetItem(file_info.get("name", "")))
                status_text = file_info.get("status", "")
                status_item = QTableWidgetItem(status_text)
                if "失敗" in status_text or "エラー" in status_text or "中断" in status_text:
                    status_item.setForeground(error_color)
                self.table.setItem(idx, 3, status_item)
                self.table.setItem(idx, 4, QTableWidgetItem(file_info.get("ocr_result_summary", "")))
                json_status_text = file_info.get("json_status", "-")
                json_status_item = QTableWidgetItem(json_status_text)
                if "失敗" in json_status_text or "エラー" in json_status_text or "中断" in json_status_text:
                    json_status_item.setForeground(error_color)
                self.table.setItem(idx, 5, json_status_item)
                pdf_status_text = file_info.get("searchable_pdf_status", "-")
                pdf_status_item = QTableWidgetItem(pdf_status_text)
                if ("失敗" in pdf_status_text or "エラー" in pdf_status_text or "中断" in pdf_status_text) and \
                   "部品PDFは結合されません(設定)" not in pdf_status_text and \
                   "個の部品PDF出力成功" not in pdf_status_text : 
                    pdf_status_item.setForeground(error_color)
                self.table.setItem(idx, 6, pdf_status_item)
                size_bytes = file_info.get("size", 0)
                size_mb = size_bytes / (1024 * 1024)
                size_mb_display_text = f"{size_mb:,.3f} MB"
                size_item = NumericTableWidgetItem(size_mb_display_text, size_bytes)
                size_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(idx, 7, size_item)

        finally:
            self.table.setSortingEnabled(current_sorting_enabled_state) 
            self.table.setUpdatesEnabled(True)
            self._suspend_item_changed_signal = False

    def update_files(self, files_data):
        self.populate_table(files_data)

    def restore_column_widths(self):
        default_widths = [35, 50, 280, 100, 270, 100, 120, 100] # 0列目の幅を調整
        widths = self.config.get("column_widths", default_widths)
        if len(widths) != self.table.columnCount():
            widths = default_widths
        for i, width in enumerate(widths):
            if 0 <= i < self.table.columnCount():
                self.table.setColumnWidth(i, width)

    def apply_sort_order(self, default_to_skip_col0=False): 
        if not (hasattr(self, 'table') and self.table and self.table.rowCount() > 0):
            return
        
        default_sort_column = 1  
        default_sort_order_str = "asc"
        last_sort_config = self.config.get("sort_order", {"column": default_sort_column, "order": default_sort_order_str})
        
        column_to_sort = last_sort_config.get("column", default_sort_column)
        
        if default_to_skip_col0 and column_to_sort == 0: 
            column_to_sort = default_sort_column 

        if not (0 <= column_to_sort < self.table.columnCount()):
            column_to_sort = default_sort_column

        order_str = last_sort_config.get("order", default_sort_order_str)
        sort_order_qt = Qt.SortOrder.AscendingOrder if order_str == "asc" else Qt.SortOrder.DescendingOrder
        
        current_sorting_enabled = self.table.isSortingEnabled()
        if not current_sorting_enabled: 
            self.table.setSortingEnabled(True)
        
        self.table.sortItems(column_to_sort, sort_order_qt)
        
        if not current_sorting_enabled: 
            self.table.setSortingEnabled(False)


    def get_column_widths(self):
        if hasattr(self, 'table') and self.table and self.table.columnCount() > 0:
            return [self.table.columnWidth(i) for i in range(self.table.columnCount())]
        return self.config.get("column_widths", [35, 50, 280, 100, 270, 100, 120, 100])

    def get_sort_order(self):
        if hasattr(self, 'table') and self.table and self.table.horizontalHeader().isSortIndicatorShown():
            header = self.table.horizontalHeader()
            current_sort_section = header.sortIndicatorSection()
            # 0列目はソート対象外とするため、保存されるソート列が0になることを避ける
            if current_sort_section == 0:
                 return self.config.get("sort_order", {"column": 1, "order": "asc"}) # デフォルトに戻す
            return {"column": current_sort_section, "order": "asc" if header.sortIndicatorOrder() == Qt.SortOrder.AscendingOrder else "desc"}
        return self.config.get("sort_order", {"column": 1, "order": "asc"})