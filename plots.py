"""Построение графиков. Описание графика (spec) — словарь из простых данных, поэтому графики
можно рисовать и в отдельных процессах (параллельно по ядрам).

spec = {
  'kind': 'overview' | 'single' | 'compare' | 'dynamics',
  'figsize': (ширина, высота) в дюймах,
  'style': {'palette', 'lw', 'repr', 'xmax', 'flags'},
  'items': [{'title', 'index', 'D', 'Dx', 'dlogdp', 'dn', 'mask', 'stats', 'fit_modes', 'fit'}],
  'integral': {'lo', 'hi'}                — (необязательно) закрасить диапазон интеграла
  ... для 'dynamics': 'x', 'y', 'groups', 'excluded', 'ylabel', 'title'
}
"""
import io
import math

import numpy as np
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.ticker import FixedLocator, Formatter, FuncFormatter, NullFormatter

import lognorm

PLOT_PALETTES = {
    'standard': ('Стандартная', ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300',
                                 '#6250d6', '#e34948']),
    'okabe': ('Okabe–Ito', ['#0072B2', '#E69F00', '#009E73', '#D55E00', '#56B4E9', '#CC79A7',
                            '#F0E442', '#000000']),
    'tab10': ('Matplotlib tab10', ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b',
                                   '#e377c2', '#7f7f7f', '#bcbd22', '#17becf']),
    'bw': ('Чёрно-белая (для печати)', ['#000000']),
}
MAP_PALETTES = {
    'ikt': 'Фиолетовая ИКТ',
    'viridis': 'Viridis',
    'magma': 'Magma',
    'gray': 'Оттенки серого',
}
LW_CHOICES = [0.5, 0.75, 1.0, 1.5, 2.0]
LINE_STYLES = ['-', '--', ':']
BW_STYLES = ['-', '--', ':', '-.', (0, (5, 1.5)), (0, (3, 1, 1, 1, 1, 1)), (0, (1, 3)), (0, (8, 2, 2, 2))]
STAT_COLOR = '#3f4443'
FIT_COLOR = '#7a7f7e'

X_LABEL = 'Размер, нм'
Y_LABELS = {'dN': 'Концентрация', 'dNdlogDp': 'dN/dlogDp'}
Y_UNIT = 'см⁻³'
_SUPERSCRIPT = str.maketrans('-0123456789', '⁻⁰¹²³⁴⁵⁶⁷⁸⁹')


def new_figure(figsize):
    """Фигура с движком компоновки: поля пересчитываются при каждой отрисовке."""
    try:
        return Figure(figsize=figsize, layout='tight')        # matplotlib >= 3.6
    except TypeError:
        return Figure(figsize=figsize, tight_layout=True)


def group_style(k, palette='standard'):
    """Цвет и стиль линии k-й кривой."""
    colors = PLOT_PALETTES.get(palette, PLOT_PALETTES['standard'])[1]
    if palette == 'bw':
        return '#000000', BW_STYLES[k % len(BW_STYLES)]
    return colors[k % len(colors)], LINE_STYLES[min(k // len(colors), len(LINE_STYLES) - 1)]


def sci(v, digits=3):
    """3.87·10⁶ — для подписей в легенде."""
    if not np.isfinite(v) or v == 0:
        return '0' if v == 0 else '—'
    e = int(math.floor(math.log10(abs(v))))
    if -2 <= e <= 3:
        return f'{v:.{max(0, digits - 1 - e)}f}'
    return f'{v / 10 ** e:.{digits - 1}f}·10{str(e).translate(_SUPERSCRIPT)}'


class PlainFormatter(Formatter):
    """Обычные числа без ×10ⁿ; тысячи отделяются пробелом (150 000)."""

    def set_locs(self, locs):
        super().set_locs(locs)
        self.decimals = 6
        vals = [v for v in locs if np.isfinite(v)]
        for d in range(7):
            if all(abs(v * 10 ** d - round(v * 10 ** d)) < 1e-6 * max(1.0, abs(v) * 10 ** d) for v in vals):
                self.decimals = d
                break

    def __call__(self, x, pos=None):
        s = f'{x:,.{getattr(self, "decimals", 0)}f}'.replace(',', ' ')
        return '0' if s.strip('-0. ') == '' else s


def plain_log_x(ax):
    """Логарифмическая ось X с метками 10, 20, 50, 100 …"""
    ax.set_xscale('log')
    lo, hi = ax.get_xlim()
    ticks = [m * 10 ** e for e in range(-2, 6) for m in (1, 2, 5) if lo <= m * 10 ** e <= hi]
    if ticks:
        ax.xaxis.set_major_locator(FixedLocator(ticks))
        ax.xaxis.set_major_formatter(PlainFormatter())
    ax.xaxis.set_minor_formatter(NullFormatter())


def style_plain(ax, repr_='dN', fontsize=9, ticksize=8):
    """Небольшие графики (превью, «Кривые»): обычные числа, лог. ось X."""
    plain_log_x(ax)
    ax.yaxis.set_major_formatter(PlainFormatter())
    ax.set_xlabel(X_LABEL, fontsize=fontsize)
    ax.set_ylabel(f'{Y_LABELS[repr_]}, {Y_UNIT}', fontsize=fontsize)
    ax.tick_params(axis='both', which='major', labelsize=ticksize)
    ax.grid(True, linestyle=':', alpha=0.6)


def style_axes(ax, repr_='dN', fontsize=14, ticksize=12):
    """Основные графики: множитель ×10ⁿ в подписи оси Y, ось X от нуля."""
    ymin, ymax = ax.get_ylim()
    max_abs = max(abs(ymin), abs(ymax))
    unit = Y_UNIT
    if max_abs > 0:
        exponent = int(np.floor(np.log10(max_abs)))
        scale = 10 ** exponent
        ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f'{value / scale:.1f}'))
        if exponent:
            unit = f'×10{str(exponent).translate(_SUPERSCRIPT)} {Y_UNIT}'
    ax.set_ylabel(f'{Y_LABELS[repr_]}, {unit}', fontsize=fontsize)
    ax.set_xlabel(X_LABEL, fontsize=fontsize)
    ax.tick_params(axis='both', which='major', labelsize=ticksize)
    ax.grid(True, linestyle=':', alpha=0.6)


