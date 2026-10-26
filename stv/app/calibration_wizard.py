"""Мастер калибровки прямой печати.

Основной путь — по фото: напечатать лист с линиями → сфотографировать (или отсканировать) → программа сама
сравнивает чёрную печать с синей клеткой и считает поправки до десятых миллиметра, включая «растяжение».
Запасной путь — вручную, как у Cricut «Print Then Cut»: «какая риска легла на линию?» → номер 1–9.
В обоих случаях знак и миллиметры считает программа: люди часто сдвигают в обратную сторону.
"""

import re
import tempfile
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, QThread, Signal
from PySide6.QtGui import QColor, QFont, QImage, QKeySequence, QPainter, QPainterPath, QPen, QPixmap, QShortcut
from PySide6.QtWidgets import (QApplication, QButtonGroup, QDialog, QDoubleSpinBox, QFileDialog, QHBoxLayout, QLabel,
                               QMessageBox, QPushButton, QVBoxLayout, QWidget)

from ..engine import printers
from ..engine.calibration import BRACKET_MM, STEPS, check_lines, photo_lines, solve_shift, tick_label
from ..engine.paper import Side
from ..engine.settings import PageSettings, PrinterOffset
from .ui import theme
from .ui.motion import AnimatedStack, fade_in

EXAMPLE = 5  # на картинке-примере совпала риска № 6 (индекс 5)


class ScalePicture(QWidget):
    """Увеличенный кусочек шкалы: синие линии клетки, чёрные риски, совпавшая обведена."""

    def __init__(self, axis: str):
        super().__init__()
        self.axis = axis  # "x" — шкала А, "y" — шкала Б
        self.setMinimumHeight(150 if axis == "x" else 200)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pal = theme.current()
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(QPen(QColor(pal.border), 1))
        p.setBrush(QColor("#FFFFFF"))
        p.drawRoundedRect(r, 14, 14)
        grid, ink = QColor("#8FB0E0"), QColor("#1F1E1C")
        f = QFont(theme.FONT_FAMILY)
        f.setPixelSize(13)
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        k = 7.0  # пикселей на мм сдвига: на картинке сдвиги преувеличены, чтобы разница была видна
        if self.axis == "x":
            n = len(STEPS)
            step = (r.width() - 40) / n
            y0, y1 = r.top() + 34, r.bottom() - 40
            for i, v in enumerate(STEPS):
                gx = r.left() + 20 + step * (i + 0.5)  # линия клетки, к которой привязана риска
                p.setPen(QPen(grid, 1.4))
                p.drawLine(QPointF(gx, r.top() + 10), QPointF(gx, r.bottom() - 10))
                x = gx + (v - STEPS[EXAMPLE]) * k
                p.setPen(QPen(ink, 2.4))
                p.drawLine(QPointF(x, y0), QPointF(x, y1))
                p.drawText(QRectF(x - 15, y1 + 6, 30, 20), Qt.AlignCenter, tick_label(i))
            ex = r.left() + 20 + step * (EXAMPLE + 0.5)
            self._ring(p, QRectF(ex - 18, y0 - 10, 36, y1 - y0 + 40), pal.accent)
        else:
            n = 5
            first = EXAMPLE - 2
            step = (r.height() - 30) / n
            x0 = r.center().x() - 60
            for i in range(n):
                j = first + i
                y_line = r.top() + 15 + step * i + step / 2
                p.setPen(QPen(grid, 1.4))
                p.drawLine(QPointF(r.left() + 10, y_line), QPointF(r.right() - 10, y_line))
                y = y_line + (STEPS[j] - STEPS[EXAMPLE]) * k
                p.setPen(QPen(ink, 2.4))
                p.drawLine(QPointF(x0, y), QPointF(x0 + 80, y))
                p.drawText(QRectF(x0 + 88, y - 10, 30, 20), Qt.AlignVCenter | Qt.AlignLeft, tick_label(j))
                if j == EXAMPLE:
                    self._ring(p, QRectF(x0 - 12, y - 16, 136, 32), pal.accent)
        p.setPen(QColor(pal.accent))
        p.drawText(r.adjusted(14, 8, -14, -8), Qt.AlignRight | Qt.AlignTop, f"пример: ответ «{tick_label(EXAMPLE)}»")

    @staticmethod
    def _ring(p: QPainter, rect: QRectF, color: str):
        p.setPen(QPen(QColor(color), 2.5))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(rect, 12, 12)


