"""Чтение документов: расписание занятий и план-конспект в DOCX, текст из TXT.

Разметка расписания (по образцам 1 ПСО, апрель и июль 2026):
- заголовок «Расписание занятий по специальной подготовке …» — специальная подготовка,
  «Расписание занятий … с общей группой …» — служебная;
- таблица с колонкой «Дата» и колонкой темы («Предмет обучения, тема и учебные вопросы»
  или «Наименование тем»); строка «1 | 2 | 3 …» — нумерация колонок, пропускается.
"""

import datetime as dt
import re
from dataclasses import dataclass, field
from pathlib import Path

_DATE_RE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{2,4})")
_TOPIC_RE = re.compile(r"^\s*Тема\s*(?:№\s*\d+[.,]?)?\s*[:.]?\s*", re.IGNORECASE)
_QUESTION_RE = re.compile(r"^\s*(?:\d+\.\s*)?Учебный\s+вопрос", re.IGNORECASE)


@dataclass
class Lesson:
    date: str            # дд.мм.гг
    kind: str            # service | special
    subject: str = ""    # «Психологическая подготовка»
    topic: str = ""      # без «Тема № N.»
    questions: list[str] = field(default_factory=list)
    hours: str = ""


# ---------- низкий уровень: DOCX ----------

def _docx():
    import docx  # python-docx, MIT
    return docx


_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _local(el) -> str:
    return el.tag.rsplit("}", 1)[-1] if isinstance(el.tag, str) else ""


def _blocks(path):
    """Абзацы и таблицы в порядке следования — и те, что спрятаны в шаблонах: в элементах управления
    содержимым (поля «Введите текст»), в исправлениях и в надписях (текстовых полях) внутри абзацев."""
    docx = _docx()
    d = docx.Document(str(path))
    yield from _walk(d.element.body, d)


def _walk(el, parent):
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    for child in el.iterchildren():
        tag = _local(child)
        if tag == "p":
            yield Paragraph(child, parent)
            for box in child.iter("{*}txbxContent"):
                # у надписи две копии: новая (Choice) и запасная для старого Word (Fallback) — берём одну
                if not any(_local(a) == "Fallback" for a in box.iterancestors()):
                    yield from _walk(box, parent)
        elif tag == "tbl":
            yield Table(child, parent)
        elif tag == "sdt":
            content = child.find(_W + "sdtContent")
            if content is not None:
                yield from _walk(content, parent)
        elif tag in ("customXml", "ins", "smartTag"):
            yield from _walk(child, parent)


def _cell_text(tc) -> str:
    """Текст ячейки со всем, что внутри: и абзацы вложенных таблиц (python-docx их пропускает)."""
    from docx.text.paragraph import Paragraph
    return "\n".join(Paragraph(p, None).text for p in tc.iter(_W + "p"))


def _row_cells(row) -> list[str]:
    out, prev = [], None
    for c in row.cells:
        if c._tc is prev:  # объединённые ячейки python-docx отдаёт повторно
            continue
        prev = c._tc
        out.append(_cell_text(c._tc).strip())
    return out


def _is_list_item(par) -> bool:
    """Пункт маркированного/нумерованного списка: нумерация у самого абзаца или в его стиле."""
    ppr = par._p.pPr
    if ppr is not None and ppr.numPr is not None:
        num = ppr.numPr.numId
        return num is None or num.val != 0  # numId=0 — нумерация явно снята
    style = par.style
    while style is not None:
        sppr = style.element.pPr
        if sppr is not None and sppr.numPr is not None:
            return True
        style = style.base_style
    return False


def _short_date(s: str) -> str:
    m = _DATE_RE.search(s)
    if not m:
        return ""
    d, mth, y = (int(x) for x in m.groups())
    y = y + 2000 if y < 100 else y
    try:
        return dt.date(y, mth, d).strftime("%d.%m.%y")
    except ValueError:
        return ""


def clean_topic(s: str) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    s = _TOPIC_RE.sub("", s)
    s = re.sub(r"\(\s*\d+\s*ч\.?\s*\)", "", s)  # «(2ч)»
    s = s.strip(" .:—–-")  # «Тема — …» из таблицы «Тема | …»
    return s + ("." if s and not s.endswith(("!", "?", "»", '"')) else "")


