"""Текст «О программе». До сборки берётся из about.txt (его можно править); в собранной программе —
только вшитый при сборке текст (about_builtin.py генерируется файлом SMPS_Analyzer.spec)."""
import os
import sys

FALLBACK = 'SMPS Analyzer\nВерсия {version}'


def about_text(version):
    text = None
    if not getattr(sys, 'frozen', False):
        try:
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'about.txt'), encoding='utf-8') as f:
                text = f.read()
        except OSError:
            text = None
    if text is None:
        try:
            from about_builtin import TEXT as text
        except ImportError:
            text = FALLBACK
    return text.replace('{version}', version)