class SheetPicture(QWidget):
    """Лист из блока с отверстиями слева (лицевая) или справа (оборот) и стрелка в принтер."""

    def __init__(self, holes_left: bool, flip: bool = False):
        super().__init__()
        self.holes_left, self.flip = holes_left, flip
        self.setMinimumHeight(170)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pal = theme.current()
        h = self.height() - 20
        w = h * 0.72
        x = (self.width() - w) / 2
        sheet = QRectF(x, 10, w, h)
        p.setPen(QPen(QColor(pal.border_strong), 1.2))
        p.setBrush(QColor("#FFFFFF"))
        p.drawRoundedRect(sheet, 6, 6)
        p.setPen(QPen(QColor("#C9D7F2"), 1))
        for i in range(1, 14):
            y = sheet.top() + i * h / 14
            p.drawLine(QPointF(sheet.left() + 2, y), QPointF(sheet.right() - 2, y))
        for i in range(1, 10):
            x = sheet.left() + i * w / 10
            p.drawLine(QPointF(x, sheet.top() + 2), QPointF(x, sheet.bottom() - 2))
        hx = sheet.left() + 11 if self.holes_left else sheet.right() - 11
        p.setPen(QPen(QColor(pal.border_strong), 1.2))
        p.setBrush(QColor(pal.bg))
        for k in range(4):
            p.drawEllipse(QPointF(hx, sheet.top() + h * (0.15 + 0.23 * k)), 5, 5)
        p.setPen(QPen(QColor(pal.accent), 3, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        if self.flip:  # перевернуть, как страницу книги
            path = QPainterPath(QPointF(sheet.right() + 16, sheet.center().y() + 20))
            path.cubicTo(sheet.right() + 60, sheet.center().y() - 40, sheet.left() - 60, sheet.center().y() - 40,
                         sheet.left() - 16, sheet.center().y() + 20)
            p.drawPath(path)
            tip = QPointF(sheet.left() - 16, sheet.center().y() + 20)
            p.drawLine(tip, tip + QPointF(-2, -14))
            p.drawLine(tip, tip + QPointF(12, -6))
        else:  # верхом в принтер
            cx = sheet.center().x()
            p.drawLine(QPointF(cx, sheet.top() + 30), QPointF(cx, sheet.top() - 4))
            p.drawLine(QPointF(cx, sheet.top() - 4), QPointF(cx - 9, sheet.top() + 6))
            p.drawLine(QPointF(cx, sheet.top() - 4), QPointF(cx + 9, sheet.top() + 6))


def _label(text: str, role: str = "") -> QLabel:
    lb = QLabel(text)
    lb.setWordWrap(True)
    if role:
        lb.setProperty("role", role)
    return lb


class Question(QWidget):
    """«Какая риска легла на линию?» — девять кнопок и запасной путь с линейкой."""

    def __init__(self, title: str, text: str, axis: str, edge: str, on_answer):
        super().__init__()
        self.answer: float | None = None
        self.on_answer = on_answer
        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        lay.addWidget(_label(title, "h2"))
        lay.addWidget(_label(text, "muted"))
        lay.addWidget(ScalePicture(axis))
        row = QHBoxLayout()
        row.setSpacing(6)
        self.group = QButtonGroup(self)
        for i in range(len(STEPS)):
            b = QPushButton(tick_label(i))
            b.setCheckable(True)
            b.setProperty("kind", "chip")
            b.setFixedSize(52, 44)
            b.setStyleSheet("font-size: 13pt; font-weight: 600;")
            self.group.addButton(b, i)
            row.addWidget(b)
        row.addStretch(1)
        self.group.idClicked.connect(self._picked)
        lay.addLayout(row)
        self.more = QPushButton("Ни одна не совпала или лист сильно уехал")
        self.more.setProperty("kind", "ghost")
        self.more.clicked.connect(self._show_ruler)
        lay.addWidget(self.more, 0, Qt.AlignLeft)
        self.ruler_box = QWidget()
        rl = QHBoxLayout(self.ruler_box)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(_label(f"Линейкой: от {edge} края листа до уголка «⌐» в углу (должно быть "
                            f"{BRACKET_MM:.0f} мм)"), 1)
        self.ruler = QDoubleSpinBox()
        self.ruler.setRange(0, 40)
        self.ruler.setDecimals(1)
        self.ruler.setSingleStep(0.5)
        self.ruler.setSuffix(" мм")
        self.ruler.setValue(BRACKET_MM)
        self.ruler.valueChanged.connect(lambda _: self._emit())
        rl.addWidget(self.ruler)
        self.ruler_box.hide()
        lay.addWidget(self.ruler_box)
        lay.addStretch(1)

    def _picked(self, i: int):
        self._emit()

    def _show_ruler(self):
        self.ruler_box.show()
        fade_in(self.ruler_box, rise=6)
        self._emit()

    def _emit(self):
        i = self.group.checkedId()
        vernier = STEPS[i] if i >= 0 else None
        measured = self.ruler.value() if self.ruler_box.isVisible() else None
        self.answer = solve_shift(measured, vernier)
        self.on_answer()


class _Measure(QThread):
    """Распознавание фото в фоне: большой снимок обрабатывается секунду-две, окно не должно замирать."""
    done = Signal(object)
    failed = Signal(str)
    wrong_side = Signal(str)

    def __init__(self, path: str, ps: PageSettings, side: Side, check: bool):
        super().__init__()
        self.path, self.ps, self.side, self.check = path, ps, side, check

    def run(self):
        from ..calib_photo import PhotoError, WrongSide, measure
        xs, ys = (check_lines if self.check else photo_lines)(self.ps.paper, self.side)
        try:
            self.done.emit(measure(self.path, self.ps.paper, self.side, self.ps.offset(self.side), xs, ys))
        except WrongSide as e:
            self.wrong_side.emit(str(e))
        except PhotoError as e:
            self.failed.emit(str(e))
        except Exception as e:  # неожиданное — тоже показать, а не упасть
            self.failed.emit(f"Не удалось обработать фото: {e}")


def _save_temp(img: QImage) -> str:
    f = Path(tempfile.gettempdir()) / "konspektai_calibration_photo.png"
    img.save(str(f))
    return str(f)


class DropArea(QLabel):
    """Поле «перетащите фото сюда или нажмите»."""
    picked = Signal(str)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setAlignment(Qt.AlignCenter)
        self.setWordWrap(True)
        self.setMinimumHeight(120)
        self.setCursor(Qt.PointingHandCursor)
        self.setText("Перетащите фото сюда или нажмите, чтобы выбрать файл.\n"
                     "Если фото скопировано — просто нажмите Ctrl+V.")
        p = theme.current()
        self.setStyleSheet(f"QLabel {{ border: 2px dashed {p.border_strong}; border-radius: 16px;"
                           f" color: {p.text_muted}; background: {p.surface}; padding: 14px; }}"
                           f" QLabel:hover {{ border-color: {p.accent}; color: {p.text}; }}")

    def mousePressEvent(self, e):
        path, _ = QFileDialog.getOpenFileName(self, "Фото или скан листа", str(Path.home()),
                                              "Изображения (*.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff)")
        if path:
            self.picked.emit(path)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() or e.mimeData().hasImage():
            e.acceptProposedAction()

    def dropEvent(self, e):
        md = e.mimeData()
        if md.hasUrls() and md.urls()[0].isLocalFile():
            self.picked.emit(md.urls()[0].toLocalFile())
        elif md.hasImage():
            self.picked.emit(_save_temp(QImage(md.imageData())))  # перетащили картинку из браузера


def _mm(v: float) -> str:
    return f"{abs(v):.1f}".replace(".", ",")


def _miss_words(sx: float, sy: float) -> str:
    """Куда печать уходит сейчас (до исправления)."""
    parts = []
    if abs(sx) >= 0.1:
        parts.append(f"на {_mm(sx)} мм {'вправо' if sx > 0 else 'влево'}")
    if abs(sy) >= 0.1:
        parts.append(f"на {_mm(sy)} мм {'вниз' if sy > 0 else 'вверх'}")
    if not parts:
        return "Печать уже ложится точно на клетку."
    return "Сейчас печать уходит " + " и ".join(parts) + " — исправлю."


def _scale_words(o: PrinterOffset) -> str:
    notes = []
    for v, axis in ((o.sx, "по ширине"), (o.sy, "по высоте")):
        if abs(v - 1) > 1e-6:
            notes.append(f"{axis} {'мельче' if v < 1 else 'крупнее'} на {abs(v - 1) * 100:.1f}%".replace(".", ","))
    return ("<br>Клетка блока " + " и ".join(notes) + ", чем 5 мм, — учту, чтобы строки не съезжали к низу листа."
            if notes else "")


def _skew_words(res) -> str:
    from ..calib_photo import SKEW_WARN_MM
    if max(res.x.skew, res.y.skew) < SKEW_WARN_MM:
        return ""
    return ("<br>Лист прошёл через принтер немного наискосок. Перед печатью конспектов придвиньте "
            "направляющие лотка вплотную к листу.")


def _fix_words(dx: float, dy: float) -> str:
    if abs(dx) < 0.05 and abs(dy) < 0.05:
        return "всё и так было ровно"
    parts = []
    if abs(dx) >= 0.05:
        parts.append(f"на {_mm(dx)} мм {'правее' if dx > 0 else 'левее'}")
    if abs(dy) >= 0.05:
        parts.append(f"на {_mm(dy)} мм {'ниже' if dy > 0 else 'выше'}")
    return "печать пойдёт " + " и ".join(parts)


MAX_CHECKS = 2      # после второй проверки небольшой остаток доводим без третьего листа
BIG_SHIFT_MM = 8.0  # печать ушла дальше — лист, скорее всего, лежал в лотке не вплотную к направляющим
SIDES_APART_MM = 6.0  # лицевая и оборот ушли вбок по-разному — лист ложится в лоток каждый раз иначе


def _miss(res) -> float:
    return max(abs(res.x.shift_mm), abs(res.y.shift_mm))


def _plain(html: str) -> str:
    """Текст для телефона: без разметки."""
    return re.sub(r"\s+", " ", re.sub(r"<br\s*/?>", " ", re.sub(r"<(?!br)[^>]+>", "", html))).strip()


def holes_word(profile: printers.PrinterProfile, front: bool) -> str:
    """«влево» или «вправо»: как класть лист в лоток этого принтера для лицевой (front) или оборота."""
    return "влево" if profile.holes_left(front) else "вправо"


GUIDES = ("<b>Придвиньте направляющие лотка вплотную к листу</b> — иначе узкий лист ложится то левее, то правее, "
          "и строки уезжают.")


def flip_note(profile: printers.PrinterProfile) -> str:
    if not profile.flip_feed:
        return ""
    return ("<br><span style='color:%s'>Этот принтер печатает на обратной стороне листа, поэтому отверстия — "
            "в другую сторону. Программа узнала это по фото.</span>" % theme.current().text_muted)


class PhotoStep(QWidget):
    """«Сфотографируйте лист» → распознавание → короткий итог и картинка того, что нашлось.

    Фото — с компьютера (файл, перетаскивание, Ctrl+V) или с телефона по QR-коду: код показан сразу, рядом.
    Что происходит, видно и на телефоне: распознаю → «Дальше» или «Переснять»."""

    def __init__(self, side: Side, page_settings, on_change, check: bool = False, phone=None):
        super().__init__()
        self.side, self.page_settings, self.on_change, self.check = side, page_settings, on_change, check
        self.result = None
        self.worker = None
        self.on_wrong_side = None  # мастер подскажет, как положить лист, и запомнит это для принтера
        name = "лицевую сторону" if side is Side.FRONT else "оборот"
        holes = "отверстиями влево" if side is Side.FRONT else "отверстиями вправо"
        self.phone_title = f"Сфотографируйте {'проверку: ' if check else ''}{name}"
        self.phone_hint = (f"Положите лист на тёмный стол {holes}, напечатанной стороной вверх, и снимите сверху "
                           "так, чтобы были видны все 4 угла.")
        self.phone_stage, self.phone_msg = "wait", ""
        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        lay.addWidget(_label(self.phone_title, "h2"))
        lay.addWidget(_label(
            f"• Положите лист на <b>тёмный</b> стол {holes}, напечатанной стороной вверх.<br>"
            "• Снимите <b>сверху</b>, чтобы были видны все 4 угла листа. Свет ровный, без вспышки.<br>"
            "• Или отсканируйте лист <b>с открытой крышкой</b> сканера.", "muted"))
        # раскладки сначала прикрепляем к странице, потом кладём в них виджеты: иначе PySide считает виджет
        # своим, Qt удаляет его вместе со страницей, и при выходе из программы он удаляется второй раз
        row = QHBoxLayout()
        row.setSpacing(14)
        lay.addLayout(row)
        pc = QVBoxLayout()
        pc.setSpacing(6)
        row.addLayout(pc, 1)
        self.drop = DropArea()
        self.drop.picked.connect(lambda path: self.analyze(path))
        pc.addWidget(_label("<b>С компьютера</b>"))
        pc.addWidget(self.drop, 1)
        if phone is not None:
            row.addWidget(self._qr_box(phone))
        row = QHBoxLayout()
        lay.addLayout(row)
        self.preview = QLabel()
        self.preview.setFixedSize(110, 150)
        self.preview.hide()
        self.status = _label("")
        row.addWidget(self.preview)
        row.addWidget(self.status, 1)
        lay.addStretch(1)
        QShortcut(QKeySequence.Paste, self, activated=self._paste)

    @staticmethod
    def _qr_box(phone) -> QWidget:
        box = QWidget()
        box.setFixedWidth(230)
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        v.addWidget(_label("<b>С телефона</b>"))
        if phone.error:
            v.addWidget(_label(f"QR-код недоступен: {phone.error}", "muted"))
        else:
            qr = QLabel()
            qr.setPixmap(phone.qr())
            qr.setAlignment(Qt.AlignCenter)
            qr.setStyleSheet("background: white; border-radius: 12px; padding: 6px;")
            v.addWidget(qr, 0, Qt.AlignLeft)
            v.addWidget(_label("Наведите камеру телефона на код — фото придёт сюда. Код один на всю калибровку. "
                               "Телефон и компьютер — в одной сети Wi-Fi. Если Windows спросит про доступ к сети, "
                               "нажмите «Разрешить».", "muted"))
        v.addStretch(1)
        return box

    def _paste(self):
        img = QApplication.clipboard().image()
        if not img.isNull():
            self.analyze(_save_temp(img), "фото из буфера обмена")
            return
        urls = QApplication.clipboard().mimeData().urls()
        if urls and urls[0].isLocalFile():
            self.analyze(urls[0].toLocalFile())
        else:
            self._failed("В буфере обмена нет фото. Скопируйте фото ещё раз или выберите файл.")

    def analyze(self, path: str, name: str | None = None):
        if self.worker is not None and self.worker.isRunning():
            return
        self.result = None
        # сразу показать, что фото принято: миниатюра и имя файла
        pm = QPixmap(path)
        if not pm.isNull():
            self.preview.setPixmap(pm.scaled(self.preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.preview.show()
        self.drop.setText(f"Добавлено: {name or Path(path).name}\nНажмите, чтобы выбрать другое фото.")
        self.status.setText("Распознаю лист и линии…")
        self.phone_stage, self.phone_msg = "busy", "Фото получено, распознаю…"
        self.on_change()
        self.worker = _Measure(path, self.page_settings(), self.side, self.check)
        self.worker.done.connect(self._done)
        self.worker.failed.connect(self._failed)
        self.worker.wrong_side.connect(self._wrong_side)
        self.worker.start()

    def _failed(self, msg: str):
        self.status.setText(f"<span style='color:{theme.current().danger}'>{msg}</span>")
        self.phone_stage, self.phone_msg = "error", _plain(msg)
        self.on_change()

    def _wrong_side(self, msg: str):
        self._failed(msg + (" " + self.on_wrong_side(self) if self.on_wrong_side else ""))

    def _done(self, res):
        self.result = res
        rgb = res.debug[:, :, ::-1].copy()
        img = QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0], QImage.Format_RGB888)
        self.preview.setPixmap(QPixmap.fromImage(img.copy()).scaled(self.preview.size(), Qt.KeepAspectRatio,
                                                                    Qt.SmoothTransformation))
        self.preview.show()
        p = theme.current()
        if self.check:
            m = _miss(res)
            verdict = (f"<b style='color:{p.success}'>✓ Отлично: расхождение {_mm(m)} мм</b>"
                       if m <= printers.CHECK_OK_MM
                       else f"<b style='color:{p.warning}'>Расхождение {_mm(m)} мм — уточню поправки</b>")
            text = verdict + _skew_words(res)
        else:
            text = (f"<b style='color:{p.success}'>✓ Лист распознан</b> (линий: {res.x.lines} и {res.y.lines}).<br>"
                    f"{_miss_words(res.x.shift_mm, res.y.shift_mm)}" + _skew_words(res))
        self.status.setText(text)
        fade_in(self.status, rise=6)
        self.phone_stage, self.phone_msg = "ok", _plain(text) + " Нажмите «Дальше» — здесь или на компьютере."
        self.on_change()


class CalibrationWizard(QDialog):
    """Калибровка прямой печати выбранного принтера на листе из блока.

    Калибровка: лист с линиями → фото обеих сторон → поправки сохранены. Проверка (по желанию, но мастер
    её предлагает): новый лист с сеткой по клетке → фото обеих сторон → «всё точно» или поправки уточняются
    и можно проверить ещё раз. Точность проверки записывается в профиль принтера.
    verify=True — сразу к проверке: принтер уже откалиброван, проверку отложили или она не прошла."""

    def __init__(self, printer_name: str, parent=None, verify: bool = False):
        super().__init__(parent)
        self.setWindowTitle(f"{'Проверка' if verify else 'Калибровка'}: {printer_name}")
        self.resize(820, 700)
        self.printer = printer_name
        self.profiles = printers.load()
        self.profile = self.profiles.setdefault(printer_name, printers.PrinterProfile(printer_name))
        method = printers.DIRECT
        if not self.profile.direct_calibrated and self.profile.calibrated:
            method = printers.PDF  # стартуем с поправок печати через PDF: подача та же, обычно близко
        self.front, self.back = self.profile.offsets(method)
        self.saved = False
        self.mode = None
        self.qs: dict[str, Question] = {}
        self.photos: dict[Side, PhotoStep] = {}
        self.checks: dict[Side, PhotoStep] = {}
        self.verify_from = None  # с какой страницы начинается проверка
        self.checks_done = 0
        self.verdict_page = None
        self.phone = None  # телефон по QR-коду: один на весь мастер
        self.load_views = []  # подсказки «как положить лист» — меняются, если принтер печатает на обороте

        self.stack = AnimatedStack()
        self.pages: list[QWidget] = [self._choose_page()]
        self.stack.addWidget(self.pages[0])
        self.result_page = self._result_page()
        self.step = QLabel()
        self.step.setProperty("role", "muted")
        self.back_btn = QPushButton("Назад")
        self.back_btn.setProperty("kind", "ghost")
        self.next_btn = QPushButton("Дальше")
        self.next_btn.setProperty("kind", "primary")
        self.next_btn.setMinimumWidth(130)
        self.back_btn.clicked.connect(lambda: self._go(self.stack.currentIndex() - 1))
        self.next_btn.clicked.connect(self._next)
        nav = QHBoxLayout()
        nav.addWidget(self.back_btn)
        nav.addWidget(self.step)
        nav.addStretch(1)
        nav.addWidget(self.next_btn)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 20)
        lay.addWidget(self.stack, 1)
        lay.addLayout(nav)
        if verify:
            self.mode = "photo"
            self.saved = True
            self._start_verify()
        else:
            self._go(0)

    # --- страницы ---

    def _choose_page(self) -> QWidget:
        from .onboarding import OptionCard
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(12)
        lay.addWidget(_label("Калибровка принтера", "h1"))
        lay.addWidget(_label("Один раз подстроим печать под ваш принтер, чтобы строки ложились точно в клетку. "
                             "Понадобится один лист из блока и ещё один — на проверку.", "muted"))
        lay.addSpacing(8)
        for key, icon, title, sub in (
                ("photo", "file-image", "По фото — точнее всего (рекомендуем)",
                 "Напечатаете лист, сфотографируете телефоном по QR-коду или отсканируете — программа всё "
                 "измерит сама до десятых миллиметра."),
                ("manual", "sliders-horizontal", "Вручную, без фото",
                 "Посмотрите на шкалы на листе и нажмёте номера рисок. Быстро, но на глаз легко ошибиться.")):
            card = OptionCard(key, icon, title, sub)
            card.clicked.connect(self._start)
            lay.addWidget(card)
        lay.addStretch(1)
        return w

    def _phone_link(self):
        if self.phone is None:
            from .phone_dialog import PhoneLink
            self.phone = PhoneLink(f"Калибровка: {self.printer}", "", self)
            self.phone.photo.connect(self._phone_photo)
            self.phone.next.connect(self._phone_next)
        return self.phone

    def _photo_step(self, side: Side, check: bool) -> PhotoStep:
        step = PhotoStep(side, self._page, self._sync, check=check, phone=self._phone_link())
        step.on_wrong_side = self._wrong_side
        return step

    def _front_text(self, what: str, extra: str = "") -> str:
        return (f"Положите в лоток {what} из блока <b>отверстиями {holes_word(self.profile, True)}</b>, верхом в "
                f"принтер{extra}. {GUIDES}{flip_note(self.profile)}")

    def _back_text(self) -> str:
        return ("Возьмите этот же лист и переверните его <b>как страницу книги</b>: отверстия теперь "
                f"<b>{'слева' if self.profile.holes_left(False) else 'справа'}</b>, верх остаётся верхом. "
                "Положите в лоток так же и придвиньте направляющие.")

    def _start(self, mode: str):
        self.mode = mode
        self.verify_from, self.checks_done, self.load_views = None, 0, []
        self._truncate(1)
        front = self._print_page(
            "Лицевая сторона", lambda: self._front_text("<b>один</b> лист", " — так же, как будете печатать конспекты"),
            True, "Напечатать лицевую", Side.FRONT)
        back = self._print_page("Оборот", self._back_text, False, "Напечатать оборот", Side.BACK)
        if mode == "photo":
            self.photos = {s: self._photo_step(s, False) for s in (Side.FRONT, Side.BACK)}
            middle_f, middle_b = [self.photos[Side.FRONT]], [self.photos[Side.BACK]]
        else:
            self.qs = {
                "fx": Question("Шкала А на лицевой стороне",
                               "Посмотрите на ряд вертикальных рисок «А». Какая из них легла точно на синюю линию "
                               "клетки? Если ровно ни одна — выберите ту, что ближе всех.", "x", "левого", self._sync),
                "fy": Question("Шкала Б на лицевой стороне",
                               "Теперь столбик горизонтальных рисок «Б». Какая легла точно на синюю линию?",
                               "y", "верхнего", self._sync),
                "bx": Question("Шкала А на обороте",
                               "То же самое на обороте: какая риска «А» легла на синюю линию?", "x", "левого",
                               self._sync),
                "by": Question("Шкала Б на обороте", "И последняя: какая риска «Б» легла на синюю линию?",
                               "y", "верхнего", self._sync),
            }
            middle_f, middle_b = [self.qs["fx"], self.qs["fy"]], [self.qs["bx"], self.qs["by"]]
        self.saved = False
        self._append([front, *middle_f, back, *middle_b, self.result_page])
        self._go(1)

    def _truncate(self, n: int):
        """Оставить первые n страниц (смена способа или повторная проверка — страницы заново)."""
        while self.stack.count() > n:
            self.stack.removeWidget(self.stack.widget(n))
        self.pages = self.pages[:n]

    def _append(self, pages: list[QWidget]):
        for w in pages:
            self.pages.append(w)
            self.stack.addWidget(w)

    def _print_page(self, title: str, html, front: bool, button: str, side: Side, check: bool = False) -> QWidget:
        """html — функция: текст подсказки зависит от того, какой стороной этот принтер печатает."""
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(12)
        lay.addWidget(_label(title, "h2"))
        text = _label(html())
        lay.addWidget(text)
        picture = SheetPicture(self.profile.holes_left(front), flip=not front)
        lay.addWidget(picture, 1)
        self.load_views.append((w, text, picture, html, front))
        b = QPushButton(button)
        b.setProperty("kind", "primary")
        b.setIcon(theme.icon("printer", theme.current().accent_text, 18))
        b.clicked.connect(lambda: self._print(side, check))
        lay.addWidget(b, 0, Qt.AlignHCenter)
        done = _label("Уже напечатали? Нажмите «Дальше».", "muted")
        done.setWordWrap(False)
        lay.addWidget(done, 0, Qt.AlignHCenter)
        w.phone_text = (f"Напечатайте лист: на компьютере кнопка «{button}». Когда напечатается — нажмите там "
                        "«Дальше», и здесь появится кнопка для фото.")
        return w

    def _refresh_load(self):
        for _, text, picture, html, front in self.load_views:
            text.setText(html())
            picture.holes_left = self.profile.holes_left(front)
            picture.update()

    def _wrong_side(self, step: PhotoStep) -> str:
        """Печать легла не на ту сторону. Если это лицевая и правильной лицевой ещё не было — значит, этот
        принтер печатает на другой стороне листа: запоминаем и меняем подсказки."""
        if step.side is Side.BACK:
            return ("Нажмите «Назад», переверните лист как страницу книги и напечатайте оборот снова. Если "
                    "обратная сторона уже занята — возьмите новый лист и начните с лицевой.")
        known = any(st.result is not None for st in (self.photos.get(Side.FRONT), self.checks.get(Side.FRONT))
                    if st is not None)
        if known:
            return "Нажмите «Назад» и напечатайте на новом листе, положив его так, как в подсказке."
        self.profile.flip_feed = not self.profile.flip_feed
        try:
            printers.save(self.profiles)
        except OSError:
            pass  # подсказка всё равно поменяется в этом мастере
        self._refresh_load()
        return (f"Запомнил: в этот принтер лист нужно класть <b>отверстиями {holes_word(self.profile, True)}</b>. "
                "Нажмите «Назад» и напечатайте лицевую на новом листе — подсказка уже исправлена.")

    def _result_page(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(12)
        lay.addWidget(_label("Поправки сохранены", "h2"))
        self.result = _label("")
        lay.addWidget(self.result)
        lay.addSpacing(10)
        lay.addWidget(_label("<b>Теперь проверим.</b> Принтер напечатает на <b>новом</b> листе сетку прямо по "
                             "клетке — на лицевой стороне и на обороте. Сфотографируете обе стороны, и программа "
                             "скажет, всё ли легло точно, а если нет — сама доведёт поправки."))
        chk = QPushButton("Проверить по фото")
        chk.setProperty("kind", "primary")
        chk.setIcon(theme.icon("circle-check", theme.current().accent_text, 18))
        chk.clicked.connect(self._start_verify)
        lay.addWidget(chk, 0, Qt.AlignLeft)
        lay.addStretch(1)
        w.phone_text = "Поправки сохранены. Теперь проверка: на компьютере нажмите «Проверить по фото»."
        return w

    def _start_verify(self):
        """Страницы проверки: печать сетки → фото → оборот → фото → итог. Повторная проверка — заново."""
        if self.verify_from is None:
            self.verify_from = len(self.pages)
        self._truncate(self.verify_from)
        self.load_views = [v for v in self.load_views if v[0] in self.pages]  # страницы проверки — заново
        self.checks = {s: self._photo_step(s, True) for s in (Side.FRONT, Side.BACK)}
        front = self._print_page("Проверка: лицевая сторона",
                                 lambda: self._front_text("<b>новый</b> лист", ". Принтер напечатает пунктирную сетку "
                                                          "прямо по синей клетке"),
                                 True, "Напечатать проверку", Side.FRONT, check=True)
        back = self._print_page("Проверка: оборот", self._back_text, False, "Напечатать проверку оборота",
                                Side.BACK, check=True)
        self.verdict_page = self._verdict_page()
        self._append([front, self.checks[Side.FRONT], back, self.checks[Side.BACK], self.verdict_page])
        self._go(self.verify_from)

    def _verdict_page(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(12)
        self.verdict_title = _label("", "h2")
        self.verdict = _label("")
        lay.addWidget(self.verdict_title)
        lay.addWidget(self.verdict)
        self.again = QPushButton("Проверить ещё раз")
        self.again.setProperty("kind", "primary")
        self.again.setIcon(theme.icon("refresh-cw", theme.current().accent_text, 18))
        self.again.clicked.connect(self._start_verify)
        lay.addWidget(self.again, 0, Qt.AlignLeft)
        lay.addStretch(1)
        return w

    # --- телефон ---

    def _phone_sync(self):
        """Телефон показывает то же, что мастер: на шаге с фото — кнопку и итог распознавания, иначе — что
        сделать на компьютере."""
        if self.phone is None:
            return
        w = self.stack.currentWidget()
        if isinstance(w, PhotoStep):
            self.phone.set_state(stage=w.phone_stage, title=w.phone_title, hint=w.phone_hint, msg=w.phone_msg,
                                 next=True)
        elif w is self.verdict_page and w is not None:
            self.phone.set_state(stage="idle", title=self.verdict_title.text(), hint="",
                                 msg=_plain(self.verdict.text()), next=False)
        else:
            self.phone.set_state(stage="idle", title=f"Калибровка: {self.printer}", hint="",
                                 msg=getattr(w, "phone_text", "Продолжайте на компьютере. Когда понадобится фото, "
                                                              "кнопка появится здесь сама."), next=False)

    def _phone_photo(self, path: str):
        w = self.stack.currentWidget()
        if isinstance(w, PhotoStep):
            w.analyze(path, "фото с телефона")

    def _phone_next(self):
        w = self.stack.currentWidget()
        if isinstance(w, PhotoStep) and w.result is not None:
            self._next()

    def _stop_phone(self):
        if self.phone is not None:
            self.phone.stop()  # сервер живёт только пока открыт мастер

    def done(self, r):
        self._stop_phone()
        super().done(r)

    def closeEvent(self, e):
        self._stop_phone()  # close() у скрытого окна не вызывает done()
        super().closeEvent(e)

    # --- логика ---

    def _sync(self):
        q = self.stack.currentWidget()
        if isinstance(q, Question):
            self.next_btn.setEnabled(q.answer is not None)
        elif isinstance(q, PhotoStep):
            self.next_btn.setEnabled(q.result is not None)
        self._phone_sync()

    def _next(self):
        w = self.stack.currentWidget()
        if w is self.result_page or w is self.verdict_page:
            self.accept()
        else:
            self._go(self.stack.currentIndex() + 1)

    def _go(self, i: int):
        i = max(0, min(len(self.pages) - 1, i))
        w = self.pages[i]
        if w is self.result_page and not self.saved and not self._save():
            return
        if w is self.verdict_page:
            self._verdict()
        self.stack.go(i)
        terminal = w is self.result_page or w is self.verdict_page
        self.back_btn.setVisible(0 < i and not terminal)
        self.next_btn.setVisible(i > 0)
        self.next_btn.setText("Готово" if terminal else "Дальше")
        if self.verify_from is not None and i >= self.verify_from:
            self.step.setText("" if terminal else f"Проверка: шаг {i - self.verify_from + 1} из 4")
        else:
            total = self.pages.index(self.result_page) - 1 if self.result_page in self.pages else 0
            self.step.setText("" if terminal or i == 0 else f"Шаг {i} из {total}")
        self.next_btn.setEnabled(True)
        self._sync()

    def _page(self) -> PageSettings:
        return PageSettings(offset_front=self.front, offset_back=self.back)

    def _print(self, side: Side, check: bool = False):
        from ..printing import PrintError, print_calibration
        try:
            print_calibration(self._page(), side, self.printer, photo=self.mode == "photo" or check, check=check)
        except PrintError as e:
            QMessageBox.warning(self, "Печать", str(e))
            return
        self._go(self.stack.currentIndex() + 1)

    def _store(self, check_mm: float = -1.0, how: str | None = None) -> bool:
        self.profile.set_offsets(printers.DIRECT, self.front, self.back, how=how or self.mode, check_mm=check_mm)
        try:
            printers.save(self.profiles)
        except OSError as e:
            QMessageBox.critical(self, "Калибровка", f"Не удалось сохранить: {e}")
            return False
        return True

    def _save(self) -> bool:
        if self.mode == "photo":
            rf, rb = self.photos[Side.FRONT].result, self.photos[Side.BACK].result
            if rf is None or rb is None:
                return False
            from ..calib_photo import combine
            self.front, self.back = combine(rf, rb)
            text = (f"<b>Лицевая сторона:</b> {_miss_words(rf.x.shift_mm, rf.y.shift_mm)}<br>"
                    f"<b>Оборот:</b> {_miss_words(rb.x.shift_mm, rb.y.shift_mm)}{_scale_words(self.front)}"
                    f"{_placement_words(rf, rb)}")
        else:
            d = {k: q.answer or 0.0 for k, q in self.qs.items()}
            self.front = PrinterOffset(round(self.front.dx_mm + d["fx"], 2), round(self.front.dy_mm + d["fy"], 2),
                                       self.front.sx, self.front.sy)
            self.back = PrinterOffset(round(self.back.dx_mm + d["bx"], 2), round(self.back.dy_mm + d["by"], 2),
                                      self.back.sx, self.back.sy)
            text = (f"<b>Лицевая сторона:</b> {_fix_words(d['fx'], d['fy'])}.<br>"
                    f"<b>Оборот:</b> {_fix_words(d['bx'], d['by'])}.")
        if not self._store():
            return False
        self.saved = True
        self.result.setText(text)
        return True

    def _verdict(self):
        """Итог проверки. «Завершена» — только если печать и правда легла в клетку: промах до CHECK_OK_MM,
        или после второй проверки небольшой остаток, который доводим по ней. Большой промах на проверке
        после калибровки — не ошибка измерения, а лист, который каждый раз ложится в лоток по-разному:
        это честно говорим и предлагаем проверить ещё раз."""
        rf, rb = self.checks[Side.FRONT].result, self.checks[Side.BACK].result
        if rf is None or rb is None:
            return
        self.checks_done += 1
        miss = max(_miss(rf), _miss(rb))
        p = theme.current()
        sides = (f"<b>Лицевая:</b> {_miss_words(rf.x.shift_mm, rf.y.shift_mm)}<br>"
                 f"<b>Оборот:</b> {_miss_words(rb.x.shift_mm, rb.y.shift_mm)}<br><br>")
        if miss <= printers.CHECK_OK_MM:
            self._store(check_mm=miss, how="photo")
            self.verdict_title.setText("✓ Калибровка завершена")
            self.verdict.setText(f"Печать ложится в клетку с точностью <b>{_mm(miss)} мм</b> на обеих сторонах. "
                                 "Можно печатать конспекты.")
            self.verdict_title.setStyleSheet(f"color: {p.success};")
            self.again.hide()
            return
        from ..calib_photo import combine
        self.front, self.back = combine(rf, rb)  # проверочный лист тоже даёт поправки — доводим
        if miss <= printers.CHECK_FAIR_MM and self.checks_done >= MAX_CHECKS:
            # вторая проверка: остаток небольшой — доводим поправки по ней, третий лист не нужен
            self._store(check_mm=miss, how="photo")
            self.verdict_title.setText("✓ Калибровка завершена")
            self.verdict.setText(f"Довёл поправки по второй проверке (было расхождение {_mm(miss)} мм).<br>"
                                 + sides + "Можно печатать конспекты.")
            self.verdict_title.setStyleSheet(f"color: {p.success};")
            self.again.hide()
            return
        self._store(how="photo")  # поправки уточнены, но не проверены
        self.verdict_title.setStyleSheet(f"color: {p.warning};")
        self.again.show()
        if miss <= printers.CHECK_FAIR_MM:
            self.verdict_title.setText("Почти: уточнил поправки")
            self.verdict.setText(sides + "Проверим ещё раз на новом листе — после второй проверки поправки будут "
                                         "доведены окончательно.")
            return
        self.verdict_title.setText(f"Расхождение {_mm(miss)} мм — проверку не прошли")
        self.verdict.setText(
            sides + "Это намного больше, чем ошибка измерения: печать после калибровки должна ложиться точно. "
            "Так бывает, когда лист каждый раз ложится в лоток по-разному. " + GUIDES + " Поправки по этой "
            "проверке я уточнил — проверьте ещё раз на новом листе, положив его так же плотно.")


def _placement_words(rf, rb) -> str:
    """Предупреждение, если печать ушла очень далеко или по-разному на двух сторонах: обычно это лист, который
    лежал в лотке не вплотную к направляющим. Поправку такая калибровка даёт, но повторится ли сдвиг — неизвестно."""
    far = max(_miss(rf), _miss(rb)) > BIG_SHIFT_MM
    apart = abs(rf.x.shift_mm - rb.x.shift_mm) > SIDES_APART_MM
    if not (far or apart):
        return ""
    p = theme.current()
    return (f"<br><br><b style='color:{p.warning}'>Печать ушла далеко от клетки</b>"
            f"{' и по-разному на двух сторонах' if apart else ''}. Обычно так бывает, если узкий лист лежал в "
            "широком лотке не вплотную к направляющим и сдвинулся вбок — в следующий раз он может лечь иначе. "
            f"{GUIDES} И обязательно пройдите проверку: она покажет, повторяется ли сдвиг.")
