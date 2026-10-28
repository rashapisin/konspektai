"""Точка входа программы KonspektAI.

KonspektAI.exe                       — обычный запуск
KonspektAI.exe <файл.konspekt>       — открыть тетрадь
KonspektAI.exe <файл.kpack>          — загрузить файл переноса с другого компьютера
KonspektAI.exe --selftest <папка>    — без окна создать PDF и проверить, что всё упаковано
"""

import sys


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "--selftest":
        from .selftest import selftest
        sys.exit(selftest(sys.argv[2]))

    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    from .brand import APP_NAME, VERSION
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(VERSION)
    from PySide6.QtGui import QIcon
    from .resources import asset
    app.setWindowIcon(QIcon(str(asset("brand", "icon.ico"))))
    try:  # своя кнопка на панели задач, а не общая с Python
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_NAME)
    except (AttributeError, OSError):
        pass
    app.setStyle("Fusion")  # своя дизайн-система поверх нейтрального стиля
    from PySide6.QtCore import Qt
    app.setEffectEnabled(Qt.UI_AnimateTooltip, False)
    app.setEffectEnabled(Qt.UI_FadeTooltip, False)

    from .app.main_window import MainWindow
    from .app.project import AppSettings
    from .app.ui import theme
    theme.load_font()
    theme.apply(app, AppSettings.get("theme", "Как в Windows"))
    # тема «как в Windows» следует за системной сменой светлой/тёмной
    app.styleHints().colorSchemeChanged.connect(
        lambda *_: theme.apply(app, AppSettings.get("theme", "Как в Windows")))
    w = MainWindow()
    w.show()
    if len(sys.argv) >= 2 and sys.argv[1].lower().endswith((".konspekt", ".stv")):
        w.open_path(sys.argv[1])  # двойной щелчок по файлу тетради
    elif len(sys.argv) >= 2 and sys.argv[1].lower().endswith(".kpack"):
        from PySide6.QtCore import QTimer
        QTimer.singleShot(300, lambda: w.import_pack(sys.argv[1]))  # файл переноса — когда окно уже на экране
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
