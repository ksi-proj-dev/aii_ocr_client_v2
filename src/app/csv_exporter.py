# csv_exporter.py

import os
import json
import csv
from typing import List
from file_model import FileInfo
from log_manager import LogManager
from config_manager import ConfigManager

def export_atypical_to_csv(successful_files: List[FileInfo], output_csv_path: str, log_manager: LogManager, model_id: str):
    """
    成功したFileInfoのリストから、dx_atypical_v2のJSON結果を読み取り、
    一つのCSVファイルに集約して出力する。
    ヘッダー行には日本語の「表示名」を使用する。

    Args:
        successful_files: 正常に処理されたFileInfoオブジェクトのリスト。
        output_csv_path: 出力するCSVファイルのフルパス。
        log_manager: ログ出力用のLogManagerインスタンス。
        model_id: 使用された帳票モデルのID (e.g., "invoice")。
    """
    log_manager.info(f"CSVエクスポート処理を開始します。対象ファイル数: {len(successful_files)}, モデル: {model_id}", context="CSV_EXPORT")
    if not successful_files:
        log_manager.info("CSVエクスポートの対象となる成功ファイルがないため、処理を終了します。", context="CSV_EXPORT")
        return

    # --- 1. モデル定義から、カラム名と表示名の対応表を作成 ---
    class_definitions = ConfigManager.get_class_definitions_for_model(model_id)
    value_to_display_map = {item['value']: item['display'] for item in class_definitions}

    # --- 2. 全てのJSON結果から、実際に存在するクラス名とデータを収集する ---
    all_class_values_in_results = set()
    results_to_process = []

    for file_info in successful_files:
        # この時点では、OcrWorkerが保存した最終的なJSONを読み込む
        # このパスの命名規則は OcrWorker.run に依存する
        temp_result_dir = os.path.join(os.path.dirname(file_info.path), "OCR結果")
        json_filename = f"{os.path.splitext(file_info.name)[0]}.json"
        json_path = os.path.join(temp_result_dir, json_filename)
        
        if not os.path.exists(json_path):
            log_manager.warning(f"結果JSONファイルが見つかりません。スキップします: {json_path}", context="CSV_EXPORT")
            continue

        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            parts = data.get("files", [{}])[0].get("ocrResults", [{}])[0].get("parts", [])
            file_results = {}
            for part in parts:
                class_name = part.get("className")
                text = part.get("text")
                if class_name and "table" not in class_name: # 明細行は除外
                    all_class_values_in_results.add(class_name)
                    # 同じクラス名が複数ある場合は改行で連結
                    if class_name in file_results:
                        file_results[class_name] = f"{file_results[class_name]}\\n{text}"
                    else:
                        file_results[class_name] = text
            
            results_to_process.append({"SourceFile": file_info.name, **file_results})

        except (json.JSONDecodeError, IndexError, KeyError) as e:
            log_manager.error(f"結果JSONの解析中にエラーが発生しました。スキップします: {json_path}, エラー: {e}", context="CSV_EXPORT", exc_info=True)
            continue

    if not results_to_process:
        log_manager.info("処理可能な結果データがなかったため、CSVファイルは作成されませんでした。", context="CSV_EXPORT")
        return
        
    # --- 3. CSVファイルに書き出す ---
    # 実際にOCR結果に含まれていたクラス名のみをヘッダーとする
    sorted_class_values = sorted(list(all_class_values_in_results))
    
    # 表示用のヘッダー行（日本語）と、DictWriter用のヘッダー行（カラム名）を作成
    header_display = ['元ファイル名'] + [value_to_display_map.get(v, v) for v in sorted_class_values]
    header_value = ['SourceFile'] + sorted_class_values
    
    try:
        with open(output_csv_path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=header_value)
            
            # ヘッダー行は手動で日本語表示名を書き込む
            header_row_dict = dict(zip(header_value, header_display))
            writer.writerow(header_row_dict)
            
            # データ行を書き込む
            writer.writerows(results_to_process)
            
        log_manager.info(f"CSVファイルを正常に出力しました: {output_csv_path}", context="CSV_EXPORT")
    except IOError as e:
        log_manager.error(f"CSVファイルの書き込み中にエラーが発生しました: {output_csv_path}, エラー: {e}", context="CSV_EXPORT", exc_info=True)