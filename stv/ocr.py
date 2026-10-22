"""Распознавание текста на сканах и фото (офлайн): RapidOCR + модели PP-OCRv5 для русского языка.

Модели лежат в assets/ocr (Apache-2.0, PaddleOCR / RapidAI). Интернет не нужен.
"""

import re
import threading

import numpy as np

from .resources import asset

_engine = None
_lock = threading.Lock()

# Латинские буквы, похожие на русские: распознаватель путает их в русских словах
_HOMO = str.maketrans("AaBEeKkMHOoPpCcTXxYym∃", "АаВЕеКкМНОоРрСсТХхУуmЭ".replace("m", "м"))
_CYR = re.compile(r"[А-Яа-яЁё]")
_LAT = re.compile(r"[A-Za-z]")


def _get_engine():
    global _engine
    with _lock:
        if _engine is None:
            from rapidocr import RapidOCR
            _engine = RapidOCR(params={
                "Global.use_cls": False,
                "Global.log_level": "error",
                "Det.model_path": str(asset("ocr", "ch_PP-OCRv5_det_mobile.onnx")),
                "Rec.model_path": str(asset("ocr", "eslav_PP-OCRv5_rec_mobile.onnx")),
            })
    return _engine


def fix_homoglyphs(text: str) -> str:
    """В русских словах латинские двойники меняем на русские буквы («Огнетушuтель», «3–4 m»)."""
    if len(_CYR.findall(text)) < 3 * len(_LAT.findall(text)):
        return text  # текст в основном не русский — не трогаем

    def word(m):
        w = m.group(0)
        t = w.translate(_HOMO)
        if _LAT.search(t):
            return w  # есть латиница без русского двойника — настоящее латинское слово («MS», «Word»)
        if _CYR.search(w) or len(w) <= 2:
            return t
        return w
    return re.sub(r"[A-Za-zА-Яа-яЁё∃]+", word, text)


def assemble(boxes, texts) -> str:
    """Куски строк от распознавателя → строки → абзацы (с учётом переносов и отступов)."""
    items = []
    for b, t in zip(boxes, texts):
        b = np.asarray(b, dtype=float)
        y0, y1 = b[:, 1].min(), b[:, 1].max()
        items.append(((y0 + y1) / 2, y1 - y0, b[:, 0].min(), t.strip()))
    items = [it for it in items if it[3]]
    if not items:
        return ""
    items.sort(key=lambda it: it[0])
    lines: list[list] = []
    for it in items:
        if lines and abs(it[0] - lines[-1][0][0]) < 0.55 * max(it[1], lines[-1][0][1]):
            lines[-1].append(it)
        else:
            lines.append([it])
    rows = []
    for ln in lines:
        ln.sort(key=lambda it: it[2])
        rows.append((ln[0][0], ln[0][1], ln[0][2], " ".join(it[3] for it in ln)))
    left = min(r[2] for r in rows)
    out = rows[0][3]
    for prev, cur in zip(rows, rows[1:]):
        gap = cur[0] - prev[0]
        indent = cur[2] - left > 1.5 * cur[1]
        text = cur[3]
        if gap > 2.0 * cur[1] or indent:
            out += "\n" + text  # пустая строка или красная строка — новый абзац
        elif out.endswith("-") and text[:1].islower():
            out = out[:-1] + text  # перенос слова
        elif text[:1].islower() or not out.rstrip().endswith((".", ":", ";", "!", "?")):
            out += " " + text
        else:
            out += "\n" + text
    return fix_typography(fix_homoglyphs(out))


def fix_typography(text: str) -> str:
    """Типичные ошибки распознавания знаков: тире, кавычки, градусы.

    Тире между словами распознаётся как дефис; «ёлочки» — как "…", <<…>> или ,,…"; градус после числа — как
    буква o, ноль или звёздочка («-70 oC»). «- » в начале строки не трогаем: в программе это пункт списка."""
    text = re.sub(r"(?<=\S) [-–] (?=\S)", " — ", text)                    # слово - слово → слово — слово
    text = text.replace("<<", "«").replace(">>", "»").replace(",,", "«")
    text = re.sub(r'"([^"\n]{1,200})"', r"«\1»", text)                     # "слово" → «слово»
    text = re.sub(r'«([^«»"\n]{1,200})"', r"«\1»", text)                   # ,,слово" → «слово»
    text = re.sub(r"(\d) ?[oOоО0*º](?= ?[CСcс]\b)", r"\1 °", text)        # 70 oC, 70*C → 70 °C
    text = re.sub(r"(\d)° ?([CС])\b", r"\1 °\2", text)                     # 4°С → 4 °С
    return text


def ocr_image(image) -> str:
    """Текст с картинки: путь к файлу или массив numpy (BGR)."""
    import cv2
    if not isinstance(image, np.ndarray):
        data = np.fromfile(str(image), dtype=np.uint8)  # кириллица в пути
        image = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("Не удалось открыть изображение")
    res = _get_engine()(image)
    if res is None or res.txts is None:
        return ""
    return assemble(res.boxes, res.txts)
