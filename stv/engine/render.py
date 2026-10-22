"""Отрисовка страниц через QPainter. Один код для предпросмотра, PDF и картинок."""

from pathlib import Path

from PySide6.QtCore import QMarginsF, QPointF, QRectF, QSizeF, Qt
from PySide6.QtGui import QBrush, QColor, QImage, QPageLayout, QPageSize, QPainter, QPdfWriter, QPen

from .layout import Document, Page
from .paper import Side

GRID_COLOR = "#9ec3ea"
HOLE_COLOR = "#3a3f4a"


def draw_page(p: QPainter, doc: Document, page: Page, *, preview: bool = False, apply_offset: bool = True):
    """Рисует страницу в координатах «мм от левого верхнего угла листа».
    preview=True — дорисовать клетку, отверстия и белый лист (для экрана и PNG-превью)."""
    ps = doc.page
    paper = ps.paper
    p.save()
    p.setRenderHint(QPainter.Antialiasing, True)
    if preview:
        p.fillRect(QRectF(0, 0, paper.width_mm, paper.height_mm), QColor("#ffffff"))
        if not paper.printed:
            _draw_grid(p, doc, page.side)  # клетка тетрадного листа — только на экране, она уже на бумаге
        if paper.holes:
            _draw_holes(p, doc, page.side)
    if apply_offset:
        off = ps.offset(page.side)
        p.translate(off.dx_mm, off.dy_mm)
        p.scale(off.sx, off.sy)
    if paper.printed or ps.print_grid:
        _draw_grid(p, doc, page.side)  # обычная бумага: клетку или линейку печатаем вместе с текстом
    if ps.margin_line:
        x = ps.margin_line_x_mm(page.side)
        pen = QPen(QColor(ps.margin_line_color), ps.margin_line_width_mm)
        pen.setCapStyle(Qt.FlatCap)
        p.setPen(pen)
        p.drawLine(QPointF(x, 0), QPointF(x, paper.height_mm))
    for g in page.all_glyphs():
        col = QColor(g.color)
        p.setBrush(QBrush(col))
        if g.stroke_mm > 0:
            pen = QPen(col, g.stroke_mm)
            pen.setJoinStyle(Qt.RoundJoin)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
        else:
            p.setPen(Qt.NoPen)
        p.drawPath(g.path)
    p.restore()


def _draw_grid(p: QPainter, doc: Document, side: Side):
    paper = doc.page.paper
    pen = QPen(QColor(GRID_COLOR), 0.15)
    p.setPen(pen)
    ys = paper.horizontal_lines()
    if paper.ruling == "lines":  # линейка: только горизонтальные линии во всю ширину
        for y in ys:
            p.drawLine(QPointF(0, y), QPointF(paper.width_mm, y))
        return
    xs = paper.vertical_lines(side)
    for x in xs:
        p.drawLine(QPointF(x, ys[0]), QPointF(x, ys[-1]))
    for y in ys:
        p.drawLine(QPointF(xs[0], y), QPointF(xs[-1], y))


def _draw_holes(p: QPainter, doc: Document, side: Side):
    paper = doc.page.paper
    x = 8.0 if side is Side.FRONT else paper.width_mm - 8.0
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(HOLE_COLOR))
    for frac in (0.11, 0.33, 0.67, 0.89):
        p.drawEllipse(QPointF(x, paper.height_mm * frac), 2.75, 2.75)


def _page_size(doc: Document) -> QPageSize:
    paper = doc.page.paper
    return QPageSize(QSizeF(paper.width_mm, paper.height_mm), QPageSize.Millimeter,
                     paper.name, QPageSize.ExactMatch)


def export_pdf(doc: Document, path: str | Path, pages: list[Page] | None = None, resolution: int = 1200):
    """Векторный PDF с точным физическим размером листа."""
    pages = doc.pages if pages is None else pages
    w = QPdfWriter(str(path))
    w.setPageLayout(QPageLayout(_page_size(doc), QPageLayout.Portrait, QMarginsF(0, 0, 0, 0)))
    w.setResolution(resolution)
    w.setCreator("KonspektAI")
    w.setTitle("Конспект")
    p = QPainter(w)
    scale = resolution / 25.4
    for i, page in enumerate(pages):
        if i:
            w.newPage()
        p.save()
        p.scale(scale, scale)
        draw_page(p, doc, page)
        p.restore()
    p.end()


def render_image(doc: Document, page: Page, dpi: int = 300, preview: bool = True) -> QImage:
    paper = doc.page.paper
    scale = dpi / 25.4
    img = QImage(round(paper.width_mm * scale), round(paper.height_mm * scale), QImage.Format_ARGB32)
    img.fill(QColor("#ffffff") if preview else QColor(0, 0, 0, 0))
    img.setDotsPerMeterX(round(dpi / 0.0254))
    img.setDotsPerMeterY(round(dpi / 0.0254))
    p = QPainter(img)
    p.scale(scale, scale)
    draw_page(p, doc, page, preview=preview, apply_offset=not preview)
    p.end()
    return img


def export_images(doc: Document, folder: str | Path, dpi: int = 300, fmt: str = "png",
                  preview: bool = False) -> list[Path]:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    out = []
    for page in doc.pages:
        img = render_image(doc, page, dpi, preview)
        if fmt.lower() in ("jpg", "jpeg"):
            img = img.convertToFormat(QImage.Format_RGB32)
        f = folder / f"страница_{page.index + 1:03d}.{fmt}"
        img.save(str(f), None, 95)
        out.append(f)
    return out


def split_for_manual_duplex(doc: Document, reverse_backs: bool = False) -> tuple[list[Page], list[Page]]:
    """Для ручной двусторонней печати: сначала все лицевые, затем все обороты."""
    fronts = [p for p in doc.pages if p.side is Side.FRONT]
    backs = [p for p in doc.pages if p.side is Side.BACK]
    if reverse_backs:
        backs.reverse()
    return fronts, backs
