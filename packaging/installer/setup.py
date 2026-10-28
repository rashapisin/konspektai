"""Установщик и удаление KonspektAI — одно окно в стиле программы.

Один и тот же EXE работает в двух режимах:
- KonspektAI-Setup.exe: в конец файла дописан zip с программой → установка;
- Uninstall.exe (тот же EXE без zip, лежит в папке программы) → удаление.

Ставит только для текущего пользователя, без прав администратора:
%LOCALAPPDATA%\\Programs\\KonspektAI, ярлыки на рабочем столе и в «Пуске», строка в «Установленных
приложениях» Windows. Тетради (Документы\\KonspektAI) и настройки (%APPDATA%\\KonspektAI) установка
не трогает; при удалении настройки удаляются, только если поставить галочку.

Для проверки без сборки: python packaging/installer/setup.py --payload build\\installer\\payload.zip
"""

import ctypes
import os
import shutil
import subprocess
import sys
import tempfile
import winreg
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import (QEasingCurve, QPoint, QPointF, QRectF, QSize, QStandardPaths, Qt, QThread, QTimer,
                            QVariantAnimation, Signal)
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QIcon, QLinearGradient, QPainter, QPainterPath, QPen)
from PySide6.QtWidgets import (QApplication, QCheckBox, QFileDialog, QGraphicsDropShadowEffect, QHBoxLayout, QLabel,
                               QLineEdit, QProgressBar, QPushButton, QVBoxLayout, QWidget)

from stv.app.ui import theme
from stv.app.ui.motion import AnimatedStack, _anim, fade_in
from stv.brand import APP_NAME, FILE_EXT, PACK_EXT, TAGLINE, VERSION, data_dir
from stv.resources import asset

EXE = f"{APP_NAME}.exe"
UNINSTALL_EXE = "Uninstall.exe"
MARKER = ".konspektai"  # метка «это папка KonspektAI»: удаляется только папка, где она есть
UNINSTALL_KEY = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_NAME}"
PROG_ID = f"{APP_NAME}.Notebook"
PACK_ID = f"{APP_NAME}.Pack"  # файл переноса на другой компьютер
CLASSES = r"Software\Classes"

PHRASES = ("Раскладываю листы…", "Точу карандаши…", "Разлиновываю клетку…", "Заправляю ручку чернилами…",
           "Проверяю поля…", "Почти готово…")


# ---------- система ----------

def default_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Programs" / APP_NAME


def installed_dir() -> Path | None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as k:
            return Path(winreg.QueryValueEx(k, "InstallLocation")[0])
    except OSError:
        return None


def start_menu_lnk() -> Path:
    return Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / f"{APP_NAME}.lnk"


def desktop_lnk() -> Path:
    return Path(QStandardPaths.writableLocation(QStandardPaths.DesktopLocation)) / f"{APP_NAME}.lnk"


def is_running(exe: Path) -> bool:
    """Запущенный EXE Windows не даёт открыть на запись."""
    try:
        with open(exe, "r+b"):
            return False
    except FileNotFoundError:
        return False
    except PermissionError:
        return True


def make_shortcut(target: Path, lnk: Path):
    from PySide6.QtCore import QFile
    lnk.parent.mkdir(parents=True, exist_ok=True)
    lnk.unlink(missing_ok=True)
    if not QFile.link(str(target), str(lnk)):  # в Windows QFile.link создаёт ярлык .lnk
        raise OSError(f"не удалось создать ярлык {lnk}")


def notify_shell():
    try:  # Проводник перечитывает иконки и связи файлов
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)
    except (AttributeError, OSError):
        pass


def _set(root_key: str, name: str, value, kind=winreg.REG_SZ):
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, root_key) as k:
        winreg.SetValueEx(k, name, 0, kind, value)


def _delete_tree(path: str):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_ALL_ACCESS) as k:
            while True:
                try:
                    sub = winreg.EnumKey(k, 0)
                except OSError:
                    break
                _delete_tree(rf"{path}\{sub}")
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
    except FileNotFoundError:
        pass


