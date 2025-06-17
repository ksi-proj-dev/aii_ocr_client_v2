# list_view.py

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QCheckBox, QHBoxLayout
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QColor, QPalette

from config_manager import ConfigManager
from file_model import FileInfo


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

    def __init__(self, initial_file_list_data: list[FileInfo] = None):
        super().__init__()
        self.config = ConfigManager.load()
        self.file_list_data: list[FileInfo] = initial_file_list_data if initial_file_list_data is not None else []
        self._suspend_item_changed_signal = False
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        self.table = QTableWidget()
        self.table.setColumnCount(10)
        self.table.setHorizontalHeaderLabels(["☑", "No", "ファイル名", "ステータス", "OCR結果", "JSON", "CSV", "サーチャブルPDF", "ページ数", "サイズ(MB)"])
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        
        current_palette = self.palette()
        base_color = current_palette.color(QPalette.ColorRole.Base).name()
        alternate_base_color = "#f5f5f5"
        highlight_color = current_palette.color(QPalette.ColorRole.Highlight).name()
        highlighted_text_color = current_palette.color(QPalette.ColorRole.HighlightedText).name()
        
        self.table.setStyleSheet(f"""
            QHeaderView::section {{ 
                background-color: #f0f0f0; 
                padding: 4px; 
                border: 1px solid #d0d0d0; 
            }}
            QTableWidget {{ 
                gridline-color: #e0e0e0; 
                alternate-background-color: {alternate_base_color}; /* 固定色を適用 */
                background-color: {base_color};
                outline: 0;
            }}
            QTableWidget::item {{ 
                padding: 3px; 
                border: 1px solid transparent;
            }}
            QTableWidget::item:focus {{
                border: 1px solid transparent;
                outline: 0;
            }}
            QTableWidget::item:selected {{
                background-color: {highlight_color};
                color: {highlighted_text_color};
            }}
        """)

        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(0, 35)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionsClickable(True)
        header.sectionClicked.connect(self.on_header_section_clicked)
        
        col0_header_item_text = "☑"
        actual_header_item_col0 = QTableWidgetItem(col0_header_item_text)
        font = self.table.horizontalHeader().font()
        font.setBold(True)
        actual_header_item_col0.setFont(font)
        actual_header_item_col0.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setHorizontalHeaderItem(0, actual_header_item_col0)

        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().sortIndicatorChanged.connect(self.handle_sort_indicator_changed)

        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        # itemChanged はもうチェックボックスには使わないが、他のセルで使う可能性を考慮して残す
        self.table.itemChanged.connect(self.on_item_changed)

        layout.addWidget(self.table)
        self.setLayout(layout)

        self.populate_table(self.file_list_data)
        self.restore_column_widths()
        self.apply_sort_order(default_to_skip_col0=True)

    def get_sorted_file_info_list(self) -> list[FileInfo]:
        sorted_list = []
        if not (hasattr(self, 'table') and self.table):
            return self.file_list_data

        for visual_row_index in range(self.table.rowCount()):
            no_item = self.table.item(visual_row_index, 1)
            if no_item:
                try:
                    file_no = int(no_item.text())
                    found_file_info = next((f for f in self.file_list_data if f.no == file_no), None)
                    if found_file_info:
                        sorted_list.append(found_file_info)
                except (ValueError, StopIteration):
                    continue
        
        if len(sorted_list) != len(self.file_list_data):
            return self.file_list_data
            
        return sorted_list
        
    def set_checkboxes_enabled(self, is_enabled: bool):
        for row in range(self.table.rowCount()):
            cell_widget = self.table.cellWidget(row, 0)
            if cell_widget:
                checkbox = cell_widget.findChild(QCheckBox)
                if checkbox:
                    no_item = self.table.item(row, 1)
                    if not no_item: continue
                    try:
                        file_no = int(no_item.text())
                        file_info = next((f for f in self.file_list_data if f.no == file_no), None)
                        if not file_info: continue
                        
                        original_is_disabled_by_logic = (file_info.ocr_engine_status == "対象外(サイズ上限)")
                        if is_enabled and not original_is_disabled_by_logic:
                            checkbox.setEnabled(True)
                        elif not is_enabled:
                            checkbox.setEnabled(False)
                    except (ValueError, StopIteration):
                        continue

    def handle_sort_indicator_changed(self, logical_index, order):
        if logical_index == 0:
            QTimer.singleShot(0, lambda: self.table.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.AscendingOrder))

    def on_header_section_clicked(self, logical_index):
        if logical_index == 0:
            self.toggle_all_checkboxes()

    def toggle_all_checkboxes(self):
        is_currently_all_checked = True
        found_editable_checkbox = False
        for row in range(self.table.rowCount()):
            cell_widget = self.table.cellWidget(row, 0)
            if cell_widget:
                checkbox = cell_widget.findChild(QCheckBox)
                if checkbox and checkbox.isEnabled():
                    found_editable_checkbox = True
                    if not checkbox.isChecked():
                        is_currently_all_checked = False
                        break
        
        if not found_editable_checkbox:
            return

        new_check_state = not is_currently_all_checked
        
        for row in range(self.table.rowCount()):
            cell_widget = self.table.cellWidget(row, 0)
            if cell_widget:
                checkbox = cell_widget.findChild(QCheckBox)
                if checkbox and checkbox.isEnabled():
                    checkbox.setChecked(new_check_state)

    def on_checkbox_state_changed(self, file_no: int, state: int):
        is_checked = (state == Qt.CheckState.Checked.value)
        
        target_file_info = next((f for f in self.file_list_data if f.no == file_no), None)
        if target_file_info:
            target_file_info.is_checked = is_checked
            try:
                original_idx = self.file_list_data.index(target_file_info)
                self.item_check_state_changed.emit(original_idx, is_checked)
            except ValueError:
                pass # リストにない場合は何もしない

    def on_item_changed(self, item: QTableWidgetItem):
        # このメソッドはもうチェックボックスには使用されませんが、
        # 将来的に他のセルを編集可能にする可能性を考慮して残しておきます。
        if self._suspend_item_changed_signal:
            return
        # print(f"Item changed: row {item.row()}, col {item.column()}")

    def populate_table(self, files_data: list[FileInfo], is_running: bool = False):
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
                cell_widget = QWidget()
                layout = QHBoxLayout(cell_widget)
                layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
                layout.setContentsMargins(0, 0, 0, 0)
                
                checkbox = QCheckBox()
                checkbox.setChecked(file_info.is_checked)
                
                # stateChangedシグナルに、ファイル番号(no)と新しい状態を渡すラムダを接続
                checkbox.stateChanged.connect(
                    lambda state, fn=file_info.no: self.on_checkbox_state_changed(fn, state)
                )

                is_disabled_by_logic = (file_info.ocr_engine_status == "対象外(サイズ上限)")
                if is_running or is_disabled_by_logic:
                    checkbox.setEnabled(False)
                if is_disabled_by_logic:
                    checkbox.setToolTip("サイズ上限のため処理対象外です")

                layout.addWidget(checkbox)
                self.table.setCellWidget(idx, 0, cell_widget)

                no_value = file_info.no
                no_item = NumericTableWidgetItem(str(no_value), no_value)
                no_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(idx, 1, no_item)

                self.table.setItem(idx, 2, QTableWidgetItem(file_info.name))
                status_item = QTableWidgetItem(file_info.status)
                if "失敗" in file_info.status or "エラー" in file_info.status or "中断" in file_info.status: status_item.setForeground(error_color)
                self.table.setItem(idx, 3, status_item)
                self.table.setItem(idx, 4, QTableWidgetItem(file_info.ocr_result_summary))
                json_status_item = QTableWidgetItem(file_info.json_status)
                if "失敗" in file_info.json_status or "エラー" in file_info.json_status or "中断" in file_info.json_status: json_status_item.setForeground(error_color)
                self.table.setItem(idx, 5, json_status_item)

                auto_csv_status_item = QTableWidgetItem(file_info.auto_csv_status)
                if "失敗" in file_info.auto_csv_status or "エラー" in file_info.auto_csv_status:
                    auto_csv_status_item.setForeground(error_color)
                self.table.setItem(idx, 6, auto_csv_status_item)

                pdf_status_item = QTableWidgetItem(file_info.searchable_pdf_status)
                if ("失敗" in file_info.searchable_pdf_status or "エラー" in file_info.searchable_pdf_status or "中断" in file_info.searchable_pdf_status) and "部品PDFは結合されません(設定)" not in file_info.searchable_pdf_status and "個の部品PDF出力成功" not in file_info.searchable_pdf_status : 
                    pdf_status_item.setForeground(error_color)
                self.table.setItem(idx, 7, pdf_status_item)

                page_count_value = file_info.page_count
                if page_count_value is not None:
                    page_count_item = NumericTableWidgetItem(str(page_count_value), page_count_value)
                    page_count_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                else:
                    page_count_item = QTableWidgetItem("-")
                    page_count_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(idx, 8, page_count_item)
                
                size_bytes = file_info.size
                size_mb = size_bytes / (1024 * 1024)
                size_mb_display_text = f"{size_mb:,.3f} MB"
                size_item = NumericTableWidgetItem(size_mb_display_text, size_bytes)
                size_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(idx, 9, size_item)

        finally:
            self.table.setSortingEnabled(current_sorting_enabled_state) 
            self.table.setUpdatesEnabled(True)
            self._suspend_item_changed_signal = False

    def update_files(self, files_data: list[FileInfo], is_running: bool = False):
        self.populate_table(files_data, is_running)

    def restore_column_widths(self):
        default_widths = [35, 50, 280, 100, 270, 100, 100, 120, 60, 100]
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
        return self.config.get("column_widths", [35, 50, 280, 100, 270, 100, 120, 60, 100])

    def get_sort_order(self):
        if hasattr(self, 'table') and self.table and self.table.horizontalHeader().isSortIndicatorShown():
            header = self.table.horizontalHeader()
            current_sort_section = header.sortIndicatorSection()
            if current_sort_section == 0:
                return self.config.get("sort_order", {"column": 1, "order": "asc"})
            return {"column": current_sort_section, "order": "asc" if header.sortIndicatorOrder() == Qt.SortOrder.AscendingOrder else "desc"}
        return self.config.get("sort_order", {"column": 1, "order": "asc"})