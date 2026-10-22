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
    return s.strip(" .") + ("." if s.strip(" .") else "")


# ---------- расписание ----------

def parse_schedule(path) -> list[Lesson]:
    kind = "service"
    lessons: list[Lesson] = []
    for b in _blocks(path):
        if hasattr(b, "text"):  # абзац
            if "специальной подготовк" in b.text.lower():
                kind = "special"
            continue
        rows = [_row_cells(r) for r in b.rows]
        if not rows:
            continue
        head = [c.lower() for c in rows[0]]
        if not any(c.startswith("дата") for c in head):
            # таблица «УТВЕРЖДАЮ» или другая служебная
            if any("специальной подготовк" in c for c in head):
                kind = "special"
            continue
        i_date = next(i for i, c in enumerate(head) if c.startswith("дата"))
        i_topic = next((i for i, c in enumerate(head) if "тем" in c), i_date + 2)
        i_hours = next((i for i, c in enumerate(head) if "час" in c and "заняти" not in c), None)
        for r in rows[1:]:
            if len(r) <= max(i_date, i_topic) or all(c.strip().isdigit() for c in r if c.strip()):
                continue  # нумерация колонок «1 | 2 | 3»
            date = _short_date(r[i_date])
            if not date:
                continue
            lessons.append(_lesson_from_cell(r[i_topic], date, kind,
                                             r[i_hours] if i_hours is not None and i_hours < len(r) else ""))
    return lessons


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
    les.topic = clean_topic(" ".join(topic_parts) if topic_parts else les.subject)
    if not topic_parts:
        les.subject = ""
    return les


# ---------- план-конспект ----------

_START = ("развернутый план", "развёрнутый план", "ход занятия", "содержание занятия")
_END = ("пособия и оборудование", "составил план", "составил:")
_SIGNATURE = re.compile(r"(инженер|начальник|заместитель|психолог|лейтенант|капитан|майор|полковник)\b", re.I)


@dataclass
class Plan:
    topic: str
    text: str        # очищенный текст для конспекта (разметка KonspektAI: «- » для пунктов)
    goal: str = ""


_LIST_MARK = re.compile(r"^\s*[-–—•·▪]\s+")


def _plan_lines(path):
    """(текст, это пункт списка) построчно: из DOCX — по абзацам, из PDF и сканов — по строкам."""
    if Path(path).suffix.lower() != ".docx":
        for ln in read_any(path).split("\n"):
            yield (_LIST_MARK.sub("", ln), bool(_LIST_MARK.match(ln)))
        return
    for b in _blocks(path):
        if hasattr(b, "text"):
            yield (b.text, _is_list_item(b))
        else:  # таблицы переносим строками «ячейка — ячейка»
            for r in b.rows:
                cells = [c for c in _row_cells(r) if c]
                if cells:
                    yield (" — ".join(cells), False)


def parse_plan(path) -> Plan:
    """План-конспект (DOCX, PDF или скан): тема, цель и очищенный текст развёрнутого плана."""
    topic, goal = "", ""
    body: list[str] = []
    started = False
    for raw, is_list in _plan_lines(path):
        t = re.sub(r"\s+", " ", raw).strip()
        if not t:
            continue
        low = t.lower()
        if not topic and low.startswith("тема"):
            topic = clean_topic(t)
            continue
        if low.startswith("цель занятия"):
            goal = t.split(":", 1)[-1].strip()
            continue
        if not started:
            if low.startswith(_START):
                started = True
            continue
        if low.startswith(_END):
            break
        if _SIGNATURE.match(low) and len(t) < 120:
            break  # подпись составителя
        if _QUESTION_RE.match(t):
            body.append("")
            body.append(re.sub(r"^\d+\.\s*", "", t))
        elif is_list:
            body.append("- " + t)
        else:
            body.append(t)
    text = "\n".join(body).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    return Plan(topic=topic, text=text, goal=goal)


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
