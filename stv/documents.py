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
_TOPIC_RE = re.compile(r"^\s*Тема\s*[:.]?\s*(?:№\s*)?(?:\d+\s*[.,:]?\s*)?", re.IGNORECASE)
_QUESTION_RE = re.compile(r"^\s*(?:\d+\.\s*)?Учебный\s+вопрос", re.IGNORECASE)


@dataclass
class Lesson:
    date: str            # дд.мм.гг
    kind: str            # service | special
    subject: str = ""    # «Психологическая подготовка»
    topic: str = ""      # без «Тема № N.»
    questions: list[str] = field(default_factory=list)
    hours: str = ""
    number: str = ""     # «Тема № 11» → «11»: по номеру план-конспект находится надёжнее, чем по словам
    group: str = ""      # с какой группой занятие (GROUPS): по шапке расписания «с общей группой…»


# Группы из шапки расписания: (как узнать, название, вид подготовки). Общая группа — служебная подготовка,
# ШОМ (школа оперативного мастерства, тактическая подготовка начальствующего состава) — специальная. Группа
# обслуживания и учебно-тренировочный полигон — тоже специальная, но это расписания других людей.
GROUPS = {
    "general": (re.compile(r"общей\s+групп", re.I), "Общая группа", "service"),
    "shom": (re.compile(r"\bШОМ\b|оперативного\s+мастерства|тактической\s+подготовк", re.I), "ШОМ", "special"),
    "maintenance": (re.compile(r"групп\w*\s+обслуживани", re.I), "Группа обслуживания", "special"),
    "utp": (re.compile(r"учебно-тренировочн\w*\s+полигон|\bУТП\b", re.I), "УТП", "special"),
}


def schedule_group(text: str) -> str:
    """Группа по строке шапки расписания: «с общей группой начальника…» → «general»; не узнали — «»."""
    return next((g for g, (rx, _, _) in GROUPS.items() if rx.search(text)), "")


# ---------- низкий уровень: DOCX ----------

def _docx():
    import docx  # python-docx, MIT
    return docx


def _blocks(path):
    """Абзацы и таблицы в порядке следования."""
    docx = _docx()
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    d = docx.Document(str(path))
    for child in d.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            yield Paragraph(child, d)
        elif tag == "tbl":
            yield Table(child, d)


def _row_cells(row) -> list[str]:
    out, prev = [], None
    for c in row.cells:
        if c._tc is prev:  # объединённые ячейки python-docx отдаёт повторно
            continue
        prev = c._tc
        out.append(c.text.strip())
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
    s = s.strip(" .:—–-")  # «Тема: — «…»» из строки таблицы
    return s + ("." if s and not s.endswith(("!", "?", "»", '"')) else "")


# ---------- расписание ----------

def _schedule_items(path):
    """("p", текст абзаца) и ("tbl", строки таблицы) по порядку — из DOCX или из старого Word (.doc)."""
    if Path(path).suffix.lower() == ".doc":
        yield from read_doc_items(path)
        return
    for b in _blocks(path):
        if hasattr(b, "text"):
            yield "p", b.text
        else:
            yield "tbl", [_row_cells(r) for r in b.rows]


