# list_view.py

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QApplication
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QColor, QFont, QPalette

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
    item_check_state_changed = pyqtSignal(int, bool) # row_index, is_checked

    def __init__(self, initial_file_list_data: list[FileInfo] = None):
        super().__init__()
        self.config = ConfigManager.load()
        self.file_list_data: list[FileInfo] = initial_file_list_data if initial_file_list_data is not None else []
        self._suspend_item_changed_signal = False
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        self.table = QTableWidget()
        self.table.setColumnCount(9)
        self.table.setHorizontalHeaderLabels(["☑", "No", "ファイル名", "ステータス", "OCR結果", "JSON", "サーチャブルPDF", "ページ数", "サイズ(MB)"])
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        
        current_palette = self.palette()
        base_color = current_palette.color(QPalette.ColorRole.Base).name()
        alternate_base_color = current_palette.color(QPalette.ColorRole.AlternateBase).name()
        highlight_color = current_palette.color(QPalette.ColorRole.Highlight).name()

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
                border: 1px solid transparent;
            }}
            QTableWidget::item:focus {{
                border: 1px solid {base_color}; 
                outline: none;
            }}
            QTableWidget::item:selected {{
                background-color: {highlight_color};
                color: {current_palette.color(QPalette.ColorRole.HighlightedText).name()};
                border: 1px solid {highlight_color};
            }}
            QTableWidget::item:selected:focus {{
                border: 1px solid {highlight_color};
                outline: none;
            }}
        """)

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
        self.table.itemChanged.connect(self.on_item_changed)

        layout.addWidget(self.table)
        self.setLayout(layout)

        self.populate_table(self.file_list_data)
        self.restore_column_widths()
        self.apply_sort_order(default_to_skip_col0=True)

    def get_sorted_file_info_list(self) -> list[FileInfo]:
        """
        現在テーブルに表示されている順番（ソート後）でFileInfoオブジェクトのリストを返します。
        
        Returns:
            list[FileInfo]: 現在の表示順にソートされたFileInfoオブジェクトのリスト。
        """
        sorted_list = []
        if not (hasattr(self, 'table') and self.table):
            return self.file_list_data # テーブルがなければ元のリストを返す

        for visual_row_index in range(self.table.rowCount()):
            # 'No'列のアイテムから、対応する元のファイルNoを取得
            no_item = self.table.item(visual_row_index, 1) # 'No' は2列目(インデックス1)
            if no_item:
                try:
                    file_no = int(no_item.text())
                    # 元のデータリストから、該当するNoを持つFileInfoオブジェクトを検索
                    found_file_info = next((f for f in self.file_list_data if f.no == file_no), None)
                    if found_file_info:
                        sorted_list.append(found_file_info)
                except (ValueError, StopIteration):
                    # Noが数値でない、または対応するFileInfoが見つからない場合はスキップ
                    continue
        
        # もし何らかの理由でソート済みリストが作成できなかった場合は、安全のために元のリストを返す
        if len(sorted_list) != len(self.file_list_data):
            return self.file_list_data
            
        return sorted_list
        
    def set_checkboxes_enabled(self, is_enabled: bool):
        """リストビュー内の全てのチェックボックスの有効/無効を切り替える。"""
        self._suspend_item_changed_signal = True # 状態変更時にシグナルが発行されないように
        for row in range(self.table.rowCount()):
            check_item = self.table.item(row, 0)
            if check_item:
                current_flags = check_item.flags()
                
                # 'No'列から対応するfile_infoを検索
                no_item = self.table.item(row, 1)
                if not no_item: continue
                try:
                    file_no = int(no_item.text())
                    file_info = next((f for f in self.file_list_data if f.no == file_no), None)
                    if not file_info: continue

                    # サイズ上限などで元々無効化されているチェックボックスは、有効化しない
                    original_is_disabled_by_logic = (file_info.ocr_engine_status == "対象外(サイズ上限)")

                    if is_enabled and not original_is_disabled_by_logic:
                        check_item.setFlags(current_flags | Qt.ItemFlag.ItemIsEnabled)
                    elif not is_enabled:
                        check_item.setFlags(current_flags & ~Qt.ItemFlag.ItemIsEnabled)
                except (ValueError, StopIteration):
                    continue
        self._suspend_item_changed_signal = False

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
                no_item = self.table.item(row, 1)
                if no_item:
                    try:
                        file_no = int(no_item.text())
                        file_info = next((f for f in self.file_list_data if f.no == file_no), None)
                        if file_info:
                            file_info.is_checked = (new_check_state == Qt.CheckState.Checked)
                            item.setCheckState(new_check_state)
                            self.item_check_state_changed.emit(file_info.no - 1, file_info.is_checked) # 元のリストのインデックスを想定
                    except (ValueError, StopIteration):
                        continue
        self._suspend_item_changed_signal = False

    def on_item_changed(self, item: QTableWidgetItem):
        if self._suspend_item_changed_signal:
            return
        if item.column() == 0:
            row = item.row()
            no_item = self.table.item(row, 1)
            if not no_item: return
            
            try:
                file_no = int(no_item.text())
                target_file_info_idx = -1
                for i, f_info in enumerate(self.file_list_data):
                    if f_info.no == file_no:
                        target_file_info_idx = i
                        break

                if target_file_info_idx != -1:
                    is_checked = item.checkState() == Qt.CheckState.Checked
                    self.file_list_data[target_file_info_idx].is_checked = is_checked
                    self.item_check_state_changed.emit(target_file_info_idx, is_checked)
            except (ValueError, IndexError):
                pass

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
                check_item = QTableWidgetItem()
                flags = Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled
                
                is_disabled_by_logic = (file_info.ocr_engine_status == "対象外(サイズ上限)")
                if is_running or is_disabled_by_logic:
                    flags &= ~Qt.ItemFlag.ItemIsEnabled

                check_item.setFlags(flags)
                
                if is_disabled_by_logic:
                    check_item.setToolTip("サイズ上限のため処理対象外です")

                is_checked_val = file_info.is_checked 
                check_item.setCheckState(Qt.CheckState.Checked if is_checked_val else Qt.CheckState.Unchecked)
                check_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(idx, 0, check_item)

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
                pdf_status_item = QTableWidgetItem(file_info.searchable_pdf_status)
                if ("失敗" in file_info.searchable_pdf_status or "エラー" in file_info.searchable_pdf_status or "中断" in file_info.searchable_pdf_status) and "部品PDFは結合されません(設定)" not in file_info.searchable_pdf_status and "個の部品PDF出力成功" not in file_info.searchable_pdf_status : 
                    pdf_status_item.setForeground(error_color)
                self.table.setItem(idx, 6, pdf_status_item)

                page_count_value = file_info.page_count
                if page_count_value is not None:
                    page_count_item = NumericTableWidgetItem(str(page_count_value), page_count_value)
                    page_count_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                else:
                    page_count_item = QTableWidgetItem("-")
                    page_count_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(idx, 7, page_count_item)
                
                size_bytes = file_info.size
                size_mb = size_bytes / (1024 * 1024)
                size_mb_display_text = f"{size_mb:,.3f} MB"
                size_item = NumericTableWidgetItem(size_mb_display_text, size_bytes)
                size_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(idx, 8, size_item)

        finally:
            self.table.setSortingEnabled(current_sorting_enabled_state) 
            self.table.setUpdatesEnabled(True)
            self._suspend_item_changed_signal = False

    def update_files(self, files_data: list[FileInfo], is_running: bool = False):
        self.populate_table(files_data, is_running)

    def restore_column_widths(self):
        default_widths = [35, 50, 280, 100, 270, 100, 120, 60, 100]
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