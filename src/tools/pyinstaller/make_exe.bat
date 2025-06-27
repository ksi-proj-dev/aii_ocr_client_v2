pyinstaller --name=dx_suite_client main.py --icon=../images/dx_suite_client.ico --onefile --noconsole

# corporate.cerをmain.pyと同じフォルダに置いた場合
# Windowsでは区切り文字に ; を使います
# pyinstaller --name=aii_ocr_client main.py --onefile --additional-hooks-dir=../hooks/ --add-data "dx-suite.crt;."
REM pyinstaller --name=aii_ocr_client main.py --additional-hooks-dir=../hooks --onefile
rem TEST
rem pyinstaller --name=aii_ocr_client main.py --additional-hooks-dir=../hooks
rem pyinstaller --name=aii_ocr_client main.py --additional-hooks-dir=../hooks --onefile
rem pyinstaller --name=aii_ocr_client main.py --additional-hooks-dir=../hooks --onefile
rem pyinstaller --name=aii_ocr_client main.py --additional-hooks-dir=../hooks --onefile --noconsole
