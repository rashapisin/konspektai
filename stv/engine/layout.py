"""Вёрстка: текст → страницы с готовыми контурами букв.

Главные гарантии:
- базовая линия каждой строки лежит на линии клетки (± волна почерка);
- ни одна буква не выходит за поля: ширина проверяется по реальным контурам
  уже после всех искажений, а не по «идеальной» ширине шрифта.
"""

import math
import random
from dataclasses import dataclass, field, replace

import numpy as np
import pyphen
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainterPath, QPainterPathStroker, QTransform

from .fonts import HandFont, load_font
from .markup import Block, parse
from .paper import Side, side_of
from .settings import HandSettings, PageSettings

CHECKSHEET_COLUMNS = (
    ("Дата проверки", 0.20),
    ("Выявленные замечания", 0.28),
    ("Должность, звание, ФИО и подпись проверяющего", 0.32),
    ("Отметка о выполнении", 0.20),
)


@dataclass
class PlacedGlyph:
    char: str
    path: QPainterPath  # итоговый контур в мм, координаты страницы
    color: str
    stroke_mm: float
    soft: bool = False  # дефис, добавленный переносом (не из исходного текста)
    joiner: bool = False  # связка слитного письма между буквами (не символ текста)

    def bbox(self) -> QRectF:
        r = self.path.boundingRect()
        h = self.stroke_mm / 2
        return r.adjusted(-h, -h, h, h)


@dataclass
class Line:
    baseline_mm: float
    left_mm: float
    right_mm: float
    glyphs: list[PlacedGlyph] = field(default_factory=list)


@dataclass
class Page:
    index: int
    side: Side
    lines: list[Line] = field(default_factory=list)
    date: str = ""
    date_glyphs: list[PlacedGlyph] = field(default_factory=list)
    rows_used: int = 0   # сколько строк страницы занято (включая пустые между абзацами)
    capacity: int = 0    # сколько строк помещается на страницу
    note: str = ""       # пометка для предпросмотра (не печатается), например о переносе конспекта
    note_bottom: bool = False  # пометка у нижнего края: «продолжение на следующей странице»
    entry_id: str = ""   # из какого конспекта журнала эта страница

    @property
    def fill(self) -> float:
        return self.rows_used / self.capacity if self.capacity else 0.0

    def all_glyphs(self):
        for ln in self.lines:
            yield from ln.glyphs
        yield from self.date_glyphs


@dataclass
class Document:
    pages: list[Page]
    page: PageSettings
    hand: HandSettings
    warnings: list[str] = field(default_factory=list)


@dataclass
class _GlyphSpec:
    """Символ слова до размещения: всё случайное уже выбрано."""
    face: object
    char: str
    x_mm: float        # смещение от начала слова
    adv_mm: float
    scale: float
    rot: float
    lift: float
    warp: tuple[float, float, float, float]
    color: str
    pressure: float = 1.0  # нажим: множитель толщины линии


class _LineGeom:
    """Волна и уклон конкретной строки."""

    def __init__(self, rng: random.Random, hand: HandSettings, x0: float):
        self.x0 = x0
        self.amp = hand.baseline_wobble_mm * rng.uniform(0.5, 1.0)
        self.wavelength = rng.uniform(60, 130)
        self.phase = rng.uniform(0, 2 * math.pi)
        self.slope = math.tan(math.radians(rng.uniform(-1, 1) * hand.line_slope_deg))

    def dy(self, x: float) -> float:
        return (self.amp * math.sin(2 * math.pi * (x - self.x0) / self.wavelength + self.phase)
                + self.slope * (x - self.x0))


# Слитно пишем только к буквам, которые и в прописях начинаются снизу, от строки. Буквы, которые начинаются
# сверху или с овала (о, а, с, г, д, б, в…), — с отрыва: иначе «о» превращается в «а», а «г» — в «к».
JOIN_INTO = set("иййцшщыьъулмнкжхяюзчп")
# Выходим только из букв, которые заканчиваются внизу справа; из «г», «т», «р», «о»… связка их портит.
JOIN_FROM = set("аеиймнлкцчшщыьъяжхуд")


