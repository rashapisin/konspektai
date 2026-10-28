"""Главное окно: полоска разделов слева, рабочий экран тетради, плавные переходы.

Режим работы (учёба, служба МЧС, просто писать), способ печати и AI задаются мастером первого
запуска и меняются в «Настройках»; от них зависит, какие разделы и кнопки видны.
"""

from pathlib import Path

from PySide6.QtCore import QSize, QTimer, Qt, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QApplication, QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
                               QMessageBox, QPushButton, QScrollArea, QSplitter, QVBoxLayout, QWidget, QFileDialog)

from ..engine.render import export_pdf
from .hands_page import HandsPage
from .home import HomePage
from .journal_panel import JournalPanel
from .preview import PreviewPanel
from .print_wizard import PrintWizard
from .printers_page import PrintersPage
from .project import APP_NAME, FILE_EXT, OLD_FILE_EXT, AppSettings, Project, documents_dir
from .settings_panel import SettingsPanel
from .ui import theme
from .ui.motion import AnimatedStack, Drawer, Rail, Toast

THEMES = ("Как в Windows", "Светлая", "Тёмная")
MODES = (("study", "Учёба — конспекты для школы и вуза"), ("mchs", "Служба МЧС — подготовка, расписания, планы"),
         ("free", "Просто писать — любой текст от руки"))
PRINT_TARGETS = (("printer", "Печатаю на принтере"), ("pdf", "Только PDF, без принтера"))
AI_MODES = (("off", "Без AI"), ("chat", "Через любой чат (копировать и вставить)"),
            ("api", "Нейросеть одной кнопкой (свой ключ; GigaChat — бесплатно)"))

HOME, WORK, HANDS, PRINTERS, SETTINGS = range(5)


def apply_theme(name: str):
    theme.apply(QApplication.instance(), name)


def prefs() -> dict:
    """Режим работы и прочие выборы мастера первого запуска."""
    return {"mode": AppSettings.get("mode", "mchs"), "print": AppSettings.get("print", "printer"),
            "ai": AppSettings.get("ai", "chat")}


