"""Отдельные окна: журнал, справка, «О программе», диапазон, анализ, таблицы, сравнение, динамика."""
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk

import plots
import smps_data as sd
import specs
from ui_common import (CARD, INK, MUTED, PURPLE, PURPLE_LIGHT, FlatButton, FlatCheck, FlatRadio, px, ui_font,
                       widget_bg)


_STYLE_FONTS = []   # ссылки на шрифты стилей: иначе Python удалит их, и ttk вернётся к мелкому шрифту


def setup_styles(root):
    """Таблицы и вкладки ttk с учётом масштаба экрана (по умолчанию строки Treeview не растут с DPI)."""
    st = ttk.Style(root)
    body, head = ui_font(10), ui_font(10, 'bold')
    _STYLE_FONTS.extend([body, head])
    st.configure('Treeview', rowheight=px(24), font=body)
    st.configure('Treeview.Heading', font=head)
    st.configure('TNotebook.Tab', padding=(px(10), px(4)), font=body)


class Window(tk.Toplevel):
    """Небольшое окно поверх главного."""

    def __init__(self, app, title, size=None, modal=False):
        super().__init__(app.root)
        self.app = app
        self.title(title)
        self.transient(app.root)
        try:
            self.iconphoto(False, app.icon)
        except Exception:
            pass
        if size:
            self.geometry(f'{px(size[0])}x{px(size[1])}')
        self.body = tk.Frame(self, padx=px(12), pady=px(10))
        self.body.pack(fill=tk.BOTH, expand=True)
        self.bind('<Escape>', lambda e: self.destroy())
        if modal:
            self.after_idle(self._grab)

    def _grab(self):
        try:
            self.grab_set()
        except tk.TclError:
            pass

    def buttons(self, items, side=tk.BOTTOM):
        row = tk.Frame(self.body)
        row.pack(side=side, fill=tk.X, pady=(px(8), 0))
        for text, cmd, primary in reversed(items):
            FlatButton(row, text, command=cmd, primary=primary).pack(side=tk.RIGHT, padx=px(3))
        return row


# ------------------------------------------------------------
# Журнал, справка, «О программе»
# ------------------------------------------------------------

class JournalWindow(Window):
    def __init__(self, app):
        super().__init__(app, 'Журнал — SMPS Analyzer', (720, 340))
        self.text = scrolledtext.ScrolledText(self.body, wrap=tk.WORD, font=ui_font(10), relief='solid', bd=1)
        self.buttons([('Копировать всё', self._copy, False), ('Закрыть', self.destroy, False)])
        self.text.pack(fill=tk.BOTH, expand=True)
        for line in app.log_lines:
            self.text.insert(tk.END, line + '\n')
        self.text.see(tk.END)
        self.text.configure(state='disabled')

    def append(self, line):
        self.text.configure(state='normal')
        self.text.insert(tk.END, line + '\n')
        self.text.see(tk.END)
        self.text.configure(state='disabled')

    def _copy(self):
        self.clipboard_clear()
        self.clipboard_append('\n'.join(self.app.log_lines))


def _text_window(app, title, text, size, header_image=None):
    w = Window(app, title, size)
    if header_image is not None:
        tk.Label(w.body, image=header_image).pack(anchor='w', pady=(0, px(6)))
    t = scrolledtext.ScrolledText(w.body, wrap=tk.WORD, font=ui_font(10), relief='flat', bd=0,
                                  bg=widget_bg(w.body), padx=px(4), pady=px(4))
    t.tag_configure('h', font=ui_font(12, 'bold'), spacing1=px(8), spacing3=px(2))
    t.tag_configure('title', font=ui_font(15, 'bold'), spacing3=px(4))
    t.tag_configure('b', font=ui_font(10, 'bold'))
    w.buttons([('Закрыть', w.destroy, True)])
    t.pack(fill=tk.BOTH, expand=True)
    return w, t


def show_about(app, version):
    from about import about_text
    text = about_text(version)
    w, t = _text_window(app, 'О программе', text, (640, 620), header_image=app.icon_large)
    headings = {'Назначение', 'Основные возможности', 'Разработчик', 'Авторские права', 'Ограничение ответственности',
                'Использованные методы', 'Сторонние компоненты', 'Техническая поддержка'}
    for k, line in enumerate(text.splitlines()):
        tag = 'title' if k == 0 else ('h' if line.strip() in headings else None)
        t.insert(tk.END, line + '\n', tag)
    t.configure(state='disabled')
    return w