# ---------- расписание ----------

# Колонка темы: заголовок со словами ниже (по порядку); «План-задание на день», «Содержание», «Наименование
# мероприятия» — тоже темы. Если ни одного — берём колонку с самым длинным текстом.
_TOPIC_HEAD = ("тем", "задани", "содержан", "наименован", "предмет", "мероприят", "вопрос")
_NOT_TOPIC = ("дата", "№", "час", "время", "оценк", "подпис", "отметк", "примечан", "метод", "место", "ответствен",
              "руковод", "вид ", "кол")
_TOTAL = re.compile(r"^(итого|всего)\b", re.I)


def _header(rows: list[list[str]]) -> int | None:
    """Строка заголовка таблицы (в первых трёх: сверху бывает общее название, растянутое на всю ширину)."""
    for k, r in enumerate(rows[:3]):
        head = [c.lower() for c in r]
        if any(len(c) > 60 or c.startswith(("«", '"', "“")) for c in head):
            continue  # это уже данные: «Тема | «Огонь — друг…»» — карточка занятия, а не заголовок таблицы
        if any(c.startswith("дата") for c in head) or any(_topic_head(c) for c in head):
            return k
    return None


def _topic_head(c: str) -> bool:
    return any(k in c for k in _TOPIC_HEAD) and not c.startswith(_NOT_TOPIC)


def parse_schedule(path) -> list[Lesson]:
    """Занятия из таблиц документа: расписание, индивидуальный план, план-задание. Даты могут быть не
    заполнены («__» ______ 2026 г.) — такие строки тоже нужны: дату человек поставит сам."""
    kind = "service"
    lessons: list[Lesson] = []
    for b in _blocks(path):
        if hasattr(b, "text"):  # абзац
            if "специальной подготовк" in b.text.lower():
                kind = "special"
            continue
        rows = [_row_cells(r) for r in b.rows]
        k = _header(rows)
        if k is None:
            # таблица «УТВЕРЖДАЮ» или другая служебная
            if rows and any("специальной подготовк" in c.lower() for c in rows[0]):
                kind = "special"
            continue
        head = [c.lower() for c in rows[k]]
        data = [r for r in rows[k + 1:] if any(c.strip() for c in r)]
        i_date = next((i for i, c in enumerate(head) if c.startswith("дата")), None)
        i_topic = next((i for kw in _TOPIC_HEAD for i, c in enumerate(head)
                        if kw in c and not c.startswith(_NOT_TOPIC) and i != i_date), None)
        if i_topic is None:
            if i_date is None:
                continue
            cand = [i for i in range(len(head)) if i != i_date and not head[i].startswith(_NOT_TOPIC)]
            if not cand:
                continue
            i_topic = max(cand, key=lambda i: sum(len(r[i]) for r in data if i < len(r)))
        i_hours = next((i for i, c in enumerate(head) if "час" in c and "заняти" not in c), None)
        for r in data:
            if len(r) <= i_topic or all(c.strip().isdigit() for c in r if c.strip()):
                continue  # нумерация колонок «1 | 2 | 3»
            cell = r[i_topic].strip()
            if not cell or _TOTAL.match(cell):
                continue
            date = _short_date(r[i_date]) if i_date is not None and i_date < len(r) else ""
            if i_date is not None and not date and _DATE_RE.search(r[i_date] or ""):
                continue  # дата есть, но не разобралась — странная строка, не выдумываем
            lessons.append(_lesson_from_cell(cell, date, kind,
                                             r[i_hours] if i_hours is not None and i_hours < len(r) else ""))
    return lessons


_TASK = re.compile(r"^\s*изучить\s*:?\s*", re.I)