def parse_schedule(path) -> list[Lesson]:
    kind, group, explicit = "service", "", False
    lessons: list[Lesson] = []
    cols, i_date, i_topic, i_hours, last_date = 0, 0, 0, None, ""  # колонки последней таблицы расписания
    for what, item in _schedule_items(path):
        if what == "p":
            low = item.lower()
            if "специальной подготовк" in low or "служебной подготовк" in low:
                kind, explicit = ("special" if "специальной" in low else "service"), True  # прямо написано
            g = schedule_group(item)
            if g:
                group = g
                if not explicit:
                    kind = GROUPS[g][2]  # ШОМ — специальная, хотя в шапке «по тактической подготовке»
            continue
        rows = item
        if not rows:
            continue
        head = [c.lower() for c in rows[0]]
        if any(c.startswith("дата") for c in head):
            i_date = next(i for i, c in enumerate(head) if c.startswith("дата"))
            i_topic = next((i for i, c in enumerate(head) if "тем" in c), i_date + 2)
            i_hours = next((i for i, c in enumerate(head) if "час" in c and "заняти" not in c), None)
            cols, data, last_date = len(head), rows[1:], ""
        elif cols and len(rows[0]) == cols and _short_date(rows[0][i_date] if i_date < len(rows[0]) else ""):
            data = rows  # продолжение таблицы после разрыва страницы: заголовка нет, колонки те же
        else:
            # таблица «УТВЕРЖДАЮ» или другая служебная
            if any("специальной подготовк" in c for c in head):
                kind = "special"
            continue
        for r in data:
            if len(r) <= max(i_date, i_topic) or all(c.strip().isdigit() for c in r if c.strip()):
                continue  # нумерация колонок «1 | 2 | 3»
            date_cell = r[i_date]
            if _short_date(date_cell):
                last_date = date_cell
            elif not date_cell.strip() and last_date and r[i_topic].strip():
                date_cell = last_date  # дата объединена на весь день: в следующих строках ячейка пустая
            else:
                continue
            for les in _lessons_from_row(date_cell, r[i_topic], kind,
                                         r[i_hours] if i_hours is not None and i_hours < len(r) else ""):
                les.group = group
                lessons.append(les)
    return lessons


_TOPIC_START = re.compile(r"^\s*Тема\b", re.IGNORECASE)
_MID_TOPIC = re.compile(r"(?<=\S)\s+(?=Тема\s*(?:№|:|\d))")


def _lessons_from_row(date_cell: str, cell: str, kind: str, hours: str) -> list[Lesson]:
    """Строка расписания — одно или несколько занятий: в одной ячейке бывает «Тема № 4 …» и ниже «Тема № 8 …»,
    а в колонке даты — две даты (по одной на тему). Раньше вторая тема затирала первую."""
    # «Школа оперативного мастерства:   Тема № 13 «…»» — тема с середины строки: переносим её на свою строку
    lines = [part for ln in cell.splitlines() for part in _MID_TOPIC.split(ln)]
    cell = "\n".join(lines)
    starts = [i for i, ln in enumerate(lines) if _TOPIC_START.match(ln)]
    dates = [_short_date(m.group(0)) for m in _DATE_RE.finditer(date_cell)]
    dates = [d for d in dates if d] or [""]
    if len(starts) < 2:
        return [_lesson_from_cell(cell, dates[0], kind, hours)]
    # всё, что выше первой «Темы» («Психологическая подготовка», «Дополнительное занятие»), — к первой
    cuts = [0] + starts[1:]
    out = []
    for k, (a, b) in enumerate(zip(cuts, cuts[1:] + [len(lines)])):
        out.append(_lesson_from_cell("\n".join(lines[a:b]), dates[min(k, len(dates) - 1)], kind, hours))
    return out


def _lesson_from_cell(cell: str, date: str, kind: str, hours: str) -> Lesson:
    lines = [ln.strip() for ln in cell.splitlines() if ln.strip()]
    les = Lesson(date=date, kind=kind, hours=hours)
    topic_parts: list[str] = []
    in_topic = False
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
    if topic_parts:
        les.number = _topic_number(topic_parts[0])
        les.topic = clean_topic(" ".join(topic_parts))
    else:
        # без «Тема …» тема — вся ячейка: «Групповое упражнение (деловая игра): Тушение пожаров в резервуарах…»
        les.topic = clean_topic(" ".join(ln for ln in lines if not _QUESTION_RE.match(ln)))
        les.subject = ""
    return les


# ---------- план-конспект ----------

_START = ("развернутый план", "развёрнутый план", "ход занятия", "содержание занятия")
_END = ("пособия и оборудование", "пособие и оборудование", "составил план", "составил:")
_SIGNATURE = re.compile(r"(инженер|начальник|заместитель|психолог|лейтенант|капитан|майор|полковник)\b", re.I)


@dataclass
class Plan:
    topic: str
    text: str        # очищенный текст для конспекта (разметка KonspektAI: «- » для пунктов)
    goal: str = ""
    number: str = ""  # номер темы: из «Тема № 9» в шапке или из имени файла «Т9.doc», «Тема 11.doc»