def register(dest: Path, size_kb: int, associate: bool):
    exe = dest / EXE
    for name, value in (("DisplayName", APP_NAME), ("DisplayVersion", VERSION), ("Publisher", APP_NAME),
                        ("DisplayIcon", f'"{exe}",0'), ("InstallLocation", str(dest)),
                        ("UninstallString", f'"{dest / UNINSTALL_EXE}"'),
                        ("QuietUninstallString", f'"{dest / UNINSTALL_EXE}"')):
        _set(UNINSTALL_KEY, name, value)
    for name in ("NoModify", "NoRepair"):
        _set(UNINSTALL_KEY, name, 1, winreg.REG_DWORD)
    _set(UNINSTALL_KEY, "EstimatedSize", size_kb, winreg.REG_DWORD)
    if associate:
        _set(rf"{CLASSES}\{FILE_EXT}", "", PROG_ID)
        _set(rf"{CLASSES}\{PROG_ID}", "", f"Тетрадь {APP_NAME}")
        _set(rf"{CLASSES}\{PROG_ID}\DefaultIcon", "", f'"{exe}",0')
        _set(rf"{CLASSES}\{PROG_ID}\shell\open\command", "", f'"{exe}" "%1"')
        _set(rf"{CLASSES}\{PACK_EXT}", "", PACK_ID)
        _set(rf"{CLASSES}\{PACK_ID}", "", f"Перенос {APP_NAME}")
        _set(rf"{CLASSES}\{PACK_ID}\DefaultIcon", "", f'"{exe}",0')
        _set(rf"{CLASSES}\{PACK_ID}\shell\open\command", "", f'"{exe}" "%1"')


def unregister():
    _delete_tree(UNINSTALL_KEY)
    for ext, pid in ((FILE_EXT, PROG_ID), (PACK_EXT, PACK_ID)):
        _delete_tree(rf"{CLASSES}\{pid}")
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"{CLASSES}\{ext}") as k:
                ours = winreg.QueryValueEx(k, "")[0] == pid
        except OSError:
            ours = False
        if ours:  # связь расширения удаляем, только если она наша
            _delete_tree(rf"{CLASSES}\{ext}")


def open_payload(path: str | None) -> zipfile.ZipFile | None:
    try:
        z = zipfile.ZipFile(path or sys.executable)
    except (OSError, zipfile.BadZipFile):
        return None
    return z if any(n.startswith("app/") for n in z.namelist()) else None


# ---------- работа в фоне ----------