def _lesson_from_cell(cell: str, date: str, kind: str, hours: str) -> Lesson:
    lines = [ln.strip() for ln in cell.splitlines() if ln.strip()]
    les = Lesson(date=date, kind=kind, hours=hours)
    topic_parts: list[str] = []
    in_topic = False
    rest: list[str] = []
    for ln in lines:
        if _QUESTION_RE.match(ln):
            les.questions.append(ln)
            in_topic = False
        elif ln.lower().startswith("тема"):
            topic_parts = [ln]
            in_topic = True
        elif in_topic:
            topic_parts.append(ln)  # тема перенесена на следующую строку ячейки
        elif not topic_parts and not les.subject:
            les.subject = ln
        else:
            rest.append(ln)
    if topic_parts:
        les.topic = clean_topic(" ".join(topic_parts))
        return les
    # без «Тема …»: план-задание «Изучить: …» — тема то, что изучить; остальные строки — подробности
    lines = [ln for ln in lines if not _QUESTION_RE.match(ln)]
    task = next((ln for ln in lines if _TASK.match(ln)), lines[0] if lines else "")
    topic = clean_topic(_TASK.sub("", task) if _TASK.match(task) else task)
    les.topic = topic[:1].upper() + topic[1:]
    les.subject = ""
    les.questions += [ln for ln in lines if ln is not task]
    return les


# ---------- план-конспект ----------

_START = ("развернутый план", "развёрнутый план", "ход занятия", "ход беседы", "ход урока", "ход мероприятия",
          "содержание занятия", "содержание беседы")
_END = ("пособия и оборудование", "составил план", "составил:")
_SIGNATURE = re.compile(r"(инженер|начальник|заместитель|психолог|лейтенант|капитан|майор|полковник)\b", re.I)
# Части одного файла: «Материал 2. Конспект урока…», «Приложение 3», «Занятие 1» — каждая — свой конспект
_SECTION = re.compile(r"^(материал|приложение|раздел|занятие|урок|беседа)\s*№?\s*\d+\s*[.:)]?\s*", re.I)
# Пометки для себя («ПОМЕТКА (удалить): …», «СЛУЖЕБНАЯ ПОМЕТКА (удалить перед печатью)») и где разместить
_META = re.compile(r"^(служебная\s+)?пометка\b|^рекомендуемое\s+размещение|^подготовил\s*:", re.I)


@dataclass
class Plan:
    topic: str
    text: str        # очищенный текст для конспекта (разметка KonspektAI: «- » для пунктов)
    goal: str = ""


_LIST_MARK = re.compile(r"^\s*[-–—•·▪]\s+")


def _plan_items(path, text: str | None = None):
    """(текст, пункт списка, ячейки строки таблицы или None): из DOCX — по абзацам и строкам таблиц,
    из PDF и сканов — по строкам (text — уже прочитанный текст: скан второй раз не распознаём)."""
    if Path(path).suffix.lower() != ".docx":
        for ln in (read_any(path) if text is None else text).split("\n"):
            yield (_LIST_MARK.sub("", ln), bool(_LIST_MARK.match(ln)), None)
        return
    for b in _blocks(path):
        if hasattr(b, "text"):
            yield (b.text, _is_list_item(b), None)
        else:  # таблицы переносим строками «ячейка — ячейка»
            for r in b.rows:
                cells = [c for c in _row_cells(r) if c]
                if cells:
                    yield (" — ".join(cells), False, cells)


def _norm(t: str) -> str:
    return re.sub(r"\s+", " ", t).strip()


def _chunks(items: list) -> list[list]:
    """Делим файл на материалы: по заголовкам «Материал N», а если их нет — по строкам «Тема: …»."""
    heads = [i for i, (t, _, cells) in enumerate(items) if cells is None and _SECTION.match(_norm(t))]
    # заголовок — начало материала, только если под ним есть текст: список «Приложение 1…, Приложение 2…»
    # в отчёте — это перечень, а не 20 материалов
    real = [h for h, nxt in zip(heads, heads[1:] + [len(items)])
            if sum(1 for t, _, _ in items[h + 1:nxt] if _norm(t)) >= 2]
    if len(real) >= 2:
        cuts = ([0] if real[0] > 0 else []) + real  # текст до первого «Материала» тоже не теряем
        return [items[a:b] for a, b in zip(cuts, cuts[1:] + [len(items)])]
    tops = [i for i, (t, _, cells) in enumerate(items) if _topic_of(t, cells) is not None]
    if len(tops) >= 2:
        cuts = [0] + tops[1:]
        return [items[a:b] for a, b in zip(cuts, cuts[1:] + [len(items)])]
    return [items]


def _topic_of(t: str, cells) -> str | None:
    """Тема из строки «Тема: …» или из строки таблицы «Тема | …»."""
    if cells is not None:
        if len(cells) >= 2 and cells[0].lower().strip(" :.").startswith("тема"):
            return cells[1]
        return None
    t = _norm(t)
    return t if t.lower().startswith("тема") and len(t) > 6 else None


