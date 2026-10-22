"""Рукописные шрифты: загрузка, метрики и контуры отдельных символов."""

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtGui import QFont, QFontDatabase, QPainterPath, QRawFont

from ..resources import asset

UNITS = 200.0  # размер шрифта в условных единицах, из которых берутся контуры


@dataclass(frozen=True)
class FontInfo:
    id: str
    title: str
    files: tuple[str, ...]  # несколько файлов одного почерка = варианты букв
    license: str
    x_height_mm: float      # размер по умолчанию: подобран так, чтобы строки в клетку 5 мм не касались


FONTS = {
    "caveat": FontInfo("caveat", "Caveat", ("caveat/Caveat-Variable.ttf",), "OFL-1.1", 2.1),
    "badscript": FontInfo("badscript", "Bad Script", ("badscript/BadScript-Regular.ttf",), "OFL-1.1", 1.7),
}


class _Face:
    def __init__(self, path: Path):
        fid = QFontDatabase.addApplicationFont(str(path))
        if fid < 0:
            raise RuntimeError(f"Не удалось загрузить шрифт: {path}")
        self.family = QFontDatabase.applicationFontFamilies(fid)[0]
        self.font = QFont(self.family)
        self.font.setPixelSize(int(UNITS))
        self.raw = QRawFont(str(path), UNITS)
        self._cache: dict[str, tuple[QPainterPath, float]] = {}

    def supports(self, ch: str) -> bool:
        # supportsCharacter(str) в PySide6 некорректно работает с кириллицей — передаём код символа
        return self.raw.supportsCharacter(ord(ch))

    def glyph(self, ch: str) -> tuple[QPainterPath, float]:
        """Контур символа (базовая линия в y=0, ось y вниз) и ширина продвижения в единицах."""
        if ch not in self._cache:
            path = QPainterPath()
            path.addText(0, 0, self.font, ch)
            ids = self.raw.glyphIndexesForString(ch)
            adv = self.raw.advancesForGlyphIndexes(ids)
            width = sum(a.x() for a in adv)
            self._cache[ch] = (path, width)
        return self._cache[ch]


MM_UNITS = 100.0  # собственный почерк хранится в мм; в движок отдаём в сотых долях мм


class _CustomFace:
    """Один «слой» вариантов собственного почерка: variant-й вариант каждой буквы.

    Если буквы нет в образце, берётся из Caveat и подгоняется по высоте строчных."""

    def __init__(self, data: dict, variant: int, fallback: _Face, fallback_xh: float):
        self.glyphs = data["glyphs"]
        self.variant = variant
        m = data["metrics"]
        self.xh = m["x_height"]
        self.lsb = 0.06 * self.xh  # поля слева и справа от буквы: рукописные буквы стоят плотно
        self.fallback = fallback
        self.fb_scale = self.xh * MM_UNITS / fallback_xh
        self._cache: dict[str, tuple[QPainterPath, float]] = {}

    def has_own(self, ch: str) -> bool:
        return len(self.glyphs.get(ch, ())) > self.variant

    def supports(self, ch: str) -> bool:
        if self.has_own(ch):
            return True
        # недостающие буквы и пробел даёт только первый слой, чтобы не плодить одинаковые «варианты»
        return self.variant == 0 and (ch == " " or self.fallback.supports(ch))

    def glyph(self, ch: str) -> tuple[QPainterPath, float]:
        if ch in self._cache:
            return self._cache[ch]
        if ch == " ":
            res = (QPainterPath(), 0.55 * self.xh * MM_UNITS)
        elif self.has_own(ch):
            g = self.glyphs[ch][self.variant]
            path = QPainterPath()
            for poly in g["polys"]:
                x, y = poly[0]
                path.moveTo((x + self.lsb) * MM_UNITS, y * MM_UNITS)
                for x, y in poly[1:]:
                    path.lineTo((x + self.lsb) * MM_UNITS, y * MM_UNITS)
                path.closeSubpath()
            res = (path, (g["w"] + 2 * self.lsb) * MM_UNITS)
        else:
            from PySide6.QtGui import QTransform
            p, adv = self.fallback.glyph(ch)
            t = QTransform.fromScale(self.fb_scale, self.fb_scale)
            res = (t.map(p), adv * self.fb_scale)
        self._cache[ch] = res
        return res


class HandFont:
    """Почерк: один или несколько файлов шрифта, между которыми чередуются варианты букв,
    либо собственный почерк из образцов (info.files пуст)."""

    def __init__(self, info: FontInfo, custom: dict | None = None):
        self.info = info
        if custom is None:
            self.faces = [_Face(asset("fonts", f)) for f in info.files]
            main = self.faces[0].raw
            self.x_height = main.xHeight()
            self.cap_height = main.capHeight()
            self.ascent = main.ascent()
            self.descent = main.descent()
            return
        fb = load_font("caveat")
        n = max((len(v) for v in custom["glyphs"].values()), default=1)
        self.faces = [_CustomFace(custom, i, fb.faces[0], fb.x_height) for i in range(n)]
        m = custom["metrics"]
        self.x_height = m["x_height"] * MM_UNITS
        self.cap_height = m["cap_height"] * MM_UNITS
        self.ascent = m["ascent"] * MM_UNITS
        self.descent = m["descent"] * MM_UNITS

    def supports(self, ch: str) -> bool:
        return any(f.supports(ch) for f in self.faces)

    def variants(self, ch: str) -> list[_Face]:
        return [f for f in self.faces if f.supports(ch)]

    def space_width(self) -> float:
        return self.faces[0].glyph(" ")[1]


_loaded: dict[str, HandFont] = {}


def load_font(font_id: str) -> HandFont:
    if font_id not in _loaded:
        from PySide6.QtCore import QCoreApplication, QThread
        app = QCoreApplication.instance()
        if app is not None and QThread.currentThread() is not app.thread():
            # Qt загружает шрифты из фонового потока неполностью (теряется кириллица)
            raise RuntimeError("Шрифты нужно загрузить в главном потоке: вызовите preload_fonts()")
        if font_id in FONTS:
            _loaded[font_id] = HandFont(FONTS[font_id])
        else:
            from ..hands import handset
            data = handset.load(font_id)
            _loaded[font_id] = HandFont(font_info(font_id, data), data)
    return _loaded[font_id]


def font_info(font_id: str, data: dict | None = None) -> FontInfo:
    """Описание почерка: встроенного шрифта или собственного набора."""
    if font_id in FONTS:
        return FONTS[font_id]
    from ..hands import handset
    data = data or handset.load(font_id)
    return FontInfo(font_id, data.get("name", "Мой почерк"), (), "собственный", handset.default_x_height(data))


def all_fonts() -> list[tuple[str, str]]:
    """(id, название) всех почерков: встроенные шрифты и сохранённые образцы."""
    from ..hands import handset
    return [(fid, info.title) for fid, info in FONTS.items()] + handset.list_hands()


def forget_font(font_id: str):
    """Сбросить загруженный почерк (после повторного распознавания образцов)."""
    _loaded.pop(font_id, None)


def preload_fonts():
    """Загрузить все почерки заранее, в главном потоке."""
    for fid, _ in all_fonts():
        try:
            load_font(fid)
        except (OSError, ValueError, KeyError):
            pass  # испорченный файл собственного почерка не должен мешать запуску
