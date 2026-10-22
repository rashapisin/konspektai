"""Инструмент разработчика: текст → PDF/PNG без интерфейса.

    python -m stv.devcli samples/sample.txt -o output --date 21.10.26
"""

import argparse
import os
import sys
import time
from pathlib import Path


def main(argv=None):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QGuiApplication

    from .engine.layout import typeset
    from .engine.render import export_images, export_pdf, render_image, split_for_manual_duplex
    from .engine.settings import HandSettings, PageSettings

    ap = argparse.ArgumentParser()
    ap.add_argument("text")
    ap.add_argument("-o", "--out", default="output")
    ap.add_argument("--date", default="")
    ap.add_argument("--font", default="caveat")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--size", type=float, default=None, help="высота строчных букв, мм")
    ap.add_argument("--printer", default="", help="имя принтера в Windows; пусто — без поправок")
    args = ap.parse_args(argv)

    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    from .engine import printers
    name = args.printer
    prof = printers.get(name) if name else printers.NO_PROFILE
    front, back = prof.offsets(printers.PDF)  # devcli сохраняет PDF — поправки для печати через PDF
    page = PageSettings(date=args.date, offset_front=front, offset_back=back)
    hand = HandSettings(font_id=args.font, seed=args.seed)
    if args.size:
        hand.x_height_mm = args.size
    text = Path(args.text).read_text(encoding="utf-8")

    t = time.perf_counter()
    doc = typeset(text, page, hand)
    t_layout = time.perf_counter() - t
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    export_pdf(doc, out / "конспект.pdf")
    fronts, backs = split_for_manual_duplex(doc)
    export_pdf(doc, out / "1_лицевые.pdf", fronts)
    if backs:
        export_pdf(doc, out / "2_обороты.pdf", backs)
    for pg in doc.pages:
        render_image(doc, pg, 200, preview=True).save(str(out / f"превью_{pg.index + 1}.png"))
    export_images(doc, out / "png", dpi=300)
    from .engine.calibration import export_calibration_pdf, export_check_grid_pdf
    export_calibration_pdf(page, out / "калибровка.pdf")
    export_check_grid_pdf(page, out / "проверка_сетки.pdf", prof.name)
    print(f"страниц: {len(doc.pages)}, вёрстка {t_layout:.2f} c, всего {time.perf_counter() - t:.2f} c")
    for w in doc.warnings:
        print("ВНИМАНИЕ:", w)


if __name__ == "__main__":
    main()
