"""Обновления в интерфейсе: строка в Настройках и тихая проверка при запуске (не чаще раза в сутки)."""

import time

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget

from .. import updater
from ..brand import VERSION
from .project import AppSettings
from .ui import theme
from .ui.motion import fade_in

DAY = 24 * 3600


class _Check(QThread):
    found = Signal(object)   # Release или None
    failed = Signal(str)

    def run(self):
        try:
            self.found.emit(updater.latest())
        except updater.UpdateError as e:
            self.failed.emit(str(e))


class _Download(QThread):
    progress = Signal(int, int)
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, rel):
        super().__init__()
        self.rel = rel
        self.stop = False

    def run(self):
        try:
            path = updater.download(self.rel, lambda a, b: self.progress.emit(a, b), lambda: self.stop)
        except updater.UpdateError as e:
            self.failed.emit(str(e))
        else:
            self.done.emit(str(path))


class UpdateRow(QWidget):
    """«Версия 0.9.0 · [Проверить обновления]» → «Доступна 1.0.0 · [Обновить]» → полоска загрузки."""

    def __init__(self):
        super().__init__()
        self.rel = None
        self.worker = None
        self.browser = False  # проверка не прошла — кнопка открывает страницу загрузки в браузере
        self.info = QLabel(f"Версия {VERSION}")
        self.info.setWordWrap(True)
        self.btn = QPushButton("Проверить обновления")
        self.btn.setIcon(theme.icon("refresh-cw", theme.current().text, 18))
        self.btn.clicked.connect(self._click)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        self.bar.hide()
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.info, 1)
        row.addWidget(self.btn)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addLayout(row)
        lay.addWidget(self.bar)
        if not updater.enabled():
            self.info.setText(f"Версия {VERSION}. Обновления заработают, когда программа появится на GitHub.")
            self.btn.setEnabled(False)

    def show_release(self, rel):
        """Вызвать, если новая версия нашлась при запуске."""
        self.rel = rel
        self.info.setText(f"Доступна версия <b>{rel.version}</b> (у вас {VERSION}).")
        self.btn.setText("Обновить")
        self.btn.setProperty("kind", "primary")
        self.btn.setIcon(theme.icon("download", theme.current().accent_text, 18))
        self.btn.style().unpolish(self.btn)
        self.btn.style().polish(self.btn)

    def _click(self):
        from ..brand import portable_root
        if self.browser:
            # программа до GitHub не достучалась, а браузер на работе обычно ходит через прокси — пусть скачает он
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl(self.rel.page if self.rel and self.rel.page else updater.releases_page()))
            self.info.setText("Скачайте файл KonspektAI-Setup-….exe и запустите его: он поставит новую версию "
                              "поверх старой, тетради и настройки сохранятся.")
        elif self.rel is not None and updater.is_newer(self.rel) and portable_root() is not None:
            # переносную версию установщик не обновит: открываем релиз, там новый ZIP
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl(self.rel.page or f"https://github.com/{updater.repo()}/releases/latest"))
            self.info.setText("Скачайте новый ZIP и распакуйте поверх: папка «Данные» сохранится.")
        elif self.rel is not None and updater.is_newer(self.rel):
            self._download()
        else:
            self._check()

    def _check(self):
        self.btn.setEnabled(False)
        self.info.setText("Проверяю…")
        self.worker = _Check()
        self.worker.found.connect(self._found)
        self.worker.failed.connect(self._failed)
        self.worker.start()

    def _found(self, rel):
        self.btn.setEnabled(True)
        AppSettings.set("update_checked", time.time())
        if updater.is_newer(rel):
            self.show_release(rel)
        else:
            self.info.setText(f"Версия {VERSION} — последняя.")
        fade_in(self.info, rise=4)

    def _failed(self, msg: str):
        self.btn.setEnabled(True)
        self.bar.hide()
        self.info.setText(f"<span style='color:{theme.current().danger}'>{msg}</span>")
        self.browser = True
        self.btn.setText("Скачать в браузере")
        self.btn.setIcon(theme.icon("download", theme.current().text, 18))

    def _download(self):
        self.btn.setEnabled(False)
        self.bar.setValue(0)
        self.bar.show()
        self.info.setText(f"Скачиваю версию {self.rel.version}…")
        self.worker = _Download(self.rel)
        self.worker.progress.connect(self._progress)
        self.worker.done.connect(self._install)
        self.worker.failed.connect(self._failed)
        self.worker.start()

    def _progress(self, got: int, total: int):
        if total:
            self.bar.setValue(int(1000 * got / total))
            self.info.setText(f"Скачиваю версию {self.rel.version}… {got / 1e6:.0f} из {total / 1e6:.0f} МБ")

    def _install(self, path: str):
        try:
            updater.run_installer(path)
        except updater.UpdateError as e:
            self._failed(str(e))
            return
        self.info.setText("Ставлю обновление — программа сейчас закроется и откроется снова.")
        QApplication.instance().quit()  # установщик ждёт, пока программа закроется


def check_on_start(on_found):
    """Тихо проверить обновления, если с прошлой проверки прошли сутки. on_found(release) — если есть новее."""
    if not updater.enabled() or time.time() - float(AppSettings.get("update_checked", 0) or 0) < DAY:
        return None
    w = _Check()

    def found(rel):
        AppSettings.set("update_checked", time.time())
        if updater.is_newer(rel):
            on_found(rel)
    w.found.connect(found)
    w.start()
    return w  # держать ссылку, пока поток работает
