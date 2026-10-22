"""Скриншоты для README: docs/screenshots/*.png. Чистые временные настройки — без личных данных.

    python packaging/screenshots.py
"""

import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["APPDATA"] = tempfile.mkdtemp()  # настоящие настройки и принтеры не попадут в картинки
OUT = ROOT / "docs" / "screenshots"


def main():
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv[:1])
    app.setStyle("Fusion")
    from stv.app import project
    from stv.app.project import AppSettings
    from stv.app.ui import theme
    project.documents_dir = lambda: Path(tempfile.mkdtemp())
    theme.load_font()
    theme.apply(app, "Светлая")
    AppSettings.set("onboarded", True)
    AppSettings.set("mode", "study")
    AppSettings.set("print", "pdf")
    from stv.app.main_window import HANDS, WORK, MainWindow

    def pump(t):
        end = time.time() + t
        while time.time() < end:
            app.processEvents()
            time.sleep(0.02)

    OUT.mkdir(parents=True, exist_ok=True)
    w = MainWindow()
    w.resize(1400, 860)
    w.show()
    pump(1.0)
    j = w.work.journal
    w.go(WORK)
    w.work.title.setText("История России")
    j.topic.setText("Реформы Петра I")
    j._edited()
    j.editor.edit.setPlainText(
        "Пётр I провёл реформы, которые изменили государственное управление, армию и культуру России.\n"
        "- Создание регулярной армии и флота.\n- Учреждение Сената и коллегий вместо приказов.\n"
        "- Введение Табели о рангах: служба по способностям, а не по знатности.\n"
        "Реформы укрепили государство, но легли тяжёлым бременем на крестьян.")
    pump(6.0)
    w.grab().save(str(OUT / "notebook.png"))
    w.go(HANDS)
    pump(1.0)
    w.grab().save(str(OUT / "hands.png"))
    w.go(0)
    w.show_onboarding()
    pump(2.5)
    w.grab().save(str(OUT / "welcome.png"))
    from stv.app.calibration_wizard import CalibrationWizard
    cw = CalibrationWizard("Принтер")
    cw.show()
    pump(0.8)
    cw.grab().save(str(OUT / "calibration.png"))
    print("готово:", OUT)


if __name__ == "__main__":
    main()
