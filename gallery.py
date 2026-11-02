"""Галерея построенных графиков, нарисованная прямо на холсте прокручиваемой страницы.

Графики — элементы холста, а не отдельные окна, поэтому при прокрутке не остаётся «следов».
Картинки хранятся сжатыми (PNG, ~80 КБ); развёрнутыми в памяти (≈3 МБ каждая) держатся только
плитки рядом с видимой частью страницы — так память не растёт с числом графиков и вкладок."""
import io

from PIL import Image, ImageTk

from ui_common import BTN_BG, BTN_EDGE, CARD, CARD_EDGE, INK, MUTED, PURPLE_LIGHT, PURPLE_MID, px, ui_font

FIG_DPI = 100


class Tile:
    """Плитка: заголовок, картинка графика, кнопки «Сохранить PNG», «Сохранить CSV», «Открыть крупно»."""

    def __init__(self, gallery, title, spec, save_name, img_w, img_h, box_w=0, index=0):
        self.g, self.title, self.spec, self.save_name = gallery, title, spec, save_name
        self.index = index
        self.img_w, self.img_h = int(img_w), int(img_h)
        self.box_w = int(box_w)
        self.png = None           # сжатая картинка (байты PNG)
        self.photo = None         # развёрнутая — только пока плитка рядом с экраном
        self.x = self.y = 0
        self.img_id = self.ph_id = None

    @property
    def size(self):
        p = self.g.pad
        return max(self.img_w + 2 * p, self.box_w), self.g.title_h + self.img_h + self.g.btn_h + 3 * p

    def draw(self, x, y):
        g, cv, p = self.g, self.g.cv, self.g.pad
        self.x, self.y = x, y
        w, h = self.size
        tags = ('gallery',)
        cv.create_rectangle(x, y, x + w, y + h, fill=CARD, outline=CARD_EDGE, width=max(1, px(1)), tags=tags)
        title = self.title
        while title and g.font_title.measure(title) > w - 2 * p:
            title = title[:-2]
        if title != self.title:
            title = title.rstrip() + '…'
        cv.create_text(x + p, y + p, text=title, anchor='nw', font=g.font_title, fill=INK, tags=tags)
        iy = y + p + g.title_h
        self.ph_id = cv.create_text(x + w / 2, iy + self.img_h / 2, text='строится…', font=g.font, fill=MUTED,
                                    tags=tags)
        self.img_id = cv.create_image(x + (w - self.img_w) / 2, iy, anchor='nw', tags=tags)
        if self.png is not None:
            cv.itemconfigure(self.ph_id, state='hidden')
        by = iy + self.img_h + p
        bx = x + w - p
        for text, cmd in [('Открыть крупно', lambda: g.app.open_large(self)),
                          ('Шкала', lambda: g.app.tile_scale_menu(self)),
                          ('Сохранить CSV', lambda: g.app.save_spec_csv(self.spec, self.save_name)),
                          ('Сохранить PNG', lambda: g.app.save_spec(self.spec, self.save_name))]:
            bx = g.button(bx, by, text, cmd, tags) - px(6)

    def set_png(self, w, h, png):
        self.png = png
        cache = self.g.cache
        if cache is not None and self.index < len(cache['pngs']):
            cache['pngs'][self.index] = png         # графики вкладки живут в её кеше
        self.g.cv.itemconfigure(self.ph_id, state='hidden')
        self.photo = None
        self.g.update_visible()

    def show(self):
        if self.photo is None and self.png is not None:
            img = Image.open(io.BytesIO(self.png))
            if img.size != (self.img_w, self.img_h):
                img = img.resize((self.img_w, self.img_h), Image.LANCZOS)
            self.photo = ImageTk.PhotoImage(img, master=self.g.cv)
            self.g.cv.itemconfigure(self.img_id, image=self.photo)

    def hide(self):
        if self.photo is not None:
            self.g.cv.itemconfigure(self.img_id, image='')
            self.photo = None


