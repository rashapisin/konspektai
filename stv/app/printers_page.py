"""Раздел «Принтеры»: принтеры из Windows, насколько точно каждый настроен, мастер калибровки."""

import tempfile
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QComboBox, QDialog, QDoubleSpinBox, QGridLayout, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout, QWidget)

from ..engine import printers
from ..engine.calibration import export_calibration_pdf, export_check_grid_pdf
from ..engine.paper import Side
from ..engine.settings import PageSettings, PrinterOffset
from .ui import theme
from .ui.motion import fade_in
from .ui.widgets import Card, label, page_header

METHODS = ((printers.DIRECT, "Печать из KonspektAI (рекомендуется)"), (printers.PDF, "Через PDF в Chrome/Edge"))


def _spin():
    s = QDoubleSpinBox()
    s.setRange(-15, 15)
    s.setDecimals(2)
    s.setSingleStep(0.1)
    s.setSuffix(" мм")
    return s


class CheckPrintDialog(QDialog):
    """Проверочная сетка: какую сторону печатать — выбирает человек, по одной кнопке на сторону."""

    def __init__(self, parent, printer: str, ps: PageSettings, print_fn, error_cls, profile=None):
        super().__init__(parent)
        self.setWindowTitle("Проверочная сетка")
        self.setMinimumWidth(460)
        self.printer, self.ps, self.print_fn, self.error_cls = printer, ps, print_fn, error_cls
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 22, 24, 18)
        lay.setSpacing(12)
        t = QLabel("Какую сторону напечатать?")
        t.setProperty("role", "h2")
        lay.addWidget(t)
        hint = QLabel("Тонкая чёрная сетка ляжет прямо на синюю клетку — так видно, насколько точно настроена "
                      "печать. Одну сторону можно проверить отдельно от другой.")
        hint.setWordWrap(True)
        hint.setProperty("role", "muted")
        lay.addWidget(hint)
        profile = profile or printers.PrinterProfile(printer)
        for side, title in ((Side.FRONT, "Лицевая сторона"), (Side.BACK, "Оборот")):
            holes = "влево" if profile.holes_left(side is Side.FRONT) else "вправо"
            b = QPushButton(f"{title} — лист отверстиями {holes}")
            b.setIcon(theme.icon("printer", theme.current().text, 18))
            b.setMinimumHeight(40)
            b.clicked.connect(lambda _=False, s=side: self._print(s))
            lay.addWidget(b)
        self.done_label = QLabel("")
        self.done_label.setProperty("role", "muted")
        lay.addWidget(self.done_label)
        close = QPushButton("Закрыть")
        close.setProperty("kind", "ghost")
        close.clicked.connect(self.accept)
        lay.addWidget(close, 0, Qt.AlignRight)

    def _print(self, side: Side):
        try:
            self.print_fn(self.ps, side, self.printer)
        except self.error_cls as e:
            QMessageBox.warning(self, "Проверка", str(e))
            return
        name = "лицевая сторона" if side is Side.FRONT else "оборот"
        self.done_label.setText(f"✓ Отправлено на принтер: {name}.")