_NUMBER = re.compile(r"^\s*тема\s*[:.]?\s*№?\s*(\d+)", re.I)
_FILE_NUMBER = re.compile(r"^\s*(?:тема|т)\s*№?\s*(\d+)", re.I)
# Список литературы перед текстом плана: «Приказ МЧС России от…», «Ресурсы сети Интернет», «1. Указ…»
_LITERATURE = re.compile(r"^(\d+[.)]\s*)?(приказ|указ|федеральн|постановлен|закон|интернет|ресурс|учебн|пособи|гост|"
                         r"свод |методическ|руководств|наставлен|устав|положени|конституци|кодекс|распоряжени|"
                         r"сайт|https?:|www\.)", re.I)


_AUTHOR = re.compile(r"^\d+[.)]\s*[А-ЯЁ][а-яё-]+\s+[А-ЯЁ]\.\s?([А-ЯЁ]\.)?")  # «1. Бойко В.В. Синдром…»


def _is_signature(t: str, is_list: bool) -> bool:
    """Подпись составителя «Инженер отделения ОСПиП…», а не пункт перечня «начальник гарнизона;» в тексте."""
    return (not is_list and t[:1].isupper() and not t.rstrip().endswith((";", ",", ":", "."))
            and len(t.split()) <= 10 and bool(_SIGNATURE.match(t.lower())) and len(t) < 120)


def _topic_number(t: str) -> str:
    m = _NUMBER.match(t)
    return m.group(1) if m else ""


def _topic_from_cells(cells: list[str]) -> tuple[str, str] | None:
    """Тема из шапки-таблицы: «Тема: «…»» в одной ячейке или «Тема № 9:» | «…» — в соседней."""
    for k, c in enumerate(cells):
        if c.strip().lower().startswith("тема"):
            rest = clean_topic(c)
            if rest:
                return rest, _topic_number(c)
            nxt = next((x for x in cells[k + 1:] if x.strip()), "")
            if nxt:
                return clean_topic(nxt), _topic_number(c)
    return None


_LIST_MARK = re.compile(r"^\s*[-–—•·▪]\s+")


def _plan_lines(path):
    """(текст, это пункт списка, ячейки строки таблицы или None): из DOCX и старого DOC — по абзацам и
    строкам таблиц (шапка плана-конспекта — таблица «Тема: | …»), из PDF и сканов — по строкам."""
    ext = Path(path).suffix.lower()
    if ext == ".doc":
        for what, item in read_doc_items(path):
            if what == "p":
                for ln in item.split("\n"):
                    yield (_LIST_MARK.sub("", ln), bool(_LIST_MARK.match(ln)), None)
            else:
                for r in item:
                    cells = [c for c in r if c.strip()]
                    if cells:
                        yield (" — ".join(cells), False, cells)
        return
    if ext != ".docx":
        for ln in read_any(path).split("\n"):
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


