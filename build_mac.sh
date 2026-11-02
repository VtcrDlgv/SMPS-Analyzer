#!/bin/bash
# Сборка «SMPS Analyzer.app» для macOS. Нужен Python 3.9+ с Tk 8.6 или новее
# (установщик с python.org подходит; системный Python от Apple — нет).
set -e
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
    echo "Создаю окружение .venv ..."
    python3 -m venv .venv
fi
source .venv/bin/activate

echo "Устанавливаю зависимости ..."
python -m pip install --upgrade pip >/dev/null
python -m pip install -r requirements.txt pyinstaller

echo "Собираю приложение ..."
pyinstaller --noconfirm --clean SMPS_Analyzer.spec

echo
echo "Готово: dist/SMPS Analyzer.app"
echo "Приложение не подписано: при первом запуске откройте его через правый клик → «Открыть»."
