import os
import io
import random
import time
import json
from flask import Flask, request, jsonify, make_response, send_file
from PyPDF2 import PdfWriter # ダミーPDF生成用

app = Flask(__name__)

# --- Helper Functions ---
def create_dummy_pdf_binary():
    """簡単な1ページのPDFバイナリを生成します。"""
    try:
        writer = PdfWriter()
        writer.add_blank_page(width=595, height=842) # A4 size
        pdf_bio = io.BytesIO()
        writer.write(pdf_bio)
        pdf_bio.seek(0)
        return pdf_bio.getvalue()
    except Exception as e:
        print(f"Error creating dummy PDF: {e}")
        return None

# --- Mock API Endpoints ---

@app.route('/api/v1/domains/aiinside/endpoints/fullocr-read-document', methods=['POST'])
def mock_fullocr_read_document():
    print(f"\n--- Request to /fullocr-read-document ---")
    print(f"Headers: {request.headers}")
    print(f"Form data: {request.form}")
    
    api_key = request.headers.get('apikey')
    if not api_key:
        print("  Error: API key is missing.")
        return jsonify({"errors": [{"errorCode": "MOCK_AUTH_ERROR", "message": "API key is missing in headers."}]}), 401 # Unauthorized

    if 'document' not in request.files:
        print("  Error: 'document' file part is missing.")
        return jsonify({"errors": [{"errorCode": "MOCK_BAD_REQUEST", "message": "Required file 'document' is missing."}]}), 400

    uploaded_file = request.files['document']
    file_name = uploaded_file.filename
    print(f"  Uploaded file: {file_name}")

    # Simulate processing time
    time.sleep(random.uniform(0.5, 2.0))

    # Simulate error based on filename
    if "error_400" in file_name:
        print("  Simulating 400 Bad Request.")
        return jsonify({"errors": [{"errorCode": "MOCK_INPUT_ERROR", "message": "Simulated bad input parameter."}]}), 400
    if "error_500" in file_name:
        print("  Simulating 500 Internal Server Error.")
        return jsonify({"issues": [{"message": "Simulated workflow execution error."}]}), 500

    # Get options from form data
    character_extraction_option = request.form.get('character_extraction', '0')
    fulltext_option = request.form.get('fulltext', '0')
    concatenate_option = request.form.get('concatenate', '1')
    
    print(f"  Options: char_extract='{character_extraction_option}', fulltext_mode='{fulltext_option}', concatenate='{concatenate_option}'")

    # Construct dummy JSON response based on API spec
    # (This is a simplified version; more details can be added as needed)
    results_part = []
    text_block_1 = {
        "text": f"Mock text block 1 for {file_name}.",
        "bbox": {"top": 0.1, "left": 0.1, "bottom": 0.15, "right": 0.8},
        "vertices": [{"x": 0.1, "y": 0.1}, {"x": 0.8, "y": 0.1}, {"x": 0.8, "y": 0.15}, {"x": 0.1, "y": 0.15}],
        "detectConfidence": 0.98,
        "ocrConfidence": 0.95
    }
    if character_extraction_option == '1':
        text_block_1["characters"] = [
            {"char": "M", "ocrConfidence": 0.99, "bbox": {"top": 0.1, "left": 0.1, "bottom": 0.15, "right": 0.12}},
            {"char": "o", "ocrConfidence": 0.98, "bbox": {"top": 0.1, "left": 0.12, "bottom": 0.15, "right": 0.14}},
            # ... add more dummy characters ...
        ]
    results_part.append(text_block_1)

    page_result_data = {
        "fileName": file_name,
        "fulltext": f"This is the full mock OCR text for {file_name}. Concatenate option: {concatenate_option}.",
    }

    if fulltext_option == '0': # Detailed mode
        page_result_data["aGroupingFulltext"] = f"Grouped mock text for {file_name}."
        page_result_data["results"] = results_part
        page_result_data["tables"] = [ # Dummy table structure
            {
                "bbox": {"top": 0.2, "left": 0.1, "bottom": 0.4, "right": 0.9},
                "cells": [
                    {"row_index": 0, "col_index": 0, "text": "Header 1", "bbox": {}},
                    {"row_index": 0, "col_index": 1, "text": "Header 2", "bbox": {}},
                    {"row_index": 1, "col_index": 0, "text": "Data A", "bbox": {}},
                    {"row_index": 1, "col_index": 1, "text": "Data B", "bbox": {}},
                ]
            }
        ]
        page_result_data["textGroups"] = [ # Dummy textGroups structure
            {
                "allText": "Group 1 text.",
                "isTable": False,
                "texts": [results_part[0]] # Reuse the first text block for simplicity
            }
        ]
        page_result_data["deskewAngle"] = 0

    response_data = [{
        "page": 0, # Assuming single page for mock, can be extended
        "result": page_result_data,
        "status": "success"
    }]
    
    print(f"  Responding with success JSON for {file_name}.")
    return jsonify(response_data), 200


@app.route('/api/v1/domains/aiinside/endpoints/make-searchable-pdf', methods=['POST'])
def mock_make_searchable_pdf():
    print(f"\n--- Request to /make-searchable-pdf ---")
    print(f"Headers: {request.headers}")
    
    api_key = request.headers.get('apikey')
    if not api_key:
        print("  Error: API key is missing.")
        return jsonify({"errors": [{"errorCode": "MOCK_AUTH_ERROR", "message": "API key is missing in headers."}]}), 401

    if 'document' not in request.files:
        print("  Error: 'document' file part is missing.")
        return jsonify({"errors": [{"errorCode": "MOCK_BAD_REQUEST", "message": "Required file 'document' is missing."}]}), 400

    uploaded_file = request.files['document']
    file_name = uploaded_file.filename
    print(f"  Uploaded file for PDF: {file_name}")

    # Simulate processing time
    time.sleep(random.uniform(0.5, 1.5))

    # Simulate error based on filename
    if "pdf_error_400" in file_name:
        print("  Simulating 400 Bad Request for PDF.")
        return jsonify({"errors": [{"errorCode": "MOCK_PDF_INPUT_ERROR", "message": "Simulated bad input for PDF."}]}), 400
    if "pdf_error_500" in file_name:
        print("  Simulating 500 Internal Server Error for PDF.")
        return jsonify({"message": "Simulated PDF workflow execution error."}), 500

    dummy_pdf_content = create_dummy_pdf_binary()
    if dummy_pdf_content:
        print(f"  Responding with dummy PDF for {file_name}.")
        response = make_response(dummy_pdf_content)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename="mock_searchable_{file_name}.pdf"'
        return response, 200
    else:
        print("  Error generating dummy PDF.")
        return jsonify({"message": "Error generating mock PDF on server."}), 500

if __name__ == '__main__':
    print("Starting Cube Mock Server on http://localhost:5000")
    app.run(debug=True, host='0.0.0.0', port=5000)
