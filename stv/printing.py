"""Прямая печать из KonspektAI через драйвер принтера, без программы просмотра PDF.

Бумага в драйвере — A5 или A4 (по профилю бумаги), книжная, «вся страница» (начало координат в углу листа), масштаб 1:1.
Лист блока 145×202 мм рисуется от угла; сдвиг подачи учитывается поправками профиля (способ DIRECT).
"""

from pathlib import Path

from PySide6.QtGui import QPageLayout, QPageSize, QPainter
from PySide6.QtPrintSupport import QPrinter

from .engine.layout import Document, Page
from .engine.paper import Side
from .engine.render import draw_page
from .engine.settings import PageSettings


class PrintError(Exception):
    pass


def make_printer(printer_name: str, title: str, output_pdf: str | Path | None = None,
                 page: str = "A5") -> QPrinter:
    pr = QPrinter(QPrinter.HighResolution)
    if output_pdf:  # для проверки без бумаги: тот же код, вывод в файл
        pr.setOutputFormat(QPrinter.PdfFormat)
        pr.setOutputFileName(str(output_pdf))
    else:
        pr.setPrinterName(printer_name)
        if not pr.isValid():
            raise PrintError(f"Принтер «{printer_name}» недоступен. Проверьте, что он включён и подключён.")
    # Размер — отдельно от полей: setPageLayout с нулевыми полями драйвер HP отклоняет целиком (поля меньше
    # допустимых) и оставляет A4, а в центрующей ручной подаче лист A5 тогда уезжает на 31 мм влево.
    want = QPageSize.A4 if page == "A4" else QPageSize.A5
    pr.setPageOrientation(QPageLayout.Portrait)
    if not pr.setPageSize(QPageSize(want)) or pr.pageLayout().pageSize().id() != want:
        raise PrintError(f"Принтер «{printer_name}» не принял бумагу {page}. "
                         f"Проверьте, что в его настройках есть формат {page}.")
    pr.setFullPage(True)  # начало координат в углу листа, поля драйвера не мешают
    pr.setDuplex(QPrinter.DuplexNone)  # двусторонняя — вручную, переворотом листа
    pr.setColorMode(QPrinter.Color)
    pr.setDocName(title)
    return pr


def _run(pr: QPrinter, draws):
    p = QPainter()
    if not p.begin(pr):
        raise PrintError("Не удалось начать печать: драйвер принтера отказал.")
    try:
        scale = pr.resolution() / 25.4
        for i, draw in enumerate(draws):
            if i and not pr.newPage():
                raise PrintError("Принтер не принял следующую страницу.")
            p.save()
            p.scale(scale, scale)
            draw(p)
            p.restore()
    finally:
        p.end()


def print_pages(doc: Document, pages: list[Page], printer_name: str, title: str = "Конспект",
                output_pdf: str | Path | None = None):
    if not pages:
        return
    pr = make_printer(printer_name, title, output_pdf, doc.page.paper.printer_page)
    _run(pr, [lambda p, pg=pg: draw_page(p, doc, pg) for pg in pages])


def print_calibration(ps: PageSettings, side: Side, printer_name: str, output_pdf: str | Path | None = None,
                      photo: bool = False, check: bool = False):
    """Калибровочный лист: со шкалами для ручного ответа, с линиями для фото (photo=True)
    или проверочная сетка для фото (check=True)."""
    from .engine.calibration import _draw_photo_check, _draw_photo_side, _draw_side
    pr = make_printer(printer_name, "Калибровка KonspektAI", output_pdf, ps.paper.printer_page)
    draw = _draw_photo_check if check else (_draw_photo_side if photo else _draw_side)
    _run(pr, [lambda p: draw(p, ps, side)])


def print_check_grid(ps: PageSettings, side: Side, printer_name: str, output_pdf: str | Path | None = None):
    from .engine.calibration import _draw_check_grid
    pr = make_printer(printer_name, "Проверка KonspektAI", output_pdf, ps.paper.printer_page)
    _run(pr, [lambda p: _draw_check_grid(p, ps, side, printer_name)])
