"""Панель выбора групп активной вкладки: кнопки семплов в «прорезях» групп, тепловая карта с
границами диапазона, статус сканов, полоса параметров, кривые и превью."""
import math
import tkinter as tk
from tkinter import ttk

import matplotlib
import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from PIL import Image, ImageDraw, ImageTk

import plots
import smps_data as sd
import specs
from ui_common import (CARD, CARD_EDGE, GRID, HEATMAP_RAMP, INK, IS_MAC, MOD, MOD_LABEL, MUTED, OFF_EDGE, PILL,
                       PILL_EDGE, PURPLE, PURPLE_LIGHT, RANGE_RED, STATUS_BAD, STATUS_NONE, STATUS_OK, FlatButton,
                       FlatCheck, Grip, Tooltip, bind_right_click, px, ui_font)

# Размеры в логических пикселях (умножаются на масштаб экрана)
LEFT_W, LABEL_H, STRIP_H, TICK_H, GAP, GRIP_H, STATUS_H = 74, 22, 60, 20, 6, 10, 14
SIZE_LIMITS = {'map': (50, 700), 'curves': (150, 1400), 'preview': (120, 900)}
MIN_CELL, MAX_BTN = 11, 18
SS = 3                    # сглаживание кнопок в Windows/Linux: рисуем втрое крупнее и уменьшаем
N_APPLY_DELAY_MS = 350    # «По N»: пауза после ввода числа перед перестроением групп
LINE_HIT = 5              # насколько близко к красной линии надо попасть, логические пиксели

GESTURES = [
    ('ЛКМ', 'исключить / включить семпл; вне групп — станет группой из одного'),
    ('ЛКМ + протянуть', 'объединить всё от начала до конца (вместе с группами на концах)'),
    ('Shift + ЛКМ', 'объединить всё между выделенным и кликнутым'),
    ('← / →', 'перевести выделение'),
    ('Shift + ← / →', 'добавить к группе семпл с этой стороны; к середине группы — убрать крайний'),
    ('Пробел', 'исключить / включить выделенный семпл'),
    (f'{MOD_LABEL} + ЛКМ', 'разрезать: с этого семпла начинается новая группа'),
    ('ПКМ' + (' (или Ctrl + клик)' if IS_MAC else ''), 'показать график семпла'),
    ('ЛКМ по номеру группы', 'показать график группы'),
    ('2× ЛКМ по номеру группы', 'ввести название (для легенды и CSV)'),
    (f'{MOD_LABEL} + Z / {MOD_LABEL} + Shift + Z', 'отменить / вернуть'),
    (f'{MOD_LABEL} + колесо / Shift + колесо', 'масштаб ряда / прокрутка ряда вбок'),
    ('Потянуть полоску ═', 'изменить высоту карты, кривых или превью'),
    ('Красные линии на карте', 'границы диапазона: тянуть мышью; 2× ЛКМ по числу — ввести значение'),
]


def _ramp_lut(colors, n=256):
    rgb = np.array([[int(c[i:i + 2], 16) for i in (1, 3, 5)] for c in colors], dtype=float)
    pos = np.linspace(0, 1, len(colors))
    x = np.linspace(0, 1, n)
    return np.stack([np.interp(x, pos, rgb[:, k]) for k in range(3)], axis=1).astype(np.uint8)


_LUTS = {}


def map_lut(name):
    if name not in _LUTS:
        if name == 'ikt':
            _LUTS[name] = _ramp_lut(HEATMAP_RAMP)
        elif name == 'gray':
            _LUTS[name] = _ramp_lut(['#ffffff', '#000000'])
        else:
            cmap = matplotlib.colormaps[name]
            _LUTS[name] = (cmap(np.linspace(0, 1, 256))[:, :3] * 255).astype(np.uint8)
    return _LUTS[name]


class _Painter:
    """Кружки, прорези и линии. В Windows/Linux — сглаженной картинкой (холст Tk там без
    сглаживания), на Mac — векторными элементами холста (там они сглажены и резкие на Retina)."""

    def __init__(self):
        self.ops = []

    def pill(self, x0, y0, x1, y1, fill, outline, width):
        self.ops.append(('pill', x0, y0, x1, y1, fill, outline, width))

    def circle(self, cx, cy, r, fill, outline, width):
        self.ops.append(('circle', cx, cy, r, fill, outline, width))

    def line(self, x0, y0, x1, y1, color, width):
        self.ops.append(('line', x0, y0, x1, y1, color, width))

    def render(self, canvas, x, y, w, h, keep):
        if w <= 0 or h <= 0:
            return
        if IS_MAC:
            for op in self.ops:
                self._vector(canvas, x, y, op)
            return
        img = Image.new('RGBA', (int(w * SS), int(h * SS)), (255, 255, 255, 0))
        dr = ImageDraw.Draw(img)
        for kind, *a in self.ops:
            if kind == 'pill':
                x0, y0, x1, y1, fill, outline, width = a
                dr.rounded_rectangle([x0 * SS, y0 * SS, x1 * SS, y1 * SS], radius=(y1 - y0) * SS / 2,
                                     fill=fill, outline=outline, width=max(1, round(width * SS)) if outline else 0)
            elif kind == 'circle':
                cx, cy, r, fill, outline, width = a
                dr.ellipse([(cx - r) * SS, (cy - r) * SS, (cx + r) * SS, (cy + r) * SS],
                           fill=fill, outline=outline, width=max(1, round(width * SS)) if outline else 0)
            else:
                x0, y0, x1, y1, color, width = a
                dr.line([x0 * SS, y0 * SS, x1 * SS, y1 * SS], fill=color, width=max(1, round(width * SS)))
        photo = ImageTk.PhotoImage(img.resize((int(w), int(h)), Image.LANCZOS))
        keep.append(photo)
        canvas.create_image(x, y, image=photo, anchor='nw')

    @staticmethod
    def _vector(canvas, x, y, op):
        kind, *a = op
        if kind == 'pill':
            x0, y0, x1, y1, fill, outline, width = a
            r = (y1 - y0) / 2
            pts = []
            for k in range(13):
                t = -math.pi / 2 + math.pi * k / 12
                pts += [x + x1 - r + r * math.cos(t), y + y0 + r + r * math.sin(t)]
            for k in range(13):
                t = math.pi / 2 + math.pi * k / 12
                pts += [x + x0 + r + r * math.cos(t), y + y0 + r + r * math.sin(t)]
            canvas.create_polygon(pts, fill=fill, outline=outline or '', width=width)
        elif kind == 'circle':
            cx, cy, r, fill, outline, width = a
            canvas.create_oval(x + cx - r, y + cy - r, x + cx + r, y + cy + r,
                               fill=fill or '', outline=outline or '', width=width)
        else:
            x0, y0, x1, y1, color, width = a
            canvas.create_line(x + x0, y + y0, x + x1, y + y1, fill=color, width=width)