class PrintersPage(QWidget):
    """Слева — принтеры из Windows с коротким статусом, справа — выбранный принтер: насколько точно он
    настроен и что сделать. Числа поправок спрятаны в «Для опытных»: обычно они не нужны."""
    profiles_changed = Signal()

    SHORT = {"ok": "Настроен точно", "warn": "Нужна проверка", "none": "Не настроен"}

    def __init__(self):
        super().__init__()
        self.setObjectName("Page")
        refresh = QPushButton("Обновить список")
        refresh.setProperty("kind", "ghost")
        refresh.setIcon(theme.icon("refresh-cw", theme.current().text_muted, 16))
        refresh.setToolTip("Если подключили новый принтер")
        refresh.clicked.connect(self._fill)
        header = page_header("Принтеры", "У каждого принтера свои поправки печати — программа сама выбирает их "
                                         "по имени принтера в Windows.", refresh)

        self.list = QListWidget()
        self.list.setFixedWidth(320)
        self.list.currentItemChanged.connect(lambda *_: self._select())
        left = Card(10, 6)
        left.setFixedWidth(342)
        left.lay.addWidget(self.list, 1)

        # выбранный принтер
        self.name = label("", "h2")
        self.pill = label("", wrap=False)
        self.status = label("", "muted")
        self.calibrate = QPushButton("Откалибровать")
        self.calibrate.setProperty("kind", "primary")
        self.calibrate.setIcon(theme.icon("sliders-horizontal", theme.current().accent_text, 18))
        self.calibrate.clicked.connect(self._wizard)
        self.verify = QPushButton("Пройти проверку")
        self.verify.setProperty("kind", "primary")
        self.verify.setIcon(theme.icon("circle-check", theme.current().accent_text, 18))
        self.verify.setToolTip("Новый лист и фото: программа скажет, точно ли легла печать, и сама доведёт поправки")
        self.verify.clicked.connect(lambda: self._wizard(verify=True))
        check = QPushButton("Проверочная сетка")
        check.setIcon(theme.icon("grid-3x3", theme.current().text, 18))
        check.setToolTip("Чёрная сетка ляжет на клетку листа — видно, насколько точно настроена печать")
        check.clicked.connect(self._print_check)
        buttons = QHBoxLayout()
        buttons.addWidget(self.verify)
        buttons.addWidget(self.calibrate)
        buttons.addWidget(check)
        buttons.addStretch(1)
        main = Card(24, 12)
        pill_row = QHBoxLayout()
        pill_row.addWidget(self.pill)
        pill_row.addStretch(1)
        main.lay.addWidget(self.name)
        main.lay.addLayout(pill_row)
        main.lay.addWidget(self.status)
        main.lay.addSpacing(6)
        main.lay.addLayout(buttons)

        # для опытных: поправки числами
        self.adv_btn = QPushButton("Поправки вручную")
        self.adv_btn.setProperty("kind", "ghost")
        self.adv_btn.setCheckable(True)
        self.adv_btn.toggled.connect(self._toggle_adv)
        self.method = QComboBox()
        for m, title in METHODS:
            self.method.addItem(title, m)
        self.method.currentIndexChanged.connect(self._select)
        self.f_dx, self.f_dy, self.b_dx, self.b_dy = _spin(), _spin(), _spin(), _spin()
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(8)
        grid.addWidget(label("", wrap=False), 0, 0)
        grid.addWidget(label("вправо →", "muted", wrap=False), 0, 1)
        grid.addWidget(label("вниз ↓", "muted", wrap=False), 0, 2)
        for r, (title, a, b) in enumerate((("Лицевая", self.f_dx, self.f_dy), ("Оборот", self.b_dx, self.b_dy)), 1):
            grid.addWidget(label(title, wrap=False), r, 0)
            grid.addWidget(a, r, 1)
            grid.addWidget(b, r, 2)
        save = QPushButton("Сохранить поправки")
        save.clicked.connect(self._save)
        pdfs = QPushButton("PDF для печати через Chrome/Edge")
        pdfs.setProperty("kind", "ghost")
        pdfs.clicked.connect(self._open_pdfs)
        adv_buttons = QHBoxLayout()
        adv_buttons.addWidget(save)
        adv_buttons.addWidget(pdfs)
        adv_buttons.addStretch(1)
        self.adv = Card(24, 12)
        method_row = QHBoxLayout()
        method_row.addWidget(label("Способ печати", wrap=False))
        method_row.addWidget(self.method, 1)
        self.adv.lay.addLayout(method_row)
        self.adv.lay.addWidget(label("Плюс — сдвинуть печать вправо или вниз, в миллиметрах. Обычно хватает "
                                     "мастера калибровки; числа нужны, только если хочется подправить вручную.",
                                     "muted"))
        self.adv.lay.addLayout(grid)
        self.adv.lay.addLayout(adv_buttons)
        self.adv.hide()

        right = QVBoxLayout()
        right.setSpacing(12)
        right.setContentsMargins(0, 0, 0, 0)
        right.addWidget(main)
        right.addWidget(self.adv_btn, 0, Qt.AlignLeft)
        right.addWidget(self.adv)
        right.addStretch(1)
        right_box = QWidget()
        right_box.setMaximumWidth(720)
        right_box.setLayout(right)

        left_col = QVBoxLayout()
        left_col.addWidget(left)
        left_col.addStretch(1)
        body = QHBoxLayout()
        body.setSpacing(18)
        body.addLayout(left_col)
        body.addWidget(right_box, 1)
        body.addStretch(0)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(36, 32, 36, 32)
        lay.setSpacing(22)
        lay.addWidget(header)
        lay.addLayout(body, 1)
        theme.on_change(self._select)
        self._fill()

    def _toggle_adv(self, on: bool):
        self.adv.setVisible(on)
        self.adv_btn.setText("Скрыть поправки" if on else "Поправки вручную")
        if on:
            fade_in(self.adv, rise=8)

    def _item(self, name: str, default: bool, installed: bool) -> QWidget:
        p = theme.current()
        level, _ = self._profile(name).status()
        dot = {"ok": p.success, "warn": p.warning}.get(level, p.border_strong)
        w = QWidget()
        w.setAttribute(Qt.WA_TransparentForMouseEvents)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(2)
        t = QLabel()
        t.setStyleSheet("font-weight: 600; background: transparent;")
        t.setText(t.fontMetrics().elidedText(name, Qt.ElideRight, 270))
        extra = " · по умолчанию" if default else ("" if installed else " · не подключён")
        m = QLabel(f"<span style='color:{dot}'>●</span>&nbsp;{self.SHORT[level]}{extra}")
        m.setStyleSheet(f"color: {p.text_muted}; font-size: 8.5pt; background: transparent;")
        lay.addWidget(t)
        lay.addWidget(m)
        return w

    def _fill(self):
        self.profiles = printers.load()
        installed, default = printers.system_printers()
        self._installed = installed
        extra = [n for n, p in self.profiles.items() if n not in installed and (p.calibrated or p.direct_calibrated)]
        names = list(installed) + extra
        cur = self._name()
        self.list.blockSignals(True)
        self.list.clear()
        for n in names:
            it = QListWidgetItem()
            it.setData(Qt.UserRole, n)
            it.setToolTip(n)
            self.list.addItem(it)
            w = self._item(n, n == default, n in installed)
            it.setSizeHint(QSize(0, max(62, w.sizeHint().height() + 10)))
            self.list.setItemWidget(it, w)
        self.list.blockSignals(False)
        self.list.setFixedHeight(min(520, max(70, sum(self.list.sizeHintForRow(i) + 4
                                                       for i in range(self.list.count())) + 8)))
        pick = cur if cur in names else default
        self.list.setCurrentRow(names.index(pick) if pick in names else 0)
        self._select()

    def _name(self) -> str | None:
        it = self.list.currentItem() if hasattr(self, "list") else None
        return it.data(Qt.UserRole) if it else None

    def _profile(self, name: str) -> printers.PrinterProfile:
        return self.profiles.get(name) or printers.PrinterProfile(name)

    def _select(self):
        name = self._name()
        if not name:
            self.name.setText("Принтеров нет")
            self.pill.hide()
            self.status.setText("Windows не нашла ни одного принтера. Подключите принтер и нажмите "
                                "«Обновить список». Без принтера можно сохранять тетради в PDF.")
            self.calibrate.setEnabled(False)
            self.verify.hide()
            return
        p = self._profile(name)
        level, text = p.status()
        self.name.setText(name)
        self.pill.show()
        self.pill.setText(self.SHORT[level])
        self.pill.setProperty("role", f"pill_{level}")
        self.pill.style().unpolish(self.pill)
        self.pill.style().polish(self.pill)
        can_verify = level == "warn" and p.direct_calibrated
        hint = {"ok": "Можно печатать конспекты: строки лягут в клетку.",
                "warn": ("Пройдите проверку: один новый лист и фото — программа скажет, точно ли легла печать, "
                         "и сама доведёт поправки." if can_verify else
                         "Лучше пройти мастер калибровки по фото — он сам всё измерит и проверит."),
                "none": "Пройдите мастер калибровки: понадобится один лист из блока и телефон."}[level]
        self.status.setText(hint if level == "none" else text[0].upper() + text[1:] + ".<br>" + hint)
        self.calibrate.setEnabled(name in self._installed)
        self.calibrate.setText("Откалибровать заново" if p.direct_calibrated else "Откалибровать")
        # главная кнопка — то, что сейчас нужнее: проверка, если калибровка есть, но не подтверждена
        self.verify.setVisible(can_verify)
        self.verify.setEnabled(name in self._installed)
        self.calibrate.setProperty("kind", "" if can_verify else "primary")
        self.calibrate.setIcon(theme.icon("sliders-horizontal", theme.current().text if can_verify
                                          else theme.current().accent_text, 18))
        self.calibrate.style().unpolish(self.calibrate)
        self.calibrate.style().polish(self.calibrate)
        front, back = p.offsets(self.method.currentData())
        self.f_dx.setValue(front.dx_mm)
        self.f_dy.setValue(front.dy_mm)
        self.b_dx.setValue(back.dx_mm)
        self.b_dy.setValue(back.dy_mm)

    def _save(self):
        name = self._name()
        if not name:
            return
        p = self.profiles.setdefault(name, printers.PrinterProfile(name))
        p.set_offsets(self.method.currentData(), PrinterOffset(self.f_dx.value(), self.f_dy.value()),
                      PrinterOffset(self.b_dx.value(), self.b_dy.value()))
        try:
            printers.save(self.profiles)
        except OSError as e:
            QMessageBox.critical(self, "Принтеры", f"Не удалось сохранить: {e}")
            return
        self._fill()
        self.profiles_changed.emit()

    def _wizard(self, verify: bool = False):
        from .calibration_wizard import CalibrationWizard
        name = self._name()
        if not name or name not in self._installed:
            QMessageBox.information(self, "Калибровка", "Выберите подключённый принтер.")
            return
        w = CalibrationWizard(name, self, verify=verify)
        w.exec()
        if w.saved or w.checks_done:  # поправки могли сохраниться, даже если окно закрыли крестиком
            self._fill()
            self.profiles_changed.emit()

    def _print_check(self):
        from ..printing import PrintError, print_check_grid
        name = self._name()
        if not name or name not in self._installed:
            QMessageBox.information(self, "Проверка", "Выберите подключённый принтер.")
            return
        front, back = self._profile(name).offsets(printers.DIRECT)
        ps = PageSettings(offset_front=front, offset_back=back)
        CheckPrintDialog(self, name, ps, print_check_grid, PrintError, self._profile(name)).exec()

    def _open_pdfs(self):
        name = self._name() or ""
        front, back = self._profile(name).offsets(printers.PDF)
        ps = PageSettings(offset_front=front, offset_back=back)
        folder = Path(tempfile.mkdtemp(prefix="konspektai_cal_"))
        export_check_grid_pdf(ps, folder / "проверка_сетки.pdf", name)
        export_calibration_pdf(ps, folder / "калибровка.pdf")
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
