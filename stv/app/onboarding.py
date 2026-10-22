"""Мастер первого запуска: приветствие с «пишущейся» надписью и три вопроса.

Ответы сохраняются в настройках программы (режим, печать, AI) и сразу меняют интерфейс.
"""

from PySide6.QtCore import (QEasingCurve, QParallelAnimationGroup, QPoint, QPointF, QPropertyAnimation, QRectF, QSize, Qt,
                            QVariantAnimation, Signal)
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QTransform
from PySide6.QtWidgets import (QGraphicsOpacityEffect, QHBoxLayout, QLabel, QPushButton, QStackedWidget,
                               QVBoxLayout, QWidget)

from .project import AppSettings
from .ui import theme
from .ui.motion import NORMAL, SLOW, fade_in

STEPS = [
    ("mode", "Для чего вам KonspektAI?", "От ответа зависит, какие функции будут на экране. Поменять можно в Настройках.", [
        ("study", "graduation-cap", "Учёба", "Конспекты для школы, колледжа и вуза"),
        ("mchs", "flame", "Служба МЧС", "Самостоятельная, служебная и специальная подготовка, расписания"),
        ("free", "pen-line", "Просто писать", "Любой текст от руки: письма, заметки, открытки"),
    ]),
    ("print", "Как будете получать листы?", "Печатать можно прямо из программы — масштаб и бумагу она выставит сама.", [
        ("printer", "printer", "Печатать на принтере", "Сразу на лист: обычный или тетрадный в клетку"),
        ("pdf", "file-text", "Только PDF", "Сохранять файлы, печатать где-нибудь ещё"),
    ]),
    ("ai", "Нужна помощь AI?", "AI сжимает длинный материал до страницы конспекта. Можно и без него.", [
        ("off", "x", "Без AI", "Буду вставлять готовый текст сам"),
        ("chat", "message-circle", "Через любой чат", "Бесплатно: программа готовит запрос, вы вставляете ответ"),
        ("api", "key-round", "Нейросеть одной кнопкой", "Любая по своему ключу; GigaChat — бесплатно"),
    ]),
]


class HandwrittenTitle(QWidget):
    """Надпись, которая «пишется» слева направо рукописным шрифтом."""

    def __init__(self, text: str):
        super().__init__()
        self.text = text
        self.progress = 0.0
        self.setMinimumHeight(110)
        from ..engine.fonts import load_font
        face = load_font("caveat").faces[0]
        self.font = QFont(face.family)
        self.font.setPixelSize(84)
        self.anim = QVariantAnimation(self)
        self.anim.setDuration(1300)
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.setEasingCurve(QEasingCurve.InOutSine)
        self.anim.valueChanged.connect(self._tick)

    def start(self):
        self.anim.start()

    def _tick(self, v):
        self.progress = float(v)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addText(0, 0, self.font, self.text)
        br = path.boundingRect()
        k = min(1.0, (self.width() - 24) / max(1.0, br.width()))  # длинная надпись уменьшается под ширину окна
        if k < 1.0:
            path = QTransform().scale(k, k).map(path)
            br = path.boundingRect()
        path.translate((self.width() - br.width()) / 2 - br.left(), (self.height() - br.height()) / 2 - br.top())
        br = path.boundingRect()
        reveal = br.left() + br.width() * self.progress
        p.setClipRect(QRectF(0, 0, reveal, self.height()))
        col = QColor(theme.current().accent)
        p.fillPath(path, col)
        if 0 < self.progress < 1:  # «кончик пера»
            p.setClipping(False)
            p.setPen(Qt.NoPen)
            p.setBrush(col)
            p.drawEllipse(QPointF(reveal, br.bottom() - br.height() * 0.35), 4, 4)


class OptionCard(QWidget):
    clicked = Signal(str)

    def __init__(self, key: str, icon_name: str, title: str, subtitle: str):
        super().__init__()
        self.key, self.icon_name = key, icon_name
        self.selected = False
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setMinimumHeight(72)
        self.icon = QLabel()
        self.icon.setFixedSize(40, 40)
        self.icon.setAlignment(Qt.AlignCenter)
        t = QLabel(title)
        t.setStyleSheet("font-weight: 600; font-size: 11pt; background: transparent;")
        s = QLabel(subtitle)
        s.setProperty("role", "muted")
        s.setWordWrap(True)
        s.setStyleSheet("background: transparent;")
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(t)
        text.addWidget(s)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(14)
        lay.addWidget(self.icon)
        lay.addLayout(text, 1)
        self._restyle()

    def set_selected(self, on: bool):
        self.selected = on
        self._restyle()

    def _restyle(self):
        p = theme.current()
        border = p.accent if self.selected else p.border
        bg = p.accent_soft if self.selected else p.surface
        self.setStyleSheet(f"OptionCard {{ background: {bg}; border: {2 if self.selected else 1}px solid {border};"
                           f" border-radius: 14px; }} OptionCard:hover {{ border-color: {p.accent}; }}")
        self.icon.setStyleSheet(f"background: {p.accent_soft if not self.selected else p.surface};"
                                " border-radius: 12px;")
        self.icon.setPixmap(theme.pixmap(self.icon_name, 22, p.accent))

    def mousePressEvent(self, e):
        self.clicked.emit(self.key)


