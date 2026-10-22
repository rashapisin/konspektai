"""Импорт расписания: список занятий с галочками «писать конспект»."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QHeaderView, QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout)

from ..documents import Lesson
from ..engine.journal import KINDS
from .ui.widgets import label


class ScheduleDialog(QDialog):
    def __init__(self, lessons: list[Lesson], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Занятия из расписания")
        self.resize(860, 520)
        self.lessons = lessons
        title = label(f"Нашлось занятий: {len(lessons)}", "h2")
        info = label("Отметьте темы, по которым нужно написать конспект. Темы только для изучения оставьте без "
                     "галочки — они добавятся серыми и не напечатаются.", "muted")
        self.table = QTableWidget(len(lessons), 4)
        self.table.setHorizontalHeaderLabels(["Писать", "Дата", "Вид", "Тема"])
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.setFocusPolicy(Qt.NoFocus)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        for i, les in enumerate(lessons):
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            chk.setCheckState(Qt.Checked)
            self.table.setItem(i, 0, chk)
            for j, val in enumerate((les.date, KINDS[les.kind], les.topic), start=1):
                it = QTableWidgetItem(val)
                it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                if j == 3 and les.questions:
                    it.setToolTip("\n".join(les.questions))
                self.table.setItem(i, j, it)
        self.table.resizeColumnsToContents()
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
        lay.addWidget(title)
        lay.addWidget(info)
        lay.addWidget(self.table, 1)
        lay.addLayout(buttons)

    def selection(self) -> list[tuple[Lesson, bool]]:
        return [(les, self.table.item(i, 0).checkState() == Qt.Checked) for i, les in enumerate(self.lessons)]
