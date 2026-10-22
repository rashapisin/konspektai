"""Калибровочный лист: показывает, насколько принтер сдвигает печать относительно клетки.

Принцип нониуса: рядом с линиями клетки печатаются риски со сдвигами от −2 до +2 мм.
Риска, которая на бумаге совпала с настоящей линией клетки, показывает нужную поправку.
"""

from pathlib import Path

from PySide6.QtCore import QMarginsF, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPageLayout, QPainter, QPdfWriter, QPen

from .paper import Side
from .render import _page_size
from .settings import PageSettings

STEPS = [-2.0, -1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5, 2.0]
# Чёрный и жирный: должно читаться даже при почти пустом картридже
INK = QColor("#000000")
LINE_MM = 0.4


def _label(p: QPainter, x: float, y: float, text: str, size_mm: float = 2.8, align=Qt.AlignHCenter):
    f = QFont("Arial")
    f.setBold(True)
    f.setPixelSize(100)  # рисуем крупно и уменьшаем, иначе хинтинг ломает буквы
    p.save()
    p.translate(x, y)
    p.scale(size_mm / 100, size_mm / 100)
    p.setFont(f)
    r = QRectF(-2000, -50, 4000, 140) if align == Qt.AlignHCenter else QRectF(0, -50, 6000, 140)
    p.drawText(r, align | Qt.AlignTop, text)
    p.restore()


def tick_label(i: int) -> str:
    """Риски подписаны 1…9 (5 — «всё ровно»): людям проще запомнить номер, чем «−1,5 мм»."""
    return str(i + 1)


