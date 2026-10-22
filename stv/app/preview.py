"""Живой предпросмотр тетради: вёрстка и отрисовка идут в фоновом потоке, окно не подвисает."""

from dataclasses import dataclass

from PySide6.QtCore import QEvent, QMutex, QRectF, QSize, Qt, QThread, QTimer, QWaitCondition, Signal
from PySide6.QtGui import QColor, QFont, QImage, QKeySequence, QPainter, QPen, QPixmap, QShortcut
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout,
                               QWidget)

from ..engine.fonts import font_info
from ..engine.journal import Entry, build
from ..engine.layout import Document, Page
from ..engine.paper import Side
from ..engine.render import render_image
from ..engine.settings import HandSettings, PageSettings
from .ui import theme

PREVIEW_DPI = 130


@dataclass
class Job:
    entries: list[Entry]
    page: PageSettings
    hand: HandSettings
    serial: int


def base_x_height(hand: HandSettings) -> float:
    return hand.x_height_mm or font_info(hand.font_id).x_height_mm


class RenderWorker(QThread):
    """Берёт только самое свежее задание: пока пользователь печатает, старые отбрасываются."""
    laid_out = Signal(int, object, list)  # serial, Document, [EntryResult] — сразу после вёрстки
    done = Signal(int, list)              # serial, [QImage]
    failed = Signal(int, str)

    def __init__(self):
        super().__init__()
        self._mutex = QMutex()
        self._cond = QWaitCondition()
        self._job: Job | None = None
        self._stop = False
        self._cache: dict = {}  # свёрстанные конспекты: неизменённые не пересчитываются

    def submit(self, job: Job):
        self._mutex.lock()
        self._job = job
        self._cond.wakeOne()
        self._mutex.unlock()

    def stop(self):
        self._mutex.lock()
        self._stop = True
        self._cond.wakeOne()
        self._mutex.unlock()
        self.wait(5000)

    def run(self):
        while True:
            self._mutex.lock()
            while self._job is None and not self._stop:
                self._cond.wait(self._mutex)
            if self._stop:
                self._mutex.unlock()
                return
            job, self._job = self._job, None
            self._mutex.unlock()
            try:
                if len(self._cache) > 300:
                    self._cache.clear()
                doc, results = build(job.entries, job.page, job.hand, base_x_height(job.hand), self._cache)
                self.laid_out.emit(job.serial, doc, results)
                # страницы рисует окно — только ту, что на экране, и только изменившиеся (см. PreviewPanel)
                self.done.emit(job.serial, [])
            except Exception as e:  # ошибка вёрстки не должна ронять программу
                self.failed.emit(job.serial, str(e))


