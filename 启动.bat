@echo off
rem 开发期启动：双击即可（无黑框）。正式版 P6 打包成安装包后不再需要本文件
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0app.py"
