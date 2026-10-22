"""Окно «С телефона»: QR-код, подсказка и счётчик пришедших фото."""

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout

from ..phone_upload import PhoneUpload, UploadError, qr_png
from .ui.widgets import label


class _Bridge(QObject):
    """Фото приходит в потоке сервера — в интерфейс передаём сигналом."""
    photo = Signal(str)


class PhoneDialog(QDialog):
    """multiple=False — окно закрывается само после первого фото; иначе — по кнопке «Готово»."""

    def __init__(self, parent, title: str, hint: str, multiple: bool = False):
        super().__init__(parent)
        self.setWindowTitle("Фото с телефона")
        self.setMinimumWidth(480)
        self.multiple = multiple
        self.paths: list[str] = []
        self.bridge = _Bridge()
        self.bridge.photo.connect(self._got)
        self.server = PhoneUpload(self.bridge.photo.emit, title, hint, multiple)
        self.server.start()

        qr = QLabel()
        pm = QPixmap()
        pm.loadFromData(qr_png(self.server.url))
        qr.setPixmap(pm)
        qr.setAlignment(Qt.AlignCenter)
        qr.setStyleSheet("background: white; border-radius: 16px; padding: 10px;")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 20)
        lay.setSpacing(12)
        lay.addWidget(label("Наведите камеру телефона на код", "h2"))
        lay.addWidget(label("Откроется страница — сфотографируйте лист, и фото сразу придёт сюда. Телефон и "
                            "компьютер должны быть в одной сети Wi-Fi. Если Windows спросит, разрешить ли программе "
                            "доступ к сети, — нажмите «Разрешить».", "muted"))
        lay.addWidget(qr, 0, Qt.AlignHCenter)
        link = label(f"или откройте на телефоне: {self.server.url}", "muted")
        link.setTextInteractionFlags(Qt.TextSelectableByMouse)
        link.setAlignment(Qt.AlignCenter)
        lay.addWidget(link)
        self.status = label("Жду фото…")
        self.status.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.status)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("Отмена")
        cancel.setProperty("kind", "ghost")
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        if multiple:
            self.done_btn = QPushButton("Готово")
            self.done_btn.setProperty("kind", "primary")
            self.done_btn.setEnabled(False)
            self.done_btn.clicked.connect(self.accept)
            row.addWidget(self.done_btn)
        lay.addLayout(row)

    def _got(self, path: str):
        self.paths.append(path)
        if not self.multiple:
            self.accept()
            return
        self.status.setText(f"✓ Пришло фото: {len(self.paths)}. Можно снять ещё или нажать «Готово».")
        self.done_btn.setEnabled(True)

    def done(self, r):
        self.server.stop()  # сервер живёт только пока открыто окно
        super().done(r)


def ask_photos(parent, title: str, hint: str, multiple: bool = False) -> list[str]:
    """Показать QR-код и дождаться фото. Пусто — человек закрыл окно или сети нет."""
    try:
        dlg = PhoneDialog(parent, title, hint, multiple)
    except (UploadError, OSError) as e:
        QMessageBox.warning(parent, "Фото с телефона", str(e))
        return []
    return dlg.paths if dlg.exec() and dlg.paths else []