class Onboarding(QWidget):
    """Полупрозрачный фон на всё окно и карточка мастера по центру."""
    finished_choice = Signal()

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setGeometry(parent.rect())
        self.setAttribute(Qt.WA_StyledBackground, True)
        p = theme.current()
        self.setStyleSheet(f"Onboarding {{ background: {QColor(0, 0, 0, 110).name(QColor.HexArgb)}; }}")
        parent.installEventFilter(self)
        self.answers = {"mode": AppSettings.get("mode", "study"), "print": AppSettings.get("print", "printer"),
                        "ai": AppSettings.get("ai", "chat")}
        self.cards: dict[str, list[OptionCard]] = {}

        self.panel = QWidget(self)
        self.panel.setObjectName("Card")
        self.panel.setAttribute(Qt.WA_StyledBackground, True)
        self.panel.setFixedSize(640, 560)
        self.pages = QStackedWidget()
        self.pages.addWidget(self._welcome())
        for key, title, sub, options in STEPS:
            self.pages.addWidget(self._step(key, title, sub, options))
        self.pages.addWidget(self._done())

        self.dots = QHBoxLayout()
        self.dots.setSpacing(6)
        self.dot_widgets = []
        for _ in range(len(STEPS)):
            d = QWidget()
            d.setFixedSize(26, 5)
            self.dot_widgets.append(d)
            self.dots.addWidget(d)
        self.back = QPushButton("Назад")
        self.back.setProperty("kind", "ghost")
        self.back.clicked.connect(lambda: self._go(self.pages.currentIndex() - 1))
        self.next = QPushButton("Начать")
        self.next.setProperty("kind", "primary")
        self.next.clicked.connect(self._next)
        nav = QHBoxLayout()
        nav.addWidget(self.back)
        nav.addStretch(1)
        nav.addLayout(self.dots)
        nav.addStretch(1)
        nav.addWidget(self.next)
        lay = QVBoxLayout(self.panel)
        lay.setContentsMargins(32, 28, 32, 24)
        lay.addWidget(self.pages, 1)
        lay.addLayout(nav)
        self._sync_nav()

    # ---------- страницы ----------

    def _welcome(self) -> QWidget:
        w = QWidget()
        l = QVBoxLayout(w)
        l.addStretch(1)
        from PySide6.QtGui import QIcon
        from ..resources import asset
        logo = QLabel()
        logo.setPixmap(QIcon(str(asset("brand", "icon.ico"))).pixmap(QSize(88, 88), self.devicePixelRatioF()))
        logo.setAlignment(Qt.AlignCenter)
        l.addWidget(logo)
        self.hand = HandwrittenTitle("Привет! Это KonspektAI")
        l.addWidget(self.hand)
        sub = QLabel("Программа превращает печатный текст в рукописные страницы,\n"
                     "которые можно сразу распечатать — в клетку, на линейку или в PDF.")
        sub.setAlignment(Qt.AlignCenter)
        sub.setProperty("role", "muted")
        sub.setStyleSheet("font-size: 11pt;")
        l.addWidget(sub)
        l.addSpacing(10)
        hint = QLabel("Три коротких вопроса — и можно начинать.")
        hint.setAlignment(Qt.AlignCenter)
        l.addWidget(hint)
        l.addStretch(1)
        return w

    def _step(self, key, title, sub, options) -> QWidget:
        w = QWidget()
        l = QVBoxLayout(w)
        l.setSpacing(10)
        t = QLabel(title)
        t.setProperty("role", "h1")
        s = QLabel(sub)
        s.setProperty("role", "muted")
        s.setWordWrap(True)
        l.addWidget(t)
        l.addWidget(s)
        l.addSpacing(8)
        self.cards[key] = []
        for opt_key, icon_name, otitle, osub in options:
            c = OptionCard(opt_key, icon_name, otitle, osub)
            c.set_selected(self.answers[key] == opt_key)
            c.clicked.connect(lambda k, key=key: self._choose(key, k))
            self.cards[key].append(c)
            l.addWidget(c)
        l.addStretch(1)
        return w

    def _done(self) -> QWidget:
        w = QWidget()
        l = QVBoxLayout(w)
        l.addStretch(1)
        icon = QLabel()
        icon.setAlignment(Qt.AlignCenter)
        icon.setPixmap(theme.pixmap("circle-check", 64, theme.current().success))
        t = QLabel("Всё готово")
        t.setProperty("role", "h1")
        t.setAlignment(Qt.AlignCenter)
        self.summary = QLabel()
        self.summary.setAlignment(Qt.AlignCenter)
        self.summary.setProperty("role", "muted")
        self.summary.setWordWrap(True)
        l.addWidget(icon)
        l.addWidget(t)
        l.addWidget(self.summary)
        l.addStretch(1)
        return w

    # ---------- поведение ----------

    def start(self):
        self.show()
        self.raise_()
        self._center()
        eff = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(eff)
        g = QParallelAnimationGroup(self)
        a = QPropertyAnimation(eff, b"opacity")
        a.setDuration(NORMAL)
        a.setStartValue(0.0)
        a.setEndValue(1.0)
        b = QPropertyAnimation(self.panel, b"pos")
        b.setDuration(SLOW)
        b.setStartValue(self.panel.pos() + QPoint(0, 40))
        b.setEndValue(self.panel.pos())
        b.setEasingCurve(QEasingCurve.OutBack)
        g.addAnimation(a)
        g.addAnimation(b)
        g.finished.connect(lambda: (self.setGraphicsEffect(None), self.hand.start()))
        g.start(QParallelAnimationGroup.DeleteWhenStopped)

    def _center(self):
        self.panel.move((self.width() - self.panel.width()) // 2, (self.height() - self.panel.height()) // 2)

    def eventFilter(self, obj, e):
        if obj is self.parentWidget() and e.type() == e.Type.Resize:
            self.setGeometry(obj.rect())
            self._center()
        return False

    def _choose(self, key, value):
        self.answers[key] = value
        for c in self.cards[key]:
            c.set_selected(c.key == value)

    def _next(self):
        i = self.pages.currentIndex()
        if i == self.pages.count() - 1:
            self._finish()
        else:
            self._go(i + 1)

    def _go(self, i: int):
        if not (0 <= i < self.pages.count()):
            return
        forward = i > self.pages.currentIndex()
        self.pages.setCurrentIndex(i)
        page = self.pages.currentWidget()
        if i == self.pages.count() - 1:
            self._fill_summary()
        start = QPoint(40 if forward else -40, 0)
        a = QPropertyAnimation(page, b"pos", page)
        a.setDuration(NORMAL)
        a.setStartValue(start)
        a.setEndValue(QPoint(0, 0))
        a.setEasingCurve(QEasingCurve.OutCubic)
        a.start(QPropertyAnimation.DeleteWhenStopped)
        fade_in(page, NORMAL, rise=0)
        self._sync_nav()

    def _sync_nav(self):
        i = self.pages.currentIndex()
        last = self.pages.count() - 1
        self.back.setVisible(0 < i < last)
        self.next.setText("Начать" if i == 0 else "Создать первую тетрадь" if i == last else "Дальше")
        p = theme.current()
        for k, d in enumerate(self.dot_widgets):
            on = 1 <= i and k < i
            d.setStyleSheet(f"background: {p.accent if on else p.border}; border-radius: 2px;")
        for d in self.dot_widgets:
            d.setVisible(0 < i < last)

    def _fill_summary(self):
        names = {k: {o[0]: o[2] for o in opts} for k, _, _, opts in STEPS}
        a = self.answers
        self.summary.setText(f"{names['mode'][a['mode']]} · {names['print'][a['print']]} · {names['ai'][a['ai']]}\n\n"
                             "Всё это можно поменять в Настройках. Тонкая настройка почерка и бумаги — "
                             "кнопка «Оформление» в тетради.")

    def _finish(self):
        for k, v in self.answers.items():
            AppSettings.set(k, v)
        eff = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(eff)
        a = QPropertyAnimation(eff, b"opacity", self)
        a.setDuration(NORMAL)
        a.setStartValue(1.0)
        a.setEndValue(0.0)
        a.finished.connect(lambda: (self.finished_choice.emit(), self.deleteLater()))
        a.start(QPropertyAnimation.DeleteWhenStopped)