HELP = [
    ('Начало работы', [
        'Нажмите «Выберите файл» или «Файл → Открыть файл» и выберите экспорт SMPS из Aerosol Instrument Manager '
        '(текст с запятой или табуляцией). Можно выбрать сразу несколько файлов — каждый откроется своей вкладкой.',
        'Семплы сразу раскладываются на группы по паузам между запусками («Авто»). Поправьте группы в зоне '
        '«Группы для усреднения» и нажмите «Построить».',
    ]),
    ('Вкладки и проект', [
        'Внизу окна — вкладки открытых файлов (до 16). «+» добавляет пустую вкладку, × закрывает вкладку: файл '
        'удаляется из проекта, но не с диска.',
        '«Файл → Сохранить проект» сохраняет всё — группы, названия, исключения, диапазоны, настройки — вместе с '
        'копиями исходных файлов в один архив .smpsa. Сохранение идёт в фоне; если закрыть программу во время '
        'сохранения, она закроется после его окончания. Построенные графики при открытии проекта строятся снова '
        'автоматически: текущая вкладка сразу, остальные в фоне.',
        'Справа в строке вкладок во время долгих операций (построение графиков, сохранение, экспорт) показан '
        'прогресс.',
    ]),
    ('Экспорт', [
        '«Экспорт CSV» — размер и по столбцу на группу, только каналы в диапазоне (для Origin).',
        '«Сводная таблица» — книга Excel: данные графиков, статистики в диапазоне и по данным прибора, '
        'аппроксимация, сведения и диаграммы Excel (сводная и по группам, с линиями статистик), для текущего файла '
        'или для всех файлов проекта.',
    ]),
    ('Диапазон размеров', [
        '«Правка → Ограничить диапазон» задаёт нижний и верхний пределы. На тепловой карте пределы показаны красными '
        'линиями: их можно тянуть мышью (прилипают к границам каналов), двойной щелчок по красному числу у шкалы — '
        'ввести значение. В расчёт идут каналы, целиком лежащие в диапазоне; CSV содержит только их.',
    ]),
    ('Анализ', [
        'Представление: dN (концентрация в канале, как в файле) или dN/dlogDp.',
        'Логнормальная аппроксимация: 1–3 моды для всех групп файла (или проекта); результаты — на графиках групп и в '
        'сводной таблице («Экспорт → Сводная таблица»).',
        'Интеграл в диапазоне: число частиц N, поверхность S, объём V и их доли в заданном интервале размеров.',
        'Сравнение групп: наложение групп из разных вкладок на один график.',
        'Динамика по файлу: параметр по каждому семплу записи.',
    ]),
]


def show_help(app, gestures):
    w, t = _text_window(app, 'Справка — SMPS Analyzer', '', (760, 640))
    t.insert(tk.END, 'SMPS Analyzer — справка\n', 'title')
    for head, paras in HELP:
        t.insert(tk.END, head + '\n', 'h')
        for p in paras:
            t.insert(tk.END, p + '\n\n')
    t.insert(tk.END, 'Управление группами\n', 'h')
    for g, d in gestures:
        t.insert(tk.END, g, 'b')
        t.insert(tk.END, ' — ' + d + '\n')
    t.configure(state='disabled')
    return w


# ------------------------------------------------------------
# Ввод чисел
# ------------------------------------------------------------

def parse_float(text):
    try:
        return float(str(text).replace(',', '.').strip())
    except ValueError:
        return None


def _field(parent, label, value, width=10, unit=''):
    row = tk.Frame(parent)
    row.pack(fill=tk.X, pady=px(3))
    tk.Label(row, text=label, width=18, anchor='w').pack(side=tk.LEFT)
    var = tk.StringVar(value=value)
    entry = tk.Entry(row, textvariable=var, width=width, font=ui_font(10), relief='solid', bd=1)
    entry.pack(side=tk.LEFT, ipady=px(2))
    var.entry = entry
    if unit:
        tk.Label(row, text=unit, fg=MUTED).pack(side=tk.LEFT, padx=px(6))
    return var