class PageView(QWidget):
    """Лист, вписанный в доступную область, с пометкой о переносе конспекта. Двойной щелчок — крупно."""
    opened = Signal()

    def mouseDoubleClickEvent(self, e):
        if self.image is not None:
            self.opened.emit()

    def __init__(self):
        super().__init__()
        self.image: QImage | None = None
        self.prev_image: QImage | None = None
        self.page: Page | None = None
        self.mix = 1.0  # 0 — виден прежний лист, 1 — новый
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(QSize(220, 300))
        from PySide6.QtCore import QEasingCurve, QVariantAnimation
        self.anim = QVariantAnimation(self)
        self.anim.setDuration(220)
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)
        self.anim.valueChanged.connect(self._tick)

    def set_page(self, img: QImage | None, page: Page | None):
        """Новый лист плавно «проявляется» поверх прежнего."""
        self.prev_image = self.image if img is not None else None
        self.image, self.page = img, page
        if self.prev_image is not None and self.prev_image is not img:
            self.anim.stop()
            self.anim.start()
        else:
            self.mix = 1.0
            self.update()

    def _tick(self, v):
        self.mix = float(v)
        self.update()

    def _sheet_rect(self, img: QImage) -> QRectF:
        iw, ih = img.width(), img.height()
        s = min((self.width() - 24) / iw, (self.height() - 24) / ih)
        w, h = iw * s, ih * s
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def paintEvent(self, _):
        from .ui import theme
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.setRenderHint(QPainter.Antialiasing, True)
        if self.image is None:
            p.setPen(QColor(theme.current().text_muted))
            p.drawText(self.rect(), Qt.AlignCenter, "Здесь появится лист")
            return
        r = self._sheet_rect(self.image)
        for k in range(4):  # мягкая тень под листом
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 10))
            p.drawRoundedRect(r.adjusted(-k, -k + 2, k, k + 3), 4 + k, 4 + k)
        if self.prev_image is not None and self.mix < 1.0:
            p.setOpacity(1.0 - self.mix)
            p.drawImage(self._sheet_rect(self.prev_image), self.prev_image)
            p.setOpacity(self.mix)
        p.drawImage(r, self.image)
        p.setOpacity(1.0)
        if self.page is not None and self.page.note:
            below = self.page.note_bottom
            text = self.page.note + ("  ↓" if below else "")
            if not below:
                text = "↪  " + text
            f = p.font()
            f.setPointSizeF(8)
            f.setWeight(QFont.DemiBold)
            p.setFont(f)
            fm = p.fontMetrics()
            bw = min(r.width() - 20, fm.horizontalAdvance(text) + 28)
            lines = 1 if fm.horizontalAdvance(text) + 28 <= r.width() - 20 else 2
            bh = 14 + fm.height() * lines
            y = r.bottom() - bh - 10 if below else r.top() + 10
            pill = QRectF(r.center().x() - bw / 2, y, bw, bh)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(40, 40, 46, 150))  # нейтральная полупрозрачная метка, не тревога
            p.drawRoundedRect(pill, bh / 2, bh / 2)
            p.setPen(QPen(QColor(255, 255, 255, 235)))
            p.drawText(pill.adjusted(12, 4, -12, -4), Qt.AlignCenter | Qt.TextWordWrap, text)