class AppSettingsPage(QWidget):
    prefs_changed = Signal()
    onboarding_requested = Signal()
    export_requested = Signal()
    import_requested = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("Page")
        title = QLabel("Настройки")
        title.setProperty("role", "h1")

        def combo(items, current):
            c = QComboBox()
            for key, text in items:
                c.addItem(text, key)
            c.setCurrentIndex(max(0, c.findData(current)))
            c.setMinimumWidth(380)
            return c
        p = prefs()
        self.theme = QComboBox()
        self.theme.addItems(THEMES)
        self.theme.setCurrentText(AppSettings.get("theme", THEMES[0]))
        self.theme.currentTextChanged.connect(self._theme)
        self.mode = combo(MODES, p["mode"])
        self.print_target = combo(PRINT_TARGETS, p["print"])
        self.ai = combo(AI_MODES, p["ai"])
        for c, key in ((self.mode, "mode"), (self.print_target, "print"), (self.ai, "ai")):
            c.currentIndexChanged.connect(lambda _=0, c=c, key=key: self._set(key, c.currentData()))
        again = QPushButton("Пройти первый запуск заново")
        again.clicked.connect(self.onboarding_requested.emit)
        folder = QLabel(str(documents_dir()))
        folder.setProperty("role", "muted")
        folder.setTextInteractionFlags(Qt.TextSelectableByMouse)

        form = QFormLayout()
        form.setSpacing(14)
        form.addRow("Для чего", self.mode)
        form.addRow("Печать", self.print_target)
        form.addRow("Помощь AI", self.ai)
        form.addRow("Тема оформления", self.theme)
        from .ai_ui import AISettings
        self.ai_settings = AISettings()
        self.ai_label = QLabel("Нейросеть")
        form.addRow(self.ai_label, self.ai_settings)
        form.addRow("Папка тетрадей", folder)
        # перенос: дома подготовили — на работе загрузили и печатаете из программы
        pack_out = QPushButton("Сохранить всё в файл…")
        pack_out.setToolTip("Калибровки принтеров, свои почерки, настройки и тетради — в один файл: "
                            "перенесите его на флешке или отправьте себе")
        pack_out.clicked.connect(self.export_requested.emit)
        pack_in = QPushButton("Загрузить из файла…")
        pack_in.setToolTip("Загрузить файл переноса с другого компьютера")
        pack_in.clicked.connect(self.import_requested.emit)
        pack_row = QHBoxLayout()
        pack_row.addWidget(pack_out)
        pack_row.addWidget(pack_in)
        pack_row.addStretch(1)
        pack_box = QVBoxLayout()
        pack_box.setSpacing(6)
        pack_box.addLayout(pack_row)
        pack_hint = QLabel("Принтеры, свои почерки, настройки и тетради одним файлом — чтобы продолжить на другом "
                           "компьютере. Ключ нейросети не переносится: там его нужно ввести заново.")
        pack_hint.setWordWrap(True)
        pack_hint.setProperty("role", "muted")
        pack_box.addWidget(pack_hint)
        form.addRow("Перенос на другой компьютер", pack_box)
        from .update_ui import UpdateRow
        self.updates = UpdateRow()
        form.addRow("Обновления", self.updates)
        form.addRow("", again)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(36, 32, 36, 32)
        lay.setSpacing(18)
        lay.addWidget(title)
        lay.addLayout(form)
        lay.addStretch(1)

    def _sync_ai(self):
        on = prefs()["ai"] == "api"
        self.ai_settings.setVisible(on)
        self.ai_label.setVisible(on)

    def refresh(self):
        self._sync_ai()
        p = prefs()
        for c, key in ((self.mode, "mode"), (self.print_target, "print"), (self.ai, "ai")):
            c.blockSignals(True)
            c.setCurrentIndex(max(0, c.findData(p[key])))
            c.blockSignals(False)
        self.theme.blockSignals(True)
        self.theme.setCurrentText(AppSettings.get("theme", THEMES[0]))
        self.theme.blockSignals(False)

    def _set(self, key, value):
        AppSettings.set(key, value)
        self._sync_ai()
        self.prefs_changed.emit()

    def _theme(self, name):
        AppSettings.set("theme", name)
        apply_theme(name)


