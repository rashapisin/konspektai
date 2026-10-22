"""Пути к встроенным ресурсам: работают и из исходников, и из собранного EXE."""

import sys
from pathlib import Path


def root() -> Path:
    # PyInstaller распаковывает ресурсы в sys._MEIPASS
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base)
    return Path(__file__).resolve().parent.parent


def asset(*parts: str) -> Path:
    return root().joinpath("assets", *parts)
