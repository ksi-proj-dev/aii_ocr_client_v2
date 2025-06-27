cd aii_ocr_client_v2/src
pyinstaller --name=dx_suite_client app/main.py --icon=images/dx_suite_client.ico --onefile --noconsole --add-data "images:images"