class PageViewer(QDialog):
    """Лист крупно: листать (‹ › или стрелки), приближать (+ −, Ctrl+колесо), «по ширине». Esc — закрыть.
    Лист перерисовывается под нужный масштаб, поэтому буквы остаются чёткими при любом увеличении."""

    MIN_ZOOM, MAX_ZOOM = 0.5, 3.0

    def __init__(self, doc: Document, index: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Просмотр листов")
        self.doc, self.index = doc, index
        self.zoom = 1.0          # 1.0 — лист целиком по высоте окна
        self._cache: dict = {}
        screen = self.screen().availableGeometry() if self.screen() else None
        if screen is not None:
            self.resize(int(screen.width() * 0.9), int(screen.height() * 0.92))

        self.image = QLabel()
        self.image.setAlignment(Qt.AlignCenter)
        self.scroll = QScrollArea()
        self.scroll.setWidget(self.image)
        self.scroll.setWidgetResizable(True)
        self.scroll.setAlignment(Qt.AlignCenter)
        self.scroll.viewport().installEventFilter(self)

        def tool(icon: str, tip: str, fn, text: str = "") -> QPushButton:
            b = QPushButton(text)
            b.setProperty("kind", "ghost")
            if icon:
                b.setIcon(theme.icon(icon, theme.current().text, 18))
            b.setToolTip(tip)
            b.clicked.connect(fn)
            return b

        self.prev_btn = tool("arrow-left", "Предыдущая страница (←)", lambda: self.go(self.index - 1))
        self.next_btn = tool("arrow-right", "Следующая страница (→)", lambda: self.go(self.index + 1))
        self.label = QLabel()
        self.label.setProperty("role", "muted")
        out = tool("zoom-out", "Отдалить (−)", lambda: self.set_zoom(self.zoom / 1.25))
        inn = tool("zoom-in", "Приблизить (+)", lambda: self.set_zoom(self.zoom * 1.25))
        whole = tool("", "Весь лист в окне (0)", lambda: self.set_zoom(1.0), "Весь лист")
        width = tool("", "Лист по ширине окна", self.fit_width, "По ширине")
        self.percent = QLabel()
        self.percent.setProperty("role", "muted")
        close = tool("x", "Закрыть (Esc)", self.accept)
        bar = QHBoxLayout()
        bar.addWidget(self.prev_btn)
        bar.addWidget(self.label)
        bar.addWidget(self.next_btn)
        bar.addStretch(1)
        for w in (out, self.percent, inn, whole, width):
            bar.addWidget(w)
        bar.addSpacing(12)
        bar.addWidget(close)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 16)
        lay.addLayout(bar)
        lay.addWidget(self.scroll, 1)
        for keys, fn in ((("Left", "PgUp"), lambda: self.go(self.index - 1)),
                         (("Right", "PgDown"), lambda: self.go(self.index + 1)),
                         (("+", "="), lambda: self.set_zoom(self.zoom * 1.25)),
                         (("-",), lambda: self.set_zoom(self.zoom / 1.25)),
                         (("0",), lambda: self.set_zoom(1.0))):
            for k in keys:
                QShortcut(QKeySequence(k), self, activated=fn)
        QTimer.singleShot(0, self._render)

    def _fit_dpi(self) -> float:
        """dpi, при котором лист целиком помещается в окно по высоте (и по ширине)."""
        paper = self.doc.page.paper
        vp = self.scroll.viewport().size()
        return max(30.0, min((vp.height() - 24) / paper.height_mm, (vp.width() - 24) / paper.width_mm) * 25.4)

    def fit_width(self):
        paper = self.doc.page.paper
        w = self.scroll.viewport().width() - 40
        self.set_zoom(w / paper.width_mm * 25.4 / self._fit_dpi())

    def set_zoom(self, z: float):
        self.zoom = max(self.MIN_ZOOM, min(self.MAX_ZOOM, z))
        self._render()

    def go(self, i: int):
        self.index = max(0, min(i, len(self.doc.pages) - 1))
        self._render()

    def _render(self):
        from ..engine.render import render_image
        dpi = round(self._fit_dpi() * self.zoom)
        key = (self.index, dpi)
        if key not in self._cache:
            if len(self._cache) > 12:
                self._cache.clear()
            self._cache[key] = render_image(self.doc, self.doc.pages[self.index], dpi, preview=True)
        self.image.setPixmap(QPixmap.fromImage(self._cache[key]))
        n = len(self.doc.pages)
        pg = self.doc.pages[self.index]
        side = "лицевая" if pg.side is Side.FRONT else "оборот"
        self.label.setText(f"Стр. {self.index + 1} из {n} · лист {self.index // 2 + 1}, {side}")
        self.percent.setText(f"{self.zoom:.0%}")
        self.prev_btn.setEnabled(self.index > 0)
        self.next_btn.setEnabled(self.index < n - 1)

    def eventFilter(self, obj, e):
        if e.type() == QEvent.Wheel and e.modifiers() & Qt.ControlModifier:
            self.set_zoom(self.zoom * (1.15 if e.angleDelta().y() > 0 else 1 / 1.15))
            return True
        return super().eventFilter(obj, e)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if hasattr(self, "image"):
            self._render()


