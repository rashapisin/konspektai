"""Разбор расписания и плана-конспекта на искусственных документах того же вида, что и настоящие."""

import docx
import pytest

from stv.ai import build_prompt, clean_answer
from stv.documents import match_plan, parse_plan, parse_schedule
from stv.engine.journal import Entry


def _schedule(path, special=False):
    d = docx.Document()
    t = d.add_table(rows=1, cols=1)
    t.rows[0].cells[0].text = "УТВЕРЖДАЮ\nНачальник отряда\n«___» ____ 2026 г."
    d.add_paragraph("Расписание занятий по специальной подготовке на апрель 2026 года" if special
                    else "Расписание занятий на апрель 2026 года")
    d.add_paragraph("с общей группой")
    t = d.add_table(rows=4, cols=4)
    for i, h in enumerate(("Дата", "Часы занятий", "Предмет обучения, тема и учебные вопросы занятий", "Метод")):
        t.rows[0].cells[i].text = h
    for i in range(4):
        t.rows[1].cells[i].text = str(i + 1)
    t.rows[2].cells[0].text = "08.04.2026"
    t.rows[2].cells[2].text = ("Психологическая подготовка\nТема № 2. Последствия хронического стресса.\n"
                               "Эмоциональное выгорание.\nУчебный вопрос № 1 Последствия (35 мин).\n"
                               "Учебный вопрос №2 – Выгорание (35 мин).")
    t.rows[3].cells[0].text = "09.04.2026"
    t.rows[3].cells[2].text = "Тема № 10 Требование к оборудованию мест проведения соревнований"
    d.add_paragraph("Инженер отделения")
    d.save(path)


def _plan(path):
    d = docx.Document()
    for t in ("УТВЕРЖДАЮ", "Начальник отряда", "ПЛАН-КОНСПЕКТ", "по служебной подготовке",
              "Тема: Последствия хронического стресса. Эмоциональное выгорание.",
              "Цель занятия: Рассмотрение последствий стресса.", "Литература:", "1. Бойко В.В. Синдром выгорания.",
              "Развернутый план занятия:", "Учебный вопрос №1 – Последствия хронического стресса (35 мин).",
              "Хронический стресс действует разрушительно."):
        d.add_paragraph(t)
    d.add_paragraph("снижение продуктивности в работе", style="List Bullet")
    d.add_paragraph("2. Учебный вопрос №2 – Эмоциональное выгорание (35 мин).")
    d.add_paragraph("Эмоциональное выгорание - комплекс последствий хронического стресса.")
    d.add_paragraph("Пособия и оборудование, используемые на занятии: ______")
    d.add_paragraph("Инженер отделения ОСПиП")
    d.save(path)


def test_service_schedule(tmp_path):
    f = tmp_path / "s.docx"
    _schedule(f)
    les = parse_schedule(f)
    assert [l.date for l in les] == ["08.04.26", "09.04.26"]
    assert les[0].kind == "service"
    assert les[0].subject == "Психологическая подготовка"
    assert les[0].topic == "Последствия хронического стресса. Эмоциональное выгорание."
    assert len(les[0].questions) == 2
    assert les[1].topic == "Требование к оборудованию мест проведения соревнований."


def test_special_schedule_kind(tmp_path):
    f = tmp_path / "s.docx"
    _schedule(f, special=True)
    assert {l.kind for l in parse_schedule(f)} == {"special"}


def test_plan_is_cleaned(tmp_path):
    f = tmp_path / "p.docx"
    _plan(f)
    p = parse_plan(f)
    assert p.topic == "Последствия хронического стресса. Эмоциональное выгорание."
    assert p.goal.startswith("Рассмотрение")
    assert p.text.startswith("Учебный вопрос №1")
    assert "- снижение продуктивности в работе" in p.text
    assert "Учебный вопрос №2" in p.text
    for junk in ("УТВЕРЖДАЮ", "Бойко", "Пособия", "Инженер"):
        assert junk not in p.text


def test_plan_matches_lesson(tmp_path):
    f = tmp_path / "p.docx"
    _plan(f)
    p = parse_plan(f)
    assert match_plan("Последствия хронического стресса. Эмоциональное выгорание.", [p]) is p
    assert match_plan("Требование к оборудованию мест проведения соревнований.", [p]) is None


def test_prompt_and_answer_cleanup():
    prompt = build_prompt(Entry(kind="service", topic="Выгорание"), "Исходный текст.", 1400)
    assert "1400" in prompt and "Исходный текст." in prompt and "Выгорание" in prompt
    answer = "Вот конспект:\n**Учебный вопрос №1**\n* пункт один\n# лишний заголовок"
    assert clean_answer(answer) == "Учебный вопрос №1\n- пункт один\nлишний заголовок"


