"""Общие элементы разделов: шапка, карточка, подписи — чтобы все экраны выглядели одинаково."""

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLayout, QVBoxLayout, QWidget


def label(text: str, role: str = "", wrap: bool = True) -> QLabel:
    lb = QLabel(text)
    lb.setWordWrap(wrap)
    if role:
        lb.setProperty("role", role)
    return lb


def page_header(title: str, subtitle: str = "", *right: QWidget) -> QWidget:
    """Крупный заголовок раздела, строка пояснения под ним и кнопки справа."""
    w = QWidget()
    row = QHBoxLayout(w)
    row.setContentsMargins(0, 0, 0, 0)
    col = QVBoxLayout()
    col.setSpacing(4)
    col.addWidget(label(title, "h1", wrap=False))
    if subtitle:
        col.addWidget(label(subtitle, "muted"))
    row.addLayout(col, 1)
    for r in right:
        row.addWidget(r, 0, Qt.AlignBottom)
    return w


class Card(QFrame):
    """Белая карточка со скруглением; содержимое — в self.lay."""

    def __init__(self, margins: int = 20, spacing: int = 12):
        super().__init__()
        self.setObjectName("Card")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(margins, margins, margins, margins)
        self.lay.setSpacing(spacing)

    def set_selected(self, on: bool):
        self.setProperty("selected", on)
        self.style().unpolish(self)
        self.style().polish(self)


def hand_sample(font_id: str, text: str, height: int, color: str, width: int | None = None) -> QPixmap:
    """Строчка текста этим почерком — для карточек почерков. Буквы берутся из того же движка, что печатает."""
    from ...engine.fonts import load_font
    font = load_font(font_id)
    path = QPainterPath()
    x = 0.0
    for i, ch in enumerate(text):
        if ch == " ":
            x += font.space_width()
            continue
        variants = font.variants(ch)
        if not variants:
            continue
        g, adv = variants[i % len(variants)].glyph(ch)
        path.addPath(g.translated(x, 0))
        x += adv
    br = path.boundingRect()
    pm = QPixmap(max(1, width or int(height * 8)), height)
    pm.fill(Qt.transparent)
    if br.isEmpty():
        return pm
    k = min((height * 0.82) / br.height(), (pm.width() - 4) / br.width())
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.translate(2 - br.left() * k, (height - br.height() * k) / 2 - br.top() * k)
    p.scale(k, k)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    p.drawPath(path)
    p.end()
    return pm



class FlowLayout(QLayout):
    """Кнопки в ряд с переносом на следующую строку, как слова в тексте: в узком окне ничего не сжимается
    и не обрезается."""

    def __init__(self, parent=None, spacing: int = 6):
        super().__init__(parent)
        self._items = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(spacing)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientations(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._place(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._place(rect, apply=True)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for it in self._items:
            size = size.expandedTo(it.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _place(self, rect, apply: bool) -> int:
        x, y, line = rect.x(), rect.y(), 0
        gap = self.spacing()
        for it in self._items:
            if it.widget() is not None and it.widget().isHidden():
                continue
            hint = it.sizeHint()
            if x + hint.width() > rect.right() + 1 and line > 0:
                x, y, line = rect.x(), y + line + gap, 0
            if apply:
                it.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + gap
            line = max(line, hint.height())
        return y + line - rect.y()
