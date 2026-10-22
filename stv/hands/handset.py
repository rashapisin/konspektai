"""Набор почерка: варианты каждой буквы в мм, метрики и хранение в %APPDATA%\\KonspektAI\\hands\\*.json."""

import json
import re
import statistics
import time
from pathlib import Path

from . import template as T

FORMAT = 1
ID_PREFIX = "my:"


def hands_dir() -> Path:
    from ..brand import data_dir
    d = data_dir() / "hands"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _median(vals, default):
    vals = [v for v in vals if v is not None]
    return statistics.median(vals) if vals else default


def build(results, name: str) -> dict:
    """Собрать набор из распознанных листов. Повторный лист заменяет старые варианты тех же клеток."""
    glyphs: dict[str, dict[int, dict]] = {}
    pages = set()
    for r in results:
        pages.add(r.page)
        for g in r.glyphs:
            glyphs.setdefault(g.char, {})[g.variant] = {"polys": g.polys, "w": round(g.width, 3),
                                                        "top": round(g.top, 3), "bottom": round(g.bottom, 3)}
    flat = {ch: [v[k] for k in sorted(v)] for ch, v in glyphs.items()}

    def tops(chars):
        return [-v["top"] for ch in chars for v in flat.get(ch, [])]

    def p90(vals, default):
        vals = sorted(vals)
        return vals[int(0.9 * (len(vals) - 1))] if vals else default

    x_h = _median(tops("аеикмнопстчшъыьэюя"), 4.0)
    cap = _median(tops("АБВГЕКМНПРСТ"), x_h * 1.5)
    asc = p90(tops("бвдАБВГДЕЖЗИКЛМНОПРСТУФХЦЧШЩЭЮЯ"), cap)  # без «й», «ё» — их дужки и точки редки
    desc = p90([v["bottom"] for ch in "друфцщДЦЩ" for v in flat.get(ch, [])], x_h * 0.5)
    return {"format": FORMAT, "name": name, "created": time.strftime("%Y-%m-%d %H:%M"),
            "pages": sorted(pages), "metrics": {"x_height": round(x_h, 3), "cap_height": round(cap, 3),
                                                "ascent": round(asc, 3), "descent": round(max(desc, 0.5), 3)},
            "glyphs": flat}


def missing_chars(data: dict) -> list[str]:
    have = data.get("glyphs", {})
    return [ch for chars, _ in T.VARIANTS for ch in chars if ch not in have]


def _slug(name: str) -> str:
    s = re.sub(r"[^\w\-]+", "_", name.strip(), flags=re.UNICODE).strip("_")
    return (s or "почерк")[:40]


def save(data: dict) -> str:
    """Сохранить набор, вернуть его id для настроек почерка."""
    slug = _slug(data["name"])
    (hands_dir() / f"{slug}.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return ID_PREFIX + slug


def load(font_id: str) -> dict:
    slug = font_id[len(ID_PREFIX):]
    return json.loads((hands_dir() / f"{slug}.json").read_text(encoding="utf-8"))


def delete(font_id: str):
    (hands_dir() / f"{font_id[len(ID_PREFIX):]}.json").unlink(missing_ok=True)


def list_hands() -> list[tuple[str, str]]:
    """(id, название) всех сохранённых почерков."""
    out = []
    for f in sorted(hands_dir().glob("*.json")):
        try:
            name = json.loads(f.read_text(encoding="utf-8")).get("name", f.stem)
        except (OSError, ValueError):
            continue
        out.append((ID_PREFIX + f.stem, name))
    return out


def default_x_height(data: dict) -> float:
    """Размер строчных по умолчанию для строк через клетку 5 мм.

    Хвост вниз одной строки и высокая буква следующей встречаются редко, а если касаются —
    движок разводит слово, поэтому берём размах чуть больше клетки."""
    m = data["metrics"]
    span = m["ascent"] + m["descent"]
    return round(max(1.5, min(2.3, 5.5 * m["x_height"] / span)), 2) if span > 0 else 2.0