def _draw_side(p: QPainter, ps: PageSettings, side: Side):
    """Лист калибровки: две крупные шкалы — «А» (влево-вправо) и «Б» (вверх-вниз) — и уголок для линейки.

    Риска № i стоит на STEPS[i] мм от линии клетки. Если на бумаге с линией совпала риска i,
    печать сдвинута на −STEPS[i], и поправка равна STEPS[i] (её считает мастер, человек называет только номер).
    """
    paper = ps.paper
    xs = paper.vertical_lines(side)
    ys = paper.horizontal_lines()
    off = ps.offset(side)
    p.save()
    p.translate(off.dx_mm, off.dy_mm)
    p.scale(off.sx, off.sy)
    pen = QPen(INK, LINE_MM)
    pen.setCapStyle(Qt.FlatCap)
    p.setPen(pen)

    name = "ЛИЦЕВАЯ СТОРОНА" if side is Side.FRONT else "ОБОРОТ"
    _label(p, xs[3], ys[4] - 1.0, f"KonspektAI · калибровка · {name}", 3.6, Qt.AlignLeft)
    _label(p, xs[3], ys[5] + 0.2, "На каждой шкале найдите чёрную риску, которая легла точно на синюю линию,", 2.4,
           Qt.AlignLeft)
    _label(p, xs[3], ys[6] - 1.0, "и нажмите её номер в программе.", 2.4, Qt.AlignLeft)

    # Шкала А (поправка влево-вправо): вертикальные риски у вертикальных линий клетки, через клетку
    row_y = ys[10]
    first = max(0, (len(xs) - 2 * (len(STEPS) - 1)) // 2)
    _label(p, xs[first] - 9.0, row_y - 5.2, "А", 6.0)
    for i, v in enumerate(STEPS):
        x = xs[first + 2 * i] + v
        p.drawLine(QPointF(x, row_y - 7.0), QPointF(x, row_y + 2.0))
        _label(p, x, row_y + 2.6, tick_label(i), 3.6)

    # Шкала Б (поправка вверх-вниз): горизонтальные риски у горизонтальных линий клетки
    col_x = xs[len(xs) // 2]
    firsty = 16
    _label(p, col_x - 4.0, ys[firsty] - 10.5, "Б", 6.0)
    for i, v in enumerate(STEPS):
        if firsty + 2 * i >= len(ys):
            break
        y = ys[firsty + 2 * i] + v
        p.drawLine(QPointF(col_x - 9.0, y), QPointF(col_x + 2.0, y))
        _label(p, col_x + 3.0, y - 1.8, tick_label(i), 3.6, Qt.AlignLeft)

    # Уголок для линейки — только если лист уехал сильнее, чем на полклетки (шкалы повторяются через 5 мм)
    b = BRACKET_MM
    p.drawLine(QPointF(b, b), QPointF(b + 10, b))
    p.drawLine(QPointF(b, b), QPointF(b, b + 10))
    _label(p, b + 1.5, b + 1.5, f"{b:.0f} мм", 2.2, Qt.AlignLeft)
    p.restore()


PHOTO_SKIP = {3, 6, 7, 12, 16, 17, 23, 28, 30, 34, 37}


def photo_lines(paper, side: Side) -> tuple[list[float], list[float]]:
    """Где на листе для фото-калибровки стоят чёрные линии (мм в координатах профиля, до поправок).

    Посередине клеток — чтобы не закрывать синие линии, по которым идёт отсчёт. Некоторые линии пропущены
    по неповторяющемуся рисунку: программа не спутает клетки, даже если принтер промахнулся на несколько
    сантиметров."""
    half = paper.cell_mm / 2
    keep = lambda i: i not in PHOTO_SKIP  # noqa: E731
    xs = [x + half for i, x in enumerate(paper.vertical_lines(side)[:-1]) if keep(i)
          and 14 <= x + half <= paper.width_mm - 14]
    ys = [y + half for i, y in enumerate(paper.horizontal_lines()[:-1]) if keep(i)
          and 14 <= y + half <= paper.height_mm - 14]
    return xs, ys


def _draw_photo_side(p: QPainter, ps: PageSettings, side: Side):
    """Лист для калибровки по фото: тонкие чёрные линии посередине клеток и маленькая подпись у края."""
    paper = ps.paper
    off = ps.offset(side)
    xs, ys = photo_lines(paper, side)
    p.save()
    p.translate(off.dx_mm, off.dy_mm)
    p.scale(off.sx, off.sy)
    pen = QPen(INK, 0.3)
    pen.setCapStyle(Qt.FlatCap)
    p.setPen(pen)
    for x in xs:
        p.drawLine(QPointF(x, ys[0] - 2.5), QPointF(x, ys[-1] + 2.5))
    for y in ys:
        p.drawLine(QPointF(xs[0] - 2.5, y), QPointF(xs[-1] + 2.5, y))
    name = "лицевая" if side is Side.FRONT else "оборот"
    _label(p, paper.width_mm / 2, 6.0, f"KonspektAI · калибровка по фото · {name}", 2.4)
    p.restore()


def check_lines(paper, side: Side) -> tuple[list[float], list[float]]:
    """Проверочный лист: чёрная сетка прямо по линиям клетки (мм профиля, до поправок)."""
    xs = [x for x in paper.vertical_lines(side) if 14 <= x <= paper.width_mm - 14]
    ys = [y for y in paper.horizontal_lines() if 14 <= y <= paper.height_mm - 14]
    return xs, ys


def _draw_photo_check(p: QPainter, ps: PageSettings, side: Side):
    """Проверка по фото: пунктирная чёрная сетка по синей клетке. Глазу сразу видно, совпало ли,
    а в просветах пунктира программе видна синяя линия под ним."""
    paper = ps.paper
    off = ps.offset(side)
    xs, ys = check_lines(paper, side)
    p.save()
    p.translate(off.dx_mm, off.dy_mm)
    p.scale(off.sx, off.sy)
    pen = QPen(INK, 0.3)
    pen.setCapStyle(Qt.FlatCap)
    pen.setDashPattern([1.5 / 0.3, 1.0 / 0.3])  # штрих 1,5 мм, просвет 1 мм (в толщинах пера)
    p.setPen(pen)
    for x in xs:
        p.drawLine(QPointF(x, ys[0]), QPointF(x, ys[-1]))
    for y in ys:
        p.drawLine(QPointF(xs[0], y), QPointF(xs[-1], y))
    name = "лицевая" if side is Side.FRONT else "оборот"
    _label(p, paper.width_mm / 2, 6.0, f"KonspektAI · проверка калибровки · {name}", 2.4)
    p.restore()


BRACKET_MM = 15.0  # дальше от края: ближе ~11 мм некоторые принтеры не печатают


def solve_shift(measured_mm: float | None, vernier: float | None, expected_mm: float = BRACKET_MM) -> float | None:
    """Поправка (мм), которую нужно прибавить к текущей.

    measured_mm — линейкой от края листа до уголка (грубо, ±1 мм); vernier — число под риской,
    совпавшей с линией клетки (точно, но с неоднозначностью 5 мм). Нет ни того, ни другого — None."""
    coarse = None if measured_mm is None else measured_mm - expected_mm  # сдвиг печати
    if vernier is None:
        return None if coarse is None else -coarse
    fine = -vernier  # сдвиг печати по шкале, с точностью до целого числа клеток
    if coarse is not None:
        fine += 5.0 * round((coarse - fine) / 5.0)
    return round(-fine, 2)


def _draw_check_grid(p: QPainter, ps: PageSettings, side: Side, profile_name: str):
    """Тонкая чёрная сетка ровно там, где должна быть клетка: сразу видно, где печать не попала."""
    paper = ps.paper
    off = ps.offset(side)
    p.save()
    p.translate(off.dx_mm, off.dy_mm)
    p.scale(off.sx, off.sy)
    xs = [x for x in paper.vertical_lines(side) if 4 <= x <= paper.width_mm - 4]
    ys = [y for y in paper.horizontal_lines() if 5 <= y <= paper.height_mm - 5]
    pen = QPen(INK, 0.15)
    p.setPen(pen)
    for x in xs:
        p.drawLine(QPointF(x, ys[0]), QPointF(x, ys[-1]))
    for y in ys:
        p.drawLine(QPointF(xs[0], y), QPointF(xs[-1], y))
    name = "ЛИЦЕВАЯ" if side is Side.FRONT else "ОБОРОТ"
    p.fillRect(QRectF(xs[3], ys[len(ys) // 2 - 1] - 0.2, 70, 9.4), QColor("#ffffff"))
    _label(p, xs[3] + 1, ys[len(ys) // 2 - 1] + 0.6, f"Проверка: {name}, профиль «{profile_name}»", 2.8, Qt.AlignLeft)
    _label(p, xs[3] + 1, ys[len(ys) // 2] + 0.6, f"X {off.dx_mm:+.2f}  Y {off.dy_mm:+.2f}  "
                                                 f"масштаб {off.sx:.4f} × {off.sy:.4f}", 2.4, Qt.AlignLeft)
    p.restore()


def export_check_grid_pdf(ps: PageSettings, path: str | Path, profile_name: str = "", resolution: int = 1200):
    _export(ps, path, resolution, lambda p, side: _draw_check_grid(p, ps, side, profile_name))


def export_calibration_pdf(ps: PageSettings, path: str | Path, resolution: int = 1200):
    _export(ps, path, resolution, lambda p, side: _draw_side(p, ps, side))


def _export(ps: PageSettings, path, resolution, draw):
    from .layout import Document  # только для _page_size
    w = QPdfWriter(str(path))
    w.setPageLayout(QPageLayout(_page_size(Document([], ps, None)), QPageLayout.Portrait, QMarginsF(0, 0, 0, 0)))
    w.setResolution(resolution)
    w.setCreator("KonspektAI")
    p = QPainter(w)
    scale = resolution / 25.4
    for i, side in enumerate((Side.FRONT, Side.BACK)):
        if i:
            w.newPage()
        p.save()
        p.scale(scale, scale)
        p.setRenderHint(QPainter.Antialiasing, True)
        draw(p, side)
        p.restore()
    p.end()
