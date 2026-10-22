"""Шаблон образца почерка: лист A4 с метками по углам и клетками для букв.

Одна и та же геометрия используется и при печати шаблона, и при распознавании фото,
поэтому все размеры заданы здесь (мм от левого верхнего угла листа A4).
"""

from dataclasses import dataclass
from pathlib import Path

PAGE_W, PAGE_H = 210.0, 297.0
MARKER = 10.0                                    # сторона чёрного квадрата-метки
MARKERS = ((15.0, 15.0), (195.0, 15.0), (195.0, 282.0), (15.0, 282.0))  # центры: ЛВ, ПВ, ПН, ЛН
CODE_SIZE = 5.0
CODE_X = (70.0, 82.0, 94.0, 106.0, 118.0)       # первый квадрат всегда залит, остальные — номер листа
CODE_Y = 15.0

GRID_X, GRID_Y = 21.0, 36.0
CELL_W, CELL_H = 14.0, 18.0
COLS, ROWS = 12, 13
LABEL_H = 4.0                                    # полоска с подписью буквы сверху клетки
BASELINE = 13.0                                  # базовая линия от верха клетки
XHEIGHT_GUIDE = 4.5                              # подсказка высоты строчных над базовой линией
INSET = 0.9                                      # отступ от рамки клетки при вырезании

LOWER = "абвгдеёжзийклмнопрстуфхцчшщъыьэюя"
UPPER = LOWER.upper()
DIGITS = "0123456789"
PUNCT = ".,:;!?-()«»\"№%/+=—"
VARIANTS = ((LOWER, 3), (UPPER, 2), (DIGITS, 2), (PUNCT, 1))


@dataclass(frozen=True)
class Cell:
    page: int
    row: int
    col: int
    char: str
    variant: int

    @property
    def x(self) -> float:
        return GRID_X + self.col * CELL_W

    @property
    def y(self) -> float:
        return GRID_Y + self.row * CELL_H


def cells() -> list[Cell]:
    seq = [(ch, v) for chars, n in VARIANTS for ch in chars for v in range(n)]
    per_page = COLS * ROWS
    out = []
    for i, (ch, v) in enumerate(seq):
        page, k = divmod(i, per_page)
        out.append(Cell(page, k // COLS, k % COLS, ch, v))
    return out


def page_count() -> int:
    return cells()[-1].page + 1


def export_template_pdf(path: str | Path):
    """PDF шаблона для печати на обычной бумаге A4 (печатать в масштабе 100%)."""
    from PySide6.QtCore import QMarginsF
    from PySide6.QtGui import QPageLayout, QPageSize, QPainter, QPdfWriter

    res = 600
    w = QPdfWriter(str(path))
    w.setPageLayout(QPageLayout(QPageSize(QPageSize.A4), QPageLayout.Portrait, QMarginsF(0, 0, 0, 0)))
    w.setResolution(res)
    w.setCreator("KonspektAI")
    p = QPainter(w)
    for page in range(page_count()):
        if page:
            w.newPage()
        p.save()
        p.scale(res / 25.4, res / 25.4)
        draw_page(p, page)
        p.restore()
    p.end()


def render_page_image(page: int, px_per_mm: float = 8.0):
    """Картинка листа шаблона (для тестов и предпросмотра)."""
    from PySide6.QtGui import QColor, QImage, QPainter
    img = QImage(int(PAGE_W * px_per_mm), int(PAGE_H * px_per_mm), QImage.Format_RGB32)
    img.fill(QColor("#ffffff"))
    p = QPainter(img)
    p.scale(px_per_mm, px_per_mm)
    draw_page(p, page)
    p.end()
    return img


def draw_page(p, page: int):
    """Лист шаблона в координатах «мм от левого верхнего угла A4»."""
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QColor, QFont, QPainter, QPen

    all_cells = cells()
    n_pages = page_count()

    def text(x, y, size_mm, t, color="#000000", bold=False, align=Qt.AlignLeft):
        f = QFont("Arial")
        f.setPixelSize(100)
        f.setBold(bold)
        p.save()
        p.translate(x, y)
        p.scale(size_mm / 100, size_mm / 100)
        p.setFont(f)
        p.setPen(QColor(color))
        r = QRectF(-3000, 0, 6000, 140) if align == Qt.AlignHCenter else QRectF(0, 0, 9000, 140)
        p.drawText(r, align | Qt.AlignTop, t)
        p.restore()

    p.save()
    p.setRenderHint(QPainter.Antialiasing, True)
    black = QColor("#000000")
    for cx, cy in MARKERS:
        p.fillRect(QRectF(cx - MARKER / 2, cy - MARKER / 2, MARKER, MARKER), black)
    for i, cx in enumerate(CODE_X):
        filled = i == 0 or (page >> (i - 1)) & 1
        r = QRectF(cx - CODE_SIZE / 2, CODE_Y - CODE_SIZE / 2, CODE_SIZE, CODE_SIZE)
        if filled:
            p.fillRect(r, black)
        else:
            p.setPen(QPen(QColor("#b0b0b0"), 0.2))
            p.drawRect(r)
    text(GRID_X, 23.5, 3.2, f"KonspektAI · образец почерка · лист {page + 1} из {n_pages}", bold=True)
    text(GRID_X, 27.6, 2.5, "Пишите тёмной ручкой, как обычно пишете конспект. Каждая буква — в своей клетке,",
         "#333333")
    text(GRID_X, 31.0, 2.5, "на сплошной линии; пунктир — высота строчных. Не касайтесь рамки и квадратов.",
         "#333333")
    guide = QPen(QColor("#c4c4c4"), 0.25)
    dotted = QPen(QColor("#d0d0d0"), 0.2, Qt.DashLine)
    for c in (c for c in all_cells if c.page == page):
        p.setPen(QPen(QColor("#d8d8d8"), 0.25))
        p.drawRect(QRectF(c.x, c.y, CELL_W, CELL_H))
        p.setPen(guide)
        p.drawLine(QPointF(c.x + 1, c.y + BASELINE), QPointF(c.x + CELL_W - 1, c.y + BASELINE))
        p.setPen(dotted)
        p.drawLine(QPointF(c.x + 1, c.y + BASELINE - XHEIGHT_GUIDE),
                   QPointF(c.x + CELL_W - 1, c.y + BASELINE - XHEIGHT_GUIDE))
        label = c.char if c.char != " " else "␣"
        text(c.x + 0.8, c.y + 0.4, 2.4, label, "#9a9a9a")
    p.restore()