def _press_color(color: str, pressure: float) -> str:
    """Сильнее нажим — чуть насыщеннее и темнее чернила, слабее — светлее."""
    c = QColor(color)
    h, s, v, a = c.getHsvF()
    v = min(1.0, max(0.0, v * (1 - 0.18 * (pressure - 1))))
    return QColor.fromHsvF(max(h, 0.0), s, v, a).name()


def _extreme(pts, y_top: float, y_bottom: float, rightmost: bool) -> QPointF | None:
    """Самая правая (или левая) точка контура в полосе по высоте; pts — (xs, ys) точек контура."""
    xs, ys = pts
    band = (ys >= y_top) & (ys <= y_bottom)
    if not band.any():
        return None
    i = np.flatnonzero(band)
    j = i[np.argmax(xs[i])] if rightmost else i[np.argmin(xs[i])]
    return QPointF(float(xs[j]), float(ys[j]))


_OUTLINES: dict = {}  # (начертание, символ) → точки контура; ключ держит начертание живым


def _outline(face, ch: str):
    """Типы и координаты точек контура символа — один раз на символ, дальше из кэша."""
    key = (face, ch)
    if key not in _OUTLINES:
        base, _ = face.glyph(ch)
        n = base.elementCount()
        types, xs, ys = [], np.empty(n), np.empty(n)
        for i in range(n):
            e = base.elementAt(i)
            types.append(e.type.value)
            xs[i], ys[i] = e.x, e.y
        _OUTLINES[key] = (types, xs, ys, base.fillRule())
    return _OUTLINES[key]


def _build_path(types: list[int], xs: list[float], ys: list[float], rule) -> QPainterPath:
    """Контур из точек: 0 — moveTo, 1 — lineTo, 2 + две 3 — кривая Безье."""
    p = QPainterPath()
    p.setFillRule(rule)
    i, n = 0, len(types)
    while i < n:
        t = types[i]
        if t == 2:
            p.cubicTo(xs[i], ys[i], xs[i + 1], ys[i + 1], xs[i + 2], ys[i + 2])
            i += 3
        elif t == 0:
            p.moveTo(xs[i], ys[i])
            i += 1
        else:
            p.lineTo(xs[i], ys[i])
            i += 1
    return p