class PreviewPanel(QWidget):
    results_ready = Signal(list)

    def __init__(self):
        super().__init__()
        from ..engine.fonts import preload_fonts
        preload_fonts()  # до запуска фонового потока
        self.worker = RenderWorker()
        self.worker.laid_out.connect(self._on_laid_out)
        self.worker.done.connect(self._on_done)
        self.worker.failed.connect(self._on_failed)
        self.worker.start()
        self._serial = 0
        self.doc: Document | None = None
        self.images: list[QImage | None] = []
        self._img_cache: dict = {}
        self.index = 0
        self._want_entry = ""

        self.view = PageView()
        self.prev_btn = QPushButton("‹")
        self.next_btn = QPushButton("›")
        for b in (self.prev_btn, self.next_btn):
            b.setFixedWidth(36)
        self.prev_btn.clicked.connect(lambda: self.show_page(self.index - 1))
        self.next_btn.clicked.connect(lambda: self.show_page(self.index + 1))
        self.zoom_btn = QPushButton()
        self.zoom_btn.setFixedWidth(36)
        self.zoom_btn.setToolTip("Открыть лист крупно (или двойной щелчок по листу)")
        self.zoom_btn.clicked.connect(self.open_viewer)
        theme.on_change(lambda: self.zoom_btn.setIcon(theme.icon("zoom-in", theme.current().text, 18)))
        self.zoom_btn.setIcon(theme.icon("zoom-in", theme.current().text, 18))
        self.view.opened.connect(self.open_viewer)
        self.label = QLabel()
        self.label.setAlignment(Qt.AlignCenter)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setProperty("role", "muted")

        nav = QHBoxLayout()
        nav.addWidget(self.prev_btn)
        nav.addWidget(self.label, 1)
        nav.addWidget(self.next_btn)
        nav.addWidget(self.zoom_btn)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.view, 1)
        lay.addLayout(nav)
        lay.addWidget(self.status)
        self._update_nav()

    def request(self, entries: list[Entry], page: PageSettings, hand: HandSettings):
        self._serial += 1
        self.status.setText("Обновляю предпросмотр…")
        self.worker.submit(Job(entries, page, hand, self._serial))

    def _on_laid_out(self, serial: int, doc: Document, results: list):
        if serial == self._serial:
            self.doc = doc
            self._doc_serial = serial
            self.results_ready.emit(results)

    def is_current(self) -> bool:
        """Свёрстан ли последний отправленный вариант текста и настроек."""
        return getattr(self, "_doc_serial", -1) == self._serial

    def _on_done(self, serial: int, _images: list):
        if serial != self._serial or self.doc is None:
            return
        self.images = [None] * len(self.doc.pages)  # рисуются по мере показа
        self.status.setText("\n".join(self.doc.warnings))
        if self._want_entry:
            self.show_entry(self._want_entry)
        else:
            self.show_page(min(self.index, len(self.images) - 1))

    def _on_failed(self, serial: int, msg: str):
        if serial == self._serial:
            self.status.setText(f"Не удалось сверстать текст: {msg}")

    def show_entry(self, entry_id: str):
        """Показать первую страницу конспекта (или запомнить, если вёрстка ещё идёт)."""
        self._want_entry = entry_id
        if self.doc is None or len(self.images) != len(self.doc.pages):
            return
        for i, pg in enumerate(self.doc.pages):
            if pg.entry_id == entry_id:
                self._want_entry = ""
                self.show_page(i)
                return

    def show_page(self, i: int):
        if not self.images or self.doc is None:
            self.view.set_page(None, None)
            self._update_nav()
            return
        self.index = max(0, min(i, len(self.images) - 1))
        if self.images[self.index] is None:
            self.images[self.index] = self._render(self.index)
        self.view.set_page(self.images[self.index], self.doc.pages[self.index])
        self._update_nav()

    def _update_nav(self):
        n = len(self.images)
        if not n or self.doc is None or self.index >= len(self.doc.pages):
            self.label.setText("—")
        else:
            pg = self.doc.pages[self.index]
            side = "лицевая" if pg.side is Side.FRONT else "оборот"
            self.label.setText(f"Стр. {self.index + 1} из {n} · лист {self.index // 2 + 1}, {side}")
        self.prev_btn.setEnabled(self.index > 0)
        self.next_btn.setEnabled(self.index < n - 1)
        self.zoom_btn.setEnabled(bool(n))

    def _render(self, i: int) -> QImage:
        """Картинка страницы. Неизменённые страницы (тот же свёрстанный конспект) берутся готовыми: после
        правки одного конспекта в длинной тетради перерисовывается только он — и только видимая страница."""
        pg = self.doc.pages[i]
        sig = (id(pg.lines), pg.side, pg.date, pg.note, pg.note_bottom, tuple(id(g) for g in pg.date_glyphs))
        hit = self._img_cache.get(sig)
        if hit is None:
            if len(self._img_cache) > 200:
                self._img_cache.clear()
            # в кэше держим и сами строки: пока они живы, их id не достанется другой странице
            hit = (pg.lines, pg.date_glyphs, render_image(self.doc, pg, PREVIEW_DPI, preview=True))
            self._img_cache[sig] = hit
        return hit[2]

    def open_viewer(self):
        if self.doc is not None and self.doc.pages:
            PageViewer(self.doc, min(self.index, len(self.doc.pages) - 1), self.window()).exec()

    def shutdown(self):
        self.worker.stop()
