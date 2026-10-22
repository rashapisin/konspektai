"""Анимации интерфейса: быстрые (150–280 мс), с мягким замедлением в конце, как в Claude и ChatGPT."""

from PySide6.QtCore import (QEasingCurve, QParallelAnimationGroup, QPoint, QPropertyAnimation, QRect, QSize, Qt,
                            QTimer, Signal)
from PySide6.QtWidgets import (QButtonGroup, QGraphicsOpacityEffect, QLabel, QStackedWidget, QToolButton,
                               QVBoxLayout, QWidget)

from . import theme

FAST, NORMAL, SLOW = 160, 240, 320
EASE = QEasingCurve.OutCubic


def _anim(target, prop: bytes, start, end, ms=NORMAL, curve=EASE) -> QPropertyAnimation:
    # владелец — сам анимируемый объект: иначе Python удалит анимацию сразу после запуска
    a = QPropertyAnimation(target, prop, target)
    a.setDuration(ms)
    a.setStartValue(start)
    a.setEndValue(end)
    a.setEasingCurve(curve)
    return a


def fade_in(w: QWidget, ms=NORMAL, rise: int = 10):
    """Появление: прозрачность 0→1 и подъём на несколько пикселей."""
    eff = QGraphicsOpacityEffect(w)
    w.setGraphicsEffect(eff)
    g = QParallelAnimationGroup(w)
    g.addAnimation(_anim(eff, b"opacity", 0.0, 1.0, ms))
    if rise:
        pos = w.pos()
        g.addAnimation(_anim(w, b"pos", pos + QPoint(0, rise), pos, ms))
    g.finished.connect(lambda: w.setGraphicsEffect(None))  # эффект тормозит перерисовку — снимаем
    g.start(QParallelAnimationGroup.DeleteWhenStopped)


class AnimatedStack(QStackedWidget):
    """Разделы сменяются плавно: старый растворяется, новый приезжает снизу."""

    def go(self, index: int):
        if index == self.currentIndex() or not (0 <= index < self.count()):
            self.setCurrentIndex(index)
            return
        old = self.currentWidget()
        shot = old.grab() if old is not None and old.isVisible() else None
        self.setCurrentIndex(index)
        new = self.currentWidget()
        g = QParallelAnimationGroup(self)
        if shot is not None:
            overlay = QLabel(self)
            overlay.setPixmap(shot)
            overlay.setGeometry(old.geometry())
            overlay.setAttribute(Qt.WA_TransparentForMouseEvents)
            overlay.show()
            overlay.raise_()
            eff = QGraphicsOpacityEffect(overlay)
            overlay.setGraphicsEffect(eff)
            g.addAnimation(_anim(eff, b"opacity", 1.0, 0.0, FAST))
            g.finished.connect(overlay.deleteLater)
        g.addAnimation(_anim(new, b"pos", QPoint(0, 18), QPoint(0, 0), SLOW))
        g.start(QParallelAnimationGroup.DeleteWhenStopped)