class WorkPage(QWidget):
    """Тетрадь: конспекты слева, текст в центре, живой лист справа; оформление — в выезжающей панели."""

    def __init__(self):
        super().__init__()
        self.setObjectName("Page")
        self.title = QLineEdit()
        self.title.setProperty("flat", True)
        self.title.setPlaceholderText("Название тетради")
        self.saved = QLabel()
        self.saved.setProperty("role", "muted")
        self.style_btn = QPushButton("Оформление")
        self.style_btn.setToolTip("Почерк, размер, чернила, бумага, поля")
        self.export_btn = QPushButton("PDF")
        self.export_btn.setToolTip("Сохранить тетрадь в PDF")
        top = QHBoxLayout()
        top.setContentsMargins(14, 10, 14, 4)
        top.addWidget(self.title, 1)
        top.addWidget(self.saved)
        top.addSpacing(8)
        top.addWidget(self.export_btn)
        top.addWidget(self.style_btn)
        self.print_btn = QPushButton("Печать")
        self.print_btn.setProperty("kind", "primary")
        self.print_btn.setCursor(Qt.PointingHandCursor)
        self.print_btn.setIconSize(QSize(18, 18))
        top.addWidget(self.print_btn)

        self.journal = JournalPanel()
        self.preview = PreviewPanel()
        self.settings = SettingsPanel()

        left = self._card(self.journal.list_box)
        mid = self._card(self.journal.entry_box)
        right = self._card(self.preview, margins=(12, 12, 12, 12))
        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        for w in (left, mid, right):
            split.addWidget(w)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 5)
        split.setStretchFactor(2, 4)
        split.setSizes([270, 560, 480])
        body = QHBoxLayout()
        body.setContentsMargins(12, 4, 12, 12)
        body.addWidget(split)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addLayout(top)
        lay.addLayout(body, 1)

        # выезжающая панель оформления
        drawer_content = QWidget()
        dl = QVBoxLayout(drawer_content)
        dl.setContentsMargins(18, 16, 14, 16)
        head = QHBoxLayout()
        dt = QLabel("Оформление")
        dt.setProperty("role", "h2")
        self.close_drawer = QPushButton()
        self.close_drawer.setProperty("kind", "ghost")
        self.close_drawer.setToolTip("Закрыть")
        head.addWidget(dt)
        head.addStretch(1)
        head.addWidget(self.close_drawer)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(self.settings)
        for c in self.settings.findChildren(QComboBox):  # длинные названия не должны распирать панель
            c.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            c.setMinimumContentsLength(14)
        dl.addLayout(head)
        dl.addWidget(scroll, 1)
        self.drawer = Drawer(self, drawer_content, 400)
        self.style_btn.clicked.connect(self.drawer.toggle)
        self.close_drawer.clicked.connect(lambda: self.drawer.set_open(False))

        theme.on_change(self._restyle)
        self._restyle()

    @staticmethod
    def _card(w: QWidget, margins=(0, 0, 0, 0)) -> QWidget:
        card = QWidget()
        card.setObjectName("Card")
        card.setAttribute(Qt.WA_StyledBackground, True)
        l = QVBoxLayout(card)
        l.setContentsMargins(*margins)
        l.addWidget(w)
        return card

    def _restyle(self):
        p = theme.current()
        self.style_btn.setIcon(theme.icon("sliders-horizontal", p.text_muted, 18))
        self.export_btn.setIcon(theme.icon("download", p.text_muted, 18))
        self.close_drawer.setIcon(theme.icon("x", p.text_muted, 18))
        self.print_btn.setIcon(theme.icon("printer", p.accent_text, 18))

    def set_print_target(self, target: str):
        printer = target == "printer"
        self.print_btn.setText("Печать" if printer else "Сохранить PDF")
        self.export_btn.setVisible(printer)  # без принтера главная кнопка и так сохраняет PDF


class _NavShim:
    """Совместимость: window.nav.setCurrentRow(i) — перейти в раздел i."""

    def __init__(self, win):
        self._win = win

    def setCurrentRow(self, i: int):
        self._win.go(i)