def test_old_word_doc_text():
    """Старый Word (.doc): текст собирается по «таблице кусков» — UTF-16 и 8-битные куски, служебные символы."""
    import struct
    from stv.documents import doc_stream_text
    part1 = "Тема: Огнетушители\rВиды: \x13 FORMTEXT \x14порошковые\x15, углекислотные\r".encode("utf-16-le")
    part2 = b"OK\x07"
    fib = bytearray(1024)
    struct.pack_into("<H", fib, 0, 0xA5EC)
    struct.pack_into("<H", fib, 32, 14)          # csw
    struct.pack_into("<H", fib, 62, 22)          # cslw
    blob = 32 + 2 + 28 + 2 + 88 + 2
    text_at = 600
    fib[text_at:text_at + len(part1)] = part1
    fib[900:900 + len(part2)] = part2
    n1 = len(part1) // 2
    plc = struct.pack("<3I", 0, n1, n1 + len(part2))
    plc += struct.pack("<HIH", 0, text_at, 0) + struct.pack("<HIH", 0, (900 * 2) | 0x40000000, 0)
    clx = b"\x02" + struct.pack("<I", len(plc)) + plc
    table = b"\x00" * 16 + clx
    struct.pack_into("<II", fib, blob + 33 * 8, 16, len(clx))
    text = doc_stream_text(bytes(fib), table)
    assert text == "Тема: Огнетушители\nВиды: порошковые, углекислотные\nOK"


# ---------- документы практики: индивидуальный план, отчёт, рапорт, сборник материалов ----------

def _approval(d):
    for t in ("УТВЕРЖДАЮ", "Начальник отделения", "майор внутренней службы", "______ М.В. Иванов",
              "«___» ______________ 2026 года"):
        d.add_paragraph(t)


def test_individual_plan_without_dates(tmp_path):
    """Индивидуальный план: даты не заполнены («__» ______ 2026 г.), колонка — «План-задание на день», в ячейке
    несколько строк. Раньше не находилось ни одного занятия."""
    d = docx.Document()
    _approval(d)
    d.add_paragraph("ИНДИВИДУАЛЬНЫЙ ПЛАН")
    t = d.add_table(rows=4, cols=5)
    for i, h in enumerate(("№", "Дата", "План-задание на день", "Оценка", "Подпись наставника")):
        t.rows[0].cells[i].text = h
    cells = ("Изучить: требования охраны труда, правила распорядка\nОзнакомиться: с распорядком дня\n"
             "Практически отработать: составление плана",
             "Изучить: порядок присвоения категории риска\nОзнакомиться: с реестром объектов",
             "Принять участие: в плановом инспекционном визите")
    for r, c in enumerate(cells, 1):
        t.rows[r].cells[0].text = f"{r}."
        t.rows[r].cells[1].text = "«__» ______ 2026 г."
        t.rows[r].cells[2].text = c
    f = tmp_path / "план.docx"
    d.save(f)
    les = parse_schedule(f)
    assert [l.topic for l in les] == ["Требования охраны труда, правила распорядка.",
                                      "Порядок присвоения категории риска.",
                                      "Принять участие: в плановом инспекционном визите."]
    assert all(l.date == "" for l in les)
    assert les[0].questions == ["Ознакомиться: с распорядком дня", "Практически отработать: составление плана"]


def test_card_table_is_not_a_schedule(tmp_path):
    """«Тема | «Огонь — друг…»», «Цель | …» — карточка занятия, а не расписание."""
    d = docx.Document()
    t = d.add_table(rows=3, cols=2)
    for r, (k, v) in enumerate((("Тема", "«Огонь — друг и огонь — враг»"), ("Цель", "Сформировать навыки"),
                                ("Дата, длительность", "«__» ______ 2026 г., 30 минут"))):
        t.rows[r].cells[0].text, t.rows[r].cells[1].text = k, v
    f = tmp_path / "карточка.docx"
    d.save(f)
    assert parse_schedule(f) == []


def test_several_materials_in_one_file(tmp_path):
    """Сборник: статья, конспект урока с карточкой и «Ходом занятия», памятка — три конспекта; пометки
    «удалить» в текст не попадают, у темы нет «— » впереди."""
    from stv.documents import parse_plans
    d = docx.Document()
    d.add_paragraph("Материал 1. Статья на противопожарную тематику")
    d.add_paragraph("Рекомендуемое размещение: газета. Подготовил: слушатель")
    d.add_paragraph("Тепло в доме без беды: правила пожарной безопасности")
    d.add_paragraph("С наступлением холодов включают печи и обогреватели.")
    d.add_paragraph("ПОМЕТКА (удалить): сохраните выпуск газеты.")
    d.add_paragraph("Материал 2. Конспект урока безопасности")
    t = d.add_table(rows=2, cols=2)
    t.rows[0].cells[0].text, t.rows[0].cells[1].text = "Тема", "«Огонь — друг и огонь — враг»"
    t.rows[1].cells[0].text, t.rows[1].cells[1].text = "Цель", "Сформировать навыки безопасного поведения"
    d.add_paragraph("Ход занятия")
    d.add_paragraph("1. Знакомство (3 мин). Инспектор рассказывает о своей работе.")
    d.add_paragraph("2. Игра «Можно — нельзя» (7 мин).")
    d.add_paragraph("Материал 3. Памятка для населения")
    d.add_paragraph("ПОЖАРНАЯ БЕЗОПАСНОСТЬ В ОТОПИТЕЛЬНЫЙ СЕЗОН")
    d.add_paragraph("–  перед сезоном проверьте печь и дымоход;")
    d.add_paragraph("–  не оставляйте топящуюся печь без присмотра.")
    f = tmp_path / "материалы.docx"
    d.save(f)
    plans = parse_plans(f)
    assert [p.topic for p in plans] == ["Тепло в доме без беды: правила пожарной безопасности.",
                                        "«Огонь — друг и огонь — враг»",
                                        "Пожарная безопасность в отопительный сезон."]
    assert plans[0].text == "С наступлением холодов включают печи и обогреватели."
    assert plans[1].goal.startswith("Сформировать") and plans[1].text.startswith("1. Знакомство")
    assert plans[2].text.startswith("- перед сезоном")
    assert not any("ПОМЕТКА" in p.text or "Рекомендуемое" in p.text for p in plans)


