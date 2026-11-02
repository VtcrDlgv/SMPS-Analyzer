@echo off
rem Сборка портативного SMPS_Analyzer.exe. Нужен установленный Python 3.9+ (python.org, с галочкой tcl/tk).
chcp 65001 >nul
cd /d "%~dp0"

if not exist .venv (
    echo Создаю окружение .venv ...
    python -m venv .venv || goto :error
)
call .venv\Scripts\activate.bat || goto :error

echo Устанавливаю зависимости ...
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt pyinstaller || goto :error

echo Собираю exe ...
pyinstaller --noconfirm --clean SMPS_Analyzer.spec || goto :error

echo.
echo Готово: dist\SMPS_Analyzer.exe
echo Этот файл можно копировать на любой компьютер с Windows 10/11, установка не нужна.
pause
exit /b 0

:error
echo.
echo Сборка не удалась, см. сообщения выше.
pause
exit /b 1