def item_xy(it, repr_):
    """Точки кривой внутри диапазона (положительные значения)."""
    y = it['dn'] / it['dlogdp'] if repr_ == 'dNdlogDp' else it['dn']
    m = np.asarray(it['mask'], bool) & np.isfinite(y) & (y > 0)
    return np.asarray(it['D'])[m], y[m]


def _xlim(ax, style):
    if style.get('xmax'):
        ax.set_xlim(0, style['xmax'])
    else:
        ax.set_xlim(left=0)


def _axes(ax, st, ylo=None, fontsize=14, ticksize=12):
    """Оси основных графиков: линейные (X от нуля, ×10ⁿ на оси Y) или логарифмические — по настройке
    этого графика (style['log_x'], style['log_y'])."""
    if st.get('log_x'):
        ax.set_xscale('log')
        if st.get('xmax'):
            ax.set_xlim(right=st['xmax'])
        plain_log_x(ax)
    else:
        _xlim(ax, st)
    if st.get('log_y'):
        ax.set_yscale('log')
        if ylo:                      # не давать «хвостам» мод уводить ось к 10⁻³⁰
            ax.set_ylim(bottom=ylo * 0.5)
        ax.set_ylabel(f"{Y_LABELS[st['repr']]}, {Y_UNIT}", fontsize=fontsize)
        ax.set_xlabel(X_LABEL, fontsize=fontsize)
        ax.tick_params(axis='both', which='major', labelsize=ticksize)
        ax.grid(True, which='major', linestyle=':', alpha=0.6)
    else:
        style_axes(ax, st['repr'], fontsize, ticksize)


def _min_positive(spec):
    vals = [item_xy(it, spec['style']['repr'])[1] for it in spec['items']]
    vals = [v.min() for v in vals if len(v)]
    return min(vals) if vals else None


def _integral_span(ax, spec):
    ig = spec.get('integral')
    if ig:
        ax.axvspan(ig['lo'], ig['hi'], color='#963cbd', alpha=0.08, lw=0)
        for x in (ig['lo'], ig['hi']):
            ax.axvline(x, color='#963cbd', lw=0.8, alpha=0.6)


def _legend_many(ax, n):
    if n > 10:   # много кривых — легенда справа от графика, в несколько столбцов
        ax.legend(loc='upper left', bbox_to_anchor=(1.01, 1.0), fontsize=10, ncol=math.ceil(n / 20), frameon=False)
    elif n:
        ax.legend(loc='upper right', fontsize=13)


def draw_overview(fig, spec):
    st = spec['style']
    ax = fig.add_subplot(111)
    lw = 1.8 * st.get('lw', 1.0)
    for it in spec['items']:
        d, y = item_xy(it, st['repr'])
        if len(d):
            color, ls = group_style(it['index'], st['palette'])
            ax.plot(d, y, color=color, linestyle=ls, linewidth=lw, label=it['title'])
        fit = (spec.get('fits') or {}).get(it['index'])
        if fit:
            _draw_fit(ax, it, fit, st, color=group_style(it['index'], st['palette'])[0], legend=False)
    _integral_span(ax, spec)
    _axes(ax, st, _min_positive(spec))
    _legend_many(ax, len(ax.get_legend_handles_labels()[0]))
    return ax


