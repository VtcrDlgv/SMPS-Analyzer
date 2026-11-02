"""Проект: несколько открытых файлов SMPS и общие настройки; сохранение в архив .smpsa.

Файл .smpsa — обычный ZIP:
    project.json   — группы, названия, исключения, диапазоны, настройки вида и анализа
    data/…         — исходные файлы прибора, байт в байт
"""
import copy
import hashlib
import json
import os
import re
import tempfile
import zipfile
from datetime import datetime

import smps_data as sd
from group_model import GroupModel

FORMAT = 'SMPS Analyzer project'
FORMAT_VERSION = 1
EXT = '.smpsa'
MAX_FILES = 16

DEFAULT_SETTINGS = {
    'plot_palette': 'standard',     # палитра графиков
    'map_palette': 'ikt',           # палитра тепловой карты
    'lw_preview': 1.0,              # множитель толщины линий превью и «Кривых»
    'lw_plots': 1.0,                # множитель толщины линий графиков
    'repr': 'dN',                   # 'dN' или 'dNdlogDp'
    'show': {'map': True, 'curves': False, 'strip': True, 'preview': True, 'status': True},
    'strip_metric': 'мода',
    'heights': {'map': 130, 'curves': 600, 'preview': 230},
    'plot_stats': {'show_mean': True, 'show_mode': True, 'show_median': False,
                   'show_geo_mean': False, 'show_total_conc': True},
    'compare': [],                  # [{'file': индекс, 'first': '1', 'last': '5'}]
}


class Document:
    """Одна вкладка: файл прибора (или пустая страница) и всё, что с ним сделано."""

    _ids = 0

    def __init__(self, data=None):
        Document._ids += 1
        self.id = Document._ids
        self.data = None
        self.model = None
        self.range = None
        self.fit = {'enabled': False, 'modes': 1}
        self.cursor = 0
        self.preview = None
        self.zoom = 1.0
        self.n_value = 3
        self.log_axes = {}        # имя графика -> [лог. X, лог. Y] (переключается у отдельного графика)
        self.built = None         # «подпись» настроек на момент последнего построения графиков
        self.plot_cache = None    # {'entries', 'pngs', 'width'} — построенные графики этой вкладки
        self.built_first = False  # последнее построение было первым (прокрутить к графикам)
        self.restore_built = False  # из проекта: графики были построены — построить при открытии
        if data is not None:
            self.set_data(data)

    @property
    def empty(self):
        return self.data is None

    @property
    def title(self):
        return self.data.name if self.data else 'Новая вкладка'

    def set_data(self, data):
        self.data = data
        self.model = GroupModel(data.n)
        self.range = sd.full_range(data)
        self.model.set_ranges(sd.auto_ranges(data), 'auto')
        self.model._undo.clear()

    # ---------- группы по номерам семплов (для файла проекта) ----------

    def groups_json(self):
        s = self.data.samples
        return [{'first': s[g['a']], 'last': s[g['b']], 'name': g['name']} for g in self.model.groups]

    def load_groups(self, groups, excluded, preset):
        pos = {num: i for i, num in enumerate(self.data.samples)}
        ranges, names = [], []
        for g in groups:
            if g.get('first') in pos and g.get('last') in pos:
                a, b = pos[g['first']], pos[g['last']]
                if a <= b:
                    ranges.append((a, b))
                    names.append(g.get('name', ''))
        m = self.model
        m.groups = [{'a': a, 'b': b, 'name': nm} for (a, b), nm in zip(ranges, names)]
        m.excluded = {pos[x] for x in excluded if x in pos}
        m.preset = preset
        m._undo.clear()
        m._redo.clear()

    def group_key(self, k):
        g = self.model.groups[k]
        return (self.data.samples[g['a']], self.data.samples[g['b']])


class Project:
    def __init__(self):
        self.docs = []
        self.active = -1
        self.path = None
        self.changes = 0          # растёт при каждой правке — чтобы фоновое сохранение знало, всё ли записало
        self._dirty = False
        self.settings = copy.deepcopy(DEFAULT_SETTINGS)

    @property
    def dirty(self):
        return self._dirty

    @dirty.setter
    def dirty(self, value):
        if value:
            self.changes += 1
        self._dirty = bool(value)

    @property
    def doc(self):
        return self.docs[self.active] if 0 <= self.active < len(self.docs) else None

    @property
    def file_docs(self):
        return [d for d in self.docs if not d.empty]

    @property
    def name(self):
        return os.path.basename(self.path) if self.path else 'Новый проект'


# ------------------------------------------------------------
# Подпись настроек — чтобы понять, что изменилось после построения графиков
# ------------------------------------------------------------

def plot_signature(doc, settings):
    m = doc.model
    rng = doc.range or {}
    return {
        'группы': (tuple((g['a'], g['b'], g['name']) for g in m.groups), tuple(sorted(m.excluded))),
        'диапазон': (rng.get('enabled'), round(rng.get('lo', 0), 6), round(rng.get('hi', 0), 6)),
        'палитра': settings['plot_palette'],
        'толщина линий': settings['lw_plots'],
        'статистики': tuple(sorted(settings['plot_stats'].items())),
        'представление': settings['repr'],
        'аппроксимация': (doc.fit['enabled'], doc.fit['modes']),
    }


def unique_name(project, path):
    """Имя вкладки: у файла, который уже открыт, — «имя (1).txt», «имя (2).txt»…"""
    base = os.path.basename(path)
    taken = {d.data.name for d in project.file_docs}
    if base not in taken:
        return ''
    stem, ext = os.path.splitext(base)
    k = 1
    while f'{stem} ({k}){ext}' in taken:
        k += 1
    return f'{stem} ({k}){ext}'


