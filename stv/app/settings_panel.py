"""Правая панель: почерк, размер, жирность, чернила, дата, принтер. Сложное — в «Ещё»."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton, QSlider, QSpinBox, QToolButton,
                               QVBoxLayout, QWidget)

from ..engine import printers
from ..engine.fonts import all_fonts, font_info
from ..engine.settings import HandSettings, PageSettings

INKS = (("Синяя", "#1d3a8a"), ("Чёрная", "#1a1a1a"), ("Фиолетовая", "#4b2a8c"))


class _Slider(QWidget):
    """Ползунок с подписью значения. Хранит значения с шагом step."""
    changed = Signal()

    def __init__(self, lo: float, hi: float, step: float, fmt: str):
        super().__init__()
        self.lo, self.step, self.fmt = lo, step, fmt
        self.s = QSlider(Qt.Horizontal)
        self.s.setRange(0, round((hi - lo) / step))
        self.v = QLabel()
        self.v.setMinimumWidth(64)
        self.v.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.s, 1)
        lay.addWidget(self.v)
        self.s.valueChanged.connect(self._on)
        self._on()

    def value(self) -> float:
        return round(self.lo + self.s.value() * self.step, 4)

    def set_value(self, v: float):
        self.s.blockSignals(True)
        self.s.setValue(round((v - self.lo) / self.step))
        self.s.blockSignals(False)
        self.v.setText(self.fmt.format(self.value()))

    def _on(self):
        self.v.setText(self.fmt.format(self.value()))
        self.changed.emit()


class SettingsPanel(QWidget):
    changed = Signal()

    def __init__(self):
        super().__init__()
        self._loading = False
        self._seed = 1
        self._ink = INKS[0][1]

        from ..engine.paper import PAPERS
        self.paper = QComboBox()
        for pid, pp in PAPERS.items():
            self.paper.addItem(pp.name, pid)
        self.paper.setToolTip("Тетрадный лист — попадаем в готовые клетки; обычный лист — клетку или линейку "
                              "программа напечатает сама")
        self.paper.currentIndexChanged.connect(self._on_paper)
        self.font = QComboBox()
        self.reload_fonts()
        self.font.currentIndexChanged.connect(self._on_font)

        self.size = _Slider(1.2, 4.5, 0.05, "{:.2f} мм")
        self.size.setToolTip("Высота строчных букв")
        self.weight = _Slider(0.0, 0.30, 0.01, "{:.2f} мм")
        self.weight.setToolTip("Утолщение линий букв. Прибавьте, если принтер печатает бледно")
        self.variation = _Slider(0.0, 2.0, 0.05, "{:.0%}")
        self.variation.setToolTip("Насколько неровный почерк: 0% — ровный шрифт, 100% — обычный")

        inks = QHBoxLayout()
        self.ink_buttons = []
        for name, col in INKS:
            b = QPushButton()
            b.setToolTip(name)
            b.setAccessibleName(f"Чернила: {name}")
            b.setCheckable(True)
            b.setFixedSize(34, 26)
            b.setStyleSheet(f"QPushButton {{ background: {col}; border: 2px solid transparent; border-radius: 6px; }}"
                            f"QPushButton:checked {{ border: 2px solid palette(highlight); }}")
            b.clicked.connect(lambda _=False, c=col: self._set_ink(c))
            self.ink_buttons.append((b, col))
            inks.addWidget(b)
        other = QPushButton("Другой…")
        other.setToolTip("Свой цвет чернил")
        other.clicked.connect(self._pick_ink)
        inks.addWidget(other)
        inks.addStretch(1)

        shuffle = QPushButton("Перемешать почерк")
        shuffle.setToolTip("Другие случайные отклонения при тех же настройках")
        shuffle.clicked.connect(self._shuffle)


        self.printer = QComboBox()
        self.printer_status = QLabel()
        self.printer_status.setWordWrap(True)
        self.reload_printers()
        self.printer.currentIndexChanged.connect(self._update_printer_status)

        main = QFormLayout()
        main.addRow("Бумага", self.paper)
        main.addRow("Почерк", self.font)
        main.addRow("Размер", self.size)
        main.addRow("Жирность", self.weight)
        main.addRow("Неровность", self.variation)
        self.joins = QCheckBox("Слитное письмо")
        self.joins.setChecked(True)
        self.joins.setToolTip("Строчные буквы в слове соединяются связками, как в прописях")
        main.addRow("", self.joins)
        main.addRow("Чернила", inks)
        main.addRow("", shuffle)
        main.addRow("Принтер", self.printer)
        main.addRow("", self.printer_status)

        # --- «Ещё» ---
        def mm(lo, hi, step=0.5):
            s = QDoubleSpinBox()
            s.setRange(lo, hi)
            s.setSingleStep(step)
            s.setDecimals(1)
            s.setSuffix(" мм")
            return s
        self.m_inner, self.m_outer = mm(0, 60), mm(0, 60)
        self.m_top, self.m_bottom = mm(0, 40), mm(0, 40)
        self.m_inner.setToolTip("Поле со стороны колец")
        self.m_outer.setToolTip("Поле с противоположной стороны")
        self.step = QSpinBox()
        self.step.setRange(1, 3)
        self.step.setSuffix(" клет.")
        self.step.setToolTip("Строка через сколько клеток")
        self.indent = QDoubleSpinBox()
        self.indent.setRange(0, 6)
        self.indent.setSingleStep(0.5)
        self.indent.setDecimals(1)
        self.indent.setSuffix(" клет.")
        self.red_line = QCheckBox("Печатать красную линию поля")
        self.red_line_x = mm(5, 40)
        self.slant = QDoubleSpinBox()
        self.slant.setRange(-15, 25)
        self.slant.setSuffix("°")
        self.slant.setToolTip("Общий наклон букв вправо")

        self.more = QGroupBox()
        more = QFormLayout(self.more)
        more.addRow("Поле у колец", self.m_inner)
        more.addRow("Внешнее поле", self.m_outer)
        more.addRow("Поле сверху", self.m_top)
        more.addRow("Поле снизу", self.m_bottom)
        more.addRow("Шаг строк", self.step)
        more.addRow("Красная строка", self.indent)
        more.addRow(self.red_line)
        more.addRow("Красная линия от внешнего края", self.red_line_x)
        more.addRow("Наклон букв", self.slant)
        self.more.setVisible(False)
        toggle = QToolButton()
        toggle.setText("Ещё настройки")
        toggle.setCheckable(True)
        toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        toggle.setArrowType(Qt.RightArrow)

        def flip(on):
            self.more.setVisible(on)
            toggle.setArrowType(Qt.DownArrow if on else Qt.RightArrow)
        toggle.toggled.connect(flip)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addLayout(main)
        lay.addWidget(toggle)
        lay.addWidget(self.more)
        lay.addStretch(1)

        for w in (self.size, self.weight, self.variation):
            w.changed.connect(self._emit)
        self.printer.currentIndexChanged.connect(self._emit)
        for s in (self.m_inner, self.m_outer, self.m_top, self.m_bottom, self.indent, self.red_line_x, self.slant):
            s.valueChanged.connect(self._emit)
        self.step.valueChanged.connect(self._emit)
        self.red_line.toggled.connect(self._emit)
        self.joins.toggled.connect(self._emit)

    def reload_fonts(self, select: str | None = None):
        """Встроенные шрифты и собственные почерки; select — выбрать указанный."""
        cur = select or self.font.currentData()
        self.font.blockSignals(True)
        self.font.clear()
        for fid, title in all_fonts():
            self.font.addItem(title if fid.startswith("my:") is False else f"{title} (мой почерк)", fid)
        i = self.font.findData(cur) if cur else -1
        self.font.setCurrentIndex(max(0, i))
        self.font.blockSignals(False)
        if select:
            self._on_font()

    def reload_printers(self):
        """Принтеры из Windows плюс откалиброванные, которые сейчас не подключены (например, рабочий)."""
        cur = self.printer.currentData()
        installed, default = printers.system_printers()
        profiles = printers.load()
        self.printer.blockSignals(True)
        self.printer.clear()
        for name in installed:
            self.printer.addItem(name, name)
        for name, p in profiles.items():
            if name not in installed and (p.calibrated or p.direct_calibrated):
                self.printer.addItem(f"{name} (не подключён)", name)
        self.printer.addItem("Без поправок", "")
        self._default_printer = default
        self.select_printer(cur if cur is not None else default)
        self.printer.blockSignals(False)
        self._update_printer_status()

    def select_printer(self, name: str):
        """Выбрать принтер проекта, а если он здесь не установлен — принтер по умолчанию."""
        i = self.printer.findData(name) if name else -1
        installed = name in printers.system_printers()[0]
        if i < 0 or not installed:
            i = self.printer.findData(self._default_printer)
        self.printer.setCurrentIndex(max(0, i))

    def _update_printer_status(self):
        name = self.printer.currentData()
        if not name:
            msg = "Печать без поправок сдвига."
        else:
            level, text = printers.get(name).status()
            msg = text[0].upper() + text[1:] + "."
            if level == "none":
                msg = ("Не откалиброван для печати из KonspektAI: текст может сместиться на 1–3 мм. "
                       "Пройдите мастер калибровки в разделе «Принтеры» — это один лист.")
        self.printer_status.setText(msg)

    # --- значения ---

    def load(self, ps: PageSettings, hs: HandSettings, printer: str):
        self._loading = True
        self.paper.setCurrentIndex(max(0, self.paper.findData(ps.paper.id)))
        i = self.font.findData(hs.font_id)
        self.font.setCurrentIndex(max(0, i))
        if i < 0:  # почерк удалён — берём первый доступный и его размер
            hs.x_height_mm = None
        self.size.set_value(hs.x_height_mm or font_info(self.font.currentData()).x_height_mm)
        self.weight.set_value(hs.stroke_mm)
        self.variation.set_value(hs.variation)
        self.joins.blockSignals(True)
        self.joins.setChecked(hs.joins)
        self.joins.blockSignals(False)
        self._set_ink(hs.ink_color, emit=False)
        self._seed = hs.seed
        self._slant = hs.slant_deg
        self.slant.setValue(hs.slant_deg)
        self.select_printer(printer)
        self.m_inner.setValue(ps.margin_inner_mm)
        self.m_outer.setValue(ps.margin_outer_mm)
        self.m_top.setValue(ps.margin_top_mm)
        self.m_bottom.setValue(ps.margin_bottom_mm)
        self.step.setValue(ps.line_step_cells)
        self.indent.setValue(ps.first_line_indent_cells)
        self.red_line.setChecked(ps.margin_line)
        self.red_line_x.setValue(ps.margin_line_offset_mm)
        self._loading = False

    def page_settings(self, method: str = printers.DIRECT) -> PageSettings:
        """Настройки страницы с поправками выбранного принтера для способа печати method."""
        name = self.printer.currentData()
        prof = printers.get(name) if name else printers.NO_PROFILE
        front, back = prof.offsets(method)
        from ..engine.paper import paper
        return PageSettings(
            paper=paper(self.paper.currentData()), margin_inner_mm=self.m_inner.value(), margin_outer_mm=self.m_outer.value(),
            margin_top_mm=self.m_top.value(), margin_bottom_mm=self.m_bottom.value(),
            line_step_cells=self.step.value(), first_line_indent_cells=self.indent.value(),
            margin_line=self.red_line.isChecked(), margin_line_offset_mm=self.red_line_x.value(),
            offset_front=front, offset_back=back)

    def hand_settings(self) -> HandSettings:
        return HandSettings(font_id=self.font.currentData(), x_height_mm=self.size.value(),
                            stroke_mm=self.weight.value(), variation=self.variation.value(),
                            ink_color=self._ink, slant_deg=self.slant.value(), seed=self._seed,
                            joins=self.joins.isChecked())

    def printer_name(self) -> str:
        return self.printer.currentData() or ""

    # --- обработчики ---

    def _emit(self):
        if not self._loading:
            self.changed.emit()

    def _on_paper(self):
        """Новая бумага — подходящие поля и размер букв (на линейке 8 мм пишут крупнее, чем в клетку 5 мм)."""
        if self._loading:
            return
        from ..engine.paper import paper
        pp = paper(self.paper.currentData())
        inner, outer, line = pp.margins
        self._loading = True
        self.m_inner.setValue(inner)
        self.m_outer.setValue(outer)
        self.red_line_x.setValue(line)
        self.size.set_value(font_info(self.font.currentData()).x_height_mm * pp.x_height_scale)
        self._loading = False
        self._emit()

    def _on_font(self):
        if not self._loading:
            # у каждого шрифта свой подобранный размер, иначе строки касаются друг друга
            from ..engine.paper import paper
            scale = paper(self.paper.currentData()).x_height_scale
            self.size.set_value(font_info(self.font.currentData()).x_height_mm * scale)
            self._emit()

    def _set_ink(self, col: str, emit: bool = True):
        self._ink = col
        for b, c in self.ink_buttons:
            b.setChecked(c.lower() == col.lower())
        if emit:
            self._emit()

    def _pick_ink(self):
        c = QColorDialog.getColor(QColor(self._ink), self, "Цвет чернил")
        if c.isValid():
            self._set_ink(c.name())

    def _shuffle(self):
        self._seed += 1
        self._emit()