class RangeDialog(Window):
    """Правка → Ограничить диапазон"""

    def __init__(self, app, doc):
        super().__init__(app, 'Ограничить диапазон', modal=True)
        self.doc = doc
        e = doc.data.edges
        rng = doc.range
        self.enabled = tk.BooleanVar(value=True)     # открыли «Ограничить диапазон» — значит, ограничиваем
        FlatCheck(self.body, 'Ограничить диапазон размеров', self.enabled).pack(anchor='w', pady=(0, px(6)))
        self.lo = _field(self.body, 'Нижний предел', f"{rng['lo']:.1f}", unit='нм')
        self.hi = _field(self.body, 'Верхний предел', f"{rng['hi']:.1f}", unit='нм')
        tk.Label(self.body, text=f'Каналы прибора: {e[0]:.1f}–{e[-1]:.1f} нм ({len(e) - 1} каналов).\n'
                                 'В расчёт идут каналы, целиком лежащие в диапазоне.',
                 fg=MUTED, justify=tk.LEFT).pack(anchor='w', pady=(px(6), 0))
        self.buttons([('Весь диапазон', self._reset, False), ('Отмена', self.destroy, False), ('OK', self._ok, True)])
        # Enter применяет то, что сейчас в окне (снятая галочка — снять ограничение)
        self.bind('<Return>', lambda ev: self._ok())
        self.bind('<KP_Enter>', lambda ev: self._ok())
        self.after(50, self._focus)

    def _focus(self):
        try:
            self.focus_force()
            self.lo.entry.focus_set()
            self.lo.entry.select_range(0, tk.END)
        except tk.TclError:
            pass

    def _reset(self):
        e = self.doc.data.edges
        self.lo.set(f'{e[0]:.1f}')
        self.hi.set(f'{e[-1]:.1f}')

    def _ok(self):
        lo, hi = parse_float(self.lo.get()), parse_float(self.hi.get())
        if self.app.apply_range(self.doc, self.enabled.get(), lo, hi, parent=self):
            self.destroy()


class FitDialog(Window):
    """Анализ → Логнормальная аппроксимация (для групп файла или всего проекта)."""

    def __init__(self, app, doc):
        super().__init__(app, 'Логнормальная аппроксимация', modal=True)
        self.doc = doc
        self.enabled = tk.BooleanVar(value=True)      # открыли диалог — значит, аппроксимация нужна
        self.modes = tk.IntVar(value=doc.fit.get('modes', 1))
        self.all_files = tk.BooleanVar(value=False)
        FlatCheck(self.body, 'Аппроксимировать группы', self.enabled).pack(anchor='w')
        row = tk.Frame(self.body)
        row.pack(anchor='w', pady=px(6))
        tk.Label(row, text='Число мод:').pack(side=tk.LEFT)
        for m in (1, 2, 3):
            FlatRadio(row, str(m), self.modes, m).pack(side=tk.LEFT, padx=px(6))
        FlatCheck(self.body, 'Применить ко всем файлам проекта', self.all_files).pack(anchor='w')
        tk.Label(self.body, text='Подбор суммы логнормальных мод по dN/dlogDp в выбранном диапазоне\n'
                                 '(метод наименьших квадратов, Левенберг–Марквардт). Результат — на графиках групп\n'
                                 'после «Перестроить» и в сводной таблице (вкладка «Аппроксимация»).',
                 fg=MUTED, justify=tk.LEFT).pack(anchor='w', pady=(px(8), 0))
        self.buttons([('Отмена', self.destroy, False), ('OK', self._ok, True)])

    def _ok(self):
        docs = self.app.project.file_docs if self.all_files.get() else [self.doc]
        for d in docs:
            d.fit = {'enabled': self.enabled.get(), 'modes': int(self.modes.get())}
        self.app.on_analysis_changed()
        self.destroy()