# Название документа без «Темы»: «РАПОРТ», «Справка», «ОТЗЫВ НАСТАВНИКА ПРАКТИКИ», «ОТЧЁТ» + следующая строка
_DOC_TITLE = re.compile(r"^(рапорт|справка|отзыв|отч[её]т|характеристика|акт|индивидуальный план|план-конспект|"
                        r"конспект|памятка|статья|заявление|объяснение|протокол|доклад|реферат)\b", re.I)
_TOC_LINE = re.compile(r"(\t|\.{3,}|…)\s*\d+\s*$")  # строка оглавления «1. Общие сведения…	3»
_TITLE_PAGE = ("составил", "согласовано", "выполнил", "проверил")


def _doc_title(chunk: list) -> tuple[int, str] | None:
    """Где в начале файла название документа: (номер последней строки названия, название)."""
    lines = [(i, _norm(t)) for i, (t, _, cells) in enumerate(chunk[:25]) if cells is None and _norm(t)]
    for k, (i, t) in enumerate(lines):
        if len(t) <= 70 and _DOC_TITLE.match(t) and (t.isupper() or len(t.split()) <= 4):
            title = t.capitalize() if t.isupper() else t
            if k + 1 < len(lines):
                j, nxt = lines[k + 1]
                if nxt[:1].islower() and len(title) + len(nxt) <= 140:  # «ОТЧЁТ» / «о прохождении практики»
                    return j, f"{title} {nxt}"
            return i, title
    return None


def _plan_from(chunk: list) -> Plan:
    topic, goal, heading = "", "", ""
    body: list[str] = []
    has_start = any(_norm(t).lower().startswith(_START) for t, _, _ in chunk)
    started = not has_start
    approval = bool(chunk) and _norm(chunk[0][0]).upper().startswith("УТВЕРЖДАЮ")
    skip_to = -1
    if not any(_topic_of(t, c) is not None for t, _, c in chunk):
        found = _doc_title(chunk)
        if found is not None:  # всё выше названия — шапка: кому, от кого, гриф
            skip_to, topic = found[0], clean_topic(found[1])
            approval = False
    title_page = False
    for n, (raw, is_list, cells) in enumerate(chunk):
        t = _norm(raw)
        if not t or n <= skip_to:
            continue
        low = t.lower()
        if _TOC_LINE.search(raw) or low in ("содержание", "оглавление"):
            title_page = False
            continue
        so_far = sum(len(x) for x in body)  # мало текста выше — это ещё титульный лист, а не конец документа
        if so_far < 1500 and low.startswith(_TITLE_PAGE):
            title_page = True  # подписи титульного листа — до оглавления или до основного текста
            continue
        if title_page:
            key = _topic_of(raw, cells) is not None or low.startswith(_START) or low.startswith("цель")
            if not key and len(t) < 150 and not re.match(r"^\d+\.\s", t):
                continue
            title_page = False
        if approval:  # гриф «УТВЕРЖДАЮ … «__» ____ 20__ г.»: до строки с годом, заголовка или темы
            if _topic_of(raw, cells) is not None or low.startswith(_START):
                approval = False  # гриф кончился — строку разбираем как обычно
            else:
                if n > 0 and (re.search(r"20\d\d|20__|г\.$|года$", low) or (t.isupper() and len(t) > 3) or n > 8):
                    approval = False
                continue
        if n == 0 and _SECTION.match(t):
            heading = _SECTION.sub("", t).strip(" .")
            continue
        if _META.match(t):
            continue
        tp = _topic_of(raw, cells)
        if tp is not None and not topic:
            topic = clean_topic(tp)
            continue
        if cells is not None and len(cells) == 2 and not started:
            if cells[0].lower().startswith("цель"):
                goal = cells[1]
            continue  # карточка занятия до «Хода занятия»: возраст, место, оборудование
        if low.startswith("цель занятия"):
            goal = t.split(":", 1)[-1].strip()
            continue
        if not started:
            if low.startswith(_START):
                started = True
            continue
        if low.startswith(_END) and (has_start or so_far >= 1500):
            break
        if (has_start or so_far >= 1500) and _SIGNATURE.match(low) and len(t) < 120 and cells is None:
            break  # подпись составителя
        if not topic and not has_start and not body and not is_list and len(t) < 160 and not t.endswith("."):
            topic = clean_topic(t.capitalize() if t.isupper() else t)  # заголовок статьи или памятки
            continue
        if _QUESTION_RE.match(t):
            body.append("")
            body.append(re.sub(r"^\d+\.\s*", "", t))
        elif is_list or _LIST_MARK.match(t):
            body.append("- " + _LIST_MARK.sub("", t))
        else:
            body.append(t)
    if not topic and heading:
        topic = clean_topic(heading)
    text = "\n".join(body).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    return Plan(topic=topic, text=text, goal=goal)


