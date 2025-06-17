# summary_view.py

from datetime import datetime
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                            QProgressBar, QFrame, QGridLayout, QSizePolicy)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFontMetrics

class StatusCard(QFrame):
    def __init__(self, title: str, color: str, show_progress_widget: bool = True):
        super().__init__()
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFrameShadow(QFrame.Shadow.Raised)
        self.show_progress_widget = show_progress_widget
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.setStyleSheet(f"""
            QFrame#StatusCard {{ 
                border: 1px solid {color}; 
                border-radius: 5px; 
                padding: 6px; 
                background-color: #ffffff; 
            }}
            QLabel#TitleLabel {{
                font-weight: bold; font-size: 11pt; /* StatusCardのタイトルフォントサイズ */
                color: #333;
            }}
            QLabel#CountLabel {{
                font-size: 14pt; /* StatusCardの件数フォントサイズ */
                font-weight: bold; 
                color: #555; 
                qproperty-alignment: 'AlignCenter';
            }}
            QProgressBar {{
                text-align: center; 
                border: 1px solid #B0B0B0;
                border-radius: 3px;
                min-height: 10px; 
                max-height: 10px; 
            }}
            QProgressBar::chunk {{
                background-color: {color};
            }}
        """)
        self.setObjectName("StatusCard")
        layout = QVBoxLayout()
        layout.setContentsMargins(4, 4, 4, 4) 
        layout.setSpacing(0) 

        self.title_label = QLabel(title)
        self.title_label.setObjectName("TitleLabel")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setWordWrap(True) 
        self.title_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        self.count_label = QLabel("0件")
        self.count_label.setObjectName("CountLabel")
        self.count_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.count_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        
        layout.addStretch(1) 
        layout.addWidget(self.title_label, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch(1) 
        layout.addWidget(self.count_label, 0, Qt.AlignmentFlag.AlignHCenter)
        
        self.progress = None 
        if self.show_progress_widget:
            self.progress = QProgressBar()
            self.progress.setFixedHeight(10) 
            self.progress.setTextVisible(False)
            layout.addStretch(1) 
            layout.addWidget(self.progress)
        else:
            # プログレスバーがない場合は、対応する高さのスペーサーを追加して
            # 他のカードとの垂直方向の要素配置のバランスを取る
            placeholder = QWidget()
            placeholder.setFixedHeight(10) # プログレスバーと同じ高さ
            placeholder.setVisible(False) # 見えないがスペースは確保される（レイアウトによる）
            layout.addStretch(1)
            layout.addWidget(placeholder)


        layout.addStretch(1) 
        
        fm_title = QFontMetrics(self.title_label.font())
        fm_count = QFontMetrics(self.count_label.font())
        min_title_height = fm_title.lineSpacing() * 2 
        min_count_height = fm_count.lineSpacing()
        
        current_min_height = min_title_height + min_count_height
        num_actual_widgets = 2 
        if self.show_progress_widget:
            num_actual_widgets +=1
            current_min_height += 10 
        else: # placeholder for progress bar height
            current_min_height +=10

        current_min_height += layout.contentsMargins().top() + layout.contentsMargins().bottom() 
        frame_padding_str = self.styleSheet().split("padding:")[1].split("px")[0].strip() if "padding:" in self.styleSheet() else "6"
        frame_padding = int(frame_padding_str) * 2
        current_min_height += frame_padding
        self.setMinimumHeight(int(current_min_height + 5)) 

        self.setLayout(layout)
    
    def update_data(self, count: int, total: int = 0, show_empty_progress_for_active_progress_bar: bool = False): 
        self.count_label.setText(f"{count}件")
        
        if self.show_progress_widget and self.progress:
            self.progress.setVisible(True)
            if total > 0:
                self.progress.setMaximum(total)
                self.progress.setValue(min(count, total)) 
            elif show_empty_progress_for_active_progress_bar: 
                self.progress.setMaximum(1 if total == 0 else total) 
                self.progress.setValue(0)
            else: 
                self.progress.setMaximum(100) 
                self.progress.setValue(0)
                self.progress.setVisible(False)
        elif self.progress: 
             self.progress.setVisible(False)


class InfoCard(QFrame):
    def __init__(self, label_text: str, color: str):
        super().__init__()
        self.setFrameShape(QFrame.Shape.StyledPanel); self.setFrameShadow(QFrame.Shadow.Raised)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding) 
        
        ##### MODIFIED START #####
        self.setStyleSheet(f"""
            QFrame#InfoCard {{ 
                border: 1px solid {color}; 
                border-radius: 5px; 
                padding: 8px; 
                background-color: #ffffff; 
            }}
             QLabel#InfoTitleLabel {{ /* StatusCard の TitleLabel と合わせる */
                font-weight: bold; font-size: 11pt; 
                color: #444; /* StatusCard は #333 なので、合わせるか検討 */
                qproperty-alignment: 'AlignCenter';
             }}
            QLabel#InfoValueLabel {{ /* StatusCard の CountLabel と合わせる */
                font-size: 14pt; /* StatusCard の CountLabel と同じサイズに */
                font-weight: bold; /* StatusCard の CountLabel と同じ太さに */
                color: #666; 
                qproperty-alignment: 'AlignCenter';
            }}
        """)
        ##### MODIFIED END #####
        self.setObjectName("InfoCard")
        layout = QVBoxLayout(); 
        layout.setContentsMargins(5,5,5,5)
        layout.setSpacing(0)

        self.label_widget = QLabel(label_text)
        self.label_widget.setObjectName("InfoTitleLabel")
        self.label_widget.setAlignment(Qt.AlignmentFlag.AlignCenter) 
        self.label_widget.setWordWrap(True)
        self.label_widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        self.value_label = QLabel("-")
        self.value_label.setObjectName("InfoValueLabel")
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignCenter) 
        self.value_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        
        layout.addStretch(1) 
        layout.addWidget(self.label_widget)
        layout.addStretch(1) 
        layout.addWidget(self.value_label)
        layout.addStretch(1) 
        
        fm_title = QFontMetrics(self.label_widget.font())
        fm_value = QFontMetrics(self.value_label.font())
        min_text_h = fm_title.lineSpacing() * 2 + fm_value.lineSpacing() 
        
        current_min_height = min_text_h
        current_min_height += layout.contentsMargins().top() + layout.contentsMargins().bottom()
        frame_padding_str = self.styleSheet().split("padding:")[1].split("px")[0].strip() if "padding:" in self.styleSheet() else "8"
        frame_padding = int(frame_padding_str) * 2
        current_min_height += frame_padding
        
        self.setMinimumHeight(int(current_min_height + 5)) 
        self.setLayout(layout)

    def update_value(self, text: str):
        self.value_label.setText(text)