STAT_LINES = [  # (флаг, ключ, подпись, стиль линии)
    ('show_mean', 'mean_val', 'Среднее', '--'),
    ('show_mode', 'mode_val', 'Мода', '-'),
    ('show_median', 'median_val', 'Медиана', '-.'),
    ('show_geo_mean', 'geo_mean_val', 'Геом. среднее', ':'),
]


def _draw_fit(ax, it, fit, st, color=FIT_COLOR, legend=True):
    """Моды аппроксимации (тонкий пунктир) и их сумма (точки); в представлении dN — ×Δlog."""
    D = np.asarray(it['Dx'])
    m = np.asarray(it['mask'], bool)
    scale = 1.0 if st['repr'] == 'dNdlogDp' else np.asarray(it['dlogdp'])
    lw = st.get('lw', 1.0)
    handles = []
    for j, mode in enumerate(fit['modes']):
        y = lognorm.curve(D, fit, j) * scale
        h, = ax.plot(D[m], y[m], color=color, ls='--', lw=1.0 * lw,
                     label=f"Логнорм. {j + 1}: {mode['CMD']:.1f} нм, σg {mode['GSD']:.2f}")
        handles.append(h)
    if len(fit['modes']) > 1:
        y = lognorm.curve(D, fit) * scale
        h, = ax.plot(D[m], y[m], color=color, ls=':', lw=1.3 * lw, label=f"Сумма мод (R² {fit['r2']:.3f})")
        handles.append(h)
    elif handles:
        handles[0].set_label(handles[0].get_label() + f" (R² {fit['r2']:.3f})")
    return handles


def compute_fit(it, modes):
    y = np.asarray(it['dn']) / np.asarray(it['dlogdp'])
    return lognorm.fit(it['Dx'], y, modes, it['mask'])


def draw_single(fig, spec):
    st = spec['style']
    flags = st.get('flags', {})
    ax = fig.add_subplot(111)
    it = spec['items'][0]
    d, y = item_xy(it, st['repr'])
    color, ls = group_style(it['index'], st['palette'])
    if len(d):
        ax.plot(d, y, color=color, linestyle=ls, linewidth=1.8 * st.get('lw', 1.0))
    else:
        ax.text(0.5, 0.5, 'Нет данных', ha='center', va='center', transform=ax.transAxes)
    stats = it['stats']
    legend = []
    for flag, key, name, style in STAT_LINES:
        val = stats.get(key, np.nan)
        if flags.get(flag) and np.isfinite(val):
            ax.axvline(val, color=STAT_COLOR, linestyle=style, linewidth=1.1 * st.get('lw', 1.0))
            legend.append(Line2D([0], [0], color=STAT_COLOR, linestyle=style, label=f'{name}: {val:.1f} нм'))
    if flags.get('show_total_conc') and np.isfinite(stats.get('total_conc_val', np.nan)):
        legend.append(Line2D([0], [0], color='none', label=f"Общая конц.: {sci(stats['total_conc_val'])} {Y_UNIT}"))
    fit = (spec.get('fits') or {}).get(it['index'])
    if fit is None and it.get('fit_modes'):
        fit = compute_fit(it, it['fit_modes'])
    _integral_span(ax, spec)
    _axes(ax, st, _min_positive(spec))
    if legend:
        first = ax.legend(handles=legend, loc='best', fontsize=13)      # где меньше всего закрывает кривую
        ax.add_artist(first)
    if fit:
        fh = _draw_fit(ax, it, fit, st)
        ax.legend(handles=fh, loc='center right', fontsize=11, framealpha=0.85)
    return ax