class Gallery:
    def __init__(self, page, app):
        self.page, self.cv, self.app = page, page.canvas, app
        self.tiles = []
        self.entries = []
        self.cache = None         # {'entries', 'pngs', 'width'} показанной вкладки (общий объект с doc.plot_cache)
        self.width = 0
        self.font = ui_font(10)
        self.font_title = ui_font(11, 'bold')
        self.pad = px(8)
        self.gap = px(10)
        self.margin = px(10)
        self.title_h = self.font_title.metrics('linespace') + px(4)
        self.btn_h = self.font.metrics('linespace') + px(8)
        self._top = 0
        self._btn_n = 0
        self._vis_after = None
        page.height_listeners.append(self._follow_inner)
        page.scroll_listeners.append(self.update_visible)

    # ---------- кнопки на холсте ----------

    def button(self, right, top, text, command, tags):
        self._btn_n += 1
        bt = f'btn{self._btn_n}'
        w = self.font.measure(text) + px(20)
        all_tags = tags + (bt,)
        rect = self.cv.create_rectangle(right - w, top, right, top + self.btn_h, fill=BTN_BG, outline=BTN_EDGE,
                                        width=max(1, px(1)), tags=all_tags)
        self.cv.create_text(right - w / 2, top + self.btn_h / 2, text=text, font=self.font, fill=INK, tags=all_tags)
        self.cv.tag_bind(bt, '<Enter>', lambda e: (self.cv.itemconfigure(rect, fill=PURPLE_LIGHT, outline=PURPLE_MID),
                                                   self.cv.configure(cursor='hand2')))
        self.cv.tag_bind(bt, '<Leave>', lambda e: (self.cv.itemconfigure(rect, fill=BTN_BG, outline=BTN_EDGE),
                                                   self.cv.configure(cursor='')))
        self.cv.tag_bind(bt, '<ButtonRelease-1>', lambda e: command())
        return right - w

    # ---------- раскладка ----------

    def clear(self):
        self.cv.delete('gallery')
        self.tiles = []
        self.entries = []
        self.cache = None
        self.page.set_extra_height(0)

    def sizes(self, entries, width=None):
        """Размеры картинок [(img_w, img_h, ширина плитки)] при данной ширине страницы."""
        width = self.cv.winfo_width() if width is None else width
        avail = max(px(500), width - 2 * self.margin)
        scale = px(1000) / 1000
        out = []
        for k, (title, spec, name) in enumerate(entries):
            fw, fh = spec['figsize']
            box = avail if k == 0 else (avail - self.gap) / 2
            limit = (avail * 0.85 if k == 0 else box) - 2 * self.pad
            img_w = min(limit, fw * FIG_DPI * scale)
            out.append((img_w, img_w * fh / fw, box))
        return out

    def build(self, entries):
        """entries: [(заголовок, spec, имя файла)] — первый сводный, далее группы."""
        return self.restore({'entries': list(entries), 'pngs': [None] * len(entries),
                             'width': self.cv.winfo_width()})

    def restore(self, cache):
        """Показать графики вкладки из её кеша (картинки, которых ещё нет, — «строится…»)."""
        self.clear()
        self.cache = cache
        self.entries = cache['entries']
        self.width = self.cv.winfo_width()
        self.tiles = [Tile(self, title, spec, name, w, h, box, k)
                      for k, ((title, spec, name), (w, h, box)) in enumerate(zip(self.entries, self.sizes(self.entries)))]
        self._draw()
        for t, png in zip(self.tiles, cache['pngs']):
            if png is not None:
                t.png = png
                self.cv.itemconfigure(t.ph_id, state='hidden')
        self.update_visible()
        return self.tiles

    def snapshot(self):
        return self.cache

    def _draw(self):
        self.cv.delete('gallery')
        self._top = self.page.inner_height() + px(2)
        avail = max(px(500), self.cv.winfo_width() - 2 * self.margin)
        y = self._top
        if not self.tiles:
            self.page.set_extra_height(0)
            return
        ov = self.tiles[0]
        w, h = ov.size
        ov.draw(self.margin + (avail - w) / 2, y)
        y += h + self.gap
        col_w = (avail - self.gap) / 2
        row_h = 0
        for pos, t in enumerate(self.tiles[1:]):
            w, h = t.size
            col = pos % 2
            x = self.margin + col * (col_w + self.gap) + (col_w - w) / 2
            t.draw(x, y)
            row_h = max(row_h, h)
            if col == 1:
                y += row_h + self.gap
                row_h = 0
        y += row_h + self.margin
        self.page.set_extra_height(y - self._top + px(2))
        self.update_visible()

    def _follow_inner(self):
        if not self.tiles:
            return
        top = self.page.inner_height() + px(2)
        if top != self._top:
            dy = top - self._top
            self.cv.move('gallery', 0, dy)
            for t in self.tiles:
                t.y += dy
            self._top = top
            self.update_visible()

    def update_visible(self):
        """Развернуть картинки рядом с экраном, остальные убрать из памяти."""
        if not self.tiles:
            return
        top = self.cv.canvasy(0)
        h = max(self.cv.winfo_height(), 1)
        lo, hi = top - h, top + 2 * h
        for t in self.tiles:
            th = t.size[1]
            if t.y + th >= lo and t.y <= hi:
                t.show()
            else:
                t.hide()

    def tile_y(self, k):
        return self.tiles[k].y if k < len(self.tiles) else 0
