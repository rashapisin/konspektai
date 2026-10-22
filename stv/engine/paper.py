"""Геометрия бумаги: размер листа, клетка или линейка и их положение относительно краёв.

Два вида бумаги:
- тетрадная (printed=False): клетка уже есть на листе, текст должен в неё попасть — нужна калибровка;
- обычная (printed=True): белый лист, клетку или линейку программа печатает сама вместе с текстом.
"""

from dataclasses import dataclass
from enum import Enum


class Side(Enum):
    FRONT = "front"  # лицевая: отверстия/корешок слева
    BACK = "back"    # оборот: справа


def side_of(page_index: int) -> Side:
    return Side.FRONT if page_index % 2 == 0 else Side.BACK


@dataclass(frozen=True)
class PaperProfile:
    name: str
    width_mm: float
    height_mm: float
    cell_mm: float             # шаг клетки или расстояние между линейками
    # Расстояния от краёв до первой линии на лицевой стороне.
    grid_hole_side_mm: float   # со стороны колец/корешка
    grid_outer_side_mm: float  # с противоположной стороны
    grid_top_mm: float
    grid_bottom_mm: float
    id: str = ""
    ruling: str = "grid"       # grid — клетка, lines — линейка
    printed: bool = False      # клетку/линейку печатаем сами (обычная бумага)
    holes: bool = False        # на превью рисуем отверстия под кольца
    printer_page: str = "A5"   # формат бумаги в драйвере принтера
    # поля по умолчанию для этой бумаги: (у корешка, внешнее, красная линия от внешнего края)
    margins: tuple[float, float, float] = (17.0, 22.0, 19.0)
    x_height_scale: float = 1.0  # во сколько раз крупнее писать относительно клетки 5 мм

    def grid_left_mm(self, side: Side) -> float:
        # Оборот — зеркальное отражение лицевой стороны по горизонтали.
        return self.grid_hole_side_mm if side is Side.FRONT else self.grid_outer_side_mm

    def horizontal_lines(self) -> list[float]:
        """Y-координаты горизонтальных линий (мм от верхнего края) — на них стоят строки."""
        ys = []
        y = self.grid_top_mm
        while y <= self.height_mm - self.grid_bottom_mm + 1e-6:
            ys.append(round(y, 4))
            y += self.cell_mm
        return ys

    def vertical_lines(self, side: Side) -> list[float]:
        xs = []
        x = self.grid_left_mm(side)
        right = self.width_mm - (self.grid_outer_side_mm if side is Side.FRONT else self.grid_hole_side_mm)
        while x <= right + 1e-6:
            xs.append(round(x, 4))
            x += self.cell_mm
        return xs


# Блок A5 в клетку, измерен по фото 21.10.2026 (точность ~±1 мм, уточняется калибровкой).
BLOCK_A5_GRID = PaperProfile(
    name="Блок A5 в клетку (145×202, с кольцами)", width_mm=145.0, height_mm=202.0, cell_mm=5.0,
    grid_hole_side_mm=2.7, grid_outer_side_mm=2.3, grid_top_mm=4.8, grid_bottom_mm=2.2,
    id="block_a5_grid", holes=True)

PAPERS = {p.id: p for p in (
    BLOCK_A5_GRID,
    PaperProfile("Обычный лист A4 — печатать клетку", 210.0, 297.0, 5.0, 5.0, 5.0, 6.0, 1.0,
                 id="a4_grid", printed=True, printer_page="A4", margins=(18.0, 30.0, 25.0)),
    PaperProfile("Обычный лист A5 — печатать клетку", 148.0, 210.0, 5.0, 4.0, 4.0, 5.0, 5.0,
                 id="a5_grid", printed=True, margins=(15.0, 22.0, 19.0)),
    PaperProfile("Обычный лист A4 — печатать линейку", 210.0, 297.0, 8.0, 0.0, 0.0, 16.0, 9.0,
                 id="a4_lines", ruling="lines", printed=True, printer_page="A4", margins=(18.0, 30.0, 25.0),
                 x_height_scale=1.45),
    PaperProfile("Обычный лист A5 — печатать линейку", 148.0, 210.0, 8.0, 0.0, 0.0, 14.0, 4.0,
                 id="a5_lines", ruling="lines", printed=True, margins=(15.0, 22.0, 19.0), x_height_scale=1.45),
    PaperProfile("Лист школьной тетради в клетку (170×205)", 170.0, 205.0, 5.0, 5.0, 5.0, 5.0, 5.0,
                 id="school_grid", margins=(12.0, 25.0, 20.0)),
)}


def paper(paper_id: str) -> PaperProfile:
    return PAPERS.get(paper_id, BLOCK_A5_GRID)
