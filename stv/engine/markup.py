"""Разбор входного текста на блоки.

Разметка прототипа:
    # Заголовок          — по центру строки
    - пункт / 1. пункт   — пункт списка, без красной строки
    [страница]           — перейти на новую страницу
    [дата 05.02.26]      — дата на поле для следующих страниц
    [лист проверки]      — страница «лист проверки»
    пустая строка        — пропустить строку
    остальное            — абзац с красной строкой
"""

import re
from dataclasses import dataclass

_LIST_RE = re.compile(r"^(?:[-–—•*]|\d{1,3}[.)])\s+")
_DATE_RE = re.compile(r"^\[\s*дата\s+(.+?)\s*\]$", re.IGNORECASE)

# Символы, которые заменяем на привычные для письма от руки
_NORMALIZE = {
    " ": " ", " ": " ", " ": " ", "\t": " ",
    "‘": "'", "’": "'", "“": "«", "”": "»", "„": "«",
    "…": "...", "­": "",
}


@dataclass(frozen=True)
class Block:
    kind: str  # para | heading | list | blank | pagebreak | date | checksheet
    text: str = ""


def normalize(text: str) -> str:
    for a, b in _NORMALIZE.items():
        text = text.replace(a, b)
    return re.sub(r" {2,}", " ", text)


def parse(text: str) -> list[Block]:
    blocks: list[Block] = []
    for raw in normalize(text.replace("\r\n", "\n").replace("\r", "\n")).split("\n"):
        line = raw.strip()
        low = line.lower()
        if not line:
            blocks.append(Block("blank"))
        elif low == "[страница]":
            blocks.append(Block("pagebreak"))
        elif low == "[лист проверки]":
            blocks.append(Block("checksheet"))
        elif m := _DATE_RE.match(line):
            blocks.append(Block("date", m.group(1)))
        elif line.startswith("#"):
            blocks.append(Block("heading", line.lstrip("#").strip()))
        elif _LIST_RE.match(line):
            blocks.append(Block("list", line))
        else:
            blocks.append(Block("para", line))
    return blocks
