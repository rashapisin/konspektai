"""Мастер ручной двусторонней печати: лицевые → переворот пачки → обороты.

По умолчанию печать идёт прямо на принтер из KonspektAI. Запасной способ — PDF в программе просмотра.
У способов разные поправки сдвига, поэтому мастер получает настройки страницы для каждого.
"""

import tempfile
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QCheckBox, QDialog, QHBoxLayout, QMessageBox, QPushButton, QVBoxLayout, QWidget

from ..engine.layout import Document
from ..engine.render import export_pdf, split_for_manual_duplex
from ..engine.settings import PageSettings
from .calibration_wizard import SheetPicture
from .ui import theme
from .ui.motion import AnimatedStack
from .ui.widgets import label

def _sheets_word(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "лист"
    return "листа" if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else "листов"


PDF_HINT = "В окне печати: масштаб «Свой» 100%, бумага A5, двусторонняя печать выключена."


class PrintWizard(QDialog):
    def __init__(self, doc: Document, title: str, printer_name: str, ps_direct: PageSettings,
                 ps_pdf: PageSettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Печать на листы блока")
        self.resize(640, 560)
        self.title = title
        self.printer = printer_name
        self.doc_direct = replace(doc, page=ps_direct)
        self.doc_pdf = replace(doc, page=ps_pdf)
        self.folder = Path(tempfile.mkdtemp(prefix="stv_print_"))
        self.fronts, self.backs = split_for_manual_duplex(doc)
        sheets = len(self.fronts)

        self.via_pdf = QCheckBox("Печатать через PDF в программе просмотра (запасной способ)")
        self.via_pdf.setVisible(bool(printer_name))
        self.via_pdf.setChecked(not printer_name)
        self.reverse = QCheckBox("Обороты в обратном порядке")
        self.reverse.setToolTip("Включите, если после переворота пачки первым в принтер идёт последний лист")

        where = f"на принтер <b>{printer_name}</b>" if printer_name else "через PDF"
        two = bool(self.backs)
        self.stack = AnimatedStack()
        self.stack.addWidget(self._step(
            "Лицевые стороны" + (" · шаг 1 из 2" if two else ""),
            f"Положите в лоток <b>{sheets} {_sheets_word(sheets)}</b> из блока <b>отверстиями влево</b>, верхом в "
            f"принтер. Печать пойдёт {where}.", SheetPicture(True), "Печатать лицевые", self._fronts, self.via_pdf))
        self.stack.addWidget(self._step(
            "Обороты · шаг 2 из 2",
            "Когда лицевые напечатаются, переверните пачку <b>как страницу книги</b>: отверстия справа, верх "
            "остаётся сверху. Порядок листов не меняйте.", SheetPicture(False, flip=True), "Печатать обороты",
            self._backs, self.reverse))

        self.next_btn = QPushButton("Дальше")
        self.next_btn.setProperty("kind", "ghost")
        self.next_btn.clicked.connect(self._next)
        close = QPushButton("Закрыть")
        close.setProperty("kind", "ghost")
        close.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.next_btn)
        buttons.addWidget(close)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 20)
        lay.addWidget(self.stack, 1)
        lay.addLayout(buttons)
        if not self.backs:
            self.next_btn.setVisible(False)

    def _step(self, title: str, html: str, picture: QWidget, button: str, fn,
              extra: QWidget | None = None) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(12)
        lay.addWidget(label(title, "h2"))
        lay.addWidget(label(html))
        lay.addWidget(picture, 1)
        b = QPushButton(button)
        b.setProperty("kind", "primary")
        b.setDefault(True)
        b.setIcon(theme.icon("printer", theme.current().accent_text, 18))
        b.clicked.connect(fn)
        lay.addWidget(b, 0, Qt.AlignHCenter)
        if extra:
            lay.addWidget(extra, 0, Qt.AlignHCenter)
        return w

    def _send(self, pages, pdf_name: str) -> bool:
        if self.via_pdf.isChecked():
            path = self.folder / pdf_name
            try:
                export_pdf(self.doc_pdf, path, pages)
            except OSError as e:
                QMessageBox.critical(self, "Печать", f"Не удалось создать файл для печати: {e}")
                return False
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
            QMessageBox.information(self, "Печать", PDF_HINT)
            return True
        from ..printing import PrintError, print_pages
        try:
            print_pages(self.doc_direct, pages, self.printer, self.title)
        except PrintError as e:
            QMessageBox.warning(self, "Печать", f"{e}\n\nМожно включить запасной способ — через PDF.")
            return False
        return True

    def _fronts(self):
        if self._send(self.fronts, "1_лицевые.pdf") and self.backs:
            self._next()

    def _backs(self):
        backs = list(reversed(self.backs)) if self.reverse.isChecked() else self.backs
        self._send(backs, "2_обороты.pdf")

    def _next(self):
        self.stack.go(1)
        self.next_btn.setVisible(False)