class GroupPanel(tk.Frame):
    """Зона «Группы для усреднения». Работает с документом (вкладкой), который ей передали."""

    def __init__(self, master, scale, app):
        super().__init__(master, bg=CARD, highlightbackground=CARD_EDGE, highlightthickness=max(1, px(1)),
                         padx=px(10), pady=px(8))
        self.s = scale
        self.app = app
        self.settings = app.project.settings
        self.doc = None
        self.data = None
        self.model = None
        self.cursor = 0
        self.preview = None          # ('sample', i) или ('group', k)
        self.zoom = 1.0
        self._images = []
        self._press = None
        self._layout = None
        self._redraw_pending = False
        self._n_after = None
        self._n_guard = False
        self._resize = None          # перетаскивание нижнего края карты
        self._line_drag = None       # перетаскивание красной линии: 'lo' / 'hi'
        self.tooltip = Tooltip(self)

        self.font = ui_font(10)
        self.font_small = ui_font(9)
        self.font_bold = ui_font(10, 'bold')
        self.font_italic = ui_font(9, slant='italic')
        L = dict(bg=CARD)

        # --- заголовок (сворачивание) ---
        head = tk.Frame(self, **L)
        head.pack(fill=tk.X)
        self.toggle_lbl = tk.Label(head, text='▼ Группы для усреднения', font=ui_font(12, 'bold'), fg=INK,
                                   cursor='hand2', **L)
        self.toggle_lbl.pack(side=tk.LEFT)
        self.toggle_lbl.bind('<Button-1>', lambda e: self.set_collapsed(not self.collapsed))
        self.summary_lbl = tk.Label(head, text='', fg=MUTED, font=self.font, **L)
        self.summary_lbl.pack(side=tk.LEFT, padx=px(12))
        self.collapsed = False

        self.hint = tk.Label(self, text='Выберите файл SMPS — здесь появятся семплы и группы.',
                             fg=MUTED, font=self.font, anchor='w', **L)
        self.hint.pack(fill=tk.X, pady=(px(6), px(2)))

        self.body = tk.Frame(self, **L)   # показывается, когда во вкладке есть файл

        # --- первая строка: разбиение ---
        bar = tk.Frame(self.body, **L)
        bar.pack(fill=tk.X, pady=(px(6), px(3)))
        tk.Label(bar, text='Разбить:', fg=INK, **L).pack(side=tk.LEFT)
        self.preset_btns = {}
        for key, text in [('auto', 'Авто'), ('by1', 'По 1'), ('by5', 'По 5'), ('by10', 'По 10')]:
            b = FlatButton(bar, text, command=lambda k=key: self.apply_preset(k))
            b.pack(side=tk.LEFT, padx=px(2))
            self.preset_btns[key] = b
        b = FlatButton(bar, 'По N:', command=lambda: self.apply_preset('byN'))
        b.pack(side=tk.LEFT, padx=(px(2), 0))
        self.preset_btns['byN'] = b
        self.n_var = tk.StringVar(value='3')
        FlatButton(bar, '−', command=lambda: self._bump_n(-1), padx=7).pack(side=tk.LEFT, padx=(px(3), 0))
        self.n_entry = tk.Entry(bar, textvariable=self.n_var, width=4, justify='center', font=self.font,
                                relief='solid', bd=1)
        self.n_entry.pack(side=tk.LEFT, padx=px(2), ipady=px(2))
        FlatButton(bar, '+', command=lambda: self._bump_n(1), padx=7).pack(side=tk.LEFT, padx=(0, px(2)))
        self.n_var.trace_add('write', lambda *a: self._n_changed())
        b = FlatButton(bar, 'Ручной выбор', command=lambda: self.apply_preset('manual'))
        b.pack(side=tk.LEFT, padx=px(2))
        self.preset_btns['manual'] = b
        self.info_lbl = FlatButton(bar, '► Info', command=self.toggle_info)
        self.info_lbl.pack(side=tk.RIGHT, padx=(px(10), 0))

        # --- вторая строка: что показывать (сохраняется в проекте) ---
        view = tk.Frame(self.body, **L)
        view.pack(fill=tk.X, pady=(0, px(3)))
        tk.Label(view, text='Показать:', fg=INK, **L).pack(side=tk.LEFT)
        sh = self.settings['show']
        self.show_map = tk.BooleanVar(value=sh['map'])
        self.show_status = tk.BooleanVar(value=sh['status'])
        self.show_strip = tk.BooleanVar(value=sh['strip'])
        self.show_curves = tk.BooleanVar(value=sh['curves'])
        self.show_preview = tk.BooleanVar(value=sh['preview'])
        FlatCheck(view, 'Карта', self.show_map, command=self._view_changed).pack(side=tk.LEFT, padx=(px(6), px(8)))
        FlatCheck(view, 'Scan status', self.show_status, command=self._view_changed).pack(side=tk.LEFT, padx=px(8))
        FlatCheck(view, 'Полоса:', self.show_strip, command=self._view_changed).pack(side=tk.LEFT, padx=(px(8), px(3)))
        self.metric_var = tk.StringVar(value=self.settings.get('strip_metric', 'мода'))
        self.metric_box = ttk.Combobox(view, textvariable=self.metric_var, state='readonly', width=13,
                                       values=[m[0] for m in sd.STRIP_METRICS], font=self.font)
        self.metric_box.pack(side=tk.LEFT)
        self.metric_box.bind('<<ComboboxSelected>>', lambda e: self._view_changed())
        FlatCheck(view, 'Кривые', self.show_curves, command=self._toggle_curves).pack(side=tk.LEFT, padx=(px(14), px(8)))
        FlatCheck(view, 'Превью', self.show_preview, command=self._toggle_preview).pack(side=tk.LEFT, padx=px(8))

        # --- Info ---
        self.info_frame = tk.Frame(self.body, bg=PURPLE_LIGHT, padx=px(10), pady=px(6))
        rows = (len(GESTURES) + 1) // 2
        for r, (g, t) in enumerate(GESTURES):
            tk.Label(self.info_frame, text=g, bg=PURPLE_LIGHT, fg=INK, font=self.font_bold, anchor='w').grid(
                row=r % rows, column=(r // rows) * 2, sticky='w', padx=(0, px(8)))
            tk.Label(self.info_frame, text='— ' + t, bg=PURPLE_LIGHT, fg=INK, font=self.font, anchor='w').grid(
                row=r % rows, column=(r // rows) * 2 + 1, sticky='w', padx=(0, px(24)))
        self.info_visible = False

        # --- холсты: ось слева + прокручиваемая вбок область ---
        self.vis = tk.Frame(self.body, **L)
        self.vis.pack(fill=tk.X, pady=(px(4), 0))
        self.axis_cv = tk.Canvas(self.vis, width=px(LEFT_W), bg=CARD, highlightthickness=0)
        self.axis_cv.pack(side=tk.LEFT, fill=tk.Y)
        right = tk.Frame(self.vis, **L)
        right.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.cv = tk.Canvas(right, bg=CARD, highlightthickness=0, height=px(80), takefocus=1)
        self.cv.pack(fill=tk.X)
        self.hbar = tk.Scrollbar(right, orient=tk.HORIZONTAL, command=self.cv.xview)
        self.cv.configure(xscrollcommand=self.hbar.set)
        self._hbar_shown = False

        self.curves_frame = tk.Frame(self.body, **L)
        self.curves_fig = None

        # --- превью (высота меняется ручкой снизу) ---
        self.preview_frame = tk.Frame(self.body, **L)
        row = tk.Frame(self.preview_frame, **L)
        row.pack(fill=tk.X)
        self.prev_fig = plots.new_figure((6.2, self.settings['heights']['preview'] / 100))
        self.prev_ax = self.prev_fig.add_subplot(111)
        self.prev_canvas = FigureCanvasTkAgg(self.prev_fig, master=row)
        self.prev_canvas.get_tk_widget().configure(bg=CARD, highlightthickness=0)
        self.prev_canvas.get_tk_widget().pack(side=tk.LEFT)
        self.prev_text = tk.Label(row, text='', justify=tk.LEFT, anchor='nw', fg=INK, font=self.font, **L)
        self.prev_text.pack(side=tk.LEFT, fill=tk.BOTH, padx=px(16), pady=px(8))
        Grip(self.preview_frame, lambda: self.settings['heights']['preview'], lambda h: self._set_size('preview', h),
             *SIZE_LIMITS['preview']).pack(fill=tk.X)
        if self.show_preview.get():
            self.preview_frame.pack(fill=tk.X, pady=(px(6), 0))

        self._bind_events()
        self.cv.bind('<Configure>', lambda e: self.schedule_redraw())
        self._update_buttons()

    # ================= вкладки =================

    def attach(self, doc):
        """Показать документ (вкладку). None или пустая вкладка — только подсказка."""
        if self.doc is not None and self.model is not None:
            self.doc.cursor, self.doc.preview, self.doc.zoom = self.cursor, self.preview, self.zoom
            if self._on_model_change in self.model.listeners:
                self.model.listeners.remove(self._on_model_change)
        self.doc = doc
        self.tooltip.hide()
        if doc is None or doc.empty:
            self.data = self.model = None
            self._layout = None
            self.body.pack_forget()
            self.hint.pack(fill=tk.X, pady=(px(6), px(2)))
            self._update_buttons()
            self._redraw()
            return
        self.data, self.model = doc.data, doc.model
        self.model.listeners.append(self._on_model_change)
        self.cursor, self.preview, self.zoom = min(doc.cursor, doc.data.n - 1), doc.preview, doc.zoom
        if self.preview and self.preview[0] == 'group' and self.preview[1] >= len(self.model.groups):
            self.preview = None
        if self.preview is None and self.model.groups:
            self.preview = ('group', 0)
        self._n_guard = True
        self.n_var.set(str(doc.n_value))
        self._n_guard = False
        self.hint.pack_forget()
        if not self.collapsed:
            self.body.pack(fill=tk.X)
        self._update_buttons()
        self.schedule_redraw()
        self._show_preview(self.preview)
        if self.show_curves.get():
            self._draw_curves()

    def apply_settings(self):
        """Настройки проекта изменились (палитры, толщины, представление, загрузка проекта)."""
        self.settings = self.app.project.settings
        sh = self.settings['show']
        for var, key in ((self.show_map, 'map'), (self.show_status, 'status'), (self.show_strip, 'strip'),
                         (self.show_curves, 'curves'), (self.show_preview, 'preview')):
            var.set(sh[key])
        self.metric_var.set(self.settings.get('strip_metric', 'мода'))
        self._toggle_curves(notify=False)
        self._toggle_preview(notify=False)
        self.prev_canvas.get_tk_widget().configure(height=px(self.settings['heights']['preview']))
        self.schedule_redraw()
        self._show_preview(self.preview)

    # ================= пресеты =================

    def apply_preset(self, key):
        if self.model is None:
            return
        if key == 'manual':
            self.model.clear()
            return
        if key == 'auto':
            if self.data.start_times is None:
                self.app.log('В файле нет времени старта семплов — «Авто» объединяет все семплы в одну группу.')
            ranges = sd.auto_ranges(self.data)
        else:
            size = {'by1': 1, 'by5': 5, 'by10': 10}.get(key) or self._n_value()
            if not size:
                self.app.log('По N: укажите целое число от 1.')
                return
            ranges = sd.chunk_ranges(self.data, size)
        self.model.set_ranges(ranges, key)

    def _n_value(self):
        try:
            v = int(self.n_var.get())
        except ValueError:
            return None
        return v if v >= 1 else None

    def _bump_n(self, d):
        v = self._n_value() or 1
        self.n_var.set(str(max(1, v + d)))

    def _n_changed(self):
        if self._n_guard:
            return
        if self._n_after is not None:
            self.after_cancel(self._n_after)
        self._n_after = self.after(N_APPLY_DELAY_MS, self._apply_n)

    def _apply_n(self):
        self._n_after = None
        if self.model is not None and self._n_value():
            self.doc.n_value = self._n_value()
            self.apply_preset('byN')

    def undo(self):
        if self.model:
            self.model.undo()

    def redo(self):
        if self.model:
            self.model.redo()

    def _on_model_change(self):
        self.cursor = min(self.cursor, self.data.n - 1)
        if self.preview and self.preview[0] == 'group' and self.preview[1] >= len(self.model.groups):
            self.preview = None
        self._update_buttons()
        self.schedule_redraw()
        self._show_preview(self.preview)
        self.app.on_doc_changed()

    def _update_buttons(self):
        preset = self.model.preset if self.model else None
        for k, b in self.preset_btns.items():
            b.set_active(k == preset)
        self.summary_lbl.config(text=self.summary_text())
        self.app.update_edit_menu()

    def summary_text(self):
        if self.model is None:
            return ''
        m = self.model
        txt = f'групп: {len(m.groups)} · семплов: {m.n} · исключено: {len(m.excluded)} · вне групп: {m.free_count()}'
        if self.data.period:
            txt += f' · длительность семпла {self.data.period:.0f} с ({self.data.period_source})'
        rng = self.doc.range
        if rng and rng.get('enabled'):
            txt += f' · диапазон {rng["lo"]:.1f}–{rng["hi"]:.1f} нм'
        return txt

    # ================= сворачивание, Info, кривые, превью =================

    def set_collapsed(self, value):
        self.collapsed = value
        self.toggle_lbl.config(text=('►' if value else '▼') + ' Группы для усреднения')
        if self.model is None:
            return
        if value:
            self.body.pack_forget()
        else:
            self.body.pack(fill=tk.X)
            self.schedule_redraw()

    def toggle_info(self):
        self.info_visible = not self.info_visible
        self.info_lbl.config(text=('▼' if self.info_visible else '►') + ' Info')
        if self.info_visible:
            self.info_frame.pack(fill=tk.X, before=self.vis, pady=(px(2), px(2)))
        else:
            self.info_frame.pack_forget()

    def _view_changed(self):
        sh = self.settings['show']
        sh['map'], sh['status'], sh['strip'] = self.show_map.get(), self.show_status.get(), self.show_strip.get()
        self.settings['strip_metric'] = self.metric_var.get()
        self.app.mark_dirty()
        self.schedule_redraw()

    def _toggle_curves(self, notify=True):
        self.settings['show']['curves'] = self.show_curves.get()
        if self.show_curves.get():
            self.curves_frame.pack(fill=tk.X, after=self.vis, pady=(px(4), 0))
            if self.curves_fig is None:
                w_in = max(4.0, (self.cv.winfo_width() + px(LEFT_W)) / (100 * self.s))
                self.curves_fig = plots.new_figure((w_in, self.settings['heights']['curves'] / 100))
                self.curves_ax = self.curves_fig.add_subplot(111)
                self.curves_canvas = FigureCanvasTkAgg(self.curves_fig, master=self.curves_frame)
                self.curves_canvas.get_tk_widget().configure(bg=CARD, highlightthickness=0)
                self.curves_canvas.get_tk_widget().pack(fill=tk.X)
                Grip(self.curves_frame, lambda: self.settings['heights']['curves'],
                     lambda h: self._set_size('curves', h), *SIZE_LIMITS['curves']).pack(fill=tk.X)
            else:
                self.curves_canvas.get_tk_widget().configure(height=px(self.settings['heights']['curves']))
            self._draw_curves()
        else:
            self.curves_frame.pack_forget()
        if notify:
            self.app.mark_dirty()

    def _toggle_preview(self, notify=True):
        self.settings['show']['preview'] = self.show_preview.get()
        if self.show_preview.get():
            self.preview_frame.pack(fill=tk.X, pady=(px(6), 0))
            self._show_preview(self.preview)
        else:
            self.preview_frame.pack_forget()
        if notify:
            self.app.mark_dirty()

    def _set_size(self, zone, h):
        lo, hi = SIZE_LIMITS[zone]
        self.settings['heights'][zone] = h = min(max(h, lo), hi)
        if zone == 'map':
            self.schedule_redraw()
        elif zone == 'curves' and self.curves_fig is not None:
            self.curves_canvas.get_tk_widget().configure(height=px(h))
        elif zone == 'preview':
            self.prev_canvas.get_tk_widget().configure(height=px(h))
        self.app.mark_dirty()

    # ================= геометрия =================

    def _compute_layout(self):
        s, n = self.s, self.data.n
        avail = max(self.cv.winfo_width(), 200)
        cell = max(avail / n, MIN_CELL * s) * self.zoom
        xs = [i * cell for i in range(n)]
        d = min(cell * 0.78, MAX_BTN * s)
        btn_h = d + 8 * s
        y = 0.0
        rows = {'label': (y, LABEL_H * s)}
        y += LABEL_H * s
        rows['buttons'] = (y, btn_h)
        y += btn_h + GAP * s / 2
        if self.show_map.get():
            map_h = self.settings['heights']['map'] * s
            rows['map'] = (y, map_h)
            y += map_h
            rows['mapgrip'] = (y, GRIP_H * s)
            y += GRIP_H * s
        if self.show_status.get():
            rows['status'] = (y, STATUS_H * s)
            y += STATUS_H * s + 2 * s
        if self.show_strip.get():
            rows['strip'] = (y, STRIP_H * s)
            y += STRIP_H * s + 2 * s
        rows['ticks'] = (y, TICK_H * s)
        y += TICK_H * s
        return {'cell': cell, 'xs': xs, 'width': n * cell, 'd': d, 'rows': rows, 'height': y}

    def sample_at(self, cx, clamp=False):
        L = self._layout
        if L is None:
            return None
        i = int(cx // L['cell'])
        if clamp:
            return min(max(i, 0), self.data.n - 1)
        return i if 0 <= i < self.data.n else None

    def row_at(self, cy):
        for name, (y, h) in self._layout['rows'].items():
            if y <= cy < y + h:
                return name
        return None

    def _map_y(self, D):
        """Координата y размера D на тепловой карте (лог. шкала, малые размеры сверху)."""
        y, h = self._layout['rows']['map']
        e = self.data.edges
        return y + (math.log(D) - math.log(e[0])) / (math.log(e[-1]) - math.log(e[0])) * h

    def _map_D(self, cy):
        y, h = self._layout['rows']['map']
        e = self.data.edges
        t = min(max((cy - y) / h, 0.0), 1.0)
        return math.exp(math.log(e[0]) + t * (math.log(e[-1]) - math.log(e[0])))

    # ================= отрисовка =================

    def schedule_redraw(self):
        if not self._redraw_pending:
            self._redraw_pending = True
            self.after_idle(self._redraw)

    def _redraw(self):
        self._redraw_pending = False
        for item in self.cv.find_all():          # поле ввода названия переживает перерисовку
            if 'editor' not in self.cv.gettags(item):
                self.cv.delete(item)
        for item in self.axis_cv.find_all():
            if 'editor' not in self.axis_cv.gettags(item):
                self.axis_cv.delete(item)
        self._images = []
        if self.data is None or self.collapsed:
            return
        L = self._layout = self._compute_layout()
        W, H = L['width'], L['height']
        self.cv.configure(height=int(H), scrollregion=(0, 0, W, H))
        self.axis_cv.configure(height=int(H))
        need_bar = W > self.cv.winfo_width() + 1
        if need_bar != self._hbar_shown:
            if need_bar:
                self.hbar.pack(fill=tk.X)
            else:
                self.hbar.pack_forget()
            self._hbar_shown = need_bar
        self._draw_labels()
        self._draw_buttons()
        if 'map' in L['rows']:
            self._draw_heatmap()
            gy, gh = L['rows']['mapgrip']
            cx = self.cv.canvasx(0) + self.cv.winfo_width() / 2
            self.cv.create_line(cx - 22 * self.s, gy + gh / 2, cx + 22 * self.s, gy + gh / 2, fill=PILL_EDGE,
                                width=max(2, round(3 * self.s)), capstyle='round')
        if 'status' in L['rows']:
            self._draw_status()
        if 'strip' in L['rows']:
            self._draw_strip()
        self._draw_ticks()
        if self.preview and self.preview[0] == 'group' and 'map' in L['rows']:
            g = self.model.groups[self.preview[1]]
            y, h = L['rows']['map']
            self.cv.create_rectangle(L['xs'][g['a']], y, L['xs'][g['b']] + L['cell'], y + h,
                                     outline=INK, width=max(1, round(2 * self.s)))
        if 'map' in L['rows']:
            self._draw_range_lines()
        self.cv.tag_raise('editor')
        if self.show_curves.get():
            self._draw_curves()

    def _group_span(self, g):
        L = self._layout
        return L['xs'][g['a']], L['xs'][g['b']] + L['cell']

    def _sel_group(self):
        return self.preview[1] if self.preview and self.preview[0] == 'group' else None

    def _draw_labels(self):
        L, m = self._layout, self.model
        y, h = L['rows']['label']
        sel_k = self._sel_group()
        for k, g in enumerate(m.groups):
            x0, x1 = self._group_span(g)
            width = x1 - x0 - 4 * self.s
            font = self.font_bold if k == sel_k else self.font_small
            text = g['name'] or str(k + 1)
            if font.measure(text) > width:
                text = str(k + 1) if font.measure(str(k + 1)) <= width + 6 * self.s else ''
                if g['name'] and text:
                    text += '…'
            self.cv.create_text((x0 + x1) / 2, y + h / 2, text=text, font=font,
                                fill=PURPLE if k == sel_k else MUTED)
        i = 0
        while i < m.n:
            if m.group_index(i) is None:
                j = i
                while j + 1 < m.n and m.group_index(j + 1) is None:
                    j += 1
                x0, x1 = L['xs'][i], L['xs'][j] + L['cell']
                if self.font_italic.measure('вне групп') < x1 - x0:
                    self.cv.create_text((x0 + x1) / 2, y + h / 2, text='вне групп', font=self.font_italic, fill=MUTED)
                i = j + 1
            else:
                i += 1

    def _draw_buttons(self):
        L, m, s = self._layout, self.model, self.s
        y, h = L['rows']['buttons']
        cell, d = L['cell'], L['d']
        p = _Painter()
        pad = max(1.0, 1.5 * s)
        sel_k = self._sel_group()
        for k, g in enumerate(m.groups):
            x0, x1 = self._group_span(g)
            sel = k == sel_k
            p.pill(x0 + pad, h / 2 - d / 2 - 3 * s, x1 - pad, h / 2 + d / 2 + 3 * s,
                   PURPLE_LIGHT if sel else PILL, INK if sel else PILL_EDGE, 1.8 * s if sel else 0.9 * s)
        r = d / 2
        for i, x in enumerate(L['xs']):
            cx, cy = x + cell / 2, h / 2
            if m.is_on(i):
                p.circle(cx, cy, r, PURPLE, PURPLE, 0.9 * s)
            else:
                p.circle(cx, cy, r, 'white', OFF_EDGE, 0.9 * s)
                if i in m.excluded:
                    p.line(cx - r * 0.55, cy + r * 0.55, cx + r * 0.55, cy - r * 0.55, INK, 1.2 * s)
        cx = L['xs'][self.cursor] + cell / 2
        p.circle(cx, h / 2, r + 2.2 * s, None, INK, 1.6 * s)
        p.render(self.cv, 0, y, L['width'], h, self._images)

    def _draw_heatmap(self):
        L, m, s = self._layout, self.model, self.s
        y, h = L['rows']['map']
        W = int(math.ceil(L['width']))
        H = max(1, int(h))
        vals = self.data.values
        pos = vals[vals > 0]
        hi = np.percentile(pos, 99.5) if len(pos) else 1.0
        lo = hi / 1e3
        with np.errstate(divide='ignore', invalid='ignore'):
            norm = np.clip((np.log10(vals) - np.log10(lo)) / 3.0, 0, 1)
        norm[~np.isfinite(norm)] = 0
        idx = (norm * 255).astype(np.uint8)
        # строки картинки -> каналы по логарифмической шкале границ (малые размеры сверху)
        e = self.data.edges
        logs = np.log(e[0]) + (np.arange(H) + 0.5) / H * (np.log(e[-1]) - np.log(e[0]))
        rows = np.clip(np.searchsorted(np.log(e), logs) - 1, 0, idx.shape[0] - 1)
        col = np.minimum((np.arange(W) / L['cell']).astype(int), m.n - 1)
        img = map_lut(self.settings['map_palette'])[idx[rows][:, col]].astype(np.float32)
        band = max(2, int(round(3 * s)))
        for i in range(1, m.n):
            xi = int(round(L['xs'][i]))
            if m.group_index(i) != m.group_index(i - 1):
                img[:, max(0, xi - band // 2):xi + (band + 1) // 2] = 255
            else:
                img[:, xi:xi + 1] = img[:, xi:xi + 1] * 0.45 + 255 * 0.55
        photo = ImageTk.PhotoImage(Image.fromarray(img.astype(np.uint8)))
        self._images.append(photo)
        self.cv.create_image(0, y, image=photo, anchor='nw')

        ax = self.axis_cv
        x_r = LEFT_W * s - 4 * s
        red = self._red_label_ys()
        for t in [5, 10, 20, 50, 100, 200, 500, 1000]:
            if e[0] <= t <= e[-1]:
                ty = self._map_y(t)
                if any(abs(ty - ry) < 11 * s for ry in red):
                    continue                     # не наезжать на красные подписи
                ax.create_text(x_r - 4 * s, ty, text=str(t), anchor='e', font=self.font_small, fill=MUTED)
                ax.create_line(x_r - 2 * s, ty, x_r + 2 * s, ty, fill=MUTED)
        ax.create_text(10 * s, y + h / 2, text='Размер, нм', angle=90, font=self.font_small, fill=INK)

    def _line_y(self, which):
        """y красной линии; на краях файла — чуть внутри карты, чтобы линия была видна."""
        y, h = self._layout['rows']['map']
        m = max(2, round(2 * self.s))
        return min(max(self._map_y(self.doc.range[which]), y + m), y + h - m)

    def _red_label_ys(self):
        rng = self.doc.range if self.doc else None
        if not rng or not rng.get('enabled') or 'map' not in self._layout['rows']:
            return []
        return [self._line_y('lo'), self._line_y('hi')]

    def _draw_range_lines(self):
        rng = self.doc.range
        if not rng or not rng.get('enabled'):
            return
        s = self.s
        W = self._layout['width']
        x_r = LEFT_W * s - 4 * s
        for which in ('lo', 'hi'):
            ty = self._line_y(which)
            self.cv.create_line(0, ty, W, ty, fill=RANGE_RED, width=max(2, round(2 * s)), tags=('rline', which))
            v = rng[which]
            text = f'{v:.1f}' if v < 1000 else f'{v:.0f}'
            self.axis_cv.create_text(x_r - 4 * s, ty, text=text, anchor='e', font=self.font_bold, fill=RANGE_RED,
                                     tags=('rlabel', f'rlabel_{which}'))
            self.axis_cv.create_line(x_r - 2 * s, ty, x_r + 4 * s, ty, fill=RANGE_RED, width=max(2, round(2 * s)))

    def _draw_status(self):
        L, s = self._layout, self.s
        y, h = L['rows']['status']
        p = _Painter()
        w = min(L['cell'] * 0.72, 16 * s)
        hh = min(h * 0.55, 7 * s)
        for i, x in enumerate(L['xs']):
            ok = self.data.is_normal(i)
            color = STATUS_NONE if ok is None else (STATUS_OK if ok else STATUS_BAD)
            cx = x + L['cell'] / 2
            p.pill(cx - w / 2, h / 2 - hh / 2, cx + w / 2, h / 2 + hh / 2, color, None, 0)
        p.render(self.cv, 0, y, L['width'], h, self._images)
        self.axis_cv.create_text(LEFT_W * s - 6 * s, y + h / 2, text='статус', anchor='e', font=self.font_small,
                                 fill=MUTED)

    def _metric(self):
        key = dict(sd.STRIP_METRICS)[self.metric_var.get()]
        return key, sd.sample_metric(self.data, key, self.doc.range)

    def _draw_strip(self):
        L, m, s = self._layout, self.model, self.s
        y, h = L['rows']['strip']
        key, vals = self._metric()
        ax = self.axis_cv
        name = self.metric_var.get()
        unit = '' if key == 'Geo. Std. Dev.' else (', см⁻³' if key == 'Total Concentration' else ', нм')
        ax.create_text(10 * s, y + h / 2, text=name.capitalize() + unit, angle=90, font=self.font_small, fill=INK)
        if vals is None or not np.any(np.isfinite(vals)):
            self.cv.create_text(8 * s, y + h / 2, text='нет данных', anchor='w', font=self.font_small, fill=MUTED)
            return
        fin = vals[np.isfinite(vals)]
        vmin, vmax = float(fin.min()), float(fin.max())
        if vmax == vmin:
            vmin, vmax = vmin - 1, vmax + 1
        padv = (vmax - vmin) * 0.12
        vmin, vmax = vmin - padv, vmax + padv

        def ty(v):
            return y + h - (v - vmin) / (vmax - vmin) * h

        def fmt(v):
            if abs(v) >= 1e4:
                return f'{v:.1e}'.replace('e+0', 'e').replace('e+', 'e')
            return f'{v:.2f}' if key == 'Geo. Std. Dev.' else f'{v:.0f}'
        for t in np.linspace(vmin + padv, vmax - padv, 3):
            self.cv.create_line(0, ty(t), L['width'], ty(t), fill=GRID)
            ax.create_text(LEFT_W * s - 6 * s, ty(t), text=fmt(t), anchor='e', font=self.font_small, fill=MUTED)
        p = _Painter()
        r = max(2.0, min(3.4 * s, L['cell'] * 0.3))
        for i, x in enumerate(L['xs']):
            if np.isfinite(vals[i]):
                cy = ty(vals[i]) - y
                if m.is_on(i):
                    p.circle(x + L['cell'] / 2, cy, r, PURPLE, None, 0)
                else:
                    p.circle(x + L['cell'] / 2, cy, r, 'white', OFF_EDGE, 1.0 * s)
        p.render(self.cv, 0, y, L['width'], h, self._images)

    def _draw_ticks(self):
        L, s = self._layout, self.s
        y, h = L['rows']['ticks']
        step = next((k for k in (1, 2, 5, 10, 20, 50, 100) if k * L['cell'] >= 28 * s), 200)
        for i, x in enumerate(L['xs']):
            if (i + 1) % step == 0 or step == 1:
                self.cv.create_text(x + L['cell'] / 2, y + h / 2, text=self.data.samples[i], font=self.font_small,
                                    fill=MUTED)
        self.axis_cv.create_text(LEFT_W * s - 6 * s, y + h / 2, text='семпл', anchor='e', font=self.font_small,
                                 fill=MUTED)

    def _range_xlim(self, ax):
        rng = self.doc.range
        if rng and rng.get('enabled'):
            ax.set_xlim(rng['lo'], rng['hi'])

    def _ycurve(self, dn):
        return sd.to_repr(dn, self.data.dlogdp, self.settings['repr'])

    def _draw_curves(self):
        if self.curves_fig is None or self.data is None or self.doc is None or self.doc.empty:
            if self.curves_fig is not None:
                self.curves_ax.clear()
                self.curves_canvas.draw_idle()
            return
        ax = self.curves_ax
        ax.clear()
        D = self.data.D
        mask = sd.range_mask(self.data, self.doc.range)
        sel_k = self._sel_group()
        lw = self.settings['lw_preview']
        pal = self.settings['plot_palette']
        for k, g in enumerate(self.model.groups):
            color, ls = plots.group_style(k, pal)
            for i in self.model.included(k):
                y = self._ycurve(self.data.values[:, i])
                ax.plot(D[mask], y[mask], color=color, ls=ls, lw=(1.6 if k == sel_k else 0.7) * lw,
                        alpha=1.0 if k == sel_k else 0.55)
        self._range_xlim(ax)
        plots.style_plain(ax, self.settings['repr'], fontsize=10, ticksize=9)
        self.curves_canvas.draw_idle()

    # ================= превью =================

    def refresh_views(self):
        """Перерисовать всё, что зависит от данных/диапазона/представления."""
        self.schedule_redraw()
        self._show_preview(self.preview)
        self._update_buttons()

    def _show_preview(self, what):
        self.preview = what
        if not self.show_preview.get():
            return
        ax = self.prev_ax
        ax.clear()
        if self.data is None or self.doc is None or self.doc.empty or what is None:
            self.prev_text.config(text='')
            self.prev_canvas.draw_idle()
            return
        D = self.data.D
        mask = sd.range_mask(self.data, self.doc.range)
        col = lambda i: self._ycurve(self.data.values[:, i])  # noqa: E731
        m = self.model
        lw = self.settings['lw_preview']
        lines = []
        if what[0] == 'group':
            k = what[1]
            inc = m.included(k)
            for i in inc:
                ax.plot(D[mask], col(i)[mask], color='#d3ccd9', lw=0.8 * lw)
            if inc:
                st = sd.group_stats(self.data, inc, self.doc.range)
                ax.plot(D[mask], self._ycurve(st['avg'])[mask], color=PURPLE, lw=2.2 * lw, label='среднее группы')
                lines = self._group_summary(k, inc, st)
            else:
                lines = [f'Группа {k + 1}: все семплы исключены']
        else:
            i = what[1]
            k = m.group_index(i)
            if k is not None:
                for j in m.included(k):
                    if j != i:
                        ax.plot(D[mask], col(j)[mask], color='#d3ccd9', lw=0.8 * lw)
                if len(m.included(k)) > 1:
                    st = sd.group_stats(self.data, m.included(k), self.doc.range)
                    ax.plot(D[mask], self._ycurve(st['avg'])[mask], color=INK, lw=1.3 * lw, ls='--',
                            label=f'среднее группы {k + 1}')
            ax.plot(D[mask], col(i)[mask], color=PURPLE, lw=2.2 * lw, label=f'семпл {self.data.samples[i]}')
            lines = self._sample_summary(i, k)
        self._range_xlim(ax)
        plots.style_plain(ax, self.settings['repr'])
        ax.legend(frameon=False, fontsize=8.5, loc='upper left')
        for sp in ('top', 'right'):
            ax.spines[sp].set_visible(False)
        self.prev_canvas.draw_idle()
        self.prev_text.config(text='\n'.join(lines))

    def _time_str(self, i):
        t = self.data.meta.get('Start Time')
        return t[i].strip() if t else ''

    def _group_summary(self, k, inc, st):
        g, s = self.model.groups[k], self.data.samples
        out = [f'Группа {k + 1}' + (f' «{g["name"]}»' if g['name'] else ''),
               f'семплы {s[g["a"]]}–{s[g["b"]]}: в усреднении {len(inc)}, исключено {g["b"] - g["a"] + 1 - len(inc)}']
        t0, t1 = self._time_str(g['a']), self._time_str(g['b'])
        if t0:
            out.append(f'время {t0} – {t1}')
        stats = [('мода', st['mode_val'], 'нм'), ('медиана', st['median_val'], 'нм'), ('GSD', st['gsd_val'], '')]
        out.append(' · '.join(f'{n} {v:.2f}' if n == 'GSD' else f'{n} {v:.1f} {u}' for n, v, u in stats
                              if np.isfinite(v)))
        out.append(f'общая конц. {plots.sci(st["total_conc_val"])} см⁻³')
        bad = [s[i] for i in range(g['a'], g['b'] + 1) if self.data.is_normal(i) is False]
        if bad:
            out.append('статус не Normal Scan: ' + ', '.join(bad[:8]) + ('…' if len(bad) > 8 else ''))
        return out

    def _sample_summary(self, i, k):
        out = [f'Семпл {self.data.samples[i]}' + (f' · группа {k + 1}' if k is not None else ' · вне групп')
               + (' · исключён' if i in self.model.excluded else '')]
        t = self._time_str(i)
        if t:
            pause = sd.pause_lengths(self.data)[i]
            out.append(f'старт {t}' + (f' · пауза перед ним {pause / 60:.1f} мин' if pause > 0 else ''))
        st = self.data.status(i)
        if st:
            out.append(f'статус: {st}')
        vals = []
        for name, key in [('мода', 'Mode(nm)'), ('медиана', 'Median(nm)')]:
            v = sd.sample_metric(self.data, key, self.doc.range)
            if np.isfinite(v[i]):
                vals.append(f'{name} {v[i]:.1f} нм')
        if vals:
            out.append(' · '.join(vals))
        tc = sd.sample_metric(self.data, 'Total Concentration', self.doc.range)
        out.append(f'общая конц. {plots.sci(tc[i])} см⁻³')
        return out

    # ================= мышь и клавиатура =================

    def _bind_events(self):
        cv = self.cv
        cv.bind('<Button-1>', self._on_press)
        cv.bind('<Double-Button-1>', self._on_double)
        cv.bind('<B1-Motion>', self._on_drag)
        cv.bind('<ButtonRelease-1>', self._on_release)
        cv.bind('<Shift-Button-1>', self._on_shift_click)
        cv.bind(f'<{MOD}-Button-1>', self._on_cut_click)
        bind_right_click(cv, self._on_right_click)
        cv.bind('<Motion>', self._on_motion)
        cv.bind('<Leave>', lambda e: self.tooltip.hide())
        for key, d in (('Left', -1), ('Right', 1)):
            cv.bind(f'<{key}>', lambda e, d=d: self._move_cursor(d))
            cv.bind(f'<Shift-{key}>', lambda e, d=d: self._step(d))
        cv.bind('<space>', lambda e: self._toggle_cursor())
        self.axis_cv.bind('<Double-Button-1>', self._on_axis_double)
        self.axis_cv.bind('<Motion>', self._on_axis_motion)

    def _xy(self, event):
        return self.cv.canvasx(event.x), self.cv.canvasy(event.y)

    def _hit(self, event):
        if self._layout is None or self.model is None:
            return None, None
        cx, cy = self._xy(event)
        return self.row_at(cy), self.sample_at(cx)

    def _line_at(self, cy):
        """'lo' / 'hi', если курсор у красной линии."""
        rng = self.doc.range if self.doc else None
        if not rng or not rng.get('enabled') or 'map' not in self._layout['rows']:
            return None
        best = None
        for which in ('lo', 'hi'):
            dist = abs(cy - self._line_y(which))
            if dist <= LINE_HIT * self.s and (best is None or dist < best[0]):
                best = (dist, which)
        return best[1] if best else None

    def _group_label_at(self, event):
        row, i = self._hit(event)
        if row != 'label' or i is None:
            return None
        return self.model.group_index(i)

    def _on_press(self, event):
        self.cv.focus_set()
        self.tooltip.hide()
        row, i = self._hit(event)
        self._press = None
        if row is None:
            return
        cy = self._xy(event)[1]
        which = self._line_at(cy)
        if which:
            self._line_drag = which
            return
        if row == 'mapgrip':
            self._resize = (event.y_root, self.settings['heights']['map'])
            return
        if row == 'label':
            k = self._group_label_at(event)
            if k is not None:
                self._show_preview(('group', k))
                self.schedule_redraw()
        elif row == 'buttons' and i is not None:
            self._press = i

    def _on_double(self, event):
        row, i = self._hit(event)
        if row == 'label':
            k = self._group_label_at(event)
            if k is not None:
                self._edit_name(k)
        else:
            self._on_press(event)   # быстрые клики по соседним кнопкам — это два клика, а не двойной

    def _on_drag(self, event):
        if self._line_drag is not None:
            self._drag_line(self._line_drag, self._xy(event)[1])
            return
        if self._resize is not None:
            y0, h0 = self._resize
            self._set_size('map', h0 + (event.y_root - y0) / self.s)
            return
        if self._press is None:
            return
        j = self.sample_at(self._xy(event)[0], clamp=True)
        self.cv.delete('drag')
        if j is not None and j != self._press:
            L = self._layout
            y, h = L['rows']['buttons']
            a, b = min(self._press, j), max(self._press, j)
            self.cv.create_rectangle(L['xs'][a], y + 1, L['xs'][b] + L['cell'], y + h - 1,
                                     outline=PURPLE, width=max(1, round(2 * self.s)), dash=(4, 2), tags='drag')

    def _on_release(self, event):
        self.cv.delete('drag')
        if self._line_drag is not None:
            self._line_drag = None
            self.app.on_range_changed()
            return
        if self._resize is not None:
            self._resize = None
            return
        if self._press is None:
            return
        i, self._press = self._press, None
        j = self.sample_at(self._xy(event)[0], clamp=True)
        if j is None or j == i:
            self.cursor = i
            self.model.toggle(i)
            self._show_preview(('sample', i))
        else:
            self.cursor = j
            self.model.merge(i, j)
            self._show_preview(('group', self.model.group_index(j)))
        self.schedule_redraw()

    def _drag_line(self, which, cy):
        """Перетаскивание границы: прилипает к границам каналов, между линиями — хотя бы один канал."""
        e = self.data.edges
        rng = self.doc.range
        k = int(np.argmin(np.abs(np.log(e) - math.log(self._map_D(cy)))))
        if which == 'lo':
            k_hi = int(np.searchsorted(e, rng['hi'] * (1 + 1e-9), side='right')) - 1
            k = min(k, k_hi - 1)
        else:
            k_lo = int(np.searchsorted(e, rng['lo'] * (1 - 1e-9), side='left'))
            k = max(k, k_lo + 1)
        k = min(max(k, 0), len(e) - 1)
        if abs(float(e[k]) - rng[which]) > 1e-9:
            rng[which] = float(e[k])
            self.refresh_views()

    def _on_shift_click(self, event):
        self.cv.focus_set()
        row, i = self._hit(event)
        if row == 'buttons' and i is not None and self.model:
            self.model.merge(self.cursor, i)
            self.cursor = i
            self._show_preview(('group', self.model.group_index(i)))
            self.schedule_redraw()

    def _on_cut_click(self, event):
        self.cv.focus_set()
        row, i = self._hit(event)
        if row == 'buttons' and i is not None and self.model:
            self.model.cut(i)
            self.cursor = i
            self._show_preview(('sample', i))
            self.schedule_redraw()

    def _on_right_click(self, event):
        self.cv.focus_set()
        self._press = None
        row, i = self._hit(event)
        if i is not None and row not in (None, 'label'):
            self.cursor = i
            self._show_preview(('sample', i))
            self.schedule_redraw()

    def _on_motion(self, event):
        row, i = self._hit(event)
        if row is None:
            return
        cy = self._xy(event)[1]
        on_line = self._line_at(cy) is not None
        cursor = 'sb_v_double_arrow' if row == 'mapgrip' or on_line else ''
        if self.cv.cget('cursor') != cursor:
            self.cv.configure(cursor=cursor)
        if on_line:
            self.tooltip.hide()
            return
        if i is None or row in ('label', 'ticks', 'mapgrip'):
            self.tooltip.hide()
            return
        text = f'Семпл {self.data.samples[i]}'
        if row == 'status':
            st = self.data.status(i)
            text += f' · {st}' if st else ' · нет данных о статусе'
        else:
            t = self._time_str(i)
            if t:
                text += f' · {t}'
            if self.data.is_normal(i) is False:
                text += f' · {self.data.status(i)}'
        self.tooltip.schedule((row == 'status', i), text, event.x_root, event.y_root)

    def _on_axis_motion(self, event):
        hit = self._axis_label_at(event)
        cursor = 'xterm' if hit else ''
        if self.axis_cv.cget('cursor') != cursor:
            self.axis_cv.configure(cursor=cursor)

    def _axis_label_at(self, event):
        for which in ('lo', 'hi'):
            for item in self.axis_cv.find_withtag(f'rlabel_{which}'):
                x0, y0, x1, y1 = self.axis_cv.bbox(item)
                if x0 - 4 <= event.x <= x1 + 4 and y0 - 3 <= event.y <= y1 + 3:
                    return which
        return None

    def _on_axis_double(self, event):
        which = self._axis_label_at(event)
        if which:
            self._edit_range_value(which)

    def _edit_range_value(self, which):
        """Ввод границы с клавиатуры: значение остаётся как введено; в расчёт идут каналы, целиком
        лежащие в диапазоне."""
        rng = self.doc.range
        ty = self._line_y(which)
        var = tk.StringVar(value=f'{rng[which]:.1f}')
        e = tk.Entry(self.axis_cv, textvariable=var, font=self.font_bold, fg=RANGE_RED, justify='right',
                     relief='solid', bd=1)
        w, h = LEFT_W * self.s - 6 * self.s, 20 * self.s
        win = self.axis_cv.create_window(2 * self.s, ty - h / 2, window=e, anchor='nw', width=w, height=h,
                                         tags='editor')
        e.focus_set()
        e.select_range(0, tk.END)
        done = {'v': False}

        def finish(save):
            if done['v']:
                return 'break'
            done['v'] = True
            text = var.get().replace(',', '.').strip()
            self.axis_cv.delete(win)
            e.destroy()
            if save:
                self.app.set_range_value(self.doc, which, text)
            self.cv.focus_set()
            return 'break'
        e.bind('<Return>', lambda ev: finish(True))
        e.bind('<KP_Enter>', lambda ev: finish(True))
        e.bind('<Escape>', lambda ev: finish(False))
        e.bind('<FocusOut>', lambda ev: finish(True))

    def _move_cursor(self, d):
        if self.model is None:
            return 'break'
        self.cursor = min(max(self.cursor + d, 0), self.data.n - 1)
        self._show_preview(('sample', self.cursor))
        self._ensure_visible(self.cursor)
        self.schedule_redraw()
        return 'break'

    def _step(self, d):
        if self.model is None:
            return 'break'
        self.cursor = self.model.step(self.cursor, d)
        self._show_preview(('sample', self.cursor))
        self._ensure_visible(self.cursor)
        self.schedule_redraw()
        return 'break'

    def _toggle_cursor(self):
        if self.model is not None:
            self.model.toggle(self.cursor)
            self._show_preview(('sample', self.cursor))
        return 'break'

    def _ensure_visible(self, i):
        L = self._layout
        if not L or not self._hbar_shown:
            return
        x0, x1 = L['xs'][i], L['xs'][i] + L['cell']
        vx0 = self.cv.canvasx(0)
        vw = self.cv.winfo_width()
        if x0 < vx0 or x1 > vx0 + vw:
            self.cv.xview_moveto(max(0.0, (x0 - vw / 2) / L['width']))

    def owns(self, widget):
        return widget in (self.cv, self.axis_cv)

    def on_wheel(self, event, delta):
        """Колесо над рядом: Ctrl/⌘ — масштаб, Shift — прокрутка вбок. True, если обработано."""
        if self.model is None:
            return False
        zoom_mod = 0x0008 if IS_MAC else 0x0004
        if event.state & zoom_mod:
            self.zoom = min(max(self.zoom * (1.15 if delta > 0 else 1 / 1.15), 1.0), 6.0)
            self.schedule_redraw()
            return True
        if event.state & 0x0001 and self._hbar_shown:
            self.cv.xview_scroll(-1 if delta > 0 else 1, 'units')
            return True
        return False

    # ================= название группы =================

    def _edit_name(self, k):
        L = self._layout
        g = self.model.groups[k]
        x0, x1 = self._group_span(g)
        y, h = L['rows']['label']
        var = tk.StringVar(value=g['name'])
        e = tk.Entry(self.cv, textvariable=var, font=self.font, relief='solid', bd=1)
        width = max(x1 - x0, 160 * self.s)
        win = self.cv.create_window(min(x0, L['width'] - width), y, window=e, anchor='nw', width=width, height=h,
                                    tags='editor')
        e.focus_set()
        e.select_range(0, tk.END)
        done = {'v': False}

        def finish(save):
            if done['v']:
                return
            done['v'] = True
            name = var.get()
            self.cv.delete(win)
            e.destroy()
            if save:
                self.model.rename(k, name)
            self.cv.focus_set()
            return 'break'
        e.bind('<Return>', lambda ev: finish(True))
        e.bind('<KP_Enter>', lambda ev: finish(True))
        e.bind('<Escape>', lambda ev: finish(False))
        e.bind('<FocusOut>', lambda ev: finish(True))

    def group_title(self, k):
        return specs.group_title(self.doc, k)
