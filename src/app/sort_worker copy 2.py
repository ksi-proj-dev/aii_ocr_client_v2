# sort_worker.py

import time
import threading
from typing import Optional, Dict, Any, List

from PyQt6.QtCore import QThread, pyqtSignal

# ポーリング設定のデフォルト値
DEFAULT_POLLING_INTERVAL_SECONDS = 3
DEFAULT_POLLING_MAX_ATTEMPTS = 100 # 仕分けは時間がかかる可能性を考慮

class SortWorker(QThread):
    # ステータス更新用のシグナル (例: 「仕分け中...」)
    sort_status_update = pyqtSignal(str)
    # 全処理完了を通知するシグナル (bool: 成功/失敗, object: 結果/エラー情報)
    sort_finished = pyqtSignal(bool, object)

    def __init__(self, api_client, file_paths: List[str], sort_config_id: str, log_manager):
        super().__init__()
        self.api_client = api_client
        self.file_paths = file_paths
        self.sort_config_id = sort_config_id
        self.log_manager = log_manager
        self.is_running = True

    def stop(self):
        """スレッドに停止を要求する"""
        self.is_running = False
        self.log_manager.info("SortWorker停止リクエスト受信。", context="SORT_WORKER_LIFECYCLE")

    def run(self):
        """仕分け処理のメインロジック"""
        thread_id = threading.get_ident()
        self.log_manager.info(f"SortWorkerスレッド開始。Thread ID: {thread_id}", context="SORT_WORKER_LIFECYCLE")

        try:
            # ステップA: 仕分けユニットの追加
            self.sort_status_update.emit("仕分けユニット作成中...")
            add_result, add_error = self.api_client.add_sort_unit(self.file_paths, self.sort_config_id)

            if add_error:
                self.log_manager.error(f"仕分けユニット追加APIエラー: {add_error}", context="SORT_WORKER_ERROR")
                self.sort_finished.emit(False, add_error)
                return

            sort_unit_id = add_result.get("sortUnitId")
            if not sort_unit_id:
                error_info = {"message": "レスポンスにsortUnitIdが含まれていません。", "code": "NO_SORT_UNIT_ID"}
                self.log_manager.error(f"仕分けユニット追加APIエラー: {error_info}", context="SORT_WORKER_ERROR")
                self.sort_finished.emit(False, error_info)
                return
            
            self.log_manager.info(f"仕分けユニット作成成功。sortUnitId: {sort_unit_id}", context="SORT_WORKER_INFO")

            # ステップB: 仕分け完了のポーリング
            last_status_result = None # ★★★ 最後の成功したステータス結果を保持する変数を追加
            for attempt in range(DEFAULT_POLLING_MAX_ATTEMPTS):
                if not self.is_running:
                    error_info = {"message": "処理がユーザーによって中断されました。", "code": "USER_INTERRUPT"}
                    self.sort_finished.emit(False, error_info)
                    return

                self.sort_status_update.emit(f"仕分け中... (確認 {attempt + 1}/{DEFAULT_POLLING_MAX_ATTEMPTS})")
                
                status_result, status_error = self.api_client.get_sort_unit_status(sort_unit_id)

                if status_error:
                    self.log_manager.error(f"仕分けステータス確認APIエラー: {status_error}", context="SORT_WORKER_ERROR")
                    self.sort_finished.emit(False, status_error)
                    return
                
                last_status_result = status_result # ★★★ 成功したレスポンスを保持
                status_code = status_result.get("statusCode")
                status_name = status_result.get("statusName", "")
                self.log_manager.info(f"仕分けステータス: {status_code} ({status_name})", context="SORT_WORKER_POLL")

                if status_code == 60:
                    self.log_manager.info("仕分け処理が正常に完了しました。OCR処理へ送信します...", context="SORT_WORKER_SUCCESS")
                    
                    self.sort_status_update.emit("OCR処理へ送信中...")
                    send_result, send_error = self.api_client.send_sort_result_to_ocr(sort_unit_id)

                    if send_error:
                        self.log_manager.error(f"仕分け結果OCR送信APIエラー: {send_error}", context="SORT_WORKER_ERROR")
                        self.sort_finished.emit(False, send_error)
                        return
                    
                    self.log_manager.info("OCR処理への送信が正常に完了しました。", context="SORT_WORKER_SUCCESS")
                    
                    final_success_payload = {
                        "message": "仕分けが完了し、OCR処理へ正常に送信されました。",
                        "sortUnitId": sort_unit_id,
                        "sendOcrResult": send_result,
                        "statusName": last_status_result.get("statusName", "仕分け完了") # ★★★ 保持したステータス名をペイロードに追加
                    }
                    self.sort_finished.emit(True, final_success_payload)
                    return
                
                if status_code in [35, 55]:
                    error_info = {"message": f"仕分け処理でエラーが発生しました: {status_name}", "code": f"SORT_API_ERROR_{status_code}"}
                    self.log_manager.error(f"仕分け処理APIエラー: {error_info}", context="SORT_WORKER_ERROR")
                    self.sort_finished.emit(False, error_info)
                    return

                time.sleep(DEFAULT_POLLING_INTERVAL_SECONDS)

            timeout_error = {"message": "仕分け処理がタイムアウトしました。", "code": "SORT_TIMEOUT"}
            self.log_manager.error(f"仕分けタイムアウト: {timeout_error}", context="SORT_WORKER_ERROR")
            self.sort_finished.emit(False, timeout_error)

        except Exception as e:
            self.log_manager.error(f"SortWorkerで予期せぬエラー: {e}", context="SORT_WORKER_UNEXPECTED_ERROR", exc_info=True)
            unexpected_error = {"message": f"予期せぬエラーが発生しました: {e}", "code": "UNEXPECTED_SORT_WORKER_ERROR"}
            self.sort_finished.emit(False, unexpected_error)
