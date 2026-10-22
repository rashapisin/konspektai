import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(scope="session", autouse=True)
def qt_app():
    from PySide6.QtWidgets import QApplication  # нужен и для окон, и для движка
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(scope="session")
def sample_text():
    return (Path(__file__).resolve().parent.parent / "assets" / "sample.txt").read_text(encoding="utf-8")