class MainWindow(QMainWindow):
    SECTIONS = (("house", "Главная"), ("notebook-pen", "Тетрадь"), ("signature", "Почерки"),
                ("printer", "Принтеры"), ("settings", "Настройки"))

    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1400, 880)
        self.setMinimumSize(1100, 700)
        self.project = Project()

        self.rail = Rail(list(self.SECTIONS))
        self.stack = AnimatedStack()
        self.home = HomePage()
        self.work = WorkPage()
        self.hands = HandsPage()
        self.printers = PrintersPage()
        self.app_settings = AppSettingsPage()
        for w in (self.home, self.work, self.hands, self.printers, self.app_settings):
            self.stack.addWidget(w)
        self.rail.changed.connect(self.go)
        self.nav = _NavShim(self)

        central = QWidget()
        central.setObjectName("Page")
        lay = QHBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.rail)
        lay.addWidget(self.stack, 1)
        self.setCentralWidget(central)
        self.toast = Toast(central)

        # таймеры: предпросмотр — после паузы в наборе, автосохранение — реже
        self._preview_timer = QTimer(self, singleShot=True, interval=450)
        self._preview_timer.timeout.connect(self._update_preview)
        self._save_timer = QTimer(self, singleShot=True, interval=2000)
        self._save_timer.timeout.connect(self.save)

        w = self.work
        w.journal.changed.connect(self._changed)
        w.journal.selected.connect(w.preview.show_entry)
        w.settings.changed.connect(self._changed)
        w.title.textEdited.connect(self._changed)
        w.preview.results_ready.connect(w.journal.set_results)
        w.journal.capacity_fn = self._page_capacity
        w.export_btn.clicked.connect(self.export_pdf)
        w.print_btn.clicked.connect(self._main_action)
        self.home.new_requested.connect(self.new_project)
        self.home.open_requested.connect(self.open_dialog)
        self.home.import_requested.connect(self.import_txt)
        self.home.recent_requested.connect(self.open_path)
        self.printers.profiles_changed.connect(self._printers_changed)
        self.hands.hand_saved.connect(self._hand_saved)
        self.app_settings.prefs_changed.connect(self.apply_prefs)
        self.app_settings.onboarding_requested.connect(self.show_onboarding)
        self.app_settings.export_requested.connect(self.export_pack)
        self.app_settings.import_requested.connect(lambda: self.import_pack())

        self.addAction(QAction(self, shortcut=QKeySequence.Save, triggered=self.save))

        self.apply_prefs()
        self.go(HOME, animate=False)
        self._load_into_ui()

    # --- разделы и режимы ---

    def go(self, i: int, animate: bool = True):
        if animate:
            self.stack.go(i)
        else:
            self.stack.setCurrentIndex(i)
        self.rail.set_current(i, animate)
        if i == HOME:
            self.home.refresh()
        if i != WORK:
            self.work.drawer.set_open(False)

    def _adapt_to_mode(self) -> bool:
        """Пустые конспекты — под выбранный режим: у студента нет «Самостоятельной подготовки» и даты МЧС.
        Нужна и при запуске: первая тетрадь создаётся раньше, чем человек выберет режим в мастере."""
        if prefs()["mode"] == "mchs":
            return False
        kind = "study" if prefs()["mode"] == "study" else "free"
        changed = False
        for e in self.project.entries:
            if e.kind == "self" and not e.text.strip() and not e.topic.strip():
                e.kind, e.date, e.date_auto = kind, "", False
                changed = True
        return changed

    def apply_prefs(self):
        if self._adapt_to_mode():
            self._load_into_ui()
        p = prefs()
        self.work.journal.set_mode(p["mode"], p["ai"])
        self.work.set_print_target(p["print"])
        self.rail.set_visible_items([True, True, True, p["print"] == "printer", True])
        self.app_settings.refresh()

    def show_onboarding(self):
        from .onboarding import Onboarding
        ob = Onboarding(self.centralWidget())
        ob.finished_choice.connect(self._onboarded)
        ob.start()

    def _onboarded(self):
        AppSettings.set("onboarded", True)
        self.apply_prefs()
        self.toast.show_text("Готово! Можно начинать", "ok")

    # --- проект ---

    def _load_into_ui(self):
        p = self.project
        self.work.title.setText(p.title)
        self.work.journal.set_entries(p.entries, p.step_days)
        self.work.settings.load(p.page_settings(), p.hand_settings(), p.printer)
        self.work.saved.setText(f"{Path(p.path).name}" if p.path else "Не сохранена")
        self._update_preview()

    def _collect(self):
        p = self.project
        p.title = self.work.title.text().strip() or "Новая тетрадь"
        p.entries = self.work.journal.entries
        p.set_settings(self.work.settings.page_settings(), self.work.settings.hand_settings())
        p.printer = self.work.settings.printer_name()

    def _changed(self):
        self.work.saved.setText("Изменено…")
        self._preview_timer.start()
        self._save_timer.start()

    def _update_preview(self):
        s = self.work.settings
        self.work.preview.request(self.work.journal.snapshot(), s.page_settings(), s.hand_settings())

    def save(self):
        self._collect()
        empty = not any(e.text.strip() or e.topic.strip() for e in self.project.entries)
        if empty and not self.project.path:
            return  # пустую новую тетрадь не сохраняем
        try:
            self.project.save()
        except OSError as e:
            self.work.saved.setText("Не сохранено")
            QMessageBox.warning(self, "Сохранение", f"Не удалось сохранить тетрадь: {e}")
            return
        self.work.saved.setText(f"Сохранено · {Path(self.project.path).name}")

    def _switch_to(self, project: Project):
        if self._save_timer.isActive():
            self._save_timer.stop()
            self.save()
        self.project = project
        self._adapt_to_mode()
        self._load_into_ui()
        self.go(WORK)

    def new_project(self):
        self._switch_to(Project())

    def open_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Открыть тетрадь", str(documents_dir()),
                                              f"Тетради {APP_NAME} (*{FILE_EXT} *{OLD_FILE_EXT})")
        if path:
            self.open_path(path)

    def open_path(self, path: str):
        try:
            self._switch_to(Project.load(path))
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "Открытие", f"Не удалось открыть файл: {e}")

    # --- перенос на другой компьютер ---

    def export_pack(self):
        from ..brand import PACK_EXT
        from ..transfer import TransferError, export_pack
        self.save()  # в файл — то, что сейчас на экране
        current = self.project.path
        others = [p for p in sorted(documents_dir().glob(f"*{FILE_EXT}")) if str(p) != current]
        box = QMessageBox(self)
        box.setWindowTitle("Перенос на другой компьютер")
        box.setText("Калибровки принтеров, свои почерки и настройки сохранятся в один файл. Какие тетради "
                    "положить вместе с ними?")
        b_cur = box.addButton("Открытую тетрадь", QMessageBox.AcceptRole) if current else None
        b_all = box.addButton(f"Все тетради ({len(others) + (1 if current else 0)})", QMessageBox.AcceptRole) \
            if others else None
        b_none = box.addButton("Без тетрадей", QMessageBox.AcceptRole)
        box.addButton("Отмена", QMessageBox.RejectRole)
        box.setDefaultButton(b_cur or b_all or b_none)
        box.exec()
        clicked = box.clickedButton()
        if clicked is b_cur and b_cur is not None:
            notebooks = [current]
        elif clicked is b_all and b_all is not None:
            notebooks = ([current] if current else []) + [str(p) for p in others]
        elif clicked is b_none:
            notebooks = []
        else:
            return
        import datetime as dt
        start = Path.home() / "Desktop"
        name = f"{APP_NAME} — перенос {dt.date.today().strftime('%d.%m.%y')}{PACK_EXT}"
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить файл переноса",
                                              str((start if start.is_dir() else documents_dir()) / name),
                                              f"Перенос {APP_NAME} (*{PACK_EXT})")
        if not path:
            return
        if not path.lower().endswith(PACK_EXT):
            path += PACK_EXT
        try:
            got = export_pack(path, notebooks)
        except (OSError, TransferError) as e:
            QMessageBox.warning(self, "Перенос", f"Не удалось сохранить файл: {e}")
            return
        QMessageBox.information(self, "Перенос", f"Сохранено в «{Path(path).name}»: {got.describe()}.\n\n"
                                "На другом компьютере установите KonspektAI и откройте этот файл двойным щелчком "
                                "или через «Настройки» → «Загрузить из файла».")

    def import_pack(self, path: str | None = None):
        from ..brand import PACK_EXT
        from ..transfer import TransferError, import_pack, read_pack
        if path is None:
            start = Path.home() / "Desktop"
            path, _ = QFileDialog.getOpenFileName(self, "Загрузить файл переноса",
                                                  str(start if start.is_dir() else documents_dir()),
                                                  f"Перенос {APP_NAME} (*{PACK_EXT})")
            if not path:
                return
        try:
            info = read_pack(path)
        except TransferError as e:
            QMessageBox.warning(self, "Перенос", str(e))
            return
        when = f" от {info.created}" if info.created else ""
        if QMessageBox.question(self, "Перенос", f"Загрузить файл переноса{when}?\n\nВнутри: {info.describe()}.\n\n"
                                "Принтеры и почерки с теми же именами обновятся. Тетради, которые здесь уже есть и "
                                "отличаются, сохранятся рядом под новым именем — ничего не пропадёт.") \
                != QMessageBox.Yes:
            return
        if self._save_timer.isActive():
            self._save_timer.stop()
        self.save()
        try:
            got = import_pack(path, documents_dir())
        except (OSError, TransferError) as e:
            QMessageBox.warning(self, "Перенос", f"Не удалось загрузить: {e}")
            return
        # всё, что пришло, — сразу в программу
        self.work.settings.reload_fonts()
        self._printers_changed()
        self.apply_prefs()
        apply_theme(AppSettings.get("theme", THEMES[0]))
        self.app_settings.refresh()
        if hasattr(self.app_settings, "ai_settings"):
            self.app_settings.ai_settings._refresh()
        self.home.refresh()
        if got.notebooks:
            self.open_path(got.notebooks[0])
        QMessageBox.information(self, "Перенос", f"Загружено: {got.describe()}."
                                + ("\n\nОткрыта тетрадь «" + Path(got.notebooks[0]).stem + "»; остальные — на "
                                   "главной в «Недавних»." if len(got.notebooks) > 1 else ""))

    def import_txt(self):
        from ..documents import read_any
        path, _ = QFileDialog.getOpenFileName(self, "Текст конспекта", str(Path.home()),
                                              "Текст, Word, PDF, фото (*.txt *.docx *.doc *.pdf *.jpg *.jpeg *.png *.webp)")
        if not path:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            text = read_any(path)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Импорт", f"Не удалось прочитать файл: {e}")
            return
        QApplication.restoreOverrideCursor()
        p = Project(title=Path(path).stem)
        p.entries[0].topic = Path(path).stem
        p.entries[0].text = text
        p.entries[0].source = text
        self._switch_to(p)
        self._changed()

    def _page_capacity(self) -> int:
        from ..ai import page_capacity_chars
        from .preview import base_x_height
        s = self.work.settings
        hs = s.hand_settings()
        return page_capacity_chars(s.page_settings(), hs, base_x_height(hs))

    def _hand_saved(self, font_id: str):
        self.work.settings.reload_fonts(select=font_id or None)
        if font_id:
            self.go(WORK)
        self._changed()

    def _printers_changed(self):
        self.work.settings.reload_printers()
        self._changed()

    # --- вывод ---

    def _current_doc(self, method: str):
        """Свёрстанная тетрадь с поправками принтера для способа печати method."""
        from dataclasses import replace
        s = self.work.settings
        doc = self.work.preview.doc
        if doc is None or self._preview_timer.isActive() or not self.work.preview.is_current():
            # предпросмотр ещё не догнал текст — верстаем синхронно, чтобы печатать актуальное
            from ..engine.journal import build
            from .preview import base_x_height
            hs = s.hand_settings()
            doc, _ = build(self.work.journal.snapshot(), s.page_settings(method), hs, base_x_height(hs))
        return replace(doc, page=s.page_settings(method))

    def _main_action(self):
        if prefs()["print"] == "printer":
            self.print_()
        else:
            self.export_pdf()

    def export_pdf(self):
        from ..engine import printers
        self._collect()
        default = documents_dir() / f"{self.project.title}.pdf"
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить PDF", str(default), "PDF (*.pdf)")
        if not path:
            return
        try:
            export_pdf(self._current_doc(printers.PDF), path)  # PDF печатают из программы просмотра
        except OSError as e:
            QMessageBox.critical(self, "PDF", f"Не удалось сохранить PDF: {e}")
            return
        self.toast.show_text("PDF сохранён", "ok")

    def print_(self):
        from ..engine import printers
        self._collect()
        s = self.work.settings
        doc = self._current_doc(printers.DIRECT)
        PrintWizard(doc, self.project.title, s.printer_name(), s.page_settings(printers.DIRECT),
                    s.page_settings(printers.PDF), self).exec()

    def showEvent(self, e):
        super().showEvent(e)
        if not AppSettings.get("onboarded", False) and not getattr(self, "_ob_shown", False):
            self._ob_shown = True
            QTimer.singleShot(150, self.show_onboarding)
        if not getattr(self, "_update_checked", False):
            self._update_checked = True
            from .update_ui import check_on_start
            self._update_worker = check_on_start(self._update_found)

    def _update_found(self, rel):
        self.app_settings.updates.show_release(rel)
        self.toast.show_text(f"Доступна версия {rel.version} — обновить можно в Настройках")

    def closeEvent(self, e):
        self._preview_timer.stop()
        if self._save_timer.isActive():
            self._save_timer.stop()
            self.save()
        self.work.preview.shutdown()
        super().closeEvent(e)
