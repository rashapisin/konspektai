"""Самопроверка собранной программы: KonspektAI.exe --selftest <папка> создаёт PDF без окна."""

import sys
from pathlib import Path


def selftest(folder: str) -> int:
    """Ошибку пишем в файл: в оконной сборке traceback иначе виден только в модальном окне."""
    try:
        return _run(folder)
    except Exception:
        import traceback
        Path(folder).mkdir(parents=True, exist_ok=True)
        (Path(folder) / "selftest.txt").write_text("FAIL\n" + traceback.format_exc(), encoding="utf-8")
        return 2


def _run(folder: str) -> int:
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])

    from .engine.calibration import export_calibration_pdf
    from .engine.layout import typeset
    from .engine.render import export_pdf, split_for_manual_duplex
    from .engine.settings import PageSettings
    from .resources import asset

    out = Path(folder)
    out.mkdir(parents=True, exist_ok=True)
    page = PageSettings(date="21.10.26")
    doc = typeset(asset("sample.txt").read_text(encoding="utf-8"), page)
    from .engine.journal import Entry, build
    jdoc, _ = build([Entry(topic="Проверка", text="Текст проверки журнала.", date="01.01.26")], page,
                    doc.hand, 2.1)
    assert len(jdoc.pages) == 1 and jdoc.pages[0].date_glyphs, "журнал не собрался"
    # распознавание почерка: OpenCV в сборке, метки чистого шаблона находятся
    import numpy as np
    from PySide6.QtGui import QImage
    from .hands import template as T
    from .hands.scanner import scan_image
    img = T.render_page_image(0, 6.0).convertToFormat(QImage.Format_RGB888)
    arr = np.frombuffer(img.constBits(), np.uint8).reshape(img.height(), img.bytesPerLine())
    arr = arr[:, :img.width() * 3].reshape(img.height(), img.width(), 3)
    import cv2
    cv2.imencode(".png", arr)[1].tofile(str(out / "шаблон.png"))
    scanned = scan_image(out / "шаблон.png")
    assert scanned.page == 0 and len(scanned.empty) > 100, "распознавание шаблона не работает"
    # распознавание текста (OCR): модели для русского в сборке, без интернета
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QColor, QFont, QPainter
    from .ocr import ocr_image
    img = QImage(1200, 160, QImage.Format_RGB32)
    img.fill(QColor("white"))
    pt = QPainter(img)
    f = QFont("Arial")
    f.setPixelSize(44)
    pt.setFont(f)
    pt.setPen(QColor("black"))
    pt.drawText(QRectF(30, 30, 1140, 100), Qt.AlignLeft, "Первичные средства пожаротушения")
    pt.end()
    img.save(str(out / "ocr.png"))
    recognized = ocr_image(out / "ocr.png").lower()
    assert "пожаротушения" in recognized, f"OCR не работает: {recognized!r}"
    fronts, backs = split_for_manual_duplex(doc)
    files = [out / "конспект.pdf", out / "1_лицевые.pdf", out / "2_обороты.pdf", out / "калибровка.pdf"]
    export_pdf(doc, files[0])
    export_pdf(doc, files[1], fronts)
    export_pdf(doc, files[2], backs)
    export_calibration_pdf(page, files[3])
    ok = all(f.exists() and f.stat().st_size > 1000 for f in files) and not doc.warnings
    (out / "selftest.txt").write_text("OK" if ok else "FAIL\n" + "\n".join(doc.warnings), encoding="utf-8")
    return 0 if ok else 1
