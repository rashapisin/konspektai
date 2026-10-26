"""Распознавание заполненного шаблона по фото или скану.

1. Находим четыре чёрных квадрата по углам и выпрямляем перспективу.
2. По квадратикам вверху узнаём номер листа.
3. В каждой клетке отделяем чернила от бумаги и серых линий-подсказок.
4. Переводим каждую букву в векторные контуры (мм от базовой линии).
"""

import itertools
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from . import template as T

PX = 12.0  # пикселей на мм после выравнивания


@dataclass
class Glyph:
    char: str
    variant: int
    polys: list[list[tuple[float, float]]]  # контуры, мм: x от левого края чернил, y от базовой линии (вниз +)
    width: float
    top: float      # самая высокая точка (отрицательная — над базовой линией)
    bottom: float   # самая низкая точка


@dataclass
class PageResult:
    page: int
    glyphs: list[Glyph] = field(default_factory=list)
    empty: list[str] = field(default_factory=list)  # клетки, где ничего не написано
    debug: np.ndarray | None = None


class ScanError(Exception):
    pass


def _imread(path) -> np.ndarray:
    data = np.fromfile(str(path), dtype=np.uint8)  # cv2.imread не понимает кириллицу в пути
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        raise ScanError(f"Не удалось открыть изображение: {Path(path).name}")
    return img


def _find_markers(gray: np.ndarray) -> np.ndarray:
    """Центры четырёх угловых квадратов: ЛВ, ПВ, ПН, ЛН."""
    h, w = gray.shape
    scale = 1600.0 / max(h, w)
    small = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else gray
    scale = min(scale, 1.0)
    blur = cv2.GaussianBlur(small, (5, 5), 0)
    _, bw = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    contours, _ = cv2.findContours(bw, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    area_img = small.shape[0] * small.shape[1]
    cands = []
    for c in contours:
        a = cv2.contourArea(c)
        if not (area_img * 0.0003 < a < area_img * 0.02):
            continue
        (cx, cy), (rw, rh), _ = cv2.minAreaRect(c)
        if min(rw, rh) == 0 or not (0.7 < rw / rh < 1.43):
            continue
        if a / (rw * rh) < 0.8:  # почти сплошной квадрат
            continue
        cands.append((cx, cy, a))
    if len(cands) < 4:
        raise ScanError("Не нашлись чёрные квадраты по углам листа. Снимите лист целиком, при хорошем свете.")
    cands.sort(key=lambda t: -t[2])
    cands = cands[:14]  # квадраты-метки — самые крупные
    want = (T.MARKERS[1][0] - T.MARKERS[0][0]) / (T.MARKERS[3][1] - T.MARKERS[0][1])
    best, best_score = None, 0.0
    for quad in itertools.combinations(cands, 4):
        pts = np.array([(x, y) for x, y, _ in quad], dtype=np.float32)
        areas = [a for _, _, a in quad]
        if max(areas) > 2.5 * min(areas):
            continue  # метки одного размера
        ordered = _order(pts)
        hull_area = cv2.contourArea(ordered)
        w1 = np.linalg.norm(ordered[1] - ordered[0])
        h1 = np.linalg.norm(ordered[3] - ordered[0])
        if h1 == 0 or not (0.6 * want < w1 / h1 < 1.6 * want):
            continue
        if hull_area > best_score:
            best, best_score = ordered, hull_area
    if best is None:
        raise ScanError("Квадраты по углам найдены не все. Проверьте, что все четыре попали в кадр.")
    return best / scale


def _order(pts: np.ndarray) -> np.ndarray:
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).ravel()
    return np.array([pts[np.argmin(s)], pts[np.argmin(d)], pts[np.argmax(s)], pts[np.argmax(d)]], dtype=np.float32)


def _warp(img: np.ndarray, markers: np.ndarray) -> np.ndarray:
    dst = np.array([(x * PX, y * PX) for x, y in T.MARKERS], dtype=np.float32)
    m = cv2.getPerspectiveTransform(markers.astype(np.float32), dst)
    return cv2.warpPerspective(img, m, (int(T.PAGE_W * PX), int(T.PAGE_H * PX)), flags=cv2.INTER_CUBIC,
                               borderValue=(255, 255, 255))


