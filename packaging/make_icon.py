"""Иконка программы: assets/brand/icon.svg → icon.ico (16–256 px) и icon_256.png.

    python packaging/make_icon.py

Для 16–32 px берётся упрощённый рисунок icon_small.svg: тонкая сетка в таком размере превращается в кашу.
"""

import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

BRAND = Path(__file__).resolve().parent.parent / "assets" / "brand"
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def render(svg: Path, size: int) -> QImage:
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    QSvgRenderer(str(svg)).render(p)
    p.end()
    return img


def png_bytes(img: QImage) -> bytes:
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(ba)


def write_ico(path: Path, images: list[QImage]):
    """ICO с PNG внутри: так хранит иконки сама Windows начиная с Vista."""
    blobs = [png_bytes(i) for i in images]
    out = struct.pack("<HHH", 0, 1, len(blobs))
    offset = 6 + 16 * len(blobs)
    for img, b in zip(images, blobs):
        s = img.width()
        out += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(b), offset)
        offset += len(b)
    path.write_bytes(out + b"".join(blobs))


def main():
    QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    imgs = [render(BRAND / ("icon_small.svg" if s <= 32 else "icon.svg"), s) for s in SIZES]
    write_ico(BRAND / "icon.ico", imgs)
    imgs[-1].save(str(BRAND / "icon_256.png"))
    print("готово:", BRAND / "icon.ico")


if __name__ == "__main__":
    main()
