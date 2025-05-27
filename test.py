# class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.log_manager = LogManager()
        self.log_manager.debug("MainWindow initializing...", context="MAINWIN_LIFECYCLE")
        self.setWindowTitle("AI inside Cube Client Ver.0.0.11") # バージョンアップ
        self.config = ConfigManager.load()

        self.log_widget = QTextEdit()
        self.log_manager.log_message_signal.connect(self.append_log_message_to_widget)
        
        self.api_client = CubeApiClient(self.config, self.log_manager)
        self.ocr_worker = None
        self.update_timer = QTimer(self); self.update_timer.setSingleShot(True); self.update_timer.timeout.connect(self.perform_batch_list_view_update)
        
        size_cfg = self.config.get("window_size", {"width": 1000, "height": 700}); state_cfg = self.config.get("window_state", "normal"); pos_cfg = self.config.get("window_position"); self.resize(size_cfg["width"], size_cfg["height"])
        if not pos_cfg or pos_cfg.get("x") is None or pos_cfg.get("y") is None:
            try: screen_geometry = QApplication.primaryScreen().geometry(); self.move((screen_geometry.width() - self.width()) // 2, (screen_geometry.height() - self.height()) // 2)
            except Exception as e: self.log_manager.error("Failed to center window.", context="UI_ERROR", exception_info=e); self.move(100, 100)
        else: self.move(pos_cfg["x"], pos_cfg["y"])
        if state_cfg == "maximized": self.showMaximized()

        self.central_widget = QWidget(); self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)
        # --- ここから変更: main_layoutのマージン設定 ---
        self.main_layout.setContentsMargins(2, 2, 2, 6) # 左, 上, 右, 下 のマージン (下は少し残す)
        # --- ここまで変更 ---
        
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.stack = QStackedWidget(); self.summary_view = SummaryView(); self.processed_files_info = []; self.list_view = ListView(self.processed_files_info)
        self.stack.addWidget(self.summary_view); self.stack.addWidget(self.list_view)
        self.splitter.addWidget(self.stack)
        
        self.log_container = QWidget()
        log_layout_inner = QVBoxLayout(self.log_container)
        log_layout_inner.setContentsMargins(0,0,0,0) # ログコンテナ内部のマージンは0
        # --- ここから変更: log_headerのスタイルシート変更 (padding-bottom削除または調整) ---
        self.log_header = QLabel("ログ：")
        self.log_header.setStyleSheet("margin-left: 6px; padding-bottom: 0px; font-weight: bold;") # padding-bottom を 0px に
        # --- ここまで変更 ---
        log_layout_inner.addWidget(self.log_header)
        
        self.log_widget.setReadOnly(True)
        self.log_widget.setStyleSheet("""
            QTextEdit {
                font-family: Consolas, Meiryo, monospace; 
                font-size: 9pt; 
                border: 1px solid #D0D0D0;
                margin: 0px;
            }
            QTextEdit QScrollBar:vertical { /* スクロールバースタイルは前回修正済み */
                border: 1px solid #C0C0C0; background: #F0F0F0; width: 15px; margin: 0px;
            }
            QTextEdit QScrollBar::handle:vertical { background: #A0A0A0; min-height: 20px; border-radius: 7px; }
            QTextEdit QScrollBar::add-line:vertical, QTextEdit QScrollBar::sub-line:vertical { border: none; background: none; height: 0px; width: 0px; }
            QTextEdit QScrollBar::up-arrow:vertical, QTextEdit QScrollBar::down-arrow:vertical { height: 0px; width: 0px; background: none; }
            QTextEdit QScrollBar::add-page:vertical, QTextEdit QScrollBar::sub-page:vertical { background: none; }
        """)
        self.log_widget.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.log_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        log_layout_inner.addWidget(self.log_widget)
        self.log_container.setStyleSheet("margin: 0px 6px 6px 6px;") # log_containerのマージン
        
        self.splitter.addWidget(self.log_container)
        self.splitter.setStyleSheet("QSplitter::handle { background-color: #CCCCCC; height: 2px; }")
        splitter_sizes = self.config.get("splitter_sizes");
        if splitter_sizes and len(splitter_sizes) == 2 and sum(splitter_sizes) > 0 : self.splitter.setSizes(splitter_sizes)
        else: default_height = self.height(); initial_splitter_sizes = [int(default_height * 0.65), int(default_height * 0.35)]; self.splitter.setSizes(initial_splitter_sizes)
        self.main_layout.addWidget(self.splitter)
        
        self.input_folder_path = self.config.get("last_target_dir", "")
        if self.input_folder_path and os.path.isdir(self.input_folder_path):
            self.log_manager.info(f"前回終了時の入力フォルダを読み込みました: {self.input_folder_path}", context="SYSTEM_INIT")
            self.perform_initial_scan() 
        elif self.input_folder_path:
            self.log_manager.warning(f"前回指定された入力フォルダ '{self.input_folder_path}' は無効です。クリアします。", context="SYSTEM_INIT")
            self.input_folder_path = ""
        else: self.log_manager.info("前回終了時の入力フォルダ指定はありませんでした。", context="SYSTEM_INIT")

        self.setup_toolbar_and_folder_labels()
        self.is_ocr_running = False; self.current_view = self.config.get("current_view", 0); self.stack.setCurrentIndex(self.current_view)
        log_visible = self.config.get("log_visible", True); self.log_container.setVisible(log_visible)
        self.update_ocr_controls(); self.check_input_folder_validity()
        self.log_manager.info("Application initialized successfully.", context="SYSTEM_LIFECYCLE")

# ... (他のメソッドは変更なし) ...