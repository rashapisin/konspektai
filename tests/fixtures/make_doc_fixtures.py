"""Как сделаны .doc-образцы для тестов (данные выдуманные): python make_doc_fixtures.py <папка>, затем
soffice --headless --convert-to doc:"MS Word 97" расписание.docx план.docx — и переименовать."""
import sys
import docx
from docx.enum.text import WD_BREAK
out = sys.argv[1]

# Расписание как у ШОМ: дата объединена на весь день, «Тема № 13» с середины строки, разрыв страницы
d = docx.Document()
t = d.add_table(rows=1, cols=1)
t.rows[0].cells[0].text = "УТВЕРЖДАЮ\nНачальник отряда\n«___» ________ 2026 г."
d.add_paragraph("Расписание занятий на октябрь 2026 года")
d.add_paragraph("с группой по тактической подготовке")
t = d.add_table(rows=4, cols=4)
for i, h in enumerate(("Дата", "Часы занятий", "Предмет обучения, тема и учебные вопросы занятий", "Метод проведения")):
    t.rows[0].cells[i].text = h
t.rows[1].cells[0].text = "15.10.2026"
t.cell(1, 0).merge(t.cell(3, 0))
t.rows[1].cells[2].text = "Групповое упражнение (деловая игра):\nТушение пожаров в резервуарах."
t.rows[2].cells[2].text = "Школа оперативного мастерства:        Тема № 13 «Закономерности развития пожара»."
t.rows[3].cells[2].text = "Анализ организации пожаротушения за 2025 год"
for r in (1, 2, 3):
    t.rows[r].cells[3].text = "Практическое"
d.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
t = d.add_table(rows=1, cols=4)
t.rows[0].cells[0].text = "16.10.2026"
t.rows[0].cells[2].text = ("Тема № 4\n«Кодекс чести сотрудника»\n\n\nТема №8.\n«Предупреждение должностных преступлений»")
t.rows[0].cells[3].text = "Классно-групповой"
d.add_paragraph("Инженер отделения")
d.save(f"{out}/расписание.docx")

# План-конспект: шапка-таблица «Тема № 9:» | «…», литература, без «Развёрнутого плана»
d = docx.Document()
d.add_paragraph("УТВЕРЖДАЮ")
d.add_paragraph("Начальник отряда")
d.add_paragraph("«___» ________ 2026 г.")
t = d.add_table(rows=2, cols=2)
t.rows[0].cells[0].text, t.rows[0].cells[1].text = "ПЛАН-КОНСПЕКТ", "Проведения занятий по служебной подготовке"
t.rows[1].cells[0].text, t.rows[1].cells[1].text = "Тема № 9:", "«Полномочия органов власти в области пожарной безопасности»"
d.add_paragraph("Литература, используемая при проведении занятия:")
d.add_paragraph("Ресурсы сети Интернет")
d.add_paragraph("Учебный вопрос № 1 – Полномочия федеральных органов. 45 минут.")
d.add_paragraph("К полномочиям федеральных органов относятся:")
d.add_paragraph("организация федерального государственного пожарного надзора;")
d.add_paragraph("Пособия и оборудование, используемые на занятии: не используются.")
d.add_paragraph("Инженер отделения")
d.save(f"{out}/план.docx")