def parse_plans(path, text: str | None = None) -> list[Plan]:
    """Все планы-конспекты файла: один файл может содержать несколько материалов («Материал 1…», «Материал 2…»)
    — каждый становится своим конспектом. Пустых не возвращаем; совсем пустой файл — один пустой план."""
    plans = [p for p in (_plan_from(c) for c in _chunks(list(_plan_items(path, text)))) if p.text]
    return plans or [Plan(topic="", text="")]


def parse_plan(path) -> Plan:
    """План-конспект (DOCX, PDF или скан): тема, цель и очищенный текст. В файле с несколькими
    материалами — первый (все — parse_plans)."""
    return parse_plans(path)[0]


def read_text_file(path) -> str:
    raw = Path(path).read_bytes()
    for enc in ("utf-8-sig", "cp1251"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ValueError("Не удалось прочитать файл: неизвестная кодировка")


def read_docx_text(path) -> str:
    """Весь текст DOCX: абзацы, пункты списков, таблицы строками."""
    out: list[str] = []
    for b in _blocks(path):
        if hasattr(b, "text"):
            t = b.text.strip()
            if t and not _META.match(t):
                out.append(("- " + t) if _is_list_item(b) else t)
        else:
            for r in b.rows:
                cells = [c for c in _row_cells(r) if c]
                if cells:
                    out.append(" — ".join(cells))
    return "\n".join(out)


def read_pdf_text(path, progress=None) -> str:
    """Текст PDF: страницы с текстовым слоем читаются напрямую, сканы — через распознавание."""
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(str(path))
    parts = []
    try:
        for i in range(len(pdf)):
            if progress:
                progress(i, len(pdf))
            page = pdf[i]
            text = page.get_textpage().get_text_bounded().replace("\r\n", "\n").strip()
            if len(re.sub(r"\s", "", text)) < 40:  # почти пусто — это скан
                import numpy as np
                bitmap = page.render(scale=220 / 72).to_numpy()
                img = np.ascontiguousarray(bitmap[:, :, :3])
                from .ocr import ocr_image
                text = ocr_image(img)
            else:
                text = _join_pdf_lines(text)
            parts.append(text)
    finally:
        pdf.close()
    return "\n".join(p for p in parts if p.strip())


def _join_pdf_lines(text: str) -> str:
    """Строки PDF → абзацы: склеиваем переносы и разорванные строки внутри предложения."""
    out = ""
    for ln in (l.strip() for l in text.split("\n")):
        if not ln:
            out += "\n"
            continue
        if not out or out.endswith("\n"):
            out += ln
        elif out.endswith("-") and ln[:1].islower():
            out = out[:-1] + ln
        elif ln[:1].islower() or not out.endswith((".", ":", ";", "!", "?")):
            out += " " + ln
        else:
            out += "\n" + ln
    return re.sub(r"\n{3,}", "\n\n", out).strip()


def read_doc_text(path) -> str:
    """Текст из старого Word (.doc, Word 97–2003) без установленного Word.

    Файл — OLE-контейнер. В потоке WordDocument заголовок (FIB) указывает, где в табличном потоке лежит
    «таблица кусков» (CLX): из каких мест файла собирается текст и в какой кодировке (UTF-16 или 8 бит).
    Служебные символы Word превращаем в обычные: конец абзаца, ячейки таблицы, поля «код→результат»."""
    import struct

    import olefile
    try:
        ole = olefile.OleFileIO(str(path))
    except OSError as e:
        raise ValueError(f"Не удалось открыть файл Word: {e}") from None
    try:
        if not ole.exists("WordDocument"):
            raise ValueError("Это не документ Word (.doc). Сохраните его в Word как .docx.")
        word = ole.openstream("WordDocument").read()
        if struct.unpack_from("<H", word, 0)[0] != 0xA5EC:
            raise ValueError("Файл .doc повреждён или очень старой версии. Сохраните его в Word как .docx.")
        flags = struct.unpack_from("<H", word, 0x0A)[0]
        if flags & 0x0100:
            raise ValueError("Документ защищён паролем. Снимите защиту в Word и попробуйте ещё раз.")
        table = ole.openstream("1Table" if flags & 0x0200 else "0Table").read()
    finally:
        ole.close()
    return doc_stream_text(word, table)


def doc_stream_text(word: bytes, table: bytes) -> str:
    """Текст по потокам WordDocument и xTable (см. read_doc_text)."""
    import struct
    try:
        pos = 32
        csw = struct.unpack_from("<H", word, pos)[0]
        pos += 2 + csw * 2
        cslw = struct.unpack_from("<H", word, pos)[0]
        pos += 2 + cslw * 4 + 2  # + cbRgFcLcb
        fc_clx, lcb_clx = struct.unpack_from("<II", word, pos + 33 * 8)  # пара №33 — fcClx/lcbClx (смещение 0x1A2)
        clx = table[fc_clx:fc_clx + lcb_clx]
    except struct.error:
        raise ValueError("Файл .doc повреждён. Сохраните его в Word как .docx.") from None
    i = 0
    while i < len(clx) and clx[i] == 0x01:  # Prc — форматирование, пропускаем
        i += 3 + struct.unpack_from("<H", clx, i + 1)[0]
    if i >= len(clx) or clx[i] != 0x02:
        raise ValueError("Не удалось найти текст в файле .doc. Сохраните его в Word как .docx.")
    lcb = struct.unpack_from("<I", clx, i + 1)[0]
    plc = clx[i + 5:i + 5 + lcb]
    n = (len(plc) - 4) // 12
    cps = struct.unpack_from(f"<{n + 1}I", plc, 0)
    parts = []
    for k in range(n):
        fc = struct.unpack_from("<I", plc, 4 * (n + 1) + 8 * k + 2)[0]
        count = cps[k + 1] - cps[k]
        if fc & 0x40000000:  # 8-битный кусок
            start = (fc & ~0x40000000) // 2
            parts.append(word[start:start + count].decode("cp1252", "replace"))
        else:
            parts.append(word[fc:fc + 2 * count].decode("utf-16-le", "replace"))
    text = "".join(parts)
    text = re.sub(r"\x13[^\x13\x14\x15]*\x14", "", text)          # код поля — убрать, результат оставить
    text = re.sub(r"\x13[^\x13\x14\x15]*\x15", "", text)          # поле без результата
    text = text.replace("\x15", "").replace("\x07", "\t").replace("\x0b", "\n").replace("\r", "\n")
    text = re.sub(r"[\x00-\x08\x0c\x0e-\x1f]", "", text)
    lines = [ln.rstrip("\t ").replace("\t\t", "\t") for ln in text.split("\n")]
    return "\n".join(lines).strip()


def read_any(path, progress=None) -> str:
    """Текст из TXT, DOC, DOCX, PDF или картинки — для «Из файла…»."""
    ext = Path(path).suffix.lower()
    if ext == ".doc":
        return read_doc_text(path)
    if ext == ".docx":
        return read_docx_text(path)
    if ext == ".pdf":
        return read_pdf_text(path, progress)
    if ext in (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"):
        from .ocr import ocr_image
        return ocr_image(path)
    return read_text_file(path)


def match_plan(topic: str, plans: list[Plan]) -> Plan | None:
    """План-конспект, тема которого ближе всего к теме занятия (по общим словам)."""
    def words(s):
        return {w for w in re.findall(r"[а-яёa-z]{4,}", s.lower())}
    tw = words(topic)
    best, score = None, 0.0
    for p in plans:
        pw = words(p.topic)
        if not tw or not pw:
            continue
        s = len(tw & pw) / len(tw | pw)
        if s > score:
            best, score = p, s
    return best if score >= 0.4 else None
