"""Раздел «Почерки»: шаблон образца, загрузка фото, проверка букв, сохранение своего почерка."""

import tempfile
from pathlib import Path

from PySide6.QtCore import QRectF, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QImage, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (QApplication, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QProgressDialog, QPushButton, QScrollArea, QVBoxLayout, QWidget)

from .ui import theme
from .ui.motion import fade_in
from .ui.widgets import Card, hand_sample, label, page_header


def _glyph_sheet(results, cols=20, cell=46) -> QImage:
    """Картинка всех распознанных букв, чтобы глазами найти неудачные."""
    glyphs = sorted((g for r in results for g in r.glyphs), key=lambda g: (g.char, g.variant))
    rows = max(1, (len(glyphs) + cols - 1) // cols)
    img = QImage(cols * cell, rows * cell, QImage.Format_RGB32)
    img.fill(QColor("#ffffff"))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    for i, g in enumerate(glyphs):
        r, c = divmod(i, cols)
        x0, y0 = c * cell, r * cell
        p.setPen(QColor("#e3e3e3"))
        p.drawRect(QRectF(x0, y0, cell, cell))
        path = QPainterPath()
        for poly in g.polys:
            path.moveTo(*poly[0])
            for pt in poly[1:]:
                path.lineTo(*pt)
            path.closeSubpath()
        k = (cell - 6) / 14.0  # клетка шаблона ~14 мм
        p.save()
        p.translate(x0 + 3, y0 + cell * 0.62)
        p.scale(k, k)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#1d3a8a"))
        p.drawPath(path)
        p.restore()
    p.end()
    return img


INK = {"light": "#1D3A8A", "dark": "#9DB2FF"}  # синие чернила; в тёмной теме — светлее, чтобы читались
SAMPLE = "Привет! Так выглядит конспект"


class HandCard(Card):
    """Почерк: образец строки, название, у своего — кнопка удаления."""

    def __init__(self, font_id: str, title: str, own: bool, on_delete):
        super().__init__(16, 6)
        self.setFixedSize(340, 130)
        self.sample = QLabel()
        self.sample.setMinimumHeight(56)
        try:
            self.sample.setPixmap(hand_sample(font_id, SAMPLE, 48, INK[theme.current().name], 300))
        except Exception:  # повреждённый файл почерка не должен ломать раздел
            self.sample.setText("не удалось показать образец")
        self.lay.addWidget(self.sample)
        row = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addWidget(label(title, wrap=False))
        col.itemAt(0).widget().setStyleSheet("font-weight: 600;")
        col.addWidget(label("ваш почерк" if own else "встроенный, шрифт OFL", "muted", wrap=False))
        row.addLayout(col, 1)
        if own:
            rm = QPushButton()
            rm.setProperty("kind", "ghost")
            rm.setIcon(theme.icon("trash-2", theme.current().text_muted, 18))
            rm.setToolTip(f"Удалить почерк «{title}»")
            rm.setFixedSize(34, 34)
            rm.clicked.connect(lambda: on_delete(font_id, title))
            row.addWidget(rm, 0, Qt.AlignBottom)
        self.lay.addLayout(row)


def _step(n: int, title: str, text: str, button: QWidget | None = None) -> Card:
    c = Card(18, 8)
    num = label(str(n), "step", wrap=False)
    num.setAlignment(Qt.AlignCenter)
    c.lay.addWidget(num)
    t = label(title)
    t.setStyleSheet("font-weight: 600; font-size: 11pt;")
    c.lay.addWidget(t)
    c.lay.addWidget(label(text, "muted"))
    c.lay.addStretch(1)
    if button is not None:
        c.lay.addWidget(button, 0, Qt.AlignLeft)
    return c


class HandsPage(QWidget):
    """Почерки в программе карточками с живым образцом и «свой почерк» в три шага."""
    hand_saved = Signal(str)  # id нового почерка

    def __init__(self):
        super().__init__()
        self.setObjectName("Page")
        self.results = []

        content = QWidget()
        content.setObjectName("Page")
        lay = QVBoxLayout(content)
        lay.setContentsMargins(36, 32, 36, 32)
        lay.setSpacing(16)
        lay.addWidget(page_header("Почерки", "Встроенные почерки и ваш собственный — по фото заполненного "
                                             "образца. Выбрать почерк для тетради можно в «Оформлении»."))
        lay.addSpacing(6)
        lay.addWidget(label("Почерки в программе", "h2"))
        self.cards = QGridLayout()
        self.cards.setSpacing(14)
        self.cards.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        lay.addLayout(self.cards)
        lay.addSpacing(10)

        lay.addWidget(label("Добавить свой почерк", "h2"))
        lay.addWidget(label("Программа соберёт почерк из ваших букв: каждую напишете несколько раз, чтобы текст "
                            "выглядел живым, а не напечатанным.", "muted"))
        tpl = QPushButton("Открыть шаблон")
        tpl.setIcon(theme.icon("printer", theme.current().text, 18))
        tpl.clicked.connect(self._open_template)
        load = QPushButton("Загрузить фото")
        load.setProperty("kind", "primary")
        load.setIcon(theme.icon("file-up", theme.current().accent_text, 18))
        load.clicked.connect(lambda: self._load_photos())
        phone = QPushButton("С телефона")
        phone.setIcon(theme.icon("smartphone", theme.current().text, 18))
        phone.setToolTip("Сфотографировать листы телефоном по QR-коду — без пересылки")
        phone.clicked.connect(self._from_phone)
        load_row = QWidget()
        lr = QHBoxLayout(load_row)
        lr.setContentsMargins(0, 0, 0, 0)
        lr.addWidget(load)
        lr.addWidget(phone)
        lr.addStretch(1)
        steps = QHBoxLayout()
        steps.setSpacing(14)
        steps.addWidget(_step(1, "Распечатайте шаблон", "Два листа A4, масштаб 100%.", tpl), 1)
        steps.addWidget(_step(2, "Заполните ручкой", "Каждая буква — в своём квадрате, на синей линии, не выходя за "
                                                    "рамку. Строчные — по три раза, заглавные и цифры — по два."), 1)
        steps.addWidget(_step(3, "Загрузите фото", "Каждый лист целиком, сверху, при хорошем свете — чтобы были "
                                                  "видны 4 чёрных квадрата по углам. Подойдёт и скан.", load_row), 1)
        lay.addLayout(steps)

        # результат распознавания — появляется после загрузки фото
        self.summary = label("")
        self.sheet = QLabel()
        self.sheet.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        sheet_scroll = QScrollArea()
        sheet_scroll.setWidget(self.sheet)
        sheet_scroll.setWidgetResizable(True)
        sheet_scroll.setMinimumHeight(240)
        self.name = QLineEdit("Мой почерк")
        self.name.setPlaceholderText("Название, например «Мой почерк»")
        self.save_btn = QPushButton("Сохранить почерк")
        self.save_btn.setProperty("kind", "primary")
        self.save_btn.clicked.connect(self._save)
        save_row = QHBoxLayout()
        save_row.addWidget(label("Название", wrap=False))
        save_row.addWidget(self.name, 1)
        save_row.addWidget(self.save_btn)
        self.result_card = Card(20, 10)
        self.result_card.lay.addWidget(label("Проверьте буквы", "h2"))
        self.result_card.lay.addWidget(self.summary)
        self.result_card.lay.addWidget(sheet_scroll)
        self.result_card.lay.addLayout(save_row)
        self.result_card.hide()
        lay.addWidget(self.result_card)
        lay.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidget(content)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        theme.on_change(self._refresh_saved)
        self._refresh_saved()

    def _refresh_saved(self):
        from ..engine.fonts import all_fonts
        from ..hands import handset
        own = {fid for fid, _ in handset.list_hands()}
        while self.cards.count():
            w = self.cards.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        for i, (fid, title) in enumerate(all_fonts()):
            self.cards.addWidget(HandCard(fid, title, fid in own, self._delete), i // 3, i % 3)

    def _open_template(self):
        from ..hands.template import export_template_pdf
        path = Path(tempfile.mkdtemp(prefix="konspektai_tpl_")) / "шаблон_почерка_A4.pdf"
        try:
            export_template_pdf(path)
        except OSError as e:
            QMessageBox.critical(self, "Шаблон", f"Не удалось создать шаблон: {e}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _from_phone(self):
        from .phone_dialog import ask_photos
        files = ask_photos(self, "Образец почерка", "Сфотографируйте каждый заполненный лист шаблона целиком, "
                                                    "сверху, чтобы были видны 4 чёрных квадрата по углам.",
                           multiple=True)
        if files:
            self._load_photos(files)

    def _load_photos(self, files: list[str] | None = None):
        from ..hands import template as T
        from ..hands.scanner import ScanError, scan_image
        if files is None:
            files, _ = QFileDialog.getOpenFileNames(self, "Фото заполненных листов", str(Path.home()),
                                                    "Изображения (*.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff)")
        if not files:
            return
        prog = QProgressDialog("Распознаю листы…", "Отмена", 0, len(files), self)
        prog.setWindowModality(Qt.WindowModal)
        prog.setMinimumDuration(0)
        errors = []
        by_page = {r.page: r for r in self.results}
        for i, f in enumerate(files):
            prog.setValue(i)
            QApplication.processEvents()
            if prog.wasCanceled():
                break
            try:
                r = scan_image(f)
                by_page[r.page] = r  # повторное фото листа заменяет прежнее
            except ScanError as e:
                errors.append(f"{Path(f).name}: {e}")
            except Exception as e:  # битый файл и т. п. — не роняем программу
                errors.append(f"{Path(f).name}: не удалось обработать ({e})")
        prog.setValue(len(files))
        self.results = [by_page[k] for k in sorted(by_page)]
        n_pages = T.page_count()
        lines = []
        for r in self.results:
            empty = sorted(set(r.empty))
            lines.append(f"Лист {r.page + 1}: распознано букв — {len(r.glyphs)}"
                         + (f"; пустые клетки: {' '.join(empty)}" if empty else ""))
        missing = [p + 1 for p in range(n_pages) if p not in by_page]
        if missing:
            lines.append(f"Не хватает листов: {', '.join(map(str, missing))}. "
                         "Буквы с них возьмутся из шрифта Caveat.")
        if errors:
            lines.append(f"<span style='color:{theme.current().danger}'>" + "<br>".join(errors) + "</span>")
        self.summary.setText("<br>".join(lines) or "Ничего не распознано.")
        if self.results:
            self.sheet.setPixmap(QPixmap.fromImage(_glyph_sheet(self.results)))
        self.save_btn.setEnabled(bool(self.results))
        self.result_card.show()
        fade_in(self.result_card, rise=10)

    def _save(self):
        from ..engine.fonts import forget_font, load_font
        from ..hands import handset
        name = self.name.text().strip() or "Мой почерк"
        data = handset.build(self.results, name)
        try:
            fid = handset.save(data)
        except OSError as e:
            QMessageBox.critical(self, "Почерк", f"Не удалось сохранить: {e}")
            return
        forget_font(fid)
        load_font(fid)  # в главном потоке, до использования в предпросмотре
        self._refresh_saved()
        self.result_card.hide()
        self.results = []
        self.hand_saved.emit(fid)
        QMessageBox.information(self, "Почерк", f"Почерк «{name}» сохранён и выбран в тетради.")

    def _delete(self, fid: str, title: str):
        from ..engine.fonts import forget_font
        from ..hands import handset
        if QMessageBox.question(self, "Почерк", f"Удалить почерк «{title}»?") != QMessageBox.Yes:
            return
        handset.delete(fid)
        forget_font(fid)
        self._refresh_saved()
        self.hand_saved.emit("")
