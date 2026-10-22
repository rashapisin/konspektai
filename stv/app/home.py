"""Главная: три большие кнопки действий и недавние тетради."""

import datetime as dt
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout,
                               QWidget)

from .project import Recent
from .ui import theme

ACTIONS = (
    ("new", "plus", "Новая тетрадь", "Начать с чистого листа"),
    ("open", "notebook-pen", "Открыть тетрадь", "Файл тетради с компьютера"),
    ("import", "file-up", "Из файла", "Текст из Word, PDF или фото"),
)


class ActionCard(QPushButton):
    def __init__(self, icon_name: str, title: str, subtitle: str):
        super().__init__()
        self.icon_name = icon_name
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumSize(QSize(230, 112))
        self.setProperty("kind", "")
        self.icon_lbl = QLabel()
        self.icon_lbl.setFixedSize(40, 40)
        self.icon_lbl.setAlignment(Qt.AlignCenter)
        t = QLabel(title)
        t.setStyleSheet("font-weight: 600; font-size: 11.5pt; background: transparent;")
        s = QLabel(subtitle)
        s.setProperty("role", "muted")
        s.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(4)
        lay.addWidget(self.icon_lbl)
        lay.addStretch(1)
        lay.addWidget(t)
        lay.addWidget(s)
        for w in (self.icon_lbl, t, s):
            w.setAttribute(Qt.WA_TransparentForMouseEvents)
        theme.on_change(self.restyle)
        self.restyle()

    def restyle(self):
        p = theme.current()
        self.setStyleSheet(f"ActionCard {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: 16px;"
                           f" text-align: left; }} ActionCard:hover {{ border-color: {p.accent}; background: {p.surface}; }}")
        self.icon_lbl.setStyleSheet(f"background: {p.accent_soft}; border-radius: 12px;")
        self.icon_lbl.setPixmap(theme.pixmap(self.icon_name, 22, p.accent))


class HomePage(QWidget):
    new_requested = Signal()
    open_requested = Signal()          # выбрать файл тетради
    import_requested = Signal()        # текст из файла
    recent_requested = Signal(str)

    def __init__(self):
        super().__init__()
        self.setObjectName("Page")
        title = QLabel("Тетради")
        title.setProperty("role", "h1")
        sub = QLabel("Печатный текст → рукописные страницы для печати")
        sub.setProperty("role", "muted")

        row = QHBoxLayout()
        row.setSpacing(14)
        sig = {"new": self.new_requested, "open": self.open_requested, "import": self.import_requested}
        for key, icon_name, t, s in ACTIONS:
            c = ActionCard(icon_name, t, s)
            c.clicked.connect(sig[key].emit)
            row.addWidget(c)
        row.addStretch(1)

        recent = QLabel("Недавние")
        recent.setProperty("role", "h2")
        self.list = QListWidget()
        self.list.setIconSize(QSize(20, 20))
        self.list.itemActivated.connect(lambda it: self.recent_requested.emit(it.data(Qt.UserRole)))
        self.list.itemClicked.connect(lambda it: self.recent_requested.emit(it.data(Qt.UserRole)))
        self.empty = QLabel("Здесь появятся ваши тетради. Начните с «Новой тетради».")
        self.empty.setProperty("role", "muted")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(40, 36, 40, 28)
        lay.setSpacing(10)
        lay.addWidget(title)
        lay.addWidget(sub)
        lay.addSpacing(18)
        lay.addLayout(row)
        lay.addSpacing(26)
        lay.addWidget(recent)
        lay.addWidget(self.list, 1)
        lay.addWidget(self.empty)
        lay.addStretch(0)
        theme.on_change(self.refresh)
        self.refresh()

    def refresh(self):
        self.list.clear()
        items = Recent.items()
        ic = theme.icon("notebook-pen", theme.current().text_muted, 20)
        for d in items:
            when = dt.datetime.fromtimestamp(d.get("opened", 0)).strftime("%d.%m.%Y, %H:%M")
            it = QListWidgetItem(ic, f"{d['title']}\n{when}  ·  {Path(d['path']).name}")
            it.setData(Qt.UserRole, d["path"])
            self.list.addItem(it)
        self.empty.setVisible(not items)
        self.list.setVisible(bool(items))