class SummaryExportDialog(Window):
    """Экспорт → Сводная таблица: для какого файла (или всех) записать книгу Excel. on_ok(all_files)."""

    def __init__(self, app, on_ok):
        super().__init__(app, 'Сводная таблица', modal=True)
        self.on_ok = on_ok
        n = len(app.project.file_docs)
        self.scope = tk.StringVar(value='doc')
        tk.Label(self.body, text='Записать в книгу Excel (.xlsx):').pack(anchor='w', pady=(0, px(4)))
        FlatRadio(self.body, f'Текущий файл — {app.project.doc.data.name}', self.scope, 'doc').pack(anchor='w')
        all_rb = FlatRadio(self.body, f'Все файлы проекта ({n})', self.scope, 'all')
        all_rb.pack(anchor='w', pady=(px(2), 0))
        tk.Label(self.body, text='Листы: данные графиков («Спектры»), статистики в диапазоне и по данным прибора,\n'
                                 'аппроксимация (если включена), сведения и графики — диаграммы Excel по этим данным.',
                 fg=MUTED, justify=tk.LEFT).pack(anchor='w', pady=(px(8), 0))
        self.buttons([('Отмена', self.destroy, False), ('Сохранить', self._ok, True)])
        self.bind('<Return>', lambda e: self._ok())

    def _ok(self):
        all_files = self.scope.get() == 'all'
        self.destroy()
        self.on_ok(all_files)


class IntegralDialog(Window):
    """Интеграл в диапазоне: N, S, V. on_ok(lo, hi, all_files)."""

    def __init__(self, app, lo, hi, on_ok, allow_scope=True, on_mouse=None):
        super().__init__(app, 'Интеграл в диапазоне')
        self.on_ok = on_ok
        self.lo = _field(self.body, 'От', f'{lo:.1f}', unit='нм')
        self.hi = _field(self.body, 'До', f'{hi:.1f}', unit='нм')
        self.all_files = tk.BooleanVar(value=False)
        if allow_scope:
            FlatCheck(self.body, 'Для всех файлов проекта', self.all_files).pack(anchor='w', pady=(px(4), 0))
        tk.Label(self.body, text='N — число частиц, S — поверхность, V — объём частиц.\n'
                                 'Учитываются каналы, целиком лежащие в интервале; доли — от величин\n'
                                 'по всему (ограниченному) диапазону.', fg=MUTED, justify=tk.LEFT).pack(
            anchor='w', pady=(px(8), 0))
        items = [('Отмена', self.destroy, False), ('Рассчитать', self._ok, True)]
        if on_mouse:
            items.insert(0, ('Выделить мышью', lambda: on_mouse(self), False))
        self.buttons(items)
        self.bind('<Return>', lambda ev: self._ok())

    def set_range(self, lo, hi):
        self.lo.set(f'{lo:.1f}')
        self.hi.set(f'{hi:.1f}')
        self.deiconify()
        self.lift()

    def _ok(self):
        lo, hi = parse_float(self.lo.get()), parse_float(self.hi.get())
        if lo is None or hi is None or lo >= hi:
            messagebox.showwarning('Интеграл в диапазоне', 'Проверьте значения: «от» должно быть меньше «до».',
                                   parent=self)
            return
        self.on_ok(lo, hi, self.all_files.get())


# ------------------------------------------------------------
# Таблицы
# ------------------------------------------------------------

def fmt(v):
    if isinstance(v, str):
        return v
    if v is None or not np.isfinite(v):
        return '—'
    a = abs(v)
    if a >= 1e5 or (0 < a < 1e-2):
        return f'{v:.3e}'
    if a >= 100:
        return f'{v:.1f}'
    return f'{v:.3g}' if a < 10 else f'{v:.2f}'


