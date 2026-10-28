"""Конспекты тетради: список (левая колонка) и редактор выбранного конспекта (центр).

Панель сама не рисуется целиком: главное окно размещает list_box и entry_box в разных колонках.
Что видно, зависит от режима: «Учёба» и «Просто писать» не показывают виды подготовки МЧС,
расписания и график дат.
"""

import copy

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QComboBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QPushButton, QVBoxLayout, QWidget)

from ..engine.journal import KINDS, Entry, EntryResult, recompute_dates
from .editor import EditorPanel
from .ui import theme
from .ui.widgets import FlowLayout

def _rows(n: int) -> str:
    """Склонение: 1 строка, 2 строки, 5 строк."""
    if n % 10 == 1 and n % 100 != 11:
        return "строка"
    return "строки" if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else "строк"


COMBO_KIND = {"self": "Самоподготовка", "service": "Служебная", "special": "Специальная"}
SHORT = {"self": "Самост.", "service": "Служеб.", "special": "Спец.", "free": "", "study": ""}
MODE_KIND = {"study": "study", "free": "free", "mchs": "self"}


def _icon_button(icon: str, tip: str, text: str = "", kind: str = "ghost") -> QPushButton:
    b = QPushButton(text)
    b.setProperty("kind", kind)
    b.setToolTip(tip)
    b.setCursor(Qt.PointingHandCursor)
    b._icon_name = icon
    return b