def parse_plan(path) -> Plan:
    """План-конспект (DOCX, DOC, PDF или скан): тема, номер темы, цель и очищенный текст плана.

    Текст начинается с «Развёрнутого плана» или «Хода занятия», а если таких строк нет — с первого «Учебного
    вопроса» или сразу после списка литературы. Если и так ничего не нашлось (у файла нет шапки) — берём весь
    текст; тема тогда — из имени файла."""
    topic, goal, number = "", "", ""
    body: list[str] = []
    started, in_lit = False, False
    lines = list(_plan_lines(path))
    # есть «Развёрнутый план» / «Ход занятия» — текст строго с него; догадки по литературе — только без него
    marked = any(re.sub(r"\s+", " ", raw).strip().lower().startswith(_START) for raw, _, _ in lines)
    for raw, is_list, cells in lines:
        t = re.sub(r"\s+", " ", raw).strip()
        if not t:
            continue
        low = t.lower()
        if not topic:
            found = _topic_from_cells(cells) if cells else (
                (clean_topic(t), _topic_number(t)) if low.startswith("тема") else None)
            if found and found[0]:
                topic, number = found
                continue
        if low.startswith("цель занятия"):
            goal = t.split(":", 1)[-1].strip()
            continue
        if not started:
            if low.startswith(_START):
                started = True
                continue
            if low.startswith("литература"):
                in_lit = True
                continue
            if marked:
                continue
            if _QUESTION_RE.match(t):
                started = True  # «Развёрнутого плана» нет — текст с первого учебного вопроса
            elif in_lit and not _LITERATURE.match(t) and not _AUTHOR.match(t) and not cells and len(t) > 3:
                started = True  # литература кончилась — дальше текст плана
            else:
                continue
        if low.startswith(_END):
            break
        if _is_signature(t, is_list):
            break  # подпись составителя
        if _QUESTION_RE.match(t):
            body.append("")
            body.append(re.sub(r"^\d+\.\s*", "", t))
        elif is_list:
            body.append("- " + t)
        else:
            body.append(t)
    if not body:  # ни плана, ни вопросов, ни литературы — например, вводная к деловой игре или анализ: весь текст
        approval, skip = False, -1
        for n, (raw, is_list, cells) in enumerate(lines):
            t = re.sub(r"\s+", " ", raw).strip()
            if not t or cells or n == skip:
                continue
            low = t.lower()
            if not body and low.startswith("утверждаю"):
                approval = True  # гриф: до строки с годом
                continue
            if approval:
                if re.search(r"20\d\d|20__", low):
                    approval = False
                continue
            first = t.split()[0].strip("«»\"'.,:")
            if not topic and not body and first.isupper() and len(first) >= 4:
                # название документа: «АНАЛИЗ организации пожаротушения … за» + «2025 год»
                nxt = next((re.sub(r"\s+", " ", x).strip() for x, _, c in lines[n + 1:n + 2] if not c), "")
                joined = bool(nxt) and len(nxt) < 40 and not nxt.split()[0].isupper()
                title = t + (" " + nxt if joined else "")
                skip = n + 1 if joined else -1
                topic = clean_topic(title[:1] + title[1:].lower() if title.isupper() else
                                    first.capitalize() + title[len(first):])
                continue
            if low.startswith(_END) or (_is_signature(t, is_list) and sum(map(len, body)) > 1500):
                break
            body.append("- " + t if is_list else t)
    stem = re.sub(r"[+_]+", " ", Path(path).stem).strip()
    if not number:
        m = _FILE_NUMBER.match(stem)
        number = m.group(1) if m else ""
    if not topic:  # «Т4 кодекс чести.doc» → «Кодекс чести»
        name = _FILE_NUMBER.sub("", stem).strip(" .-–—")
        topic = clean_topic(name[:1].upper() + name[1:]) if name else ""
    text = "\n".join(body).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    return Plan(topic=topic, text=text, goal=goal, number=number)


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
            if t:
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
    return _doc_clean(read_doc_raw(path))


def read_doc_raw(path) -> str:
    """Текст из старого Word (.doc, Word 97–2003) без установленного Word.

    Файл — OLE-контейнер. В потоке WordDocument заголовок (FIB) указывает, где в табличном потоке лежит
    «таблица кусков» (CLX): из каких мест файла собирается текст и в какой кодировке (UTF-16 или 8 бит).
    Служебные символы Word превращаем в обычные: конец абзаца, ячейки таблицы, поля «код→результат»."""
    return doc_stream_raw(*_doc_streams(path))


def _doc_streams(path) -> tuple[bytes, bytes]:
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
    return word, table


def doc_stream_text(word: bytes, table: bytes) -> str:
    """Текст по потокам WordDocument и xTable (см. read_doc_text)."""
    return _doc_clean(doc_stream_raw(word, table))


def doc_stream_raw(word: bytes, table: bytes) -> str:
    """Текст .doc со служебными символами Word: \\r — конец абзаца, \\x07 — конец ячейки (и строки таблицы)."""
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
    return text.replace("\x15", "")


