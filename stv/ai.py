"""AI в ручном режиме: программа готовит запрос, человек вставляет его в любой чат и возвращает ответ.

Бесплатно, без ключей и без отправки чего-либо из программы. Тот же запрос отправляет кнопка
«Сжать через GigaChat» (stv/gigachat.py), если в Настройках сохранён ключ.
"""

from dataclasses import replace

from .engine.journal import KINDS, Entry, build
from .engine.settings import HandSettings, PageSettings

MODES = {
    "page": "сжать до одной страницы",
    "short": "краткий конспект (половина страницы)",
    "full": "сохранить как можно больше исходного текста",
}

_FILLER = ("Первичные средства пожаротушения предназначены для борьбы с пожаром в начальной стадии "
           "его развития, они просты в применении и всегда находятся под рукой. ") * 40

_capacity_cache: dict = {}


def page_capacity_chars(ps: PageSettings, hs: HandSettings, base_x_height: float) -> int:
    """Сколько знаков текста помещается на страницу под шапкой из двух строк (оценка по самому шрифту)."""
    key = (repr(ps), hs.font_id, round(base_x_height, 3), ps.line_step_cells)
    if key not in _capacity_cache:
        e = Entry(kind="self", topic="Тема", text=_FILLER, fit=False)
        doc, _ = build([e], replace(ps, date="01.01.26"), replace(hs, x_height_mm=base_x_height), base_x_height)
        first = doc.pages[0]
        body_lines = first.lines[2:]  # без шапки
        chars = sum(1 for ln in body_lines for g in ln.glyphs if not g.joiner)  # связки — не буквы
        spaces = chars // 7  # примерно одно слово на 7 букв
        _capacity_cache[key] = int(chars + spaces)
    return _capacity_cache[key]


def build_prompt(entry: Entry, source: str, target_chars: int, mode: str = "page") -> str:
    kind = KINDS.get(entry.kind, "")
    if mode == "short":
        target_chars = target_chars // 2
    limit = f"не больше {target_chars} знаков с пробелами" if mode != "full" else \
        f"примерно {target_chars} знаков; если важного больше — можно до {int(target_chars * 1.9)}"
    return f"""Сделай из учебного материала конспект для рукописной тетради ({kind.lower() or 'подготовка'}).
Тема: {entry.topic.strip() or 'по материалу ниже'}

Требования:
1. Объём: {limit}. Это одна тетрадная страница, превышать нельзя.
2. Сохрани определения, перечни, последовательности действий, числа, сроки и ссылки на документы — дословно.
3. Убери вводные фразы, примеры, обращения к слушателям, вопросы для обсуждения и повторы.
4. Ничего не добавляй от себя: только то, что есть в материале. Не придумывай номера приказов, пунктов и дат.
5. Если в материале есть учебные вопросы («Учебный вопрос №1 – …»), оставь их отдельными строками, под каждым —
главное. Если их нет — не придумывай вопросов, разделов и нумерации, которых нет в материале.
6. Пункты перечней начинай с «- ». Не пиши первой строкой тему или название — шапку программа добавит сама.
7. Без «Вывода» и «Заключения», если их нет в материале.
8. Ответь только текстом конспекта, без пояснений и без форматирования Markdown (никаких **, #).

Материал:
<<<
{source.strip()}
>>>"""


SOURCES_MARK = "ИСТОЧНИКИ:"


def write_prompt(entry: Entry, target_chars: int) -> str:
    """Конспект с нуля — только по теме, без материала. Источники — отдельным списком в конце: в тетрадь они
    не попадут, а останутся в «Исходнике», чтобы человек мог проверить факты.
    На проверке GigaChat Pro по истории писал точно, а по узкой служебной теме выдумал часть чисел и неверно
    назвал свод правил — поэтому это черновик, и интерфейс об этом прямо говорит."""
    kind = KINDS.get(entry.kind, "")
    return f"""Напиши конспект для рукописной тетради ({kind.lower() or 'учёба'}).
Тема: {entry.topic.strip()}

Требования:
1. Объём: не больше {target_chars} знаков с пробелами — это одна тетрадная страница.
2. Только проверенные, общеизвестные сведения по теме: определения, классификации, порядок действий, ключевые
   даты и числа. Если в чём-то не уверен — лучше не пиши это вовсе, чем пиши неточно.
3. Не придумывай номера приказов, статей, пунктов и дат.
4. Пункты перечней начинай с «- ». Без заголовка с темой — шапку программа добавит сама.
5. Без форматирования Markdown (никаких **, #).
6. После конспекта отдельной строкой напиши «{SOURCES_MARK}» и перечисли 2–4 источника, по которым можно
   проверить написанное (учебники, законы, ГОСТы, справочники). Указывай только те, в существовании которых
   уверен; если не уверен — напиши «нет».
"""


def write_from_topic(llm, entry: Entry, target_chars: int) -> tuple[str, str]:
    """Тема → (конспект, источники для проверки). Источники отделены и в тетрадь не попадают."""
    raw = llm.complete(write_prompt(entry, target_chars), temperature=0.2)
    body, _, sources = raw.partition(SOURCES_MARK)
    text = clean_answer(body, entry.topic)
    if len(text) > target_chars * 1.25:
        shorter = clean_answer(llm.complete(shorten_prompt(text, target_chars)), entry.topic)
        if 40 <= len(shorter) < len(text):
            text = shorter
    return text, clean_answer(sources)


def shorten_prompt(text: str, target_chars: int) -> str:
    """Второй заход, если нейросеть написала длиннее, чем помещается на страницу."""
    return (f"Сократи этот конспект до {target_chars} знаков с пробелами. Сохрани определения, перечни, числа и "
            f"порядок действий дословно, убери второстепенное. Ничего не добавляй. Ответь только текстом.\n\n"
            f"<<<\n{text.strip()}\n>>>")


def shorten(llm, text: str, target_chars: int, topic: str = "") -> str:
    """Готовый конспект не уместился на страницу даже мелким почерком — сократить до точного объёма."""
    return clean_answer(llm.complete(shorten_prompt(text, target_chars)), topic)


def compress(llm, entry: Entry, source: str, target_chars: int) -> str:
    """Материал → конспект на страницу через нейросеть (llm.complete). Если вышло заметно длиннее —
    ещё один запрос «сократи». Небольшой перебор не страшен: «Уместить на страницу» чуть уменьшит почерк."""
    text = clean_answer(llm.complete(build_prompt(entry, source, target_chars)), entry.topic)
    if len(text) > target_chars * 1.25:  # небольшой перебор уберёт «Уместить на страницу»
        shorter = clean_answer(llm.complete(shorten_prompt(text, target_chars)), entry.topic)
        if 40 <= len(shorter) < len(text):
            text = shorter
    return text


def clean_answer(text: str, topic: str = "") -> str:
    """Убираем следы Markdown, типичные вступления чат-ботов и повтор темы первой строкой."""
    import re
    lines = []
    for ln in text.replace("\r\n", "\n").split("\n"):
        s = ln.strip()
        if not lines and re.match(r"^(вот|конечно|ниже)\b", s, re.I) and s.endswith(":"):
            continue  # «Вот конспект:»
        s = re.sub(r"^#{1,6}\s*", "", s)
        s = s.replace("**", "").replace("__", "")
        s = re.sub(r"^[*•]\s+", "- ", s)
        lines.append(s)
    out = "\n".join(lines).strip()
    first, _, rest = out.partition("\n")
    if topic.strip() and first.strip(" .:").lower() == topic.strip(" .:").lower():
        out = rest.strip()  # шапку с темой программа добавляет сама
    return out