class Installer(QThread):
    progress = Signal(float)
    failed = Signal(str)
    done = Signal()

    def __init__(self, payload: zipfile.ZipFile, dest: Path, desktop: bool, start_menu: bool, associate: bool,
                 wait_exit: bool = False):
        super().__init__()
        self.payload, self.dest = payload, dest
        self.desktop, self.start_menu, self.associate = desktop, start_menu, associate
        self.wait_exit = wait_exit  # обновление из программы: она закрывается сама, ждём

    def run(self):
        try:
            self._install()
        except Exception as e:  # покажем причину в окне, а не молча закроемся
            self.failed.emit(str(e))
        else:
            self.done.emit()

    def _install(self):
        dest = self.dest
        if self.wait_exit:
            for _ in range(120):
                if not is_running(dest / EXE):
                    break
                self.msleep(500)
            else:
                raise OSError(f"{APP_NAME} всё ещё открыта. Закройте её и запустите обновление ещё раз.")
        if dest.exists() and any(dest.iterdir()):
            if not (dest / MARKER).exists():
                raise OSError(f"Папка {dest} не пуста и не похожа на папку {APP_NAME}. Выберите другую.")
            for old in (dest / "_internal", dest / EXE, dest / UNINSTALL_EXE):  # старая версия
                if old.is_dir():
                    shutil.rmtree(old)
                else:
                    old.unlink(missing_ok=True)
        dest.mkdir(parents=True, exist_ok=True)
        (dest / MARKER).write_text(VERSION, encoding="utf-8")
        items = [i for i in self.payload.infolist() if i.filename.startswith("app/") and not i.is_dir()]
        total = sum(i.file_size for i in items) or 1
        written = 0
        for i in items:
            target = dest / i.filename[len("app/"):]
            target.parent.mkdir(parents=True, exist_ok=True)
            with self.payload.open(i) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out, 1 << 20)
            written += i.file_size
            self.progress.emit(0.95 * written / total)
        self._write_uninstaller(dest)
        if self.desktop:
            make_shortcut(dest / EXE, desktop_lnk())
        if self.start_menu:
            make_shortcut(dest / EXE, start_menu_lnk())
        register(dest, total // 1024, self.associate)
        notify_shell()
        self.progress.emit(1.0)


    def _write_uninstaller(self, dest: Path):
        """Uninstall.exe — это начало самого установщика (без приложенного архива): размер записан в архиве.
        Так в установщике нет второй копии той же оболочки (минус ~38 МБ)."""
        try:
            size = int(self.payload.read("stub_size"))
        except (KeyError, ValueError):
            return  # старый формат: Uninstall.exe лежит в архиве
        with open(sys.executable, "rb") as src, open(dest / UNINSTALL_EXE, "wb") as out:
            left = size
            while left:
                chunk = src.read(min(left, 1 << 20))
                if not chunk:
                    raise OSError("установщик повреждён: не хватает данных для Uninstall.exe")
                out.write(chunk)
                left -= len(chunk)


class Uninstaller(QThread):
    progress = Signal(float)
    failed = Signal(str)
    done = Signal()

    def __init__(self, dest: Path | None, remove_data: bool):
        super().__init__()
        self.dest, self.remove_data = dest, remove_data

    def run(self):
        try:
            if self.dest and (self.dest / MARKER).exists():
                files = [f for f in self.dest.rglob("*") if f.is_file() and f.name != MARKER]
                for n, f in enumerate(files):
                    try:
                        f.unlink(missing_ok=True)
                    except PermissionError:
                        pass  # занятый файл — скажем ниже
                    if n % 50 == 0:
                        self.progress.emit(0.9 * n / max(1, len(files)))
                shutil.rmtree(self.dest, ignore_errors=True)
                if self.dest.exists():  # метка осталась — можно повторить удаление позже
                    (self.dest / MARKER).write_text(VERSION, encoding="utf-8")
                    raise OSError(f"часть файлов занята. Закройте {APP_NAME} и попробуйте ещё раз.")
            for lnk in (desktop_lnk(), start_menu_lnk()):
                lnk.unlink(missing_ok=True)
            unregister()
            if self.remove_data:
                shutil.rmtree(data_dir(), ignore_errors=True)
            notify_shell()
            self.progress.emit(1.0)
        except Exception as e:
            self.failed.emit(str(e))
        else:
            self.done.emit()


# ---------- оформление ----------

class BrandPanel(QWidget):
    """Левая половина: фирменный градиент, тетрадная клетка, иконка, «пишущаяся» строка."""

    def __init__(self, line: str):
        super().__init__()
        self.setFixedWidth(300)
        self.line = line
        self.icon = QIcon(str(asset("brand", "icon.ico")))
        fid = QFontDatabase.addApplicationFont(str(asset("fonts", "caveat", "Caveat-Variable.ttf")))
        fams = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
        self.hand = QFont(fams[0] if fams else "Segoe Script")
        self.hand.setPixelSize(30)
        self.t = 0.0      # плавное покачивание иконки
        self.write = 0.0  # сколько строки уже «написано»
        self.bob = QVariantAnimation(self, startValue=0.0, endValue=1.0, duration=3200, loopCount=-1)
        self.bob.valueChanged.connect(self._tick)
        self.bob.start()
        self.pen = QVariantAnimation(self, startValue=0.0, endValue=1.0, duration=1600,
                                     easingCurve=QEasingCurve.InOutSine)
        self.pen.valueChanged.connect(lambda v: (setattr(self, "write", float(v)), self.update()))
        QTimer.singleShot(350, self.pen.start)

    def set_line(self, text: str):
        self.line = text
        self.pen.stop()
        self.write = 0.0
        self.pen.start()

    def _tick(self, v):
        self.t = float(v)
        self.update()

    def paintEvent(self, _):
        import math
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        g = QLinearGradient(0, 0, w, h)
        g.setColorAt(0, QColor("#3F63F2"))
        g.setColorAt(1, QColor("#6A3FD9"))
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, w + 30, h), 18, 18)  # скругление только снаружи
        p.setClipPath(path)
        p.fillRect(self.rect(), g)
        p.setPen(QPen(QColor(255, 255, 255, 22), 1))
        for x in range(0, w, 20):
            p.drawLine(x, 0, x, h)
        for y in range(0, h, 20):
            p.drawLine(0, y, w, y)
        p.setPen(QPen(QColor(255, 120, 120, 90), 1.5))
        p.drawLine(44, 0, 44, h)  # «поле» тетради
        dy = math.sin(self.t * 2 * math.pi) * 5
        size = 120
        p.drawPixmap(int((w - size) / 2), int(92 + dy), self.icon.pixmap(QSize(size, size), self.devicePixelRatioF()))
        p.setPen(QColor("white"))
        f = QFont(theme.FONT_FAMILY)
        f.setPixelSize(30)
        f.setWeight(QFont.Bold)
        p.setFont(f)
        p.drawText(QRectF(0, 236, w, 40), Qt.AlignCenter, APP_NAME)
        f.setPixelSize(13)
        f.setWeight(QFont.Normal)
        p.setFont(f)
        p.setPen(QColor(255, 255, 255, 200))
        p.drawText(QRectF(24, 276, w - 48, 40), Qt.AlignHCenter | Qt.TextWordWrap, TAGLINE)
        hp = QPainterPath()
        hp.addText(0, 0, self.hand, self.line)
        br = hp.boundingRect()
        hp.translate((w - br.width()) / 2 - br.left(), h - 64 - br.top())
        br = hp.boundingRect()
        reveal = br.left() + br.width() * self.write
        p.save()
        p.setClipRect(QRectF(0, 0, reveal, h))
        p.fillPath(hp, QColor(255, 255, 255, 235))
        p.restore()
        if 0 < self.write < 1:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#FFD25E"))
            p.drawEllipse(QPointF(reveal, br.bottom() - br.height() * 0.3), 3.5, 3.5)
        p.setPen(QColor(255, 255, 255, 140))
        f.setPixelSize(11)
        p.setFont(f)
        p.drawText(QRectF(0, h - 30, w, 20), Qt.AlignCenter, f"версия {VERSION}")