def _doc_clean(text: str) -> str:
    text = text.replace("\x07", "\t").replace("\x0b", "\n").replace("\r", "\n")
    text = re.sub(r"[\x00-\x08\x0c\x0e-\x1f]", "", text)
    lines = [ln.rstrip("\t ").replace("\t\t", "\t") for ln in text.split("\n")]
    return "\n".join(lines).strip()


def _fib(word: bytes) -> tuple[list[int], list[tuple[int, int]]]:
    """(rgLw — счётчики, rgFcLcb — пары «где/сколько») из заголовка .doc."""
    import struct
    pos = 32
    csw = struct.unpack_from("<H", word, pos)[0]
    pos += 2 + csw * 2
    cslw = struct.unpack_from("<H", word, pos)[0]
    lw = list(struct.unpack_from(f"<{cslw}i", word, pos + 2))
    pos += 2 + cslw * 4
    cb = struct.unpack_from("<H", word, pos)[0]
    flat = struct.unpack_from(f"<{cb * 2}I", word, pos + 2)
    return lw, list(zip(flat[0::2], flat[1::2]))


def _doc_pieces(word: bytes, table: bytes) -> list[tuple[int, int, int, bool]]:
    """Куски текста: (cp начала, cp конца, fc начала в WordDocument, 8-битный ли)."""
    import struct
    _, fl = _fib(word)
    fc_clx, lcb_clx = fl[33]
    clx = table[fc_clx:fc_clx + lcb_clx]
    i = 0
    while i < len(clx) and clx[i] == 0x01:
        i += 3 + struct.unpack_from("<H", clx, i + 1)[0]
    lcb = struct.unpack_from("<I", clx, i + 1)[0]
    plc = clx[i + 5:i + 5 + lcb]
    n = (len(plc) - 4) // 12
    cps = struct.unpack_from(f"<{n + 1}I", plc, 0)
    out = []
    for k in range(n):
        fc = struct.unpack_from("<I", plc, 4 * (n + 1) + 8 * k + 2)[0]
        small = bool(fc & 0x40000000)
        out.append((cps[k], cps[k + 1], (fc & ~0x40000000) // 2 if small else fc, small))
    return out


def _sprm_size(sprm: int, data: bytes, i: int) -> int:
    spra = (sprm >> 13) & 7
    if spra == 6:  # переменная длина: первый байт — размер (у таблиц — особый случай, двухбайтовый)
        if sprm in (0xD608, 0xD606):
            return int.from_bytes(data[i:i + 2], "little") + 1
        return data[i] + 1 if i < len(data) else 0
    return {0: 1, 1: 1, 2: 2, 3: 4, 4: 2, 5: 2, 7: 3}[spra]


def _doc_paragraph_props(word: bytes, table: bytes) -> list[tuple[int, int, bool, bool]]:
    """Свойства абзацев по месту в файле: (fc начала, fc конца, в таблице, конец строки таблицы).

    Берутся из страниц FKP, на которые ссылается PlcBtePapx: так Word сам отмечает абзацы в таблицах
    (sprmPFInTable) и знаки конца строки (sprmPFTtp) — гадать по символам не нужно."""
    import struct
    _, fl = _fib(word)
    fc, lcb = fl[13]  # fcPlcfBtePapx
    plc = table[fc:fc + lcb]
    n = (len(plc) - 4) // 8
    pns = struct.unpack_from(f"<{n}I", plc, 4 * (n + 1)) if n > 0 else ()
    out = []
    for pn in pns:
        page = word[(pn & 0x3FFFFF) * 512:(pn & 0x3FFFFF) * 512 + 512]
        if len(page) < 512:
            continue
        crun = page[511]
        fcs = struct.unpack_from(f"<{crun + 1}I", page, 0)
        for k in range(crun):
            off = page[4 * (crun + 1) + 13 * k] * 2
            in_table = ttp = False
            if off:
                cb = page[off]
                if cb:
                    start, size = off + 1, 2 * cb - 1
                else:
                    start, size = off + 2, 2 * page[off + 1]
                grp = page[start:start + size][2:]  # без istd
                i = 0
                while i + 2 <= len(grp):
                    sprm = struct.unpack_from("<H", grp, i)[0]
                    i += 2
                    val = grp[i] if i < len(grp) else 0
                    if sprm == 0x2416:
                        in_table = bool(val)
                    elif sprm == 0x2417:
                        ttp = bool(val)
                    elif sprm == 0x6649:
                        in_table = in_table or int.from_bytes(grp[i:i + 4], "little") > 0
                    i += _sprm_size(sprm, grp, i)
            out.append((fcs[k], fcs[k + 1], in_table, ttp))
    out.sort()
    return out


def _clean_fields(t: str) -> str:
    t = re.sub(r"\x13[^\x13\x14\x15]*\x14", "", t)
    t = re.sub(r"\x13[^\x13\x14\x15]*\x15", "", t)
    t = t.replace("\x15", "").replace("\x0b", "\n")
    return re.sub(r"[\x00-\x08\x0c\x0e-\x1f]", "", t).strip()


def doc_items(word: bytes, table: bytes):
    """Абзацы и таблицы старого Word в порядке следования: ("p", текст) и ("tbl", строки ячеек)."""
    import bisect
    lw, _ = _fib(word)
    ccp_text = lw[3] if len(lw) > 3 else None  # только основной текст, без колонтитулов и сносок
    props = _doc_paragraph_props(word, table)
    starts = [p[0] for p in props]

    def prop_at(fc: int):
        k = bisect.bisect_right(starts, fc) - 1
        if k >= 0 and props[k][0] <= fc < props[k][1]:
            return props[k][2], props[k][3]
        return False, False

    buf, cell, row, rows = [], [], [], []
    for cp0, cp1, fc0, small in _doc_pieces(word, table):
        if ccp_text is not None:
            cp1 = min(cp1, ccp_text)
        if cp1 <= cp0:
            continue
        width = 1 if small else 2
        raw = word[fc0:fc0 + (cp1 - cp0) * width]
        chars = raw.decode("cp1252" if small else "utf-16-le", "replace")
        for k, ch in enumerate(chars):
            if ch not in "\r\x07":
                buf.append(ch)
                continue
            in_table, ttp = prop_at(fc0 + k * width)
            text = "".join(buf)
            buf = []
            if ttp:  # знак конца строки таблицы
                if cell:
                    row.append(_clean_fields("\n".join(cell)))
                    cell = []
                rows.append(row)
                row = []
            elif in_table:
                cell.append(text)
                if ch == "\x07":  # конец ячейки
                    row.append(_clean_fields("\n".join(cell)))
                    cell = []
            else:
                if rows:
                    yield "tbl", rows
                    rows = []
                if _clean_fields(text):
                    yield "p", _clean_fields(text)
    if rows:
        yield "tbl", rows
    if _clean_fields("".join(buf)):
        yield "p", _clean_fields("".join(buf))


def read_doc_items(path):
    return list(doc_items(*_doc_streams(path)))


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


def match_plan(topic: str, plans: list[Plan], number: str = "") -> Plan | None:
    """План-конспект для занятия. Сначала по номеру темы («Тема № 11» в расписании и «Тема 11.doc» / «Тема № 11:»
    в шапке плана) — если и слова хоть немного совпадают (номера в разных предметах повторяются); иначе — по
    общим словам темы."""
    def words(s):
        return {w for w in re.findall(r"[а-яёa-z]{4,}", s.lower())}

    def score(p):
        tw, pw = words(topic), words(p.topic) | words(p.text[:400])
        return len(tw & pw) / len(tw | pw) if tw and pw else 0.0

    if number:
        same = [p for p in plans if p.number == number]
        if same:
            best = max(same, key=score)
            if score(best) >= 0.08 or not best.topic:
                return best
    tw = words(topic)
    best, top = None, 0.0
    for p in plans:
        pw = words(p.topic)
        if not tw or not pw:
            continue
        sc = len(tw & pw) / len(tw | pw)
        if len(pw) >= 2 and len(tw & pw) >= 0.8 * len(pw):
            sc = max(sc, 0.5)  # короткое название плана целиком есть в теме: «Деловая игра» → «…(деловая игра): …»
        if sc > top:
            best, top = p, sc
    return best if top >= 0.4 else None