class TableWindow(Window):
    """Таблица с вкладками; копирование в буфер (для Excel) и сохранение CSV."""

    def __init__(self, app, title, tabs, size=(980, 460), top=None):
        super().__init__(app, title, size)
        self.tabs = []
        if top:
            top(self.body)
        self.nb = ttk.Notebook(self.body)
        self.buttons([('Копировать', self._copy, False), ('Сохранить CSV', self._save, False),
                      ('Закрыть', self.destroy, False)])
        self.nb.pack(fill=tk.BOTH, expand=True)
        self.set_tabs(tabs)

    def set_tabs(self, tabs):
        for child in self.nb.tabs():
            self.nb.forget(child)
        self.tabs = tabs
        for name, columns, rows in tabs:
            frame = tk.Frame(self.nb)
            tv = ttk.Treeview(frame, columns=list(range(len(columns))), show='headings')
            sb = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=tv.yview)
            sbx = ttk.Scrollbar(frame, orient=tk.HORIZONTAL, command=tv.xview)
            tv.configure(yscrollcommand=sb.set, xscrollcommand=sbx.set)
            f = ui_font(10)
            for k, c in enumerate(columns):
                width = max(f.measure(c) + px(20), max((f.measure(fmt(r[k])) for r in rows), default=0) + px(16))
                tv.heading(k, text=c)
                tv.column(k, width=min(width, px(320)), anchor='w' if k < 2 else 'e', stretch=False)
            for r in rows:
                tv.insert('', tk.END, values=[fmt(v) for v in r])
            sb.pack(side=tk.RIGHT, fill=tk.Y)
            sbx.pack(side=tk.BOTTOM, fill=tk.X)
            tv.pack(fill=tk.BOTH, expand=True)
            self.nb.add(frame, text=name)

    def _current(self):
        i = self.nb.index('current') if self.tabs else 0
        return self.tabs[i]

    def _copy(self):
        name, columns, rows = self._current()
        lines = ['\t'.join(columns)] + ['\t'.join(fmt(v) if isinstance(v, str) else
                                                  ('' if v is None or not np.isfinite(v) else f'{v:.6g}')
                                                  for v in r) for r in rows]
        self.clipboard_clear()
        self.clipboard_append('\n'.join(lines))

    def _save(self):
        import csv
        name, columns, rows = self._current()
        path = filedialog.asksaveasfilename(parent=self, title='Сохранить таблицу', defaultextension='.csv',
                                            filetypes=[('CSV', '*.csv')], initialfile=name.split(' (')[0] + '.csv',
                                            initialdir=self.app.last_dir())
        if not path:
            return
        with open(path, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.writer(f)
            w.writerow(columns)
            for r in rows:
                w.writerow([v if isinstance(v, str) else ('' if v is None or not np.isfinite(v) else f'{v:.6g}')
                            for v in r])
        self.app.log(f'Таблица сохранена: {path}')


def summary_tabs(app, entries):
    """Вкладки сводной таблицы. entries: [(документ, номер группы)]."""
    calc, inst, fitrows = [], [], []
    any_fit = False
    for doc, k in entries:
        inc = doc.model.included(k)
        title = specs.group_title(doc, k)
        name = doc.data.name
        if not inc:
            continue
        st = sd.group_stats(doc.data, inc, doc.range)
        rng = doc.range
        rtxt = f"{rng['lo']:.1f}–{rng['hi']:.1f}" if rng.get('enabled') else 'весь'
        n_all = doc.model.groups[k]['b'] - doc.model.groups[k]['a'] + 1
        N, sdN = st['total_conc_val'], st['total_conc_sd']
        calc.append([name, title, len(inc), n_all - len(inc), rtxt, N, sdN, 100 * sdN / N if N else np.nan,
                     st['mode_val'], st['median_val'], st['mean_val'], st['geo_mean_val'], st['gsd_val']])
        ins = sd.instrument_stats(doc.data, inc)
        inst.append([name, title, len(inc), ins['mode'], ins['median'], ins['mean'], ins['geo_mean'], ins['gsd'],
                     ins['total_conc'], ins['total_conc_sd'],
                     100 * ins['total_conc_sd'] / ins['total_conc'] if ins['total_conc'] else np.nan])
        if doc.fit.get('enabled'):
            any_fit = True
            res = app.fit_for(doc, k)
            if res is None:
                fitrows.append([name, title, '—', np.nan, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan])
            else:
                for j, m in enumerate(res['modes']):
                    fitrows.append([name, title, str(j + 1), m['N'], m['N_err'], m['CMD'], m['CMD_err'], m['GSD'],
                                    m['GSD_err'], res['r2']])
    tabs = [
        ('Расчёт в диапазоне', ['Файл', 'Группа', 'Семплов', 'Исключено', 'Диапазон, нм', 'N, см⁻³', 'σ(N)', 'CV, %',
                                'Мода, нм', 'Медиана, нм', 'Среднее, нм', 'Геом. среднее (CMD), нм', 'GSD'], calc),
        ('По данным прибора (весь диапазон)', ['Файл', 'Группа', 'Семплов', 'Мода, нм', 'Медиана, нм', 'Среднее, нм',
                                               'Геом. среднее, нм', 'GSD', 'N, см⁻³', 'σ(N)', 'CV, %'], inst),
    ]
    if any_fit:
        tabs.append(('Аппроксимация', ['Файл', 'Группа', 'Мода №', 'N, см⁻³', '± N', 'CMD, нм', '± CMD', 'GSD',
                                       '± GSD', 'R²'], fitrows))
    return tabs


def integral_rows(entries, lo, hi):
    """entries: [(подпись файла, заголовок, item)] -> строки таблицы интегралов."""
    rows = []
    for fname, title, it in entries:
        r = sd.integrals(it['Dx'], it['edges'], it['dn'], lo, hi, base_mask=it['mask'])
        rows.append([fname, title, r['n_channels'], r['N'], 100 * r['N_frac'], r['S'], 100 * r['S_frac'],
                     r['V'], 100 * r['V_frac']])
    return rows


INTEGRAL_COLUMNS = ['Файл', 'Группа', 'Каналов', 'N, см⁻³', 'доля N, %', 'S, мкм²/см³', 'доля S, %',
                    'V, мкм³/см³', 'доля V, %']


# ------------------------------------------------------------
# Сравнение групп из разных файлов
# ------------------------------------------------------------

class CompareDialog(Window):
    """Выбор групп из вкладок проекта. on_ok(selection) — [{'file', 'first', 'last'}]."""

    def __init__(self, app, preselect, on_ok):
        super().__init__(app, 'Сравнение групп', (620, 520), modal=True)
        self.on_ok = on_ok
        tk.Label(self.body, text='Отметьте группы для наложения на один график (щелчок — отметить/снять;\n'
                                 'щелчок по файлу — все его группы).', fg=MUTED, justify=tk.LEFT).pack(anchor='w')
        frame = tk.Frame(self.body)
        frame.pack(fill=tk.BOTH, expand=True, pady=px(6))
        self.tv = ttk.Treeview(frame, show='tree', selectmode='none')
        sb = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.tv.yview)
        self.tv.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tv.pack(fill=tk.BOTH, expand=True)
        self.checked = {(s['file'], s['first'], s['last']) for s in preselect}
        self.nodes = {}
        for f, doc in enumerate(app.project.file_docs):
            parent = self.tv.insert('', tk.END, text=doc.data.name, open=True)
            self.nodes[parent] = ('file', f)
            for k in range(len(doc.model.groups)):
                a, b = doc.group_key(k)
                node = self.tv.insert(parent, tk.END, text='')
                self.nodes[node] = ('group', (f, a, b), specs.group_title(doc, k))
        self._paint()
        self.tv.bind('<Button-1>', self._click)
        self.buttons([('Все', lambda: self._all(True), False), ('Ничего', lambda: self._all(False), False),
                      ('Отмена', self.destroy, False), ('Построить', self._ok, True)])

    def _paint(self):
        if not hasattr(self, '_imgs'):        # отметки — картинками, как галочки в окне (не зависят от шрифта)
            from PIL import ImageTk
            self._imgs = {v: ImageTk.PhotoImage(FlatCheck._image(v, '#ffffff'), master=self) for v in (True, False)}
        for node, info in self.nodes.items():
            if info[0] == 'group':
                self.tv.item(node, text='  ' + info[2], image=self._imgs[info[1] in self.checked])

    def _click(self, e):
        node = self.tv.identify_row(e.y)
        if not node or node not in self.nodes:
            return
        info = self.nodes[node]
        if info[0] == 'group':
            self.checked ^= {info[1]}
        else:
            keys = [self.nodes[c][1] for c in self.tv.get_children(node)]
            if all(k in self.checked for k in keys):
                self.checked -= set(keys)
            else:
                self.checked |= set(keys)
        self._paint()

    def _all(self, value):
        keys = {info[1] for info in self.nodes.values() if info[0] == 'group'}
        self.checked = set(keys) if value else set()
        self._paint()

    def _ok(self):
        order = [info[1] for node, info in self.nodes.items() if info[0] == 'group' and info[1] in self.checked]
        if not order:
            messagebox.showinfo('Сравнение групп', 'Отметьте хотя бы одну группу.', parent=self)
            return
        self.destroy()
        self.on_ok([{'file': f, 'first': a, 'last': b} for f, a, b in order])