def draw_dynamics(fig, spec):
    st = spec['style']
    ax = fig.add_subplot(111)
    x = np.arange(1, len(spec['y']) + 1)
    y = np.asarray(spec['y'], float)
    in_group = np.zeros(len(y), bool)
    ymax = np.nanmax(y) if np.any(np.isfinite(y)) else 1
    for k, (a, b, title) in enumerate(spec['groups']):
        if k % 2 == 0:
            ax.axvspan(a + 0.5, b + 1.5, color='#efedf1', lw=0, zorder=0)
        color, _ = group_style(k, st['palette'])
        idx = np.arange(a, b + 1)
        in_group[idx] = True
        inc = [i for i in idx if i not in spec['excluded']]
        exc = [i for i in idx if i in spec['excluded']]
        ax.plot(x[inc], y[inc], 'o', color=color, ms=6 * st.get('lw', 1.0) ** 0.5, zorder=3)
        if exc:
            ax.plot(x[exc], y[exc], 'o', mfc='white', mec=color, ms=6, zorder=3)
        if len(spec['groups']) <= 24:
            ax.text((a + b) / 2 + 1, 1.01, title, transform=ax.get_xaxis_transform(), ha='center', va='bottom',
                    fontsize=9, color='#3f4443', rotation=0 if len(spec['groups']) <= 8 else 60)
    free = ~in_group
    if free.any():
        ax.plot(x[free], y[free], 'o', mfc='white', mec='#b3a9bb', ms=6, zorder=2)
    ax.set_xlim(0.5, len(y) + 0.5)
    step = next((s for s in (1, 2, 5, 10, 20, 50) if len(y) / s <= 30), 100)
    ax.xaxis.set_major_locator(FixedLocator(list(range(step, len(y) + 1, step)) if step > 1 else list(x)))
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: spec['samples'][int(v) - 1] if 1 <= v <= len(y) else ''))
    ax.set_xlabel('Семпл', fontsize=13)
    ax.set_ylabel(spec['ylabel'], fontsize=13)
    ax.yaxis.set_major_formatter(PlainFormatter())
    ax.tick_params(labelsize=11)
    ax.grid(True, axis='y', linestyle=':', alpha=0.6)
    if not np.isfinite(ymax):
        ax.text(0.5, 0.5, 'Нет данных', ha='center', va='center', transform=ax.transAxes)
    return ax


def draw(fig, spec):
    kind = spec['kind']
    if kind in ('overview', 'compare'):
        return draw_overview(fig, spec)
    if kind == 'dynamics':
        return draw_dynamics(fig, spec)
    return draw_single(fig, spec)


def make_figure(spec):
    fig = new_figure(spec['figsize'])
    draw(fig, spec)
    return fig


# ------------------------------------------------------------
# Рендер (вызывается и в рабочих процессах)
# ------------------------------------------------------------

def render_png(spec, dpi):
    """(ширина, высота, PNG-байты) — сжатая картинка для показа в окне."""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from PIL import Image
    fig = make_figure(spec)
    fig.set_dpi(dpi)
    canvas = FigureCanvasAgg(fig)
    canvas.draw()
    w, h = canvas.get_width_height()
    img = Image.frombuffer('RGBA', (w, h), bytes(canvas.buffer_rgba()), 'raw', 'RGBA', 0, 1).convert('RGB')
    buf = io.BytesIO()
    img.save(buf, 'PNG', compress_level=1)
    return w, h, buf.getvalue()


def render_file(spec, path, width_px):
    fig = make_figure(spec)
    fig.savefig(path, dpi=width_px / fig.get_size_inches()[0])
    return path


def warm_up():
    return True


# ------------------------------------------------------------
# Таблица данных графика (для «Сохранить CSV»)
# ------------------------------------------------------------

def spec_table(spec):
    """(заголовки, столбцы): общий столбец размеров, если сетки совпадают, иначе пары X/Y."""
    st = spec['style']
    items = spec['items']
    if not items:
        return [], []
    same = all(len(it['D']) == len(items[0]['D']) and np.allclose(it['D'], items[0]['D']) for it in items)
    heads, cols = [], []
    if same:
        union = np.zeros(len(items[0]['D']), bool)
        for it in items:
            union |= np.asarray(it['mask'], bool)
        heads.append(X_LABEL)
        cols.append(np.asarray(items[0]['D'])[union])
        for it in items:
            y = it['dn'] / it['dlogdp'] if st['repr'] == 'dNdlogDp' else np.asarray(it['dn'], float)
            y = np.where(it['mask'], y, np.nan)[union]
            heads.append(it['title'])
            cols.append(y)
    else:
        for it in items:
            m = np.asarray(it['mask'], bool)
            y = it['dn'] / it['dlogdp'] if st['repr'] == 'dNdlogDp' else np.asarray(it['dn'], float)
            heads += [f"{X_LABEL} ({it['title']})", it['title']]
            cols += [np.asarray(it['D'])[m], np.asarray(y)[m]]
    # одинаковые заголовки разводим, чтобы столбцы не слились при импорте
    seen = {}
    for i, h in enumerate(heads):
        if h in seen:
            seen[h] += 1
            heads[i] = f'{h} ({seen[h]})'
        else:
            seen[h] = 1
    return heads, cols


def write_csv(path, heads, cols):
    """CSV для Origin/Excel: UTF-8 с BOM, 6 значащих цифр, столбцы разной длины допускаются."""
    import csv
    n = max((len(c) for c in cols), default=0)
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(heads)
        for i in range(n):
            row = []
            for c in cols:
                v = c[i] if i < len(c) else np.nan
                row.append('' if not np.isfinite(v) else f'{v:.6g}')
            w.writerow(row)
