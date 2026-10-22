"""Импорт PDF (текстовый слой и скан) и офлайн-распознавание русского текста."""

from pathlib import Path

import pytest

from stv.ocr import assemble, fix_homoglyphs

TEXT = ("Первичные средства пожаротушения предназначены для борьбы с пожаром "
        "в начальной стадии его развития. Огнетушители бывают порошковые и углекислотные.")
TIMES = Path(r"C:\Windows\Fonts\times.ttf")


def test_homoglyphs_fixed_only_in_russian_text():
    assert fix_homoglyphs("расстояние 3-4 m, Огнeтушитель") == "расстояние 3-4 м, Огнетушитель"
    assert fix_homoglyphs("∃вакуация по плану") == "Эвакуация по плану"
    assert fix_homoglyphs("файл MS Word в папке Документы") == "файл MS Word в папке Документы"
    assert fix_homoglyphs("Hello world") == "Hello world"


def test_assemble_joins_lines_and_hyphens():
    boxes = [[[0, 0], [300, 0], [300, 20], [0, 20]],
             [[0, 30], [280, 30], [280, 50], [0, 50]],
             [[0, 60], [200, 60], [200, 80], [0, 80]]]
    texts = ["Огнетушители предназначе-", "ны для тушения пожаров.", "Новый абзац."]
    assert assemble(boxes, texts) == "Огнетушители предназначены для тушения пожаров.\nНовый абзац."


def _text_image(px_per_char=30):
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter
    fid = QFontDatabase.addApplicationFont(str(TIMES))
    family = QFontDatabase.applicationFontFamilies(fid)[0]
    img = QImage(1700, 400, QImage.Format_RGB32)
    img.fill(QColor("white"))
    p = QPainter(img)
    f = QFont(family)
    f.setPixelSize(px_per_char)
    p.setFont(f)
    p.setPen(QColor("black"))
    p.drawText(QRectF(40, 40, 1620, 320), Qt.AlignLeft | Qt.TextWordWrap, TEXT)
    p.end()
    return img, family


def _words(s):
    return [w.strip(".,").lower() for w in s.split()]


@pytest.mark.skipif(not TIMES.exists(), reason="нужен системный шрифт Times New Roman")
def test_ocr_image_russian(tmp_path):
    from stv.ocr import ocr_image
    img, _ = _text_image()
    f = tmp_path / "скан.png"
    img.save(str(f))
    got = _words(ocr_image(f))
    want = _words(TEXT)
    hit = sum(1 for w in want if w in got)
    assert hit / len(want) > 0.85, got


@pytest.mark.skipif(not TIMES.exists(), reason="нужен системный шрифт Times New Roman")
def test_pdf_text_layer_and_scan(tmp_path):
    from PySide6.QtCore import QMarginsF, QRectF, Qt
    from PySide6.QtGui import QFont, QPageLayout, QPageSize, QPainter, QPdfWriter
    from stv.documents import read_pdf_text
    img, family = _text_image()

    def make(path, scanned):
        w = QPdfWriter(str(path))
        w.setPageLayout(QPageLayout(QPageSize(QPageSize.A4), QPageLayout.Portrait, QMarginsF(10, 10, 10, 10)))
        w.setResolution(300)
        p = QPainter(w)
        if scanned:
            p.drawImage(QRectF(0, 0, 2300, 540), img)  # только картинка, без текстового слоя
        else:
            f = QFont(family)
            f.setPixelSize(40)
            p.setFont(f)
            p.drawText(QRectF(0, 0, 2300, 600), Qt.AlignLeft | Qt.TextWordWrap, TEXT)
        p.end()

    text_pdf, scan_pdf = tmp_path / "текст.pdf", tmp_path / "скан.pdf"
    make(text_pdf, False)
    make(scan_pdf, True)
    assert _words(read_pdf_text(text_pdf)) == _words(TEXT)
    got = _words(read_pdf_text(scan_pdf))
    assert sum(1 for w in _words(TEXT) if w in got) / len(_words(TEXT)) > 0.85, got


@pytest.mark.parametrize("raw,fixed", [
    ("Огнетушитель - это устройство.", "Огнетушитель — это устройство."),
    ("- пункт списка", "- пункт списка"),                       # дефис списка не трогаем
    ('Порошок "П-2АП" и ,,ОУ-5"', "Порошок «П-2АП» и «ОУ-5»"),
    ("<<да>> - если", "«да» — если"),
    ("до -70 oC, вода 4*С", "до -70 °C, вода 4 °С"),
    ("Воздух 25°С", "Воздух 25 °С"),
    ("3-4 м, 1,5 МПа", "3-4 м, 1,5 МПа"),                     # диапазоны без пробелов не трогаем
])
def test_typography_fixes(raw, fixed):
    from stv.ocr import fix_typography
    assert fix_typography(raw) == fixed
