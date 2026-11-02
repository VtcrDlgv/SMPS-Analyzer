"""Окно одного графика («Открыть крупно», «Сравнение групп»): масштабирование панелью matplotlib и
своё меню «Анализ», которое действует только на этот график (основное окно не меняется)."""
import copy
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.widgets import SpanSelector

import plots
import smps_data as sd
import specs
from dialogs import INTEGRAL_COLUMNS, CompareDialog, IntegralDialog, Window, integral_rows
from ui_common import PURPLE, FlatRadio, px, ui_font

SAVE_WIDTH_PX = 1600


class PlotWindow(Window):
    def __init__(self, app, spec, title, save_name, link=None):
        super().__init__(app, title)
        self.spec = copy.copy(spec)
        self.spec['style'] = dict(spec['style'])
        self.spec['items'] = [dict(it) for it in spec['items']]
        self.spec['fits'] = {}
        self.save_name = save_name
        self._span = None
        self._results = {}                   # текст результатов анализа по разделам
        w_in, h_in = self.spec['figsize']
        self.geometry(f'{int(w_in * 100 * app.scale)}x{int((h_in * 100 + 170) * app.scale)}')

        self.link = link                     # (id вкладки, имя графика) — шкала общая с плиткой
        self.log_x = tk.BooleanVar(value=bool(self.spec['style'].get('log_x')))
        self.log_y = tk.BooleanVar(value=bool(self.spec['style'].get('log_y')))
        menubar = tk.Menu(self)
        am = tk.Menu(menubar, tearoff=False)
        self.repr_var = tk.StringVar(value=self.spec['style']['repr'])
        rm = tk.Menu(am, tearoff=False)
        for val, text in (('dN', 'dN (концентрация в канале)'), ('dNdlogDp', 'dN/dlogDp')):
            rm.add_radiobutton(label=text, value=val, variable=self.repr_var, command=self._repr)
        am.add_cascade(label='Представление', menu=rm)
        am.add_command(label='Логнормальная аппроксимация', command=self._fit_dialog)
        am.add_command(label='Интеграл в диапазоне', command=self._integral_dialog)
        am.add_command(label='Сравнение с другими файлами', command=self._compare)
        menubar.add_cascade(label='Анализ', menu=am)
        self.configure(menu=menubar)

        self.buttons([('Шкала', self._scale_menu, False), ('Сохранить PNG', self._png, False), ('Сохранить CSV', self._csv, False),
                      ('Закрыть', self.destroy, False)])
        self.info = scrolledtext.ScrolledText(self.body, height=5, wrap=tk.WORD, font=ui_font(10), relief='solid',
                                              bd=1)
        self.fig = plots.make_figure(self.spec)
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.body)
        tb = NavigationToolbar2Tk(self.canvas, self.body, pack_toolbar=False)
        tb.update()
        tb.pack(side=tk.BOTTOM, fill=tk.X)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self.canvas.draw()
        app.large_windows.append(self)
        self.bind('<Destroy>', lambda e: e.widget is self and self in app.large_windows
                  and app.large_windows.remove(self), add='+')

    # ---------- перерисовка ----------

    def redraw(self):
        self.fig.clear()
        plots.draw(self.fig, self.spec)
        self.canvas.draw_idle()

    def _show_results(self):
        text = '\n\n'.join(v for v in self._results.values() if v)
        if text:
            self.info.configure(state='normal')
            self.info.delete('1.0', tk.END)
            self.info.insert(tk.END, text)
            self.info.configure(state='disabled')
            if not self.info.winfo_ismapped():
                self.info.pack(side=tk.BOTTOM, fill=tk.X, pady=(px(6), 0))
        elif self.info.winfo_ismapped():
            self.info.pack_forget()

    def _scale_menu(self):
        """То же меню, что у плитки: логарифмические оси. Для графика вкладки меняет и плитку."""
        m = tk.Menu(self, tearoff=False)
        m.add_checkbutton(label='Логарифмическая ось X (размер)', variable=self.log_x, command=self._scale)
        m.add_checkbutton(label='Логарифмическая ось Y (концентрация)', variable=self.log_y, command=self._scale)
        x, y = self.winfo_pointerxy()
        try:
            m.tk_popup(x, y)
        finally:
            m.grab_release()

    def _scale(self):
        self.spec['style']['log_x'] = self.log_x.get()
        self.spec['style']['log_y'] = self.log_y.get()
        self.redraw()
        if self.link is not None:
            self.app.set_doc_log(*self.link, self.log_x.get(), self.log_y.get(), source=self)

    def set_log(self, log_x, log_y):
        """Шкалу поменяли у плитки — повторить здесь."""
        if (self.log_x.get(), self.log_y.get()) == (log_x, log_y):
            return
        self.log_x.set(log_x)
        self.log_y.set(log_y)
        self.spec['style']['log_x'], self.spec['style']['log_y'] = log_x, log_y
        self.redraw()

    def _repr(self):
        self.spec['style']['repr'] = self.repr_var.get()
        self.redraw()

    # ---------- аппроксимация ----------

    def _fit_dialog(self):
        items = self.spec['items']
        if not items:
            return
        w = Window(self.app, 'Логнормальная аппроксимация', modal=True)
        curve = tk.StringVar(value=items[0]['title'])
        if len(items) > 1:
            row = tk.Frame(w.body)
            row.pack(fill=tk.X, pady=px(3))
            tk.Label(row, text='Кривая:').pack(side=tk.LEFT)
            ttk.Combobox(row, textvariable=curve, state='readonly', width=40, font=ui_font(10),
                         values=[it['title'] for it in items]).pack(side=tk.LEFT, padx=px(6))
        modes = tk.IntVar(value=max(items[0].get('fit_modes') or 1, 1))
        row = tk.Frame(w.body)
        row.pack(anchor='w', pady=px(6))
        tk.Label(row, text='Число мод:').pack(side=tk.LEFT)
        for m in (1, 2, 3):
            FlatRadio(row, str(m), modes, m).pack(side=tk.LEFT, padx=px(6))

        def target():
            return next(it for it in items if it['title'] == curve.get())

        def apply():
            it = target()
            res = plots.compute_fit(it, modes.get())
            if res is None:
                messagebox.showwarning('Аппроксимация', 'Слишком мало точек в диапазоне для такого числа мод.', parent=w)
                return
            self.spec['fits'][it['index']] = res
            it['fit_modes'] = 0
            self._results['fit'] = self._fit_text()
            self._show_results()
            self.redraw()
            w.destroy()

        def remove():
            it = target()
            self.spec['fits'].pop(it['index'], None)
            it['fit_modes'] = 0
            self._results['fit'] = self._fit_text()
            self._show_results()
            self.redraw()
            w.destroy()
        w.buttons([('Убрать', remove, False), ('Отмена', w.destroy, False), ('Применить', apply, True)])

    def _fit_text(self):
        lines = []
        for it in self.spec['items']:
            res = self.spec['fits'].get(it['index'])
            if not res:
                continue
            lines.append(f"Аппроксимация — {it['title']} (R² = {res['r2']:.4f}):")
            for j, m in enumerate(res['modes']):
                lines.append(f"  мода {j + 1}: N = {plots.sci(m['N'])} ± {plots.sci(m['N_err'], 2)} см⁻³, "
                             f"CMD = {m['CMD']:.1f} ± {m['CMD_err']:.1f} нм, GSD = {m['GSD']:.3f} ± {m['GSD_err']:.3f}")
        return '\n'.join(lines)

    # ---------- интеграл ----------

    def _integral_dialog(self):
        it0 = self.spec['items'][0]
        m = np.asarray(it0['mask'], bool)
        e = it0['edges']
        lo = self.spec.get('integral', {}).get('lo', float(e[:-1][m][0]))
        hi = self.spec.get('integral', {}).get('hi', float(e[1:][m][-1]))
        self._idlg = IntegralDialog(self.app, lo, hi, self._integral, allow_scope=False, on_mouse=self._select_span)

    def _select_span(self, dlg):
        """Выделить интервал мышью на графике."""
        dlg.withdraw()
        ax = self.fig.axes[0]

        def done(xmin, xmax):
            if xmax - xmin > 0:
                dlg.set_range(max(xmin, 0.1), xmax)
            self._span = None
            self.redraw()
        self._span = SpanSelector(ax, done, 'horizontal', useblit=True,
                                  props=dict(alpha=0.15, facecolor=PURPLE), interactive=False)
        self.lift()

    def _integral(self, lo, hi, all_files):
        self.spec['integral'] = {'lo': lo, 'hi': hi}
        rows = integral_rows([(self.app.doc_name(it), it['title'], it) for it in self.spec['items']], lo, hi)
        lines = [f'Интеграл в диапазоне {lo:.1f}–{hi:.1f} нм:']
        for r in rows:
            lines.append(f"  {r[1]}: N = {plots.sci(r[3])} см⁻³ ({r[4]:.1f} %), S = {plots.sci(r[5])} мкм²/см³ "
                         f"({r[6]:.1f} %), V = {plots.sci(r[7])} мкм³/см³ ({r[8]:.1f} %)")
        self._results['integral'] = '\n'.join(lines)
        self._integral_table = (INTEGRAL_COLUMNS, rows)
        self._show_results()
        self.redraw()
        if getattr(self, '_idlg', None) is not None and self._idlg.winfo_exists():
            self._idlg.destroy()

    # ---------- таблица и сравнение ----------

    def _compare(self):
        pre = []
        docs = self.app.project.file_docs
        for it in self.spec['items']:
            doc = self.app.doc_by_id(it.get('doc_id'))
            if doc in docs and it.get('group') is not None and it['group'] < len(doc.model.groups):
                a, b = doc.group_key(it['group'])
                pre.append({'file': docs.index(doc), 'first': a, 'last': b})

        def ok(selection):
            items = specs.compare_items(self.app.project, selection)
            if not items:
                return
            self.spec['kind'] = 'compare'
            self.link = None                 # это уже не график вкладки
            self.spec['items'] = items
            self.spec['fits'] = {}
            self.spec.pop('integral', None)
            self._results = {}
            self._show_results()
            self.title('Сравнение групп — SMPS Analyzer')
            self.save_name = 'compare.png'
            self.redraw()
        CompareDialog(self.app, pre, ok)

    # ---------- сохранение ----------

    def _png(self):
        self.app.save_spec(self.spec, self.save_name, parent=self)

    def _csv(self):
        self.app.save_spec_csv(self.spec, self.save_name, parent=self)


__all__ = ['PlotWindow', 'sd']