class Rail(QWidget):
    """Узкая полоска разделов: иконка и короткая подпись, выбранный раздел подсвечен бегающей «пилюлей»."""
    changed = Signal(int)

    def __init__(self, items: list[tuple[str, str]]):
        super().__init__()
        self.setObjectName("Rail")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedWidth(84)
        self.items = items
        self.pill = QWidget(self)
        self.pill.setAttribute(Qt.WA_StyledBackground, True)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: list[QToolButton] = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 14, 8, 14)
        lay.setSpacing(6)
        from PySide6.QtGui import QIcon
        from ...brand import APP_NAME
        from ...resources import asset
        logo = QLabel()
        logo.setPixmap(QIcon(str(asset("brand", "icon.ico"))).pixmap(QSize(36, 36), self.devicePixelRatioF()))
        logo.setToolTip(APP_NAME)
        lay.addWidget(logo, 0, Qt.AlignHCenter)
        lay.addSpacing(10)
        for i, (icon_name, title) in enumerate(items):
            b = QToolButton()
            b.setText(title)
            b.setToolTip(title)
            b.setCheckable(True)
            b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            b.setIconSize(QSize(22, 22))
            b.setFixedSize(68, 58)
            b.setCursor(Qt.PointingHandCursor)
            self.group.addButton(b, i)
            self.buttons.append(b)
            if i == len(items) - 1:
                lay.addStretch(1)  # последний раздел (настройки) — внизу
            lay.addWidget(b, 0, Qt.AlignHCenter)
        self.group.idClicked.connect(self._clicked)
        theme.on_change(self._restyle)
        self._restyle()

    def _restyle(self):
        p = theme.current()
        self.pill.setStyleSheet(f"background: {p.accent_soft}; border-radius: 14px;")
        style = (f"QToolButton {{ border: none; background: transparent; color: {p.text_muted}; font-size: 8pt;"
                 f" border-radius: 14px; }} QToolButton:hover {{ color: {p.text}; }}"
                 f" QToolButton:checked {{ color: {p.accent}; font-weight: 600; }}")
        for (icon_name, _), b in zip(self.items, self.buttons):
            b.setStyleSheet(style)
            col = p.accent if b.isChecked() else p.text_muted
            b.setIcon(theme.icon(icon_name, col, 22))

    def set_current(self, i: int, animate: bool = True):
        if not (0 <= i < len(self.buttons)):
            return
        self.buttons[i].setChecked(True)
        self._restyle()
        target = self.buttons[i].geometry()
        if not animate or self.pill.geometry().isNull() or not self.isVisible():
            self.pill.setGeometry(target)
        else:
            a = _anim(self.pill, b"geometry", self.pill.geometry(), target, NORMAL, QEasingCurve.OutBack)
            a.start(QPropertyAnimation.DeleteWhenStopped)
        self.pill.lower()

    def set_visible_items(self, visible: list[bool]):
        for b, v in zip(self.buttons, visible):
            b.setVisible(v)
        QTimer.singleShot(0, lambda: self.set_current(self.group.checkedId(), animate=False))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        QTimer.singleShot(0, lambda: self.set_current(self.group.checkedId(), animate=False))

    def _clicked(self, i: int):
        self.set_current(i)
        self.changed.emit(i)


class Drawer(QWidget):
    """Панель, выезжающая справа поверх рабочего экрана (тонкие настройки оформления)."""

    def __init__(self, parent: QWidget, content: QWidget, width: int = 380):
        super().__init__(parent)
        self.setObjectName("Drawer")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.w = width
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(content)
        self.hide()
        self._open = False
        parent.installEventFilter(self)

    def is_open(self) -> bool:
        return self._open

    def _rect(self, opened: bool) -> QRect:
        pr = self.parentWidget().rect()
        x = pr.width() - self.w if opened else pr.width()
        return QRect(x, 0, self.w, pr.height())

    def toggle(self):
        self.set_open(not self._open)

    def set_open(self, opened: bool):
        if opened == self._open:
            return
        self._open = opened
        self.show()
        self.raise_()
        a = _anim(self, b"geometry", self._rect(not opened), self._rect(opened), NORMAL)
        if not opened:
            a.finished.connect(self.hide)
        a.start(QPropertyAnimation.DeleteWhenStopped)

    def eventFilter(self, obj, e):
        if obj is self.parentWidget() and e.type() == e.Type.Resize and self.isVisible():
            self.setGeometry(self._rect(self._open))
        return False


class Toast(QLabel):
    """Короткое уведомление внизу окна: «Сохранено», «Отправлено на принтер»."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.hide()
        self._timer = QTimer(self, singleShot=True, interval=2200)
        self._timer.timeout.connect(self._hide)

    def show_text(self, text: str, kind: str = "info"):
        p = theme.current()
        col = {"ok": p.success, "warn": p.warning, "error": p.danger}.get(kind, p.accent)
        mark = {"ok": "✓", "warn": "!", "error": "✕"}.get(kind, "•")
        self.setStyleSheet(f"background: {p.surface}; color: {p.text}; border: 1px solid {p.border};"
                           f" border-left: 4px solid {col}; border-radius: 12px; padding: 10px 18px;"
                           " font-weight: 600;")
        self.setText(f"<span style='color:{col}'>{mark}</span>&nbsp;&nbsp;{text}")
        self.adjustSize()
        pr = self.parentWidget().rect()
        self.move((pr.width() - self.width()) // 2, pr.height() - self.height() - 28)
        self.show()
        self.raise_()
        fade_in(self, NORMAL, rise=6)
        self._timer.start(max(2200, len(text) * 55))  # длинное сообщение висит дольше

    def _hide(self):
        eff = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(eff)
        a = _anim(eff, b"opacity", 1.0, 0.0, NORMAL)
        a.finished.connect(lambda: (self.hide(), self.setGraphicsEffect(None)))
        a.start(QPropertyAnimation.DeleteWhenStopped)
