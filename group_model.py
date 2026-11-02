"""Модель разбиения семплов на группы: непрерывные диапазоны, исключённые семплы, названия, отмена."""
import copy


class GroupModel:
    """Семплы нумеруются с 0. Группа — непрерывный диапазон [a, b] с необязательным названием.

    Семпл может быть вне групп («свободный»). Исключённый семпл остаётся в своей группе,
    но не участвует в усреднении.
    """

    UNDO_DEPTH = 100

    def __init__(self, n):
        self.n = n
        self.groups = []      # список словарей {'a', 'b', 'name'}, по возрастанию a
        self.excluded = set()
        self.preset = None    # каким пресетом получено текущее разбиение (None — правили вручную)
        self._undo, self._redo = [], []
        self.listeners = []

    # ---------- служебное ----------

    def _state(self):
        return copy.deepcopy((self.groups, self.excluded, self.preset))

    def _restore(self, state):
        self.groups, self.excluded, self.preset = copy.deepcopy(state)

    def _begin(self):
        self._undo.append(self._state())
        del self._undo[:-self.UNDO_DEPTH]
        self._redo.clear()

    def _changed(self):
        self.groups.sort(key=lambda g: g['a'])
        for cb in self.listeners:
            cb()

    def _edit(self, func, preset=None):
        """Выполняет правку с записью в историю. Ручные правки сбрасывают отметку пресета;
        правка, ничего не изменившая, в историю не попадает."""
        before = self._state()
        self._begin()
        func()
        self.groups.sort(key=lambda g: g['a'])
        if self._state()[:2] != before[:2] or preset is not None:
            self.preset = preset
        if self._state() == before:
            self._undo.pop()
            return False
        self._changed()
        return True

    def can_undo(self):
        return bool(self._undo)

    def undo(self):
        if self._undo:
            self._redo.append(self._state())
            self._restore(self._undo.pop())
            self._changed()

    def redo(self):
        if self._redo:
            self._undo.append(self._state())
            self._restore(self._redo.pop())
            self._changed()

    # ---------- запросы ----------

    def group_index(self, i):
        for k, g in enumerate(self.groups):
            if g['a'] <= i <= g['b']:
                return k
        return None

    def included(self, k):
        g = self.groups[k]
        return [i for i in range(g['a'], g['b'] + 1) if i not in self.excluded]

    def is_on(self, i):
        return self.group_index(i) is not None and i not in self.excluded

    def free_count(self):
        return sum(1 for i in range(self.n) if self.group_index(i) is None)

    def starts(self):
        return [g['a'] for g in self.groups]

    # ---------- целые разбиения ----------

    def set_ranges(self, ranges, preset):
        """Новое разбиение: все семплы включены; названия сохраняются у совпавших диапазонов."""
        old_names = {(g['a'], g['b']): g['name'] for g in self.groups}

        def f():
            self.groups = [{'a': a, 'b': b, 'name': old_names.get((a, b), '')} for a, b in ranges]
            self.excluded = set()
        self._edit(f, preset)

    def clear(self):
        """«Ручной выбор»: все семплы вне групп."""
        def f():
            self.groups, self.excluded = [], set()
        self._edit(f, 'manual')

    # ---------- жесты ----------

    def _remove_from_groups(self, lo, hi):
        """Вынимает семплы lo..hi из групп; от задетых групп остаются куски вне диапазона."""
        rest = []
        for g in self.groups:
            if g['b'] < lo or g['a'] > hi:
                rest.append(g)
                continue
            if g['a'] < lo:
                rest.append({'a': g['a'], 'b': lo - 1, 'name': g['name']})
            if g['b'] > hi:
                rest.append({'a': hi + 1, 'b': g['b'], 'name': '' if g['a'] < lo else g['name']})
        self.groups = rest

    def toggle(self, i):
        """Клик по семплу: исключить / включить; свободный семпл становится группой из одного."""
        def f():
            if self.group_index(i) is None:
                self.groups.append({'a': i, 'b': i, 'name': ''})
                self.excluded.discard(i)
            elif i in self.excluded:
                self.excluded.discard(i)
            else:
                self.excluded.add(i)
        self._edit(f)

    def merge(self, i, j):
        """Протягивание / Shift+клик: всё от i до j и группы на концах — одна группа.
        Пройденные семплы (i..j) включаются, у групп на концах вне участка состояние сохраняется."""
        lo, hi = min(i, j), max(i, j)

        def f():
            a, b, name = lo, hi, ''
            for k in (self.group_index(lo), self.group_index(hi)):
                if k is not None:
                    a, b = min(a, self.groups[k]['a']), max(b, self.groups[k]['b'])
            for g in self.groups:  # название — первой названной группы внутри нового диапазона
                if not name and g['a'] >= a and g['b'] <= b:
                    name = g['name']
            self.groups = [g for g in self.groups if g['b'] < a or g['a'] > b]
            self.groups.append({'a': a, 'b': b, 'name': name})
            self.excluded -= set(range(lo, hi + 1))
        return self._edit(f)

    def cut(self, i):
        """Ctrl/⌘+клик: с семпла i начинается новая группа."""
        def f():
            k = self.group_index(i)
            if k is None or self.groups[k]['a'] == i:
                return
            g = self.groups[k]
            self.groups[k:k + 1] = [{'a': g['a'], 'b': i - 1, 'name': g['name']},
                                    {'a': i, 'b': g['b'], 'name': ''}]
        self._edit(f)

    def step(self, cursor, direction):
        """Shift+стрелка. Наружу — группа выделенного семпла растёт на 1, внутрь — сокращается на 1.

        «Внутрь» — когда выделен крайний семпл группы, а стрелка направлена к её середине.
        Возвращает новое положение выделения.
        """
        nxt = cursor + direction
        k = self.group_index(cursor)
        result = [cursor]

        def f():
            if k is None:  # свободный семпл: образует группу с соседом
                if 0 <= nxt < self.n:
                    self._remove_from_groups(nxt, nxt)
                    self.groups.append({'a': min(cursor, nxt), 'b': max(cursor, nxt), 'name': ''})
                    self.excluded -= {cursor, nxt}
                    result[0] = nxt
            else:
                g = self.groups[k]
                inward = (g['a'] < g['b']) and ((direction > 0 and cursor == g['a']) or
                                                (direction < 0 and cursor == g['b']))
                if inward:  # отрезать крайний семпл, он становится свободным
                    if direction > 0:
                        g['a'] += 1
                    else:
                        g['b'] -= 1
                    self.excluded.discard(cursor)
                    result[0] = nxt
                else:       # нарастить группу в сторону стрелки на один семпл
                    edge = g['b'] + 1 if direction > 0 else g['a'] - 1
                    if 0 <= edge < self.n:
                        self._remove_from_groups(edge, edge)
                        k2 = self.group_index(cursor)
                        if direction > 0:
                            self.groups[k2]['b'] = edge
                        else:
                            self.groups[k2]['a'] = edge
                        self.excluded.discard(edge)
                        result[0] = edge
        self._edit(f)
        return result[0]

    def rename(self, k, name):
        def f():
            self.groups[k]['name'] = name.strip()
        self._edit(f)
