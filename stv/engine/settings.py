"""Настройки страницы и почерка. Все размеры в миллиметрах, углы в градусах."""

from dataclasses import dataclass, field

from .paper import BLOCK_A5_GRID, PaperProfile, Side


@dataclass
class PrinterOffset:
    """Поправка печати относительно бумаги, подбирается по калибровочному листу.
    Точка (x, y) листа рисуется в (dx + x·sx, dy + y·sy)."""
    dx_mm: float = 0.0
    dy_mm: float = 0.0
    sx: float = 1.0  # масштаб: принтер или клетка блока могут отличаться на доли процента
    sy: float = 1.0


@dataclass
class PageSettings:
    paper: PaperProfile = BLOCK_A5_GRID
    # Поля: «внутреннее» — со стороны колец, «внешнее» — с противоположной, там красная линия и дата.
    margin_inner_mm: float = 17.0
    margin_outer_mm: float = 22.0
    margin_top_mm: float = 6.0
    margin_bottom_mm: float = 6.0
    line_step_cells: int = 1          # шаг строк в клетках: строка всегда на линии клетки
    first_line_indent_cells: float = 2.0
    margin_line: bool = True
    margin_line_offset_mm: float = 19.0  # от внешнего края (противоположного кольцам)
    margin_line_color: str = "#d04050"
    margin_line_width_mm: float = 0.35
    date: str = ""                    # дата на поле вверху, за красной линией
    print_grid: bool = False          # клетку не печатаем — она уже есть на бумаге
    offset_front: PrinterOffset = field(default_factory=PrinterOffset)
    offset_back: PrinterOffset = field(default_factory=PrinterOffset)

    def text_left_mm(self, side: Side) -> float:
        return self.margin_inner_mm if side is Side.FRONT else self.margin_outer_mm

    def text_right_mm(self, side: Side) -> float:
        w = self.paper.width_mm
        return w - (self.margin_outer_mm if side is Side.FRONT else self.margin_inner_mm)

    def margin_line_x_mm(self, side: Side) -> float:
        # лицевая: кольца слева, поле справа; оборот — зеркально
        if side is Side.FRONT:
            return self.paper.width_mm - self.margin_line_offset_mm
        return self.margin_line_offset_mm

    def margin_strip_mm(self, side: Side) -> tuple[float, float]:
        """Полоса поля за красной линией, где пишется дата."""
        x = self.margin_line_x_mm(side)
        if side is Side.FRONT:
            return x + 1.2, self.paper.width_mm - 1.5
        return 1.5, x - 1.2

    def offset(self, side: Side) -> PrinterOffset:
        return self.offset_front if side is Side.FRONT else self.offset_back


@dataclass
class HandSettings:
    font_id: str = "caveat"
    x_height_mm: float | None = None  # высота строчных букв; None — размер по умолчанию для шрифта
    ink_color: str = "#1d3a8a"        # синяя шариковая ручка
    stroke_mm: float = 0.08           # утолщение штриха поверх контура шрифта
    slant_deg: float = 0.0            # общий наклон букв (+ вправо)
    letter_spacing_mm: float = 0.05
    word_spacing: float = 1.0         # множитель ширины пробела
    # Вариативность (0 — выключено)
    baseline_wobble_mm: float = 0.25  # волна строки
    line_slope_deg: float = 0.35      # случайный уклон строки
    glyph_rotation_deg: float = 2.5   # поворот отдельных букв («пьяные буквы»)
    glyph_scale: float = 0.06         # разброс размера букв (доля)
    glyph_lift_mm: float = 0.2        # подъём/опускание букв
    letter_spacing_jitter_mm: float = 0.12
    word_spacing_jitter: float = 0.25  # доля ширины пробела
    shape_warp: float = 0.035         # искажение формы букв (доля высоты)
    ink_jitter: float = 0.06          # разброс оттенка чернил
    pressure_jitter: float = 0.3      # нажим: толщина линии гуляет от слова к слову и от буквы к букве (доля)
    fatigue: float = 0.5              # «усталость»: к концу страницы почерк размашистее и неровнее (0 — нет)
    joins: bool = True                # слитное письмо: строчные буквы в слове соединяются связками
    seed: int = 1
    variation: float = 1.0            # общий множитель всей вариативности (0 — ровный шрифт)

    _VARIATION_FIELDS = ("baseline_wobble_mm", "line_slope_deg", "glyph_rotation_deg", "glyph_scale",
                         "glyph_lift_mm", "letter_spacing_jitter_mm", "word_spacing_jitter", "shape_warp",
                         "ink_jitter", "pressure_jitter", "fatigue")

    def effective(self) -> "HandSettings":
        """Копия, в которой все амплитуды разброса умножены на variation."""
        from dataclasses import replace
        k = max(0.0, self.variation)
        return replace(self, variation=1.0, **{f: getattr(self, f) * k for f in self._VARIATION_FIELDS})
