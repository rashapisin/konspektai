"""Журнал конспектов: тетрадь из отдельных конспектов, каждый — с новой страницы.

Правила оформления (со слов владельца, 21.10.2026):
- самостоятельная подготовка: у каждого конспекта дата на поле и шапка
  «Самостоятельная подготовка» / «Тема: …»; даты идут по графику «сутки через трое» (+4 дня);
- служебная и специальная подготовка: дата и шапка только у первого конспекта дня,
  следующие конспекты того же дня — без даты и без названия вида подготовки.
  Это предварительно: уточним по образцам и расписанию.
"""

import datetime as dt
import uuid
from dataclasses import dataclass, field, replace

from .layout import Document, Page, typeset
from .settings import HandSettings, PageSettings

KINDS = {
    "self": "Самостоятельная подготовка",
    "service": "Служебная подготовка",
    "special": "Специальная подготовка",
    "free": "Без шапки",
    "study": "Учёба",   # тема по центру, дата на поле — если указана
}
DATE_FMT = "%d.%m.%y"

# Пределы автоподбора размера относительно размера почерка по умолчанию
FIT_MIN, FIT_MAX = 0.75, 1.2


@dataclass
class Entry:
    kind: str = "self"
    topic: str = ""
    text: str = ""
    date: str = ""
    date_auto: bool = True   # дата считается по графику от предыдущего конспекта
    write: bool = True       # писать в тетрадь (иначе — только для изучения)
    fit: bool = True         # уместить на одну страницу
    source: str = ""         # исходный материал (план-конспект), из которого сделан текст
    fit_size: float = 0.0    # размер, подобранный «Уместить на страницу» в прошлый раз, — с него ищем снова
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    def title(self) -> str:
        return self.topic.strip() or "Без темы"


def parse_date(s: str) -> dt.date | None:
    for fmt in (DATE_FMT, "%d.%m.%Y"):
        try:
            return dt.datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            continue
    return None


def recompute_dates(entries: list[Entry], step_days: int = 4):
    """Самостоятельная подготовка: каждая следующая дата = предыдущая + шаг, если не задана вручную."""
    prev: dt.date | None = None
    for e in entries:
        if e.kind != "self":
            continue
        if e.date_auto and prev is not None:
            e.date = (prev + dt.timedelta(days=step_days)).strftime(DATE_FMT)
        d = parse_date(e.date)
        if d:
            prev = d


def _header(entries: list[Entry], i: int) -> tuple[list[str], str]:
    """Строки шапки и дата для конспекта i."""
    e = entries[i]
    if e.kind == "free":
        return [], e.date
    if e.kind == "study":
        return ([f"# {e.topic.strip()}"] if e.topic.strip() else []), e.date
    topic = f"# Тема: {e.topic.strip()}" if e.topic.strip() else ""
    if e.kind in ("service", "special"):
        first_of_day = not any(p.kind == e.kind and p.date == e.date and p.write for p in entries[:i])
        if not first_of_day:
            return [topic] if topic else [], ""
    return [f"# {KINDS[e.kind]}"] + ([topic] if topic else []), e.date


@dataclass
class EntryResult:
    entry_id: str
    first_page: int
    pages: int
    fill: float          # заполненность последней страницы, 0..1
    overflow_rows: int   # сколько строк ушло за первую страницу
    x_height_mm: float   # с каким размером букв свёрстан


def _typeset_entry(markup: str, ps: PageSettings, hs: HandSettings, start: int) -> Document:
    return typeset(markup, ps, hs, first_page_index=start)


def _fit(markup: str, ps: PageSettings, hs: HandSettings, start: int, base: float,
         hint: float = 0.0) -> Document:
    """Самый крупный почерк, при котором конспект занимает одну страницу.

    hint — размер прошлого раза: после небольшой правки ответ рядом, и хватает 2–3 вёрсток вместо 8."""
    lo, hi = base * FIT_MIN, base * FIT_MAX

    def one_page(size: float) -> Document | None:
        d = _typeset_entry(markup, ps, replace(hs, x_height_mm=size), start)
        return d if len(d.pages) == 1 else None

    if lo < hint < hi:
        step = hint * 0.03
        d = one_page(hint)
        if d is not None:
            up = min(hi, hint + step)
            if one_page(up) is None:  # крупнее уже не влезает — прошлый размер и есть ответ (точность 3%)
                return d
            lo, best = up, None  # влезает и крупнее — ищем выше обычным способом
        else:
            down = max(lo, hint - step)
            d = one_page(down)
            if d is not None:
                return _bisect(one_page, down, hint, d, 2)
            hi = down  # стало заметно длиннее — ищем ниже
    doc_hi = _typeset_entry(markup, ps, replace(hs, x_height_mm=hi), start)
    if len(doc_hi.pages) == 1:
        return doc_hi  # текст короткий: даже самый крупный почерк умещается
    doc_lo = _typeset_entry(markup, ps, replace(hs, x_height_mm=lo), start)
    if len(doc_lo.pages) > 1:
        return doc_lo  # не помещается даже мелким — покажем перенос
    return _bisect(one_page, lo, hi, doc_lo, 6)


def _bisect(one_page, lo: float, hi: float, best: Document, steps: int) -> Document:
    """lo влезает (best), hi — нет: сужаем, пока разница не станет меньше процента."""
    for _ in range(steps):
        mid = (lo + hi) / 2
        d = one_page(mid)
        if d is not None:
            best, lo = d, mid
        else:
            hi = mid
    return best


def build(entries: list[Entry], ps: PageSettings, hs: HandSettings,
          base_x_height: float, cache: dict | None = None) -> tuple[Document, list[EntryResult]]:
    """Свёрстанная тетрадь из отмеченных конспектов. cache ускоряет повторную вёрстку без изменений."""
    pages: list[Page] = []
    warnings: list[str] = []
    results: list[EntryResult] = []
    for i, e in enumerate(entries):
        if not e.write:
            continue
        header, date = _header(entries, i)
        markup = "\n".join(header + ([""] if header else []) + [e.text])
        eps = replace(ps, date=date)
        start = len(pages)
        key = (markup, repr(eps), repr(hs), base_x_height, e.fit, start % 2)
        doc = cache.get(key) if cache is not None else None
        if doc is None:
            doc = (_fit(markup, eps, hs, start, base_x_height, e.fit_size) if e.fit
                   else _typeset_entry(markup, eps, hs, start))
            if cache is not None:
                cache[key] = doc
        doc_pages = [replace(p, index=start + j, entry_id=e.id) for j, p in enumerate(doc.pages)]
        for p in doc_pages[1:]:
            p.date, p.date_glyphs = "", []  # дата — только на первой странице конспекта
        overflow = sum(p.rows_used for p in doc_pages[1:])
        if overflow:
            # обычный перенос, а не ошибка: тихие пометки только в предпросмотре
            doc_pages[0].note, doc_pages[0].note_bottom = "Продолжение на следующей странице", True
            doc_pages[1].note = f"Продолжение: «{e.title()}»"
        pages.extend(doc_pages)
        warnings.extend(f"«{e.title()}»: {w}" for w in doc.warnings)
        results.append(EntryResult(e.id, start, len(doc_pages), doc_pages[-1].fill, overflow,
                                   doc.hand.x_height_mm or base_x_height))
    if not pages:
        pages = typeset("", ps, hs).pages
    return Document(pages, ps, hs, warnings), results