# SummaryView クラスの他の部分は変更なし
class SummaryView(QWidget):
    def __init__(self):
        super().__init__()
        self.total_files_for_ocr = 0 
        self.processed_count = 0
        self.ocr_completed_count = 0
        self.ocr_error_count = 0
        self.skipped_by_size_count = 0 
        self.total_scanned_files_count = 0 
        self.start_time = None
        self.log_manager = None 
        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(); main_layout.setContentsMargins(10, 10, 10, 10); main_layout.setSpacing(10)
        
        status_card_layout = QGridLayout() 
        status_card_layout.setSpacing(10) 

        self.cards = {
            "pending": StatusCard("処理待ち", "#AAAAAA", show_progress_widget=True), 
            "completed": StatusCard("OCR成功", "#32CD32", show_progress_widget=True),
            "error": StatusCard("OCRエラー", "#FF6347", show_progress_widget=True),
            "total_scanned": StatusCard("スキャン総数", "#6c757d", show_progress_widget=False), 
            "total_ocr_target": StatusCard("処理対象", "#17a2b8", show_progress_widget=False), 
            "skipped_size": StatusCard("サイズ上限スキップ", "#ffc107", show_progress_widget=False)
        }
        
        status_card_layout.addWidget(self.cards["pending"], 0, 0)
        status_card_layout.addWidget(self.cards["completed"], 0, 1)
        status_card_layout.addWidget(self.cards["error"], 0, 2)
        status_card_layout.addWidget(self.cards["total_scanned"], 1, 0)
        status_card_layout.addWidget(self.cards["total_ocr_target"], 1, 1)
        status_card_layout.addWidget(self.cards["skipped_size"], 1, 2)

        for i in range(status_card_layout.columnCount()):
            status_card_layout.setColumnStretch(i, 1)
        for i in range(status_card_layout.rowCount()): 
            status_card_layout.setRowStretch(i, 1) 

        info_layout = QHBoxLayout(); info_layout.setSpacing(10)
        self.info_cards = {
            "start_time": InfoCard("処理開始時刻", "#6c757d"), 
            "elapsed_time": InfoCard("経過時間", "#6c757d"), 
            "avg_time": InfoCard("平均処理時間/件", "#6c757d")
        }
        for card in self.info_cards.values():
            info_layout.addWidget(card, 1) 
        
        main_layout.addLayout(status_card_layout, 2) 
        main_layout.addLayout(info_layout, 1)      
        self.setLayout(main_layout)
        self.reset_summary()

    def reset_summary(self):
        self.total_files_for_ocr = 0 
        self.processed_count = 0 
        self.ocr_completed_count = 0 
        self.ocr_error_count = 0
        self.start_time = None
        self.update_display()

    def start_processing(self, total_files_to_ocr_count):
        self.total_files_for_ocr = total_files_to_ocr_count
        self.processed_count = 0 
        self.ocr_completed_count = 0 
        self.ocr_error_count = 0
        self.start_time = datetime.now()
        if self.log_manager:
            self.log_manager.info(f"SummaryView: Processing started for {self.total_files_for_ocr} files.", context="SUMMARY_VIEW")
        self.update_display()

    def update_for_processed_file(self, is_success: bool):
        if self.total_files_for_ocr > 0 and self.processed_count < self.total_files_for_ocr: 
            self.processed_count += 1
        
        if is_success:
            self.ocr_completed_count += 1
        else:
            self.ocr_error_count += 1
        self.update_display()

    def update_summary_counts(self, total_scanned=None, total_ocr_target=None, skipped_size=None):
        if total_scanned is not None:
            self.total_scanned_files_count = total_scanned
        if total_ocr_target is not None:
            if not self.start_time: 
                 self.total_files_for_ocr = total_ocr_target
                 self.processed_count = 0
                 self.ocr_completed_count = 0
                 self.ocr_error_count = 0
        if skipped_size is not None:
            self.skipped_by_size_count = skipped_size
        
        if self.log_manager:
            self.log_manager.debug(f"SummaryView counts updated: Scanned={self.total_scanned_files_count}, TargetForOCR={self.total_files_for_ocr}, Skipped={self.skipped_by_size_count}, Processed={self.processed_count}", context="SUMMARY_VIEW")
        self.update_display()


    def update_display(self):
        pending_count = self.total_files_for_ocr - self.processed_count
        if pending_count < 0: pending_count = 0 

        self.cards["total_scanned"].update_data(self.total_scanned_files_count)
        self.cards["total_ocr_target"].update_data(self.total_files_for_ocr)
        self.cards["skipped_size"].update_data(self.skipped_by_size_count)

        current_total_for_progress = self.total_files_for_ocr if self.total_files_for_ocr > 0 else 1
        show_empty_bars = self.total_files_for_ocr >= 0 

        self.cards["pending"].update_data(
            pending_count, 
            self.total_files_for_ocr if self.total_files_for_ocr > 0 else 1, 
            show_empty_progress_for_active_progress_bar=show_empty_bars
        )
        self.cards["completed"].update_data(
            self.ocr_completed_count, 
            current_total_for_progress,
            show_empty_progress_for_active_progress_bar=show_empty_bars
        )
        self.cards["error"].update_data(
            self.ocr_error_count, 
            current_total_for_progress,
            show_empty_progress_for_active_progress_bar=show_empty_bars
        )

        if self.start_time:
            self.info_cards["start_time"].update_value(self.start_time.strftime("%H:%M:%S"))
            elapsed_delta = datetime.now() - self.start_time
            self.info_cards["elapsed_time"].update_value(str(elapsed_delta).split('.')[0])
            if self.processed_count > 0:
                avg_time_sec = elapsed_delta.total_seconds() / self.processed_count
                self.info_cards["avg_time"].update_value(f"{avg_time_sec:.2f} 秒")
            else:
                self.info_cards["avg_time"].update_value("-")
        else: 
            self.info_cards["start_time"].update_value("-")
            self.info_cards["elapsed_time"].update_value("-")
            self.info_cards["avg_time"].update_value("-")