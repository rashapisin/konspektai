"""Импорт расписания: список занятий с галочками «писать конспект».

Занятия чужих групп (по умолчанию — группа обслуживания и УТП: их конспекты пишут другие) не показываются
и не добавляются; какие группы свои, человек выбирает галочками внизу, выбор запоминается."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QHBoxLayout, QHeaderView, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout)

from ..documents import GROUPS, Lesson
from ..engine.journal import KINDS
from .project import AppSettings
from .ui.widgets import label

DEFAULT_SKIP = ["maintenance", "utp"]  # пишем служебную (общая группа) и специальную (ШОМ)


def skipped_groups() -> set[str]:
    return set(AppSettings.get("schedule_skip_groups", DEFAULT_SKIP) or [])


class ScheduleDialog(QDialog):
    def __init__(self, lessons: list[Lesson], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Занятия из расписания")
        self.resize(900, 560)
        self.lessons = lessons
        self.title = label("", "h2")
        info = label("Отметьте темы, по которым нужно написать конспект. Темы только для изучения оставьте без "
                     "галочки — они добавятся серыми и не напечатаются.", "muted")
        self.table = QTableWidget(len(lessons), 5)
        self.table.setHorizontalHeaderLabels(["Писать", "Дата", "Вид", "Группа", "Тема"])
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.setFocusPolicy(Qt.NoFocus)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        for i, les in enumerate(lessons):
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            chk.setCheckState(Qt.Checked)
            self.table.setItem(i, 0, chk)
            group = GROUPS[les.group][1] if les.group in GROUPS else "—"
            for j, val in enumerate((les.date or "—", KINDS[les.kind], group, les.topic), start=1):
                it = QTableWidgetItem(val)
                it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                if j == 4 and les.questions:
                    it.setToolTip("\n".join(les.questions))
                self.table.setItem(i, j, it)
        self.table.resizeColumnsToContents()

        # свои и чужие группы: галочка — показывать и добавлять
        skip = skipped_groups()
        self.group_boxes: dict[str, QCheckBox] = {}
        found = [g for g in GROUPS if any(les.group == g for les in lessons)]
        groups_row = QHBoxLayout()
        if len(found) > 0:
            groups_row.addWidget(label("Группы:", "muted"))
        for g in found:
            n = sum(les.group == g for les in lessons)
            box = QCheckBox(f"{GROUPS[g][1]} — {KINDS[GROUPS[g][2]].lower()} ({n})")
            box.setChecked(g not in skip)
            box.toggled.connect(self._filter)
            self.group_boxes[g] = box
            groups_row.addWidget(box)
        groups_row.addStretch(1)

        add = QPushButton("Добавить в тетрадь")
        add.setProperty("kind", "primary")
        add.clicked.connect(self.accept)
        cancel = QPushButton("Отмена")
        cancel.setProperty("kind", "ghost")
        cancel.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(add)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 20)
        lay.setSpacing(12)
        lay.addWidget(self.title)
        lay.addWidget(info)
        lay.addWidget(self.table, 1)
        lay.addLayout(groups_row)
        lay.addLayout(buttons)
        self._filter()

    def _shown(self, les: Lesson) -> bool:
        box = self.group_boxes.get(les.group)
        return box is None or box.isChecked()  # группу не узнали — показываем

    def _filter(self):
        for i, les in enumerate(self.lessons):
            self.table.setRowHidden(i, not self._shown(les))
        shown = sum(self._shown(les) for les in self.lessons)
        hidden = len(self.lessons) - shown
        self.title.setText(f"Нашлось занятий: {shown}" + (f" (ещё {hidden} — других групп, скрыты)" if hidden else ""))

    def accept(self):
        # запоминаем, какие группы не наши, — в следующий раз скроются сразу
        skip = skipped_groups()
        for g, box in self.group_boxes.items():
            (skip.discard if box.isChecked() else skip.add)(g)
        AppSettings.set("schedule_skip_groups", sorted(skip))
        super().accept()

    def selection(self) -> list[tuple[Lesson, bool]]:
        return [(les, self.table.item(i, 0).checkState() == Qt.Checked) for i, les in enumerate(self.lessons)
                if self._shown(les)]
