"""Название программы и папки её данных — в одном месте."""

import os
import shutil
from pathlib import Path

APP_NAME = "KonspektAI"
VERSION = "1.0.3"
TAGLINE = "Рукописные конспекты из печатного текста"
FILE_EXT = ".konspekt"
OLD_FILE_EXT = ".stv"  # тетради, сохранённые до переименования, открываются как раньше
PACK_EXT = ".kpack"     # перенос на другой компьютер: принтеры, почерки, настройки и тетради
# Откуда брать обновления: «владелец/репозиторий» на GitHub (релизы с установщиком).
GITHUB_REPO = "rashapisin/konspektai"


PORTABLE_MARK = "portable.txt"  # лежит рядом с EXE в переносной версии


def portable_root() -> Path | None:
    """Переносная версия (распакованный ZIP): всё хранится рядом с программой, в папке «Данные», —
    на флешке ничего не теряется и на чужом компьютере ничего не остаётся."""
    import sys
    if not getattr(sys, "frozen", False):
        return None
    exe_dir = Path(sys.executable).parent
    return exe_dir / "Данные" if (exe_dir / PORTABLE_MARK).exists() else None


def data_dir() -> Path:
    r"""%APPDATA%\KonspektAI (в переносной версии — «Данные\Настройки» рядом с программой).
    Данные из прежней папки STV переезжают сюда при первом запуске."""
    root = portable_root()
    if root is not None:
        d = root / "Настройки"
        d.mkdir(parents=True, exist_ok=True)
        return d
    base = Path(os.environ.get("APPDATA") or Path.home())
    d, old = base / APP_NAME, base / "STV"
    if not d.exists() and old.is_dir():
        try:
            shutil.move(str(old), str(d))
        except OSError:
            shutil.copytree(old, d, dirs_exist_ok=True)  # старую папку держит другая программа — копируем
    d.mkdir(parents=True, exist_ok=True)
    return d