class CheckMark(QWidget):
    """Галочка, которая рисуется кругом и штрихом."""

    def __init__(self, color: str):
        super().__init__()
        self.setFixedSize(72, 72)
        self.color = color
        self.v = 0.0
        self.anim = QVariantAnimation(self, startValue=0.0, endValue=1.0, duration=700,
                                      easingCurve=QEasingCurve.OutCubic)
        self.anim.valueChanged.connect(lambda v: (setattr(self, "v", float(v)), self.update()))

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = QColor(self.color)
        p.setPen(QPen(c, 5, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(QRectF(6, 6, 60, 60), 90 * 16, int(-360 * 16 * min(1.0, self.v * 1.6)))
        t = max(0.0, (self.v - 0.45) / 0.55)
        if t > 0:
            path = QPainterPath(QPointF(22, 37))
            path.lineTo(32, 47)
            path.lineTo(51, 27)
            p.setPen(QPen(c, 6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.setClipRect(QRectF(0, 0, 22 + 30 * t, 72))
            p.drawPath(path)


def _label(text: str, role: str = "", wrap: bool = True) -> QLabel:
    lb = QLabel(text)
    if role:
        lb.setProperty("role", role)
    lb.setWordWrap(wrap)
    return lb


class SetupWindow(QWidget):
    def __init__(self, payload: zipfile.ZipFile | None, uninstall_dir: Path | None, update: bool = False):
        super().__init__()
        self.payload = payload
        self.update = update and payload is not None
        self.mode = "install" if payload else "uninstall"
        self.uninstall_dir = uninstall_dir
        self.worker = None
        self.setWindowTitle(f"Установка {APP_NAME}" if payload else f"Удаление {APP_NAME}")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(820, 520)
        self._drag = None

        self.card = QWidget(self)
        self.card.setObjectName("SetupCard")
        shadow = QGraphicsDropShadowEffect(self.card, blurRadius=40, offset=QPoint(0, 10))
        shadow.setColor(QColor(0, 0, 0, 70))
        self.card.setGraphicsEffect(shadow)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.addWidget(self.card)

        self.brand = BrandPanel("Пишет за вас — от руки" if payload else "До встречи!")
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(36, 18, 22, 28)
        top = QHBoxLayout()
        top.addStretch(1)
        self.close_btn = QPushButton()
        self.close_btn.setIcon(theme.icon("x", theme.current().text_muted, 18))
        self.close_btn.setProperty("kind", "ghost")
        self.close_btn.setFixedSize(34, 34)
        self.close_btn.setToolTip("Закрыть")
        self.close_btn.clicked.connect(self.close)
        top.addWidget(self.close_btn)
        rl.addLayout(top)
        self.stack = AnimatedStack()
        rl.addWidget(self.stack, 1)
        cl = QHBoxLayout(self.card)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(self.brand)
        cl.addWidget(right, 1)

        if payload:
            self.stack.addWidget(self._welcome_page())
        else:
            self.stack.addWidget(self._uninstall_page())
        self.stack.addWidget(self._progress_page())
        if self.update:  # из программы: сразу ставим, без вопросов
            QTimer.singleShot(450, self._start_update)
        self.stack.addWidget(self._done_page())
        self._restyle()

    def _restyle(self):
        p = theme.current()
        self.card.setStyleSheet(f"#SetupCard {{ background: {p.bg}; border-radius: 18px; }}")

    # --- страницы ---

    def _welcome_page(self) -> QWidget:
        w = QWidget()
        l = QVBoxLayout(w)
        l.setSpacing(10)
        l.addWidget(_label(f"Установка {APP_NAME}", "h1"))
        old = installed_dir()
        self.updating = bool(old and (old / EXE).exists())
        sub = (f"{APP_NAME} уже установлена — обновлю её до версии {VERSION}. "
               "Тетради и настройки останутся на месте."
               if self.updating else
               "Займёт меньше минуты. Потом программа откроется с ярлыка на рабочем столе.")
        l.addWidget(_label(sub, "muted"))
        l.addSpacing(14)
        l.addWidget(_label("Папка программы", wrap=False))
        row = QHBoxLayout()
        self.path = QLineEdit(str(old if self.updating else default_dir()))
        browse = QPushButton("Изменить…")
        browse.clicked.connect(self._browse)
        self.path.setCursorPosition(0)
        row.addWidget(self.path, 1)
        row.addWidget(browse)
        l.addLayout(row)
        l.addSpacing(8)
        self.desktop = QCheckBox("Ярлык на рабочем столе")
        self.start_menu = QCheckBox("Ярлык в меню «Пуск»")
        self.assoc = QCheckBox(f"Открывать тетради {FILE_EXT} двойным щелчком")
        for c in (self.desktop, self.start_menu, self.assoc):
            c.setChecked(True)
            l.addWidget(c)
        l.addStretch(1)
        self.error = _label("", "warn")
        self.error.hide()
        l.addWidget(self.error)
        nav = QHBoxLayout()
        nav.addWidget(_label(f"Нужно около {self._size_mb()} МБ", "muted", wrap=False))
        nav.addStretch(1)
        go = QPushButton("Обновить" if self.updating else "Установить")
        go.setProperty("kind", "primary")
        go.setIcon(theme.icon("download", theme.current().accent_text, 18))
        go.setMinimumWidth(150)
        go.clicked.connect(self._start_install)
        nav.addWidget(go)
        l.addLayout(nav)
        return w

    def _uninstall_page(self) -> QWidget:
        w = QWidget()
        l = QVBoxLayout(w)
        l.setSpacing(10)
        l.addWidget(_label(f"Удалить {APP_NAME}?", "h1"))
        l.addWidget(_label("Будут удалены программа, ярлыки и запись в «Установленных приложениях».", "muted"))
        l.addSpacing(10)
        docs = Path.home() / "Documents" / APP_NAME
        l.addWidget(_label(f"Ваши тетради в «{docs}» останутся на месте.", "muted"))
        l.addSpacing(6)
        self.remove_data = QCheckBox("Удалить также настройки, почерки и калибровку принтеров")
        l.addWidget(self.remove_data)
        l.addStretch(1)
        self.error = _label("", "warn")
        self.error.hide()
        l.addWidget(self.error)
        nav = QHBoxLayout()
        nav.addStretch(1)
        cancel = QPushButton("Оставить")
        cancel.clicked.connect(self.close)
        go = QPushButton("Удалить")
        go.setProperty("kind", "primary")
        go.setStyleSheet(f"background: {theme.current().danger}; color: white;")
        go.setIcon(theme.icon("trash-2", "#FFFFFF", 18))
        go.clicked.connect(self._start_uninstall)
        nav.addWidget(cancel)
        nav.addWidget(go)
        l.addLayout(nav)
        return w

    def _progress_page(self) -> QWidget:
        w = QWidget()
        l = QVBoxLayout(w)
        l.addStretch(1)
        self.p_title = _label("Устанавливаю…" if self.payload else "Удаляю…", "h1")
        l.addWidget(self.p_title)
        self.phrase = _label(PHRASES[0] if self.payload else "Убираю ярлыки и файлы…", "muted")
        l.addWidget(self.phrase)
        l.addSpacing(18)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(10)
        l.addWidget(self.bar)
        self.percent = _label("0%", "muted")
        l.addWidget(self.percent)
        l.addStretch(2)
        self._phrase_i = 0
        self.phrase_timer = QTimer(self, interval=1400)
        self.phrase_timer.timeout.connect(self._next_phrase)
        self.bar_anim = QVariantAnimation(self, duration=260, easingCurve=QEasingCurve.OutCubic)
        self.bar_anim.valueChanged.connect(lambda v: self.bar.setValue(int(v)))
        return w

    def _done_page(self) -> QWidget:
        w = QWidget()
        l = QVBoxLayout(w)
        l.addStretch(1)
        self.check = CheckMark(theme.current().success)
        l.addWidget(self.check)
        l.addSpacing(6)
        if self.payload:
            l.addWidget(_label("Готово!", "h1"))
            l.addWidget(_label(f"{APP_NAME} установлена. Ярлык ждёт на рабочем столе и в меню «Пуск».", "muted"))
            l.addSpacing(10)
            self.launch = QCheckBox(f"Запустить {APP_NAME}")
            self.launch.setChecked(True)
            l.addWidget(self.launch)
        else:
            l.addWidget(_label(f"{APP_NAME} удалена", "h1"))
            l.addWidget(_label("Спасибо, что пользовались! Тетради остались в папке «Документы».", "muted"))
        l.addStretch(2)
        nav = QHBoxLayout()
        nav.addStretch(1)
        fin = QPushButton("Готово")
        fin.setProperty("kind", "primary")
        fin.setMinimumWidth(150)
        fin.clicked.connect(self._finish)
        nav.addWidget(fin)
        l.addLayout(nav)
        return w

    # --- действия ---

    def _size_mb(self) -> int:
        total = sum(i.file_size for i in self.payload.infolist()) if self.payload else 0
        return max(1, round(total / 1e6 / 10) * 10)

    def _target(self) -> Path:
        d = Path(self.path.text().strip().strip('"'))
        return d if d.name.lower() == APP_NAME.lower() else d / APP_NAME  # всегда своя папка

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Куда установить", str(self._target().parent))
        if d:
            self.path.setText(str(Path(d) / APP_NAME))

    def _show_error(self, text: str):
        self.error.setText(text)
        self.error.show()
        fade_in(self.error, rise=6)

    def _start_install(self):
        dest = self._target()
        if is_running(dest / EXE):
            self._show_error(f"{APP_NAME} сейчас открыта. Закройте её и нажмите ещё раз.")
            return
        self.worker = Installer(self.payload, dest, self.desktop.isChecked(), self.start_menu.isChecked(),
                                self.assoc.isChecked())
        self.dest = dest
        self._run_worker()
        self.phrase_timer.start()

    def _start_update(self):
        dest = installed_dir() or default_dir()
        self.p_title.setText("Обновляю…")
        self.worker = Installer(self.payload, dest, desktop_lnk().exists(), start_menu_lnk().exists(), True,
                                wait_exit=True)
        self.dest = dest
        self._run_worker()
        self.phrase_timer.start()

    def _start_uninstall(self):
        if self.uninstall_dir and is_running(self.uninstall_dir / EXE):
            self._show_error(f"{APP_NAME} сейчас открыта. Закройте её и нажмите ещё раз.")
            return
        self.worker = Uninstaller(self.uninstall_dir, self.remove_data.isChecked())
        self._run_worker()

    def _run_worker(self):
        self.close_btn.setEnabled(False)
        self.worker.progress.connect(self._progress)
        self.worker.failed.connect(self._failed)
        self.worker.done.connect(self._done)
        self.stack.go(1)
        self.worker.start()

    def _progress(self, v: float):
        self.bar_anim.stop()
        self.bar_anim.setStartValue(self.bar.value())
        self.bar_anim.setEndValue(int(v * 1000))
        self.bar_anim.start()
        self.percent.setText(f"{v:.0%}")

    def _next_phrase(self):
        self._phrase_i = (self._phrase_i + 1) % len(PHRASES)
        self.phrase.setText(PHRASES[self._phrase_i])
        fade_in(self.phrase, rise=4)

    def _failed(self, msg: str):
        self.phrase_timer.stop()
        self.close_btn.setEnabled(True)
        self.stack.go(0)
        self._show_error(f"Не получилось: {msg}")

    def _done(self):
        self.phrase_timer.stop()
        self.close_btn.setEnabled(True)
        self.stack.go(2)
        self.brand.set_line("Можно писать!" if self.payload else "До встречи!")
        QTimer.singleShot(150, self.check.anim.start)
        if self.update:  # обновили — открываем программу снова
            self.launch.setChecked(True)
            QTimer.singleShot(1600, self._finish)

    def _finish(self):
        if self.payload and self.launch.isChecked():
            subprocess.Popen([str(self.dest / EXE)], cwd=str(self.dest), close_fds=True,
                             creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
        self.close()

    def closeEvent(self, e):
        if self.worker is not None and self.worker.isRunning():
            e.ignore()  # прерванная установка оставила бы полпрограммы
            return
        super().closeEvent(e)

    # перетаскивание окна без рамки
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag is not None and e.buttons() & Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e):
        self._drag = None


def _relaunch_from_temp(dest: Path, args: list[str]) -> bool:
    """Удалитель лежит в папке программы и держит её. Копируемся во временную папку и удаляем оттуда."""
    if not getattr(sys, "frozen", False):
        return False
    me = Path(sys.executable).resolve()
    if dest is None or dest.resolve() not in me.parents:
        return False
    tmp = Path(tempfile.gettempdir()) / f"{APP_NAME}-uninstall.exe"
    shutil.copy2(me, tmp)
    extra = [a for a in args if a in ("--silent", "--remove-data")]
    subprocess.Popen([str(tmp), "--uninstall", str(dest), *extra], close_fds=True,
                     creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
    return True


def silent(payload, args, uninstall_dir) -> int:
    """Без окна, со всеми галочками по умолчанию — для проверки в песочнице.
    Установка: Setup.exe --silent [--dir папка]; удаление: Uninstall.exe --uninstall папка --silent."""
    from PySide6.QtCore import QCoreApplication
    QCoreApplication.instance() or QCoreApplication(sys.argv[:1])
    if payload is not None:
        dest = Path(args[args.index("--dir") + 1]) if "--dir" in args else (installed_dir() or default_dir())
        worker = Installer(payload, dest, True, True, True)
    else:
        worker = Uninstaller(uninstall_dir, "--remove-data" in args)
    errors = []
    worker.failed.connect(errors.append)
    worker.run()  # в этом же потоке
    if errors:
        print(errors[0], file=sys.stderr)
    return 1 if errors else 0


def main():
    args = sys.argv[1:]
    payload_path = args[args.index("--payload") + 1] if "--payload" in args else None
    payload = None if "--uninstall" in args else open_payload(payload_path)
    uninstall_dir = None
    if payload is None:
        i = args.index("--uninstall") if "--uninstall" in args else -1
        given = Path(args[i + 1]) if 0 <= i < len(args) - 1 else None
        uninstall_dir = given or installed_dir() or (Path(sys.executable).parent if getattr(sys, "frozen", False)
                                                     else None)
        if _relaunch_from_temp(uninstall_dir, args):  # копия во временной папке сама не перезапускается
            return 0
    if "--silent" in args:
        return silent(payload, args, uninstall_dir)
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"{APP_NAME}.Setup")
    except (AttributeError, OSError):
        pass
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setWindowIcon(QIcon(str(asset("brand", "icon.ico"))))
    theme.load_font()
    theme.apply(app, "Как в Windows")
    w = SetupWindow(payload, uninstall_dir, update="--update" in args)
    w.setWindowOpacity(0.0)
    w.show()
    appear = _anim(w, b"windowOpacity", 0.0, 1.0, 260)  # окно мягко проявляется
    appear.start()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
