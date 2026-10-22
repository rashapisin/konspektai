"""Редактор текста конспекта с кнопками разметки и подсветкой служебных строк."""

import re

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

from .ui.widgets import FlowLayout


class MarkupHighlighter(QSyntaxHighlighter):
    RULES = [
        (re.compile(r"^\s*\[[^\]]*\]\s*$"), "#2f6fbf", True),   # [страница], [дата …]
        (re.compile(r"^\s*#.*$"), "#b03050", True),             # заголовок
        (re.compile(r"^\s*(?:[-–—•*]|\d{1,3}[.)])(?=\s)"), "#2f6fbf", False),  # маркер списка
    ]

    def highlightBlock(self, text: str):
        for rx, color, bold in self.RULES:
            m = rx.search(text)
            if m:
                fmt = QTextCharFormat()
                fmt.setForeground(QColor(color))
                if bold:
                    fmt.setFontWeight(QFont.DemiBold)
                self.setFormat(m.start(), m.end() - m.start(), fmt)


class EditorPanel(QWidget):
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.edit = QPlainTextEdit()
        self.edit.setPlaceholderText("Вставьте или напишите текст конспекта.\n\n"
                                     "Шапку и дату программа поставит сама. Кнопки сверху добавляют "
                                     "заголовок, пункт списка, новую страницу и лист проверки.")
        f = self.edit.font()
        f.setPointSize(11)
        self.edit.setFont(f)
        self.highlighter = MarkupHighlighter(self.edit.document())
        self.edit.textChanged.connect(self._on_text)

        bar = FlowLayout(spacing=6)
        for title, tip, fn in (
            ("Заголовок", "Сделать текущую строку заголовком по центру", self._heading),
            ("Пункт списка", "Строка начнётся с «-» и без отступа красной строки, как пункт перечня",
             lambda: self._prefix("- ")),
            ("С новой страницы", "Текст после этой отметки начнётся с новой страницы. "
             "Нажмите несколько раз, чтобы оставить пустые страницы", lambda: self._insert_line("[страница]")),
            ("Лист проверки", "Отдельная страница «лист проверки»", lambda: self._insert_line("[лист проверки]")),
        ):
            b = QPushButton(title)
            b.setProperty("kind", "chip")
            b.setToolTip(tip)
            b.clicked.connect(fn)
            bar.addWidget(b)
            if title == "Лист проверки":
                self.checksheet_btn = b

        self.stats = QLabel()
        self.stats.setProperty("role", "muted")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addLayout(bar)
        lay.addWidget(self.edit, 1)
        lay.addWidget(self.stats)

    def set_mchs(self, on: bool):
        self.checksheet_btn.setVisible(on)  # «лист проверки» нужен только в тетрадях МЧС

    def text(self) -> str:
        return self.edit.toPlainText()

    def set_text(self, text: str):
        self.edit.blockSignals(True)
        self.edit.setPlainText(text)
        self.edit.blockSignals(False)
        self._update_stats()

    def _update_stats(self):
        chars = len(self.edit.toPlainText())
        self.stats.setText(f"{chars:,} знаков в этом конспекте".replace(",", " "))

    def _on_text(self):
        self._update_stats()
        self.changed.emit()

    # --- кнопки разметки ---

    def _current_line_cursor(self) -> QTextCursor:
        c = self.edit.textCursor()
        c.movePosition(QTextCursor.StartOfBlock)
        return c

    def _prefix(self, prefix: str):
        c = self._current_line_cursor()
        line = c.block().text()
        if not line.startswith(prefix):
            c.insertText(prefix)
        self.edit.setFocus()

    def _heading(self):
        c = self._current_line_cursor()
        if not c.block().text().lstrip().startswith("#"):
            c.insertText("# ")
        self.edit.setFocus()

    def _insert_line(self, line: str):
        c = self.edit.textCursor()
        c.movePosition(QTextCursor.EndOfBlock)
        prefix = "\n" if c.block().text().strip() else ""
        c.insertText(f"{prefix}{line}\n")
        self.edit.setTextCursor(c)
        self.edit.setFocus()