def _dark(gray: np.ndarray, cx: float, cy: float, size: float) -> float:
    r = int(size * PX * 0.3)
    x, y = int(cx * PX), int(cy * PX)
    return 1.0 - float(gray[y - r:y + r, x - r:x + r].mean()) / 255.0


def _read_page_number(gray: np.ndarray) -> int:
    marks = [_dark(gray, x, T.CODE_Y, T.CODE_SIZE) > 0.5 for x in T.CODE_X]
    if not marks[0]:
        raise ScanError("Лист распознан неуверенно: не виден опорный квадратик вверху. Переснимите ровнее.")
    return sum(1 << i for i, on in enumerate(marks[1:]) if on)


def _ink_mask(crop: np.ndarray) -> np.ndarray:
    """Чернила: заметно темнее бумаги. Голубые линии-подсказки светлее порога и отбрасываются."""
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    paper = float(np.percentile(gray, 90))
    thr = min(paper * 0.62, paper - 55)
    core = paper * 0.45  # настоящие чернила хотя бы где-то по-настоящему тёмные, серая печать — нет
    mask = (gray < thr).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    keep = np.zeros_like(mask)
    min_area = 0.12 * PX * PX
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] < min_area:
            continue
        comp = labels == i
        if gray[comp].min() > core:
            continue
        keep[comp] = 255
    return keep


def _vectorize(mask: np.ndarray, baseline_px: float) -> tuple[list, float, float, float] | None:
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return None
    x0 = xs.min()
    soft = cv2.GaussianBlur(mask, (5, 5), 1.2)  # сглаживаем «лесенку» пикселей
    _, soft = cv2.threshold(soft, 110, 255, cv2.THRESH_BINARY)
    contours, _ = cv2.findContours(soft, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    polys = []
    for c in contours:
        if len(c) < 8:
            continue
        pts = c[:, 0, :].astype(np.float32)
        k = 5  # скользящее среднее по контуру — плавнее линия
        pad = np.concatenate([pts[-k:], pts, pts[:k]])
        kernel = np.ones(2 * k + 1) / (2 * k + 1)
        sm = np.stack([np.convolve(pad[:, i], kernel, mode="valid") for i in (0, 1)], axis=1).astype(np.float32)
        approx = cv2.approxPolyDP(sm.reshape(-1, 1, 2), 0.5, True)[:, 0, :]
        if len(approx) < 3:
            continue
        polys.append([(round(float(x - x0) / PX, 3), round(float(y - baseline_px) / PX, 3)) for x, y in approx])
    if not polys:
        return None
    width = float(xs.max() - x0 + 1) / PX
    top = float(ys.min() - baseline_px) / PX
    bottom = float(ys.max() - baseline_px) / PX
    return polys, width, top, bottom


def scan_image(path) -> PageResult:
    img = _imread(path)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    markers = _find_markers(gray)
    flat = _warp(img, markers)
    fgray = cv2.cvtColor(flat, cv2.COLOR_BGR2GRAY)
    page = _read_page_number(fgray)
    res = PageResult(page=page, debug=flat)
    cells = [c for c in T.cells() if c.page == page]
    if not cells:
        raise ScanError(f"Лист с номером {page + 1} не из этого шаблона.")
    ins = T.INSET
    for c in cells:
        # только внутри квадрата: подпись над ним и рамка — тёмная печать, не чернила
        bx, by, bw, bh = c.box
        x0, x1 = (bx + ins) * PX, (bx + bw - ins) * PX
        y0, y1 = (by + ins) * PX, (by + bh - ins) * PX
        crop = flat[int(y0):int(y1), int(x0):int(x1)]
        mask = _ink_mask(crop)
        v = _vectorize(mask, (c.y + T.BASELINE) * PX - y0)
        if v is None:
            res.empty.append(c.char)
            continue
        polys, width, top, bottom = v
        res.glyphs.append(Glyph(c.char, c.variant, polys, width, top, bottom))
    return res