# ------------------------------------------------------------
# Динамика по файлу
# ------------------------------------------------------------

class DynamicsWindow(Window):
    def __init__(self, app, doc):
        super().__init__(app, f'Динамика по файлу — {doc.data.name}', (1100, 640))
        self.doc = doc
        top = tk.Frame(self.body)
        top.pack(fill=tk.X)
        tk.Label(top, text='Параметр:').pack(side=tk.LEFT)
        self.param = tk.StringVar(value=specs.DYN_PARAMS[0][0])
        cb = ttk.Combobox(top, textvariable=self.param, state='readonly', width=26, font=ui_font(10),
                          values=[p[0] for p in specs.DYN_PARAMS])
        cb.pack(side=tk.LEFT, padx=px(6))
        cb.bind('<<ComboboxSelected>>', lambda e: self.redraw())
        self.computed = tk.BooleanVar(value=True)
        for val, text in ((True, 'расчёт в диапазоне'), (False, 'данные прибора')):
            FlatRadio(top, text, self.computed, val, command=self.redraw).pack(
                side=tk.LEFT, padx=px(6))
        FlatButton(top, 'Обновить', command=self.redraw).pack(side=tk.RIGHT)
        self.buttons([('Сохранить PNG', self._png, False), ('Сохранить CSV', self._csv, False),
                      ('Закрыть', self.destroy, False)])
        self.spec = self._spec()
        self.fig = plots.make_figure(self.spec)
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.body)
        tb = NavigationToolbar2Tk(self.canvas, self.body, pack_toolbar=False)
        tb.update()
        tb.pack(side=tk.BOTTOM, fill=tk.X)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True, pady=(px(6), 0))
        self.canvas.draw()

    def _spec(self):
        return specs.dynamics_spec(self.doc, self.app.project.settings, self.param.get(), self.computed.get(),
                                   (11.0, 5.5))

    def redraw(self):
        self.spec = self._spec()
        self.fig.clear()
        plots.draw(self.fig, self.spec)
        self.canvas.draw_idle()

    def _png(self):
        path = filedialog.asksaveasfilename(parent=self, title='Сохранить график', defaultextension='.png',
                                            filetypes=[('PNG', '*.png')], initialfile='dynamics.png',
                                            initialdir=self.app.last_dir())
        if path:
            plots.render_file(self.spec, path, 1600)
            self.app.log(f'Сохранено: {path}')

    def _csv(self):
        path = filedialog.asksaveasfilename(parent=self, title='Сохранить CSV', defaultextension='.csv',
                                            filetypes=[('CSV', '*.csv')], initialfile='dynamics.csv',
                                            initialdir=self.app.last_dir())
        if not path:
            return
        d = self.doc
        groups = np.zeros(d.data.n, dtype=object)
        groups[:] = ''
        for k in range(len(d.model.groups)):
            g = d.model.groups[k]
            groups[g['a']:g['b'] + 1] = specs.group_title(d, k)
        import csv
        with open(path, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.writer(f)
            w.writerow(['Семпл', 'Время старта', 'Группа', 'Исключён', 'Статус', self.spec['ylabel']])
            times = d.data.meta.get('Start Time', [''] * d.data.n)
            for i in range(d.data.n):
                v = self.spec['y'][i]
                w.writerow([d.data.samples[i], times[i].strip(), groups[i], 'да' if i in d.model.excluded else '',
                            d.data.status(i) or '', '' if not np.isfinite(v) else f'{v:.6g}'])
        self.app.log(f'CSV сохранён: {path}')


__all__ = ['setup_styles', 'JournalWindow', 'show_about', 'show_help', 'RangeDialog', 'FitDialog',
           'IntegralDialog', 'TableWindow', 'CompareDialog', 'DynamicsWindow', 'integral_rows',
           'INTEGRAL_COLUMNS', 'parse_float', 'PURPLE', 'PURPLE_LIGHT', 'CARD', 'INK']