def test_report_with_title_page_and_contents(tmp_path):
    """Отчёт: гриф, титульный лист с «Составил:», оглавление и перечень «Приложение 1…20» — раньше текст
    обрывался на «Составил:» или файл делился на 20 пустых «материалов»."""
    from stv.documents import parse_plans
    d = docx.Document()
    _approval(d)
    d.add_paragraph("ОТЧЁТ")
    d.add_paragraph("о прохождении практики")
    d.add_paragraph("Составил:")
    d.add_paragraph("сержант внутренней службы ______ Н.Д. Петров")
    d.add_paragraph("Согласовано:")
    d.add_paragraph("Наставник практики")
    d.add_paragraph("СОДЕРЖАНИЕ")
    d.add_paragraph("1. Общие сведения о подразделении\t3")
    d.add_paragraph("2. Выводы\t6")
    d.add_paragraph("1. Общие сведения о подразделении")
    d.add_paragraph("Отделение надзорной деятельности осуществляет надзор в районе. " * 5)
    d.add_paragraph("2. Выводы")
    d.add_paragraph("Задачи практики выполнены в полном объёме. " * 5)
    for n in range(1, 6):
        d.add_paragraph(f"Приложение {n}. Документ номер {n} — страниц: __")
    f = tmp_path / "отчёт.docx"
    d.save(f)
    plans = parse_plans(f)
    assert len(plans) == 1
    p = plans[0]
    assert p.topic == "Отчёт о прохождении практики."
    assert "Отделение надзорной деятельности" in p.text and "Задачи практики выполнены" in p.text
    for junk in ("УТВЕРЖДАЮ", "Составил", "Согласовано", "СОДЕРЖАНИЕ", "\t3", "Петров"):
        assert junk not in p.text


def test_raport_header_is_dropped(tmp_path):
    """Рапорт: строки «кому» над названием — шапка, тема — «Рапорт»."""
    d = docx.Document()
    for t in ("Исполняющему обязанности начальника кафедры", "капитану внутренней службы", "Т.П. Макаровой",
              "Рапорт", "Настоящим докладываю, что задание выполнено не в полном объёме, а именно:"):
        d.add_paragraph(t)
    d.add_paragraph("не осуществлялось участие в визите по причине отсутствия", style="List Bullet")
    f = tmp_path / "рапорт.docx"
    d.save(f)
    p = parse_plan(f)
    assert p.topic == "Рапорт."
    assert p.text.startswith("Настоящим докладываю") and "Макаровой" not in p.text
    assert "- не осуществлялось участие" in p.text


def test_text_in_content_controls_and_nested_tables(tmp_path):
    """Шаблоны Word: текст в поле «Введите текст» (элемент управления содержимым) и во вложенной таблице
    раньше не читался вовсе."""
    import copy
    from docx.oxml.ns import qn
    from stv.documents import read_docx_text
    d = docx.Document()
    par = d.add_paragraph("Текст в поле шаблона")
    sdt = d.element.body.makeelement(qn("w:sdt"), {})
    content = sdt.makeelement(qn("w:sdtContent"), {})
    sdt.append(content)
    content.append(copy.deepcopy(par._p))
    d.element.body.remove(par._p)
    d.element.body.insert(0, sdt)
    t = d.add_table(rows=2, cols=2)
    t.rows[0].cells[0].text, t.rows[0].cells[1].text = "Дата", "Тема"
    t.rows[1].cells[0].text = "05.05.2026"
    inner = t.rows[1].cells[1].add_table(rows=1, cols=1)
    inner.rows[0].cells[0].text = "Тема № 3. Огнетушители"
    f = tmp_path / "шаблон.docx"
    d.save(f)
    assert "Текст в поле шаблона" in read_docx_text(f)
    les = parse_schedule(f)
    assert [(l.date, l.topic) for l in les] == [("05.05.26", "Огнетушители.")]