def changed_parts(old, new):
    if old is None:
        return []
    return [k for k in new if old.get(k) != new[k]]


# ------------------------------------------------------------
# Сохранение и загрузка
# ------------------------------------------------------------

def _safe_name(name, k):
    base = re.sub(r'[^\w.\-]+', '_', os.path.basename(name), flags=re.UNICODE) or 'file.txt'
    return f'data/{k + 1:02d}_{base}'


def prepare(project, app_version):
    """Снимок проекта для записи: (project.json, [(имя в архиве, байты)]). Быстро — делается в окне программы,
    а сама запись архива (write) может идти в фоне: дальнейшие правки в проекте её не затронут."""
    files = []
    blobs = []
    docs = project.file_docs
    active_doc = project.doc
    for k, doc in enumerate(docs):
        arc = _safe_name(doc.data.path, k)
        rng = doc.range or {}
        files.append({
            'data': arc,
            'name': doc.data.name,
            'original_path': os.path.abspath(doc.data.path) if os.path.isabs(doc.data.path) or os.path.exists(doc.data.path)
            else doc.data.path,
            'sha256': hashlib.sha256(doc.data.raw).hexdigest(),
            'groups': doc.groups_json(),
            'excluded': [doc.data.samples[i] for i in sorted(doc.model.excluded)],
            'preset': doc.model.preset,
            'n': doc.n_value,
            'range': {'enabled': bool(rng.get('enabled')), 'lo': rng.get('lo'), 'hi': rng.get('hi')},
            'fit': dict(doc.fit),
            'log_axes': copy.deepcopy(doc.log_axes),
            'built': doc.built is not None,      # графики были построены — при открытии построить сразу
            'cursor': doc.cursor,
        })
        blobs.append((arc, doc.data.raw))
    active = docs.index(active_doc) if active_doc in docs else 0
    meta = {
        'format': FORMAT, 'format_version': FORMAT_VERSION, 'app_version': app_version,
        'saved': datetime.now().astimezone().isoformat(timespec='seconds'),
        'active': active, 'files': files, 'settings': copy.deepcopy(project.settings),
    }
    return json.dumps(meta, ensure_ascii=False, indent=1), blobs


def write(path, meta_text, blobs, progress=None):
    """Атомарно: пишем во временный файл рядом и подменяем — при сбое старый проект цел."""
    folder = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(prefix='.smpsa_', suffix='.tmp', dir=folder)
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as z:
            z.writestr('project.json', meta_text)
            for i, (arc, raw) in enumerate(blobs):
                z.writestr(arc, raw)
                if progress:
                    progress((i + 1) / len(blobs))
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def save(project, path, app_version):
    """Сохранить сразу (без фона)."""
    write(path, *prepare(project, app_version))
    project.path = path
    project.dirty = False


def load(path, log=print):
    """Читает .smpsa; возвращает Project. Предупреждения пишет в log."""
    with zipfile.ZipFile(path) as z:
        try:
            meta = json.loads(z.read('project.json').decode('utf-8'))
        except KeyError:
            raise ValueError('В архиве нет project.json — это не проект SMPS Analyzer')
        if meta.get('format') != FORMAT:
            raise ValueError('Это не проект SMPS Analyzer')
        if int(meta.get('format_version', 0)) > FORMAT_VERSION:
            log(f"Проект сохранён более новой версией программы ({meta.get('app_version')}); "
                'часть настроек может не прочитаться.')
        project = Project()
        settings = copy.deepcopy(DEFAULT_SETTINGS)
        for k, v in (meta.get('settings') or {}).items():
            if isinstance(v, dict) and isinstance(settings.get(k), dict):
                settings[k].update(v)
            else:
                settings[k] = v
        project.settings = settings
        for f in meta.get('files', []):
            try:
                raw = z.read(f['data'])
            except KeyError:
                log(f"В проекте нет данных файла {f.get('data')} — пропущен.")
                continue
            if f.get('sha256') and hashlib.sha256(raw).hexdigest() != f['sha256']:
                log(f"Данные {f['data']} повреждены (контрольная сумма не совпадает).")
            orig = f.get('original_path') or f['data']
            data = sd.read_smps_bytes(raw, orig, log=lambda m: None)
            if f.get('name') and f['name'] != os.path.basename(orig):
                data.label = f['name']
            doc = Document(data)
            doc.load_groups(f.get('groups', []), f.get('excluded', []), f.get('preset'))
            r = f.get('range') or {}
            if r.get('lo') is not None and r.get('hi') is not None:
                doc.range = {'enabled': bool(r.get('enabled')), 'lo': float(r['lo']), 'hi': float(r['hi'])}
            doc.fit.update(f.get('fit') or {})
            doc.log_axes = {k: [bool(v[0]), bool(v[1])] for k, v in (f.get('log_axes') or {}).items()}
            doc.n_value = int(f.get('n', 3) or 3)
            doc.restore_built = bool(f.get('built'))
            doc.cursor = min(int(f.get('cursor', 0) or 0), data.n - 1)
            project.docs.append(doc)
            if os.path.isfile(orig):
                try:
                    with open(orig, 'rb') as fh:
                        if hashlib.sha256(fh.read()).hexdigest() != f.get('sha256'):
                            log(f'Файл на диске изменился с момента сохранения проекта: {orig} '
                                '(в проекте используется сохранённая копия).')
                except OSError:
                    pass
        project.active = min(int(meta.get('active', 0) or 0), len(project.docs) - 1) if project.docs else -1
        project.path = path
        project.dirty = False
        return project
