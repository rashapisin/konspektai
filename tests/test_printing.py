"""Прямая печать (тот же код, что и на принтер, но в PDF-файл) и расчёт поправок мастера калибровки."""

import re

import pytest

from stv.engine.calibration import solve_shift
from stv.engine.layout import typeset
from stv.engine.paper import Side
from stv.engine.settings import PageSettings, PrinterOffset
from stv.printing import print_calibration, print_pages


@pytest.mark.parametrize("measured,vernier,expected", [
    (10.0, 0.0, 0.0),        # всё совпало
    (8.5, 1.5, 1.5),         # печать ушла на 1,5 мм влево/вверх — сдвигаем на +1,5
    (12.0, -2.0, -2.0),      # ушла на 2 мм вправо/вниз
    (7.5, -2.5 + 5, 2.5),    # полклетки: шкала неоднозначна, линейка решает (уголок ближе к краю)
    (12.5, 2.5, -2.5),       # то же в другую сторону: на шкале то же число 2,5
    (13.4, 1.5, -3.5),       # сдвиг больше полклетки: целая клетка + показание шкалы
    (10.0, None, 0.0),       # шкалу не разглядели — только линейка
    (8.0, None, 2.0),
])
def test_solve_shift(measured, vernier, expected):
    assert solve_shift(measured, vernier, expected_mm=10.0) == pytest.approx(expected)


def test_direct_print_path_to_pdf(tmp_path):
    doc = typeset("Первая страница\n[страница]\nВторая страница")
    out = tmp_path / "direct.pdf"
    print_pages(doc, doc.pages, "", "Проба", output_pdf=out)
    data = out.read_bytes().decode("latin-1")
    boxes = re.findall(r"/MediaBox\s*\[\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*\]", data)
    assert len(boxes) == 2
    w, h = float(boxes[0][2]) / 72 * 25.4, float(boxes[0][3]) / 72 * 25.4
    assert abs(w - 148) < 1 and abs(h - 210) < 1  # в драйвер уходит лист A5, рисуем от угла


def test_calibration_prints(tmp_path):
    ps = PageSettings(offset_front=PrinterOffset(1.0, 0.5))
    out = tmp_path / "cal.pdf"
    print_calibration(ps, Side.FRONT, "", output_pdf=out)
    assert out.stat().st_size > 1000


def test_plain_paper_prints_lines_and_uses_a4(tmp_path):
    from stv.engine.paper import paper
    from stv.engine.settings import HandSettings
    ps = PageSettings(paper=paper("a4_lines"))
    doc = typeset("Сочинение о лете. " * 40, ps, HandSettings(x_height_mm=3.0))
    lines = set(ps.paper.horizontal_lines())
    assert all(ln.baseline_mm in lines for p in doc.pages for ln in p.lines)
    out = tmp_path / "a4.pdf"
    print_pages(doc, doc.pages, "", output_pdf=out)
    data = out.read_bytes().decode("latin-1")
    w, h = (float(x) for x in re.findall(r"/MediaBox\s*\[\s*[\d.]+\s+[\d.]+\s+([\d.]+)\s+([\d.]+)", data)[0])
    assert abs(w / 72 * 25.4 - 210) < 1 and abs(h / 72 * 25.4 - 297) < 1