class Typesetter:
    def __init__(self, page: PageSettings, hand: HandSettings, first_page_index: int = 0):
        """first_page_index — номер первой страницы в тетради: от него зависит, лицевая она или оборот."""
        self.first_index = first_page_index
        hand = hand.effective()
        self.ps = page
        self.hs = hand
        self.font: HandFont = load_font(hand.font_id)
        self.rng = random.Random(hand.seed)
        # нажим, усталость и связки — отдельный генератор: вёрстка (строки, переносы) от них не меняется
        self.rng2 = random.Random(hand.seed * 7919 + 13)
        x_height = hand.x_height_mm or self.font.info.x_height_mm
        self.k = x_height / self.font.x_height  # мм на единицу шрифта
        self.hyph = pyphen.Pyphen(lang="ru_RU")
        self.warnings: list[str] = []
        self._missing: set[str] = set()
        self.cap_mm = self.font.cap_height * self.k
        self.desc_mm = self.font.descent * self.k
        self.baselines = self._usable_baselines()
        if not self.baselines:
            raise ValueError("На листе не помещается ни одной строки: уменьшите поля или размер букв")
        self.pages: list[Page] = []
        self.date = page.date
        self._page: Page | None = None
        self._row = 0  # индекс следующей свободной строки на странице

    # ---------- геометрия страницы ----------

    def _usable_baselines(self) -> list[float]:
        ps = self.ps
        top_limit = ps.margin_top_mm + self.cap_mm * 1.3 + self.hs.glyph_lift_mm
        bottom_limit = ps.paper.height_mm - ps.margin_bottom_mm - self.desc_mm * 1.15 - self.hs.glyph_lift_mm
        lines = [y for y in ps.paper.horizontal_lines() if top_limit <= y <= bottom_limit]
        return lines[:: max(1, ps.line_step_cells)]

    def _new_page(self) -> Page:
        idx = self.first_index + len(self.pages)
        p = Page(index=idx, side=side_of(idx), date=self.date, capacity=len(self.baselines))
        self.pages.append(p)
        self._page = p
        self._row = 0
        return p

    def _page_empty(self) -> bool:
        return self._page is None or (not self._page.lines and self._row == 0)

    def _take_row(self) -> tuple[Page, float]:
        if self._page is None or self._row >= len(self.baselines):
            self._new_page()
        y = self.baselines[self._row]
        self._row += 1
        return self._page, y

    # ---------- слова и буквы ----------

    def _char_ok(self, ch: str) -> str:
        if ch == " " or self.font.supports(ch):
            return ch
        if ch not in self._missing:
            self._missing.add(ch)
        return "?" if self.font.supports("?") else " "

    def _tired(self) -> float:
        """0 в начале страницы → hs.fatigue внизу: рука устаёт, почерк размашистее и неровнее."""
        return self.hs.fatigue * self._row / max(1, len(self.baselines))

    def _make_word(self, text: str, size: float = 1.0) -> tuple[list[_GlyphSpec], float]:
        hs, rng = self.hs, self.rng
        specs: list[_GlyphSpec] = []
        x = 0.0
        base = QColor(hs.ink_color)
        word_press = 1 + self.rng2.uniform(-0.5, 0.5) * hs.pressure_jitter
        tired = self._tired()
        for ch in text:
            ch = self._char_ok(ch)
            faces = self.font.variants(ch) or self.font.faces
            face = rng.choice(faces)
            _, adv_u = face.glyph(ch)
            sc = size * (1 + rng.uniform(-1, 1) * hs.glyph_scale)
            adv = adv_u * self.k * sc
            h, s, v, a = base.getHsvF()
            v = min(1.0, max(0.0, v * (1 + rng.uniform(-1, 1) * hs.ink_jitter)))
            col = QColor.fromHsvF(max(h, 0.0), s, v, a).name()
            specs.append(_GlyphSpec(
                face=face, char=ch, x_mm=x, adv_mm=adv, scale=sc,
                rot=rng.uniform(-1, 1) * hs.glyph_rotation_deg * (1 + 0.8 * tired),
                lift=rng.uniform(-1, 1) * hs.glyph_lift_mm * (1 + 0.8 * tired),
                warp=(rng.uniform(0, 6.283), rng.uniform(0, 6.283), rng.uniform(0.7, 1.3), rng.uniform(0.7, 1.3)),
                color=col,
                pressure=max(0.4, word_press * (1 + self.rng2.uniform(-0.5, 0.5) * hs.pressure_jitter)),
            ))
            x += adv + hs.letter_spacing_mm * size + rng.uniform(-1, 1) * hs.letter_spacing_jitter_mm * size
        return specs, x

    def _glyph_path(self, spec: _GlyphSpec, x: float, baseline: float):
        """Контур буквы на странице и координаты его точек (мм) — по ним ищутся концы для связок.
        Искажение формы считается сразу для всех точек (numpy): поточечно это было 2/3 времени вёрстки."""
        types, bx, by, rule = _outline(spec.face, spec.char)
        a = self.hs.shape_warp * self.font.x_height
        if a > 0 and len(bx):
            xh = self.font.x_height
            p1, p2, f1, f2 = spec.warp
            wx = bx + a * np.sin(2 * math.pi * by / (1.7 * xh) * f1 + p1)
            wy = by + a * np.sin(2 * math.pi * bx / (1.9 * xh) * f2 + p2)
        else:
            wx, wy = bx, by
        k = self.k * spec.scale
        half = spec.adv_mm / 2
        t = QTransform()
        t.translate(x + half, baseline + spec.lift)
        t.rotate(spec.rot)
        t.shear(-math.tan(math.radians(self.hs.slant_deg)), 0)
        t.translate(-half, 0)
        t.scale(k, k)
        fx = t.m11() * wx + t.m21() * wy + t.dx()
        fy = t.m12() * wx + t.m22() * wy + t.dy()
        return _build_path(types, fx.tolist(), fy.tolist(), rule), fx, fy

    def _place(self, specs, x0: float, baseline: float, geom: _LineGeom) -> list[PlacedGlyph]:
        out = []
        prev = None  # (буква, контур, база, нажим, цвет) предыдущей буквы — для связки
        for sp in specs:
            if sp.char == " ":
                prev = None
                continue
            gx = x0 + sp.x_mm
            y = baseline + geom.dy(gx + sp.adv_mm / 2)
            path, px, py = self._glyph_path(sp, gx, y)
            color = _press_color(sp.color, sp.pressure)
            if prev is not None and self.hs.joins:
                joint = self._joint(prev, (sp.char, (px, py), y), sp.scale)
                if joint is not None:
                    out.append(PlacedGlyph("", joint, prev[4], 0.0, joiner=True))
            out.append(PlacedGlyph(sp.char, path, color, self.hs.stroke_mm * sp.pressure))
            prev = (sp.char, (px, py), y, sp.pressure, color)
        return out

    def _joint(self, a, b, scale: float) -> QPainterPath | None:
        """Связка слитного письма: от конца буквы a у строки к началу буквы b в зоне строчных.
        Только между строчными буквами одного слова; иногда пропускается — рука отрывается от бумаги."""
        ca, pa, ya, press, _ = a
        cb, pb, yb = b
        if ca not in JOIN_FROM or cb not in JOIN_INTO:
            return None
        if self.rng2.random() < 0.12:
            return None
        xh = self.font.x_height * self.k * scale
        exit_pt = _extreme(pa, ya - 0.35 * xh, ya + 0.08 * xh, rightmost=True)
        entry = _extreme(pb, yb - 0.55 * xh, yb - 0.05 * xh, rightmost=False)  # вход — в нижней половине
        if exit_pt is None or entry is None:
            return None
        dx = entry.x() - exit_pt.x()
        if not 0.03 * xh < dx < 0.5 * xh:  # буквы и так касаются или стоят слишком далеко
            return None
        curve = QPainterPath(exit_pt)
        curve.cubicTo(QPointF(exit_pt.x() + 0.45 * dx, exit_pt.y() + 0.05 * xh),
                      QPointF(entry.x() - 0.35 * dx, entry.y() + 0.15 * xh), entry)
        stroker = QPainterPathStroker()
        stroker.setWidth(max(0.1, 0.08 * xh * press))
        stroker.setCapStyle(Qt.RoundCap)
        return stroker.createStroke(curve)

    @staticmethod
    def _extent(glyphs: list[PlacedGlyph]) -> tuple[float, float]:
        rects = [g.bbox() for g in glyphs]
        return min(r.left() for r in rects), max(r.right() for r in rects)

    def _space(self, size: float = 1.0) -> float:
        w = self.font.space_width() * self.k * self.hs.word_spacing * size
        return w * (1 + self.rng.uniform(-1, 1) * self.hs.word_spacing_jitter)

    # ---------- абзацы ----------

    def _typeset_words(self, words: list[str], bounds=None,
                       first_indent: float = 0.0, size: float = 1.0,
                       rows: list[tuple[Page, float]] | None = None,
                       hyphenate: bool = True) -> list[Line]:
        """Разбивает слова на строки. bounds — колонка (left, right); по умолчанию поля
        той стороны листа, на которую попала строка. rows — заранее выделенные строки."""
        lines: list[Line] = []
        queue = list(words)

        def start_line(indent: float):
            if rows is not None:
                page, y = rows.pop(0) if rows else (None, None)
                if page is None:
                    return None
            else:
                page, y = self._take_row()
            left, right = bounds if bounds else self._side_bounds(page.side)
            ln = Line(baseline_mm=y, left_mm=left, right_mm=right)
            ln._page = page
            ln._geom = _LineGeom(self.rng, self.hs, left)
            ln._cursor = left + indent
            # строка выше на той же странице — с ней проверяем пересечение чернил
            ln._prev = None
            if rows is None:
                above = [p for p in page.lines if 0 < y - p.baseline_mm <= self.ps.paper.cell_mm * 1.5]
                ln._prev = above[-1] if above else None
                page.lines.append(ln)
            lines.append(ln)
            return ln

        line = start_line(first_indent)
        while queue and line is not None:
            word = queue.pop(0)
            gap = self._space(size) if line.glyphs else 0.0
            placed = self._try_word(word, line, gap, size)
            if placed is not None:
                continue
            # не влезло целиком — пробуем перенос
            head, tail = self._hyphenate(word, line, gap, size) if hyphenate else (None, None)
            if head is not None:
                queue.insert(0, tail)
            elif not line.glyphs:
                # слово длиннее строки и без переносов — режем по буквам
                head, tail = self._force_split(word, line, size)
                if tail:
                    queue.insert(0, tail)
            else:
                queue.insert(0, word)
            line = start_line(0.0)
        if rows is None:
            for ln in lines:
                if not ln.glyphs:
                    ln._page.lines.remove(ln)
        return [ln for ln in lines if ln.glyphs]

    def _fits(self, glyphs, line: Line) -> bool:
        if not glyphs:
            return True
        lo, hi = self._extent(glyphs)
        return hi <= line.right_mm and lo >= line.left_mm - 0.01

    @staticmethod
    def _collides(glyphs: list[PlacedGlyph], above: Line | None) -> bool:
        if above is None or not glyphs:
            return False
        lo, hi = Typesetter._extent(glyphs)
        near = [h for h in above.glyphs if h.bbox().right() > lo and h.bbox().left() < hi]
        for g in glyphs:
            rg = g.bbox()
            for h in near:
                if rg.intersects(h.bbox()) and g.path.intersects(h.path):
                    return True
        return False

    # попытки разместить слово без касания строки выше: (сдвиг вправо, мм; уменьшение)
    _ATTEMPTS = ((0.0, 1.0), (0.0, 1.0), (0.4, 1.0), (0.0, 1.0), (0.8, 1.0), (0.0, 0.95),
                 (1.2, 0.95), (0.0, 0.9), (0.4, 0.9), (0.0, 0.85))

    def _try_word(self, word: str, line: Line, gap: float, size: float):
        for n, (dx, shrink) in enumerate(self._ATTEMPTS):
            specs, width = self._make_word(word, size * shrink)
            x = line._cursor + gap + dx
            glyphs = self._place(specs, x, line.baseline_mm, line._geom)
            if not line.glyphs and glyphs:
                # первая буква строки может «вылезти» влево за поле — сдвигаем строку вправо
                lo, _ = self._extent(glyphs)
                if lo < line.left_mm:
                    shift = line.left_mm - lo + 0.05
                    x += shift
                    glyphs = [replace(g, path=g.path.translated(shift, 0)) for g in glyphs]
            if not self._fits(glyphs, line):
                if n == 0:
                    return None  # не влезает по ширине — пусть решает перенос строки
                continue
            if self._collides(glyphs, getattr(line, "_prev", None)):
                continue
            line.glyphs.extend(glyphs)
            line._cursor = x + width
            return glyphs
        if not self._fits(glyphs, line):
            return None
        self.warnings.append(f"Слово «{word}» касается строки выше: не удалось развести")
        line.glyphs.extend(glyphs)
        line._cursor = x + width
        return glyphs

    def _hyphenate(self, word: str, line: Line, gap: float, size: float):
        core = word.rstrip(".,:;!?»)")
        positions = [p for p in self.hyph.positions(core) if 2 <= p <= len(core) - 2]
        for pos in reversed(positions):
            glyphs = self._try_word(word[:pos] + "-", line, gap, size)
            if glyphs is not None:
                glyphs[-1].soft = True
                return word[:pos], word[pos:]
        return None, None

    def _force_split(self, word: str, line: Line, size: float):
        for n in range(len(word) - 1, 0, -1):
            if self._try_word(word[:n], line, 0.0, size) is not None:
                return word[:n], word[n:]
        self._try_word(word[0], line, 0.0, size)  # хотя бы одна буква, иначе бесконечный цикл
        return word[0], word[1:]

    # ---------- блоки ----------

    def _side_bounds(self, side: Side) -> tuple[float, float]:
        return self.ps.text_left_mm(side), self.ps.text_right_mm(side)

    def _paragraph(self, text: str, indent_cells: float, align: str = "left"):
        words = text.split(" ")
        indent = indent_cells * self.ps.paper.cell_mm
        lines = self._typeset_words(words, None, indent)
        if align == "center":
            for ln in lines:
                lo, hi = self._extent(ln.glyphs)
                shift = ((ln.left_mm + ln.right_mm) - (lo + hi)) / 2
                ln.glyphs = [replace(g, path=g.path.translated(shift, 0)) for g in ln.glyphs]

    def _checksheet(self):
        if not self._page_empty():
            self._new_page()
        elif self._page is None:
            self._new_page()
        page = self._page
        page.date = ""  # на листе проверки дата не пишется
        left, right = self._side_bounds(page.side)
        width = right - left
        n_rows = min(6, len(self.baselines))
        rows = [self._take_row() for _ in range(n_rows)]
        # один размер для всей шапки: самое длинное слово должно влезать в свою колонку целиком
        size = 0.9
        for _ in range(20):
            if all(self._make_word(w, size)[1] + 0.6 <= width * frac - 1.0
                   for title, frac in CHECKSHEET_COLUMNS for w in title.split(" ")):
                break
            size *= 0.93
        x = left
        used = 0
        for title, frac in CHECKSHEET_COLUMNS:
            col_r = x + width * frac - 1.0
            col_rows = list(rows)
            col_lines = self._typeset_words(title.split(" "), (x, col_r), 0.0, size=size,
                                            rows=col_rows, hyphenate=False)
            for ln in col_lines:
                ln._page.lines.append(ln)
            used = max(used, len(col_lines))
            x += width * frac
        self._row = self._row - n_rows + used

    def _place_date(self, page: Page):
        if not page.date:
            return
        lo, hi = self.ps.margin_strip_mm(page.side)
        y = self.baselines[0]
        size = 1.0
        for _ in range(8):
            specs, w = self._make_word(page.date, size)
            geom = _LineGeom(self.rng, self.hs, lo)
            glyphs = self._place(specs, 0.0, y, geom)
            a, b = self._extent(glyphs)
            if b - a <= hi - lo:
                shift = (lo + hi) / 2 - (a + b) / 2
                page.date_glyphs = [replace(g, path=g.path.translated(shift, 0)) for g in glyphs]
                return
            size *= 0.9
        self.warnings.append(f"Дата «{page.date}» не помещается на поле страницы {page.index + 1}")

    def run(self, blocks: list[Block]) -> Document:
        while blocks and blocks[-1].kind == "blank":
            blocks = blocks[:-1]
        for b in blocks:
            if b.kind == "blank":
                # пустая строка не начинает новую страницу и не пишется в начале страницы
                if not self._page_empty() and self._row < len(self.baselines):
                    self._row += 1
            elif b.kind == "pagebreak":
                # каждый [страница] даёт новый лист, даже пустой: так видно результат и можно оставить чистую страницу
                if self._page is None:
                    self._new_page()
                self._new_page()
            elif b.kind == "date":
                self.date = b.text
                if self._page is not None and self._page_empty():
                    self._page.date = b.text
            elif b.kind == "checksheet":
                self._checksheet()
                self._row = len(self.baselines)  # после листа проверки — новая страница
            elif b.kind == "heading":
                self._paragraph(b.text, 0, align="center")
            elif b.kind == "list":
                self._paragraph(b.text, 0)
            else:
                self._paragraph(b.text, self.ps.first_line_indent_cells)
        if not self.pages:
            self._new_page()
        row_of = {y: i for i, y in enumerate(self.baselines)}
        for p in self.pages:
            p.rows_used = max((row_of.get(ln.baseline_mm, 0) + 1 for ln in p.lines), default=0)
            self._place_date(p)
        if self._missing:
            self.warnings.append("Нет в шрифте, заменено на «?»: " + " ".join(sorted(self._missing)))
        return Document(self.pages, self.ps, self.hs, self.warnings)


def typeset(text: str, page: PageSettings | None = None, hand: HandSettings | None = None,
            first_page_index: int = 0) -> Document:
    page = page or PageSettings()
    hand = hand or HandSettings()
    return Typesetter(page, hand, first_page_index).run(parse(text))
