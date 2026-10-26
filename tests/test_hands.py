"""Свой почерк: заполненный шаблон «фотографируется» с перекосом и шумом, распознаётся и пишет текст."""

import random

import cv2
import numpy as np
import pytest

from stv.hands import handset, template as T
from stv.hands.scanner import ScanError, scan_image

PX = 8.0


def _filled_page(page: int, path, seed=1, skip=()):
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QColor, QFont, QPainter

    from stv.engine.fonts import load_font

    rng = random.Random(seed)
    img = T.render_page_image(page, PX)
    face = load_font("badscript").faces[0]
    from PySide6.QtGui import QFontMetricsF
    font = QFont(face.family)
    font.setPixelSize(100)
    k = QFontMetricsF(font).xHeight() / 100
    font.setPixelSize(int(4.2 * PX / k))  # высота строчных ≈ 4,2 мм
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setFont(font)
    p.setPen(QColor("#1b2f7a"))
    for c in T.cells():
        if c.page != page or c.char in skip:
            continue
        p.save()
        p.translate((c.x + 2.5 + rng.uniform(-0.5, 0.5)) * PX, (c.y + T.BASELINE + rng.uniform(-0.4, 0.3)) * PX)
        p.rotate(rng.uniform(-4, 4))
        p.drawText(QPointF(0, 0), c.char)
        p.restore()
    p.end()
    # QImage -> numpy -> «фото»: лист на тёмном столе, перекос, размытие, шум, неравномерный свет
    img = img.convertToFormat(img.Format.Format_RGB888)
    arr = np.frombuffer(img.constBits(), np.uint8).reshape(img.height(), img.bytesPerLine())[:, :img.width() * 3]
    arr = arr.reshape(img.height(), img.width(), 3)[:, :, ::-1].copy()
    h, w = arr.shape[:2]
    W, H = int(w * 1.35), int(h * 1.25)
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    dst = np.float32([[W * 0.12, H * 0.06], [W * 0.90, H * 0.09], [W * 0.86, H * 0.95], [W * 0.15, H * 0.92]])
    m = cv2.getPerspectiveTransform(src, dst)
    photo = cv2.warpPerspective(arr, m, (W, H), borderValue=(70, 90, 120))
    grad = np.linspace(0.85, 1.05, W)[None, :, None]
    photo = np.clip(photo * grad + np.random.default_rng(seed).normal(0, 6, photo.shape), 0, 255).astype(np.uint8)
    photo = cv2.GaussianBlur(photo, (3, 3), 0.8)
    ok, buf = cv2.imencode(".jpg", photo, [cv2.IMWRITE_JPEG_QUALITY, 85])
    buf.tofile(str(path))


@pytest.fixture(scope="module")
def scanned(tmp_path_factory, qt_app):
    d = tmp_path_factory.mktemp("hand")
    results = []
    for page in range(T.page_count()):
        f = d / f"лист {page + 1}.jpg"
        _filled_page(page, f, seed=page + 1, skip=("ё",) if page == 0 else ())
        results.append(scan_image(f))
    return results


def test_pages_identified_and_cells_read(scanned):
    assert sorted(r.page for r in scanned) == list(range(T.page_count()))
    total = sum(len(r.glyphs) for r in scanned)
    expected = len(T.cells()) - 3  # «ё» оставили пустой (3 варианта)
    assert total >= expected * 0.97, total
    assert scanned[0].empty.count("ё") == 3


def test_handset_metrics_and_coverage(scanned):
    data = handset.build(scanned, "Тестовый почерк")
    assert 3.4 < data["metrics"]["x_height"] < 5.0, data["metrics"]
    assert data["metrics"]["ascent"] > data["metrics"]["x_height"]
    assert "ё" in handset.missing_chars(data)
    assert len(data["glyphs"]["а"]) == 3 and len(data["glyphs"]["Б"]) == 2


def test_custom_hand_writes_russian(scanned, tmp_path, monkeypatch, qt_app):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    from stv.engine.fonts import font_info, forget_font, load_font
    from stv.engine.layout import typeset
    from stv.engine.settings import HandSettings
    fid = handset.save(handset.build(scanned, "Тестовый почерк"))
    assert fid in [i for i, _ in handset.list_hands()]
    forget_font(fid)
    load_font(fid)
    hs = HandSettings(font_id=fid)
    doc = typeset("Ёлка и щётка: съешь ещё этих мягких французских булок, 2026 г.", hand=hs)
    assert not doc.warnings, doc.warnings  # «ё» нет в образце — взята из запасного шрифта, без «?»
    assert sum(len(l.glyphs) for p in doc.pages for l in p.lines) > 50
    assert 1.4 < font_info(fid).x_height_mm <= 2.3


def test_glyph_sheet_renders(scanned):
    from stv.app.hands_page import _glyph_sheet
    img = _glyph_sheet(scanned)
    assert img.width() > 500 and img.height() > 200


def test_photo_without_markers_is_rejected(tmp_path):
    f = tmp_path / "пусто.jpg"
    cv2.imencode(".jpg", np.full((800, 600, 3), 255, np.uint8))[1].tofile(str(f))
    with pytest.raises(ScanError):
        scan_image(f)


def test_blank_template_has_no_ink(tmp_path, qt_app):
    """Подписи и рамки напечатаны тёмными, линии внутри — голубыми: на пустом листе ни одна не считается буквой."""
    for page in range(T.page_count()):
        f = tmp_path / f"пустой {page + 1}.jpg"
        _filled_page(page, f, seed=7 + page, skip=tuple({c.char for c in T.cells()}))
        res = scan_image(f)
        assert res.page == page and not res.glyphs, [g.char for g in res.glyphs][:10]


def test_clean_render_finds_markers(tmp_path, qt_app):
    """Как самопроверка EXE: чистый шаблон без фото. Рамки квадратов для букв — тоже квадраты, но светлые
    внутри: за угловые метки их принимать нельзя."""
    from PySide6.QtGui import QImage
    img = T.render_page_image(0, 6.0).convertToFormat(QImage.Format_RGB888)
    arr = np.frombuffer(img.constBits(), np.uint8).reshape(img.height(), img.bytesPerLine())
    arr = arr[:, :img.width() * 3].reshape(img.height(), img.width(), 3)
    f = tmp_path / "шаблон.png"
    cv2.imencode(".png", arr)[1].tofile(str(f))
    res = scan_image(f)
    assert res.page == 0 and not res.glyphs and len(res.empty) > 100