class JournalPanel(QWidget):
    changed = Signal()
    selected = Signal(str)  # id конспекта

    def __init__(self):
        super().__init__()
        self.entries: list[Entry] = []
        self.step_days = 4
        self.results: dict[str, EntryResult] = {}
        self._loading = False
        self.mode = "mchs"
        self.ai_mode = "chat"
        self._icon_buttons: list[QPushButton] = []
        self._undo: list[tuple] = []  # (конспекты, выбранный, что сделали, когда) — до действия
        self._redo: list[tuple] = []

        # ---------- левая колонка: список конспектов ----------
        title = QLabel("Конспекты")
        title.setProperty("role", "h2")
        add = _icon_button("plus", "Новый конспект — с новой страницы")
        add.clicked.connect(self.add_entry)
        head = QHBoxLayout()
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(add)
        self.list = QListWidget()
        self.list.setSpacing(2)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setWordWrap(True)
        self.list.currentRowChanged.connect(self._on_select)
        up = _icon_button("chevron-up", "Выше")
        down = _icon_button("chevron-down", "Ниже")
        self.undo_btn = _icon_button("undo-2", "Отменить последнее действие с тетрадью (Ctrl+Z)")
        self.redo_btn = _icon_button("redo-2", "Вернуть отменённое (Ctrl+Y)")
        self.undo_btn.clicked.connect(self.undo)
        self.redo_btn.clicked.connect(self.redo)
        rm = _icon_button("trash-2", "Удалить конспект")
        up.clicked.connect(lambda: self._move(-1))
        down.clicked.connect(lambda: self._move(1))
        rm.clicked.connect(self._remove)
        tools = QHBoxLayout()
        tools.addWidget(up)
        tools.addWidget(down)
        tools.addWidget(self.undo_btn)
        tools.addWidget(self.redo_btn)
        tools.addStretch(1)
        tools.addWidget(rm)
        self.sched_btn = _icon_button("calendar-range", "Расписание занятий в DOCX: выбрать темы для конспектов",
                                      "Расписание…", "")
        self.sched_btn.clicked.connect(self.import_schedule)
        self.plans_btn = _icon_button("file-up", "Файлы планов-конспектов: программа сама найдёт занятие",
                                      "Планы-конспекты…", "")
        self.plans_btn.clicked.connect(self.attach_plans)
        self.list_box = QWidget()
        ll = QVBoxLayout(self.list_box)
        ll.setContentsMargins(16, 16, 10, 12)
        ll.setSpacing(8)
        ll.addLayout(head)
        ll.addWidget(self.list, 1)
        ll.addLayout(tools)
        ll.addWidget(self.sched_btn)
        ll.addWidget(self.plans_btn)

        # ---------- центр: выбранный конспект ----------
        # тема — обычное поле ввода с подписью: раньше крупная «плоская» строка выглядела заголовком,
        # и тему писали в текст конспекта
        self.topic_label = QLabel("Тема")
        self.topic_label.setProperty("role", "muted")
        self.topic = QLineEdit()
        self.topic.setPlaceholderText("Например: Пожарные автомобили")
        self.topic.setMinimumHeight(36)
        self.topic.editingFinished.connect(lambda: self.topic.setCursorPosition(0))
        self.topic.returnPressed.connect(self._topic_enter)
        self.kind = QComboBox()
        for k, v in KINDS.items():  # в списке коротко, чтобы влезало в узкое окно; на листе — полностью
            self.kind.addItem(COMBO_KIND.get(k, v), k)
            self.kind.setItemData(self.kind.count() - 1, v, Qt.ToolTipRole)
        self.kind.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.date = QLineEdit()
        self.date.setPlaceholderText("Дата")
        self.date.setToolTip("Дата конспекта, например 05.01.26")
        self.date.setFixedWidth(self.date.fontMetrics().horizontalAdvance("00.00.0000") + 34)
        self.date_auto = QCheckBox()
        self.date_auto.setToolTip("Дата считается от предыдущего конспекта самоподготовки")
        self.write = QCheckBox("Писать в тетрадь")
        self.write.setToolTip("Снимите, если тему нужно только изучить — конспект не напечатается")
        self.fit = QCheckBox("Уместить на страницу")
        self.fit.setToolTip("Подобрать размер почерка так, чтобы конспект занял ровно одну страницу")
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setProperty("role", "muted")

        meta_top = QHBoxLayout()
        meta_top.setSpacing(10)
        meta_top.addWidget(self.kind)
        meta_top.addWidget(self.date)
        meta_top.addWidget(self.date_auto)
        meta_top.addStretch(1)
        meta_opts = QHBoxLayout()
        meta_opts.setSpacing(18)
        meta_opts.addWidget(self.write)
        meta_opts.addWidget(self.fit)
        meta_opts.addStretch(1)
        meta = QVBoxLayout()
        meta.setSpacing(8)
        meta.addLayout(meta_top)
        meta.addLayout(meta_opts)

        self.file_btn = _icon_button("file-up", "Текст из TXT, Word, PDF или фото", "Из файла", "")
        self.file_btn.clicked.connect(self.load_file)
        self.prompt_btn = _icon_button("copy", "Скопировать запрос «сжать до страницы» для любого чата",
                                       "Запрос для AI", "")
        self.prompt_btn.clicked.connect(self.copy_prompt)
        self.paste_btn = _icon_button("clipboard-paste", "Вставить ответ чата вместо текста конспекта",
                                      "Вставить ответ AI", "")
        self.paste_btn.clicked.connect(self.paste_answer)
        self.source_btn = _icon_button("eye", "Исходный материал: посмотреть или вернуть", "Исходник", "")
        self.source_btn.clicked.connect(self.show_source)
        self.ai_btn = _icon_button("sparkles", "Нейросеть сожмёт материал в конспект на одну страницу",
                                   "Сжать через AI", "")
        self.ai_btn.clicked.connect(self.ai_compress)
        self.write_btn = _icon_button("sparkles", "Нейросеть напишет конспект по теме на одну страницу. Может "
                                      "выдумывать — проверьте по учебнику или документам",
                                      "Написать конспект", "primary")
        self.write_btn.setMinimumHeight(36)
        self.write_btn.clicked.connect(self.ai_write)
        self._ai_job = None
        self._fit_ai: dict[str, tuple[int, int]] = {}  # конспект → (сколько раз ещё сокращать, hash текста)
        actions = FlowLayout(spacing=6)  # в узком окне кнопки переносятся, а не обрезаются
        for b in (self.file_btn, self.ai_btn, self.prompt_btn, self.paste_btn, self.source_btn):
            actions.addWidget(b)
        from PySide6.QtGui import QKeySequence, QShortcut
        for seq, fn in ((QKeySequence.Undo, self.undo), (QKeySequence.Redo, self.redo), ("Ctrl+Y", self.redo)):
            QShortcut(QKeySequence(seq), self, activated=fn, context=Qt.WidgetWithChildrenShortcut)
        self.capacity_fn = lambda: 1400  # главное окно подставит оценку по текущему почерку

        self.editor = EditorPanel()
        self.entry_box = QWidget()
        el = QVBoxLayout(self.entry_box)
        el.setContentsMargins(14, 12, 14, 12)
        el.setSpacing(8)
        topic_row = QHBoxLayout()
        topic_row.setSpacing(8)
        el.addWidget(self.topic_label)
        el.addLayout(topic_row)
        topic_row.addWidget(self.topic, 1)
        topic_row.addWidget(self.write_btn)
        el.addLayout(meta)
        el.addWidget(self.status)
        el.addLayout(actions)
        el.addWidget(self.editor, 1)

        self._icon_buttons = [add, up, down, rm, self.undo_btn, self.redo_btn, self.sched_btn, self.plans_btn, self.file_btn, self.prompt_btn,
                              self.paste_btn, self.source_btn, self.ai_btn, self.write_btn]
        theme.on_change(self._restyle_icons)
        theme.on_change(lambda: self._refresh_list(keep_row=True))
        self._restyle_icons()

        self.kind.currentIndexChanged.connect(self._edited)
        self.date.textEdited.connect(self._date_edited)
        self.date_auto.toggled.connect(self._edited)
        self.topic.textEdited.connect(self._edited)
        self.write.toggled.connect(self._edited)
        self.fit.toggled.connect(self._edited)
        self.editor.changed.connect(self._edited)
        self.set_mode(self.mode, self.ai_mode)

    def _restyle_icons(self):
        col = theme.current().text_muted
        for b in self._icon_buttons:
            b.setIcon(theme.icon(b._icon_name, col, 18))
        self.write_btn.setIcon(theme.icon(self.write_btn._icon_name, theme.current().accent_text, 18))

    def set_mode(self, mode: str, ai_mode: str):
        """Показать только то, что нужно в выбранном режиме."""
        self.mode, self.ai_mode = mode, ai_mode
        mchs = mode == "mchs"
        for w in (self.kind, self.sched_btn, self.plans_btn, self.write):
            w.setVisible(mchs)
        self.editor.set_mchs(mchs)
        self.date_auto.setVisible(mchs and (self.current() is not None and self.current().kind == "self"))
        self.prompt_btn.setVisible(ai_mode == "chat")
        self.paste_btn.setVisible(ai_mode == "chat")
        self.ai_btn.setVisible(ai_mode == "api")
        self.write_btn.setVisible(ai_mode == "api")
        self._ai_finished()  # подпись — с названием выбранной нейросети
        self.topic_label.setText("Тема" if mode != "free" else "Название (не печатается)")
        self._refresh_list(keep_row=True)

    # --- данные ---

    def set_entries(self, entries: list[Entry], step_days: int):
        self._undo.clear()
        self._redo.clear()
        self._sync_history()
        self.entries = entries or [Entry()]
        self.step_days = step_days
        self.results = {}
        self._refresh_list()
        self.list.setCurrentRow(0)

    def snapshot(self) -> list[Entry]:
        return copy.deepcopy(self.entries)

    def current(self) -> Entry | None:
        i = self.list.currentRow()
        return self.entries[i] if 0 <= i < len(self.entries) else None

    def set_results(self, results: list[EntryResult]):
        self.results = {r.entry_id: r for r in results}
        for e in self.entries:  # подобранный размер — подсказка для следующей вёрстки и при открытии тетради
            r = self.results.get(e.id)
            if r is not None and e.fit:
                e.fit_size = r.x_height_mm
        self._refresh_list(keep_row=True)
        self._update_status()
        self._check_ai_fit()

    def _check_ai_fit(self):
        """Конспект от нейросети при «Уместить на страницу» не влез даже мелким почерком — просим её сократить
        до объёма, который точно помещается (по числу строк на странице), не больше двух раз. Объём заранее
        оценивается по числу знаков и бывает неточен: здесь — по настоящей вёрстке."""
        from ..ai import shorten
        for eid, (left, h) in list(self._fit_ai.items()):
            e = next((x for x in self.entries if x.id == eid), None)
            r = self.results.get(eid)
            if e is None or not e.fit or not e.write or hash(e.text) != h:
                self._fit_ai.pop(eid)  # текст правили руками или «уместить» сняли — не вмешиваемся
                continue
            if r is None or r.text_hash != h:
                continue  # вёрстка нового текста ещё не готова
            if not r.overflow_rows or left <= 0 or r.rows <= 0:
                self._fit_ai.pop(eid)
                continue
            if self._ai_job is not None and self._ai_job.isRunning():
                continue
            target = int(len(e.text) * r.rows / (r.rows + r.overflow_rows) * 0.92)
            self._fit_ai.pop(eid)
            self._run_ai(e, "сокращение до страницы",
                         lambda llm, limit, t=e.text, n=target, tp=e.topic: (shorten(llm, t, n, tp), None),
                         fit_tries=left - 1, busy="сокращает до страницы…")

    def _topic_enter(self):
        """Enter в теме: если текста ещё нет — сразу писать конспект, иначе — к тексту."""
        e = self.current()
        if e is not None and not e.text.strip() and self.ai_mode == "api" and self.write_btn.isEnabled():
            self.ai_write()
        else:
            self.editor.edit.setFocus()

    # --- список ---

    def _label(self, e: Entry) -> tuple[str, str, str]:
        """(тема, строка под ней, состояние: ok | warn | off)."""
        r = self.results.get(e.id)
        state = "ok"
        if not e.write:
            info, state = "только изучить", "off"
        elif r is None:
            info = "считаю…"
        elif r.overflow_rows and e.fit and self.mode == "mchs":
            info, state = f"1 стр. + {r.overflow_rows} {_rows(r.overflow_rows)} на следующей", "more"
        else:
            info = f"{r.pages} стр. · {r.fill:.0%}"
        meta = [x for x in (e.date, SHORT.get(e.kind, "") if self.mode == "mchs" else "", info) if x]
        return e.title(), "  ·  ".join(meta), state

    def _item_widget(self, title: str, meta: str, state: str) -> QWidget:
        p = theme.current()
        w = QWidget()
        w.setAttribute(Qt.WA_TransparentForMouseEvents)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(10, 7, 10, 7)
        lay.setSpacing(1)
        t = QLabel()
        t.setStyleSheet(f"font-weight: 600; color: {p.text_muted if state == 'off' else p.text};"
                        " background: transparent;")
        width = max(120, self.list.viewport().width() - 34)  # длинное — с многоточием, а не обрезано
        t.setText(t.fontMetrics().elidedText(title, Qt.ElideRight, width))
        m = QLabel()
        m.setToolTip(meta)
        col = {"more": p.accent}.get(state, p.text_muted)
        m.setStyleSheet(f"color: {col}; font-size: 8.5pt; background: transparent;")
        m.setText(m.fontMetrics().elidedText(meta, Qt.ElideRight, width))
        lay.addWidget(t)
        lay.addWidget(m)
        return w

    def _refresh_list(self, keep_row: bool = False):
        row = self.list.currentRow()
        self.list.blockSignals(True)
        self.list.clear()
        for e in self.entries:
            title, meta, state = self._label(e)
            it = QListWidgetItem()
            it.setToolTip(title)
            self.list.addItem(it)
            w = self._item_widget(title, meta, state)
            it.setSizeHint(QSize(0, max(54, w.sizeHint().height() + 6)))  # две строки и воздух
            self.list.setItemWidget(it, w)
        if keep_row and 0 <= row < len(self.entries):
            # тот же конспект: выделение возвращаем молча — иначе он «выбирается» заново, текст в поле
            # перезагружается, курсор прыгает в начало (буквы шли задом наперёд), предпросмотр — на 1-ю страницу
            self.list.setCurrentRow(row)
        self.list.blockSignals(False)

    def _on_select(self, row: int):
        e = self.current()
        if e is None:
            return
        self._loading = True
        self.kind.setCurrentIndex(max(0, self.kind.findData(e.kind)))
        self.date.setText(e.date)
        self.date_auto.setChecked(e.date_auto)
        self.date_auto.setText(f"авто: +{self.step_days} дня")
        self.date_auto.setToolTip(f"Дата считается сама: +{self.step_days} дня от предыдущего конспекта "
                                  "самоподготовки")
        self.date_auto.setVisible(self.mode == "mchs" and e.kind == "self")
        self.topic.setText(e.topic)
        self.topic.setCursorPosition(0)  # длинная тема — видно начало, а не хвост
        self.write.setChecked(e.write)
        self.fit.setChecked(e.fit)
        self.editor.set_text(e.text)
        self._loading = False
        self._update_status()
        self.selected.emit(e.id)

    def _update_status(self):
        e = self.current()
        r = self.results.get(e.id) if e else None
        if e is None or not e.write:
            self.status.setText("Этот конспект не печатается." if e else "")
        elif r is None:
            self.status.setText("Считаю страницы…")
        elif r.overflow_rows and e.fit and self.mode == "mchs":
            self.status.setText(f"На одну страницу не уместилось даже мелким почерком — {r.overflow_rows} "
                                f"{_rows(r.overflow_rows)} продолжаются на следующей. "
                                "Если нужна одна страница, текст можно сократить.")
        elif r.overflow_rows:
            self.status.setText(f"{r.pages} стр.: текст продолжается на следующей странице.")
        else:
            size = f", почерк {r.x_height_mm:.2f} мм" if e.fit else ""
            self.status.setText(f"{r.pages} стр., последняя заполнена на {r.fill:.0%}{size}.")

    # --- правка ---

    def _edited(self):
        if self._loading:
            return
        e = self.current()
        if e is None:
            return
        self._checkpoint("правку", coalesce=True)  # набор подряд — одним шагом
        e.kind = self.kind.currentData()
        e.date_auto = self.date_auto.isChecked()
        e.topic = self.topic.text()
        e.write = self.write.isChecked()
        e.fit = self.fit.isChecked()
        e.text = self.editor.text()
        self.date_auto.setVisible(self.mode == "mchs" and e.kind == "self")
        self._after_change()

    def _date_edited(self, text: str):
        e = self.current()
        if e is None or self._loading:
            return
        self._checkpoint("смену даты", coalesce=True)
        e.date = text.strip()
        e.date_auto = False  # дату поправили руками — дальше график считается от неё
        self._loading = True
        self.date_auto.setChecked(False)
        self._loading = False
        self._after_change()

    def _after_change(self):
        recompute_dates(self.entries, self.step_days)
        e = self.current()
        if e is not None and self.date.text() != e.date:
            self._loading = True
            self.date.setText(e.date)
            self._loading = False
        self.results.pop(e.id, None) if e else None
        self._refresh_list(keep_row=True)
        self._update_status()
        self.changed.emit()

    def add_entry(self):
        cur = self.current()
        kind = cur.kind if cur and self.mode == "mchs" else MODE_KIND.get(self.mode, "self")
        self._checkpoint("новый конспект")
        e = Entry(kind=kind)
        if kind != "self" and cur is not None:
            e.date = cur.date  # служебная/специальная: по умолчанию тот же день
        i = self.list.currentRow() + 1 if cur else len(self.entries)
        self.entries.insert(i, e)
        recompute_dates(self.entries, self.step_days)
        self._refresh_list()
        self.list.setCurrentRow(i)
        self.topic.setFocus()
        self.changed.emit()

    def _move(self, d: int):
        i = self.list.currentRow()
        j = i + d
        if not (0 <= i < len(self.entries) and 0 <= j < len(self.entries)):
            return
        self._checkpoint("перемещение")
        self.entries[i], self.entries[j] = self.entries[j], self.entries[i]
        recompute_dates(self.entries, self.step_days)
        self._refresh_list()
        self.list.setCurrentRow(j)
        self.changed.emit()

    def _remove(self):
        from PySide6.QtWidgets import QMessageBox
        i = self.list.currentRow()
        if not (0 <= i < len(self.entries)) or len(self.entries) == 1:
            return
        ans = QMessageBox.question(self, "Удалить конспект",
                                   f"Удалить конспект «{self.entries[i].title()}» вместе с текстом?")
        if ans != QMessageBox.Yes:
            return
        self._checkpoint("удаление конспекта")
        del self.entries[i]
        recompute_dates(self.entries, self.step_days)
        self._refresh_list()
        self.list.setCurrentRow(min(i, len(self.entries) - 1))
        self.changed.emit()

    # --- отмена действий ---

    def _checkpoint(self, what: str, coalesce: bool = False):
        """Запомнить тетрадь до действия. coalesce — набор текста подряд (пауза меньше 2 с) одним шагом."""
        import time
        now = time.monotonic()
        if coalesce and self._undo and self._undo[-1][2] == what and now - self._undo[-1][3] < 2.0:
            self._undo[-1] = (*self._undo[-1][:3], now)
            return
        self._undo.append((copy.deepcopy(self.entries), self.list.currentRow(), what, now))
        del self._undo[:-100]  # хватит с запасом
        self._redo.clear()
        self._sync_history()

    def _restore(self, src: list, dst: list, verb: str):
        if not src:
            return
        entries, row, what, _ = src.pop()
        dst.append((copy.deepcopy(self.entries), self.list.currentRow(), what, 0.0))
        self.entries = entries
        recompute_dates(self.entries, self.step_days)
        self.results = {}
        self._refresh_list()
        self.list.setCurrentRow(max(0, min(row, len(self.entries) - 1)))
        self._on_select(self.list.currentRow())
        self._sync_history()
        self.changed.emit()
        toast = getattr(self.window(), "toast", None)
        if toast is not None:
            toast.show_text(f"{verb}: {what}")

    def undo(self):
        self._restore(self._undo, self._redo, "Отменено")

    def redo(self):
        self._restore(self._redo, self._undo, "Возвращено")

    def _sync_history(self):
        self.undo_btn.setEnabled(bool(self._undo))
        self.redo_btn.setEnabled(bool(self._redo))
        self.undo_btn.setToolTip(f"Отменить {self._undo[-1][2]} (Ctrl+Z)" if self._undo
                                 else "Отменять пока нечего")
        self.redo_btn.setToolTip(f"Вернуть {self._redo[-1][2]} (Ctrl+Y)" if self._redo else "Возвращать нечего")

    # --- документы и AI ---

    def _replace_text(self, e: Entry, text: str, checkpoint: bool = True):
        if checkpoint:
            self._checkpoint("замену текста")
        e.text = text
        self._loading = True
        self.editor.set_text(text)
        self._loading = False
        self._after_change()

    def import_schedule(self):
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        from ..documents import parse_schedule
        from .import_dialog import ScheduleDialog
        files, _ = QFileDialog.getOpenFileNames(self, "Расписание занятий", "", "Документы Word (*.docx)")
        if not files:
            return
        lessons = []
        for f in files:
            try:
                lessons += parse_schedule(f)
            except Exception as ex:
                QMessageBox.warning(self, "Расписание", f"Не удалось прочитать «{f}»: {ex}")
        if not lessons:
            QMessageBox.information(self, "Расписание", "В выбранных файлах не нашлось таблицы с датами занятий.")
            return
        lessons.sort(key=lambda les: (les.date[6:], les.date[3:5], les.date[:2]))
        dlg = ScheduleDialog(lessons, self)
        if not dlg.exec():
            return
        new = [Entry(kind=les.kind, date=les.date, date_auto=False, topic=les.topic, write=write)
               for les, write in dlg.selection()]
        self._checkpoint("импорт расписания")
        # пустой стартовый конспект заменяем, а не оставляем первым
        if len(self.entries) == 1 and not self.entries[0].text.strip() and not self.entries[0].topic.strip():
            self.entries.clear()
        start = len(self.entries)
        self.entries.extend(new)
        recompute_dates(self.entries, self.step_days)
        self._refresh_list()
        self.list.setCurrentRow(start)
        self.changed.emit()

    def attach_plans(self):
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        from ..documents import match_plan, parse_plan
        files, _ = QFileDialog.getOpenFileNames(self, "Планы-конспекты", "",
                                                "Word, PDF, сканы (*.docx *.doc *.pdf *.jpg *.jpeg *.png *.webp)")
        if not files:
            return
        plans, bad = [], []
        for f in files:
            try:
                plans.append(parse_plan(f))
            except Exception:
                bad.append(f)
        self._checkpoint("планы-конспекты")
        used, matched = set(), 0
        for e in self.entries:
            p = match_plan(e.topic, [p for p in plans if id(p) not in used])
            if p is None:
                continue
            used.add(id(p))
            e.source = p.text
            if not e.text.strip():
                e.text = p.text
            matched += 1
        unmatched = [p.topic or "(без темы)" for p in plans if id(p) not in used]
        self._on_select(self.list.currentRow())
        self._after_change()
        msg = f"Прикреплено к занятиям: {matched}."
        if unmatched:
            msg += "\n\nНе нашлось занятия с похожей темой:\n" + "\n".join(f"• {t}" for t in unmatched)
        if bad:
            msg += "\n\nНе удалось прочитать:\n" + "\n".join(bad)
        if matched:
            msg += ("\n\nТекст плана-конспекта длиннее страницы. Нажмите «Запрос для AI», "
                    "чтобы сжать его в любом чате, затем «Вставить ответ AI».")
        QMessageBox.information(self, "Планы-конспекты", msg)

    def load_file(self):
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication
        from ..documents import parse_plan, read_any
        e = self.current()
        if e is None:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Текст конспекта", "",
                                              "Текст, Word, PDF, фото (*.txt *.docx *.doc *.pdf *.jpg *.jpeg *.png *.webp)")
        if not path:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)  # распознавание сканов занимает секунды
        try:
            text = read_any(path)
            if "учебный вопрос" in text.lower() and not path.lower().endswith(".txt"):
                plan = parse_plan(path)  # план-конспект: убираем шапку, литературу и подписи
                text = plan.text
                if not e.topic.strip():
                    e.topic = plan.topic
                    self.topic.setText(plan.topic)
        except Exception as ex:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Файл", f"Не удалось прочитать файл: {ex}")
            return
        QApplication.restoreOverrideCursor()
        if e.text.strip() and QMessageBox.question(self, "Файл", "Заменить текст конспекта текстом из файла?") \
                != QMessageBox.Yes:
            return
        self._checkpoint("загрузку файла")
        e.source = text
        self._replace_text(e, text, checkpoint=False)

    def copy_prompt(self):
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtWidgets import QMessageBox
        from ..ai import build_prompt
        e = self.current()
        if e is None:
            return
        src = e.source.strip() or e.text.strip()
        if not src:
            QMessageBox.information(self, "AI", "Сначала загрузите материал: «Из файла…» или «Прикрепить планы-конспекты…».")
            return
        target = int(self.capacity_fn() * 0.85)
        QGuiApplication.clipboard().setText(build_prompt(e, src, target))
        QMessageBox.information(self, "Запрос для AI", f"Запрос скопирован (объём — до {target} знаков).\n\n"
                                "1. Откройте любой чат с AI и вставьте запрос (Ctrl+V).\n"
                                "2. Скопируйте ответ целиком.\n"
                                "3. Вернитесь сюда и нажмите «Вставить ответ AI».\n\n"
                                "Проверьте результат: AI может ошибаться в цифрах и определениях.")

    def ai_compress(self):
        """Материал (исходник или текущий текст) → нейросеть → конспект на страницу. Исходник сохраняется."""
        from PySide6.QtWidgets import QMessageBox
        from ..ai import compress
        from .ai_ui import provider_name
        e = self.current()
        if e is None:
            return
        src = e.source.strip() or e.text.strip()
        if not src:
            QMessageBox.information(self, provider_name(), "Сначала вставьте или загрузите материал: «Из файла» "
                                                           "или просто текст в поле конспекта. Нет материала — "
                                                           "нажмите «Написать по теме».")
            return
        self._run_ai(e, "сжатие нейросетью", lambda llm, limit: (compress(llm, e, src, limit), None))

    def ai_write(self):
        """Конспект с нуля по теме. Источники для проверки — в «Исходник», в тетрадь они не попадают."""
        from PySide6.QtWidgets import QMessageBox
        from ..ai import write_from_topic
        from .ai_ui import provider_name
        e = self.current()
        if e is None:
            return
        if not e.topic.strip():
            QMessageBox.information(self, provider_name(), "Впишите тему конспекта — нейросеть напишет по ней.")
            self.topic.setFocus()
            return
        if e.text.strip() and QMessageBox.question(
                self, provider_name(), "Заменить текст конспекта написанным по теме? Прежний можно будет вернуть "
                                       "кнопкой «Отменить».") != QMessageBox.Yes:
            return
        self._run_ai(e, "конспект по теме", lambda llm, limit: write_from_topic(llm, e, limit))

    def _run_ai(self, e: Entry, what: str, fn, fit_tries: int = 2, busy: str = "пишет конспект…"):
        """fn(нейросеть, объём) → (текст, источники или None) в фоне; результат — в конспект, с отменой.
        fit_tries — сколько раз ещё можно попросить сократить, если с «Уместить на страницу» не влезет."""
        from PySide6.QtWidgets import QMessageBox
        from .ai_ui import Job, client, provider_name
        if self._ai_job is not None and self._ai_job.isRunning():
            return
        llm = client()
        if llm is None:
            QMessageBox.information(self, provider_name(), "Подключите нейросеть: «Настройки» → «Нейросеть» — "
                                                           "ключ и модель. Бесплатно — с GigaChat.")
            return
        limit = int(self.capacity_fn() * 0.8)  # с запасом: нейросети пишут чуть длиннее, чем просят
        for b in (self.ai_btn, self.write_btn):
            b.setEnabled(False)
        self.ai_btn.setText(f"{provider_name()} {busy}")
        self.write_btn.setText(f"{provider_name()} {busy}")
        entry_id = e.id

        def done(result):
            self._ai_finished()
            text, sources = result
            target = next((x for x in self.entries if x.id == entry_id), None)
            if target is None or len(text) < 40:
                QMessageBox.warning(self, provider_name(), "Ответ получился пустым. Попробуйте ещё раз.")
                return
            self._checkpoint(what)
            if sources is not None:  # написано с нуля: в «Исходник» — откуда проверять
                target.source = (f"Конспект написан нейросетью ({provider_name()}) по теме «{target.topic}» без "
                                 "материала — это черновик. Нейросеть может выдумывать числа, правила и даже "
                                 "названия документов: проверьте всё по настоящим источникам.\n\n"
                                 "Источники, которые назвала нейросеть (существуют ли — тоже проверьте):\n"
                                 f"{sources or 'не назвала'}")
            elif not target.source.strip():
                target.source = target.text  # «Исходник» вернёт прежний текст
            if target.fit:
                self._fit_ai[entry_id] = (fit_tries, hash(text))  # проверим по вёрстке, влезло ли
            if target is self.current():
                self._replace_text(target, text, checkpoint=False)
            else:
                target.text = text
                self._after_change()
            toast = getattr(self.window(), "toast", None)
            if toast is not None:  # нейросеть может склеить правила или ошибиться в числах — пусть проверят
                toast.show_text("Готово. Проверьте числа и формулировки: нейросеть может ошибаться"
                                + (" (источники — в «Исходнике»)" if sources is not None else ""), "warn")

        def failed(msg):
            self._ai_finished()
            QMessageBox.warning(self, provider_name(), msg)

        self._ai_job = Job(lambda: fn(llm, limit))
        self._ai_job.done.connect(done)
        self._ai_job.failed.connect(failed)
        self._ai_job.start()

    def _ai_finished(self):
        from .ai_ui import provider_name
        for b in (self.ai_btn, self.write_btn):
            b.setEnabled(True)
        self.ai_btn.setText(f"Сжать через {provider_name()}")
        self.write_btn.setText("Написать конспект")
        self.write_btn.setToolTip(f"{provider_name()} напишет конспект по теме на одну страницу. Может "
                                  "выдумывать — проверьте по учебнику или документам")

    def paste_answer(self):
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtWidgets import QMessageBox
        from ..ai import clean_answer
        e = self.current()
        if e is None:
            return
        text = clean_answer(QGuiApplication.clipboard().text(), e.topic)
        if len(text) < 40:
            QMessageBox.information(self, "AI", "В буфере обмена нет ответа. Скопируйте ответ чата целиком.")
            return
        self._checkpoint("вставку ответа")
        if not e.source.strip():
            e.source = e.text  # чтобы можно было вернуть прежний текст
        self._replace_text(e, text, checkpoint=False)

    def show_source(self):
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QMessageBox, QPlainTextEdit, QVBoxLayout
        e = self.current()
        if e is None or not e.source.strip():
            QMessageBox.information(self, "Исходник", "У этого конспекта нет исходного материала.")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Исходник: {e.title()}")
        dlg.resize(760, 640)
        view = QPlainTextEdit(e.source)
        view.setReadOnly(True)
        info = QLabel(f"Исходник: {len(e.source)} знаков, конспект сейчас: {len(e.text)} знаков.")
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        restore = buttons.addButton("Вернуть исходный текст в конспект", QDialogButtonBox.ActionRole)
        buttons.rejected.connect(dlg.reject)
        restore.clicked.connect(lambda: (self._replace_text(e, e.source), dlg.accept()))
        lay = QVBoxLayout(dlg)
        lay.addWidget(info)
        lay.addWidget(view, 1)
        lay.addWidget(buttons)
        dlg.exec()
