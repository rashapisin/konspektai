"""Калибровка принтера по фото или скану напечатанного листа — без «какая риска совпала».

Принтер печатает на листе блока тонкие чёрные линии посередине клеток. Программа находит на фото лист,
выпрямляет перспективу и в нескольких полосах листа сравнивает каждую чёрную линию с синими рядом с ней.
Изгиб бумаги, наклон телефона и искажения объектива одинаково сдвигают и синее, и чёрное, поэтому
почти не влияют: важно только, куда чёрное легло относительно своей клетки.

Модель печати по одной оси, в координатах клетки: u = A + B·(off + s·x), где x — где мы рисовали, off и s —
наши поправки, A и B — неизвестный сдвиг и «растяжение» принтера относительно клетки блока. По чёрным линиям
находим A и B, отсюда новые off и s, при которых нарисованное в x ляжет ровно в клетку x.
"""

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .engine.paper import PaperProfile, Side
from .engine.settings import PrinterOffset

PX = 8.0       # пикселей на мм после выпрямления
EDGE_MM = 11.0  # у краёв отверстия, тень и обрез — не измеряем


class PhotoError(Exception):
    pass


@dataclass
class AxisFit:
    off: float        # новая поправка, мм
    scale: float      # новый масштаб
    shift_mm: float   # насколько печать сейчас промахивается мимо клетки (в середине листа), мм
    lines: int        # сколько чёрных линий нашлось
    residual: float   # разброс точек вокруг прямой, мм — мера надёжности
    mid: float = 0.0  # середина измеренных линий, мм профиля
    skew: float = 0.0  # разница сдвига между краями листа, мм: лист прошёл через принтер наискосок

    def without_scale(self) -> float:
        """Поправка, если масштаб оставить 1: та же точка в середине листа."""
        return self.with_scale(1.0)

    def with_scale(self, s: float) -> float:
        """Поправка для масштаба s, при которой середина листа ложится туда же."""
        return round(self.off + (self.scale - s) * self.mid, 2)


@dataclass
class PhotoResult:
    offset: PrinterOffset
    x: AxisFit
    y: AxisFit
    debug: np.ndarray  # выпрямленный лист с найденными линиями — показать человеку


def imread(path) -> np.ndarray:
    try:
        data = np.fromfile(str(path), dtype=np.uint8)  # cv2.imread не понимает кириллицу в пути
    except OSError:
        raise PhotoError(f"Не удалось открыть файл: {Path(path).name}") from None
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        raise PhotoError(f"Не удалось открыть изображение: {Path(path).name}")
    return img


# ---------- лист на фото ----------

def _order(pts: np.ndarray) -> np.ndarray:
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).ravel()
    return np.array([pts[np.argmin(s)], pts[np.argmin(d)], pts[np.argmax(s)], pts[np.argmax(d)]], dtype=np.float32)


def find_sheet(img: np.ndarray) -> np.ndarray:
    """Четыре угла листа (ЛВ, ПВ, ПН, ЛН) в координатах фото. Лист светлее фона (стол, ковёр, крышка сканера
    обычно темнее белой бумаги)."""
    h, w = img.shape[:2]
    k = 1200.0 / max(h, w)
    small = cv2.resize(img, None, fx=k, fy=k, interpolation=cv2.INTER_AREA) if k < 1 else img.copy()
    k = min(k, 1.0)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    # бумага: светлая и почти бесцветная (сетка тонкая и после размытия не мешает)
    paper = ((gray > 0) & (hsv[..., 1] < 70)).astype(np.uint8)
    val = cv2.GaussianBlur(gray, (9, 9), 0)
    _, bright = cv2.threshold(val, 0, 1, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    mask = (bright & paper).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((9, 9), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        raise PhotoError("Не нашёл лист на фото. Положите лист на тёмный стол и снимите его целиком.")
    c = max(contours, key=cv2.contourArea)
    if cv2.contourArea(c) < 0.15 * small.shape[0] * small.shape[1]:
        raise PhotoError("Лист на фото слишком маленький или обрезан. Снимите ближе, но чтобы были видны все 4 угла.")
    hull = cv2.convexHull(c)
    quad = None
    for eps in (0.01, 0.015, 0.02, 0.03, 0.04):
        a = cv2.approxPolyDP(hull, eps * cv2.arcLength(hull, True), True)
        if len(a) == 4:
            quad = a.reshape(4, 2).astype(np.float32)
            break
    if quad is None:
        quad = cv2.boxPoints(cv2.minAreaRect(hull)).astype(np.float32)
    return _order(quad) / k


def warp_sheet(img: np.ndarray, corners: np.ndarray, paper: PaperProfile, side: Side) -> np.ndarray:
    """Лист «как сверху», 1 мм = PX пикселей, книжная ориентация, отверстия там, где им положено."""
    tl, tr, br, bl = corners
    if np.linalg.norm(tr - tl) > np.linalg.norm(bl - tl):  # лист лежит боком
        corners = np.array([bl, tl, tr, br], dtype=np.float32)
    W, H = int(round(paper.width_mm * PX)), int(round(paper.height_mm * PX))
    dst = np.array([(0, 0), (W - 1, 0), (W - 1, H - 1), (0, H - 1)], dtype=np.float32)
    m = cv2.getPerspectiveTransform(corners.astype(np.float32), dst)
    out = cv2.warpPerspective(img, m, (W, H), flags=cv2.INTER_CUBIC, borderValue=(255, 255, 255))
    if paper.holes:
        # отверстия: в них виден фон. Лицевая — слева, оборот — справа; иначе лист снят вверх ногами
        # тёмные круглые пятна ~5 мм; тонкие линии (сетка, печать) убирает «открытие» крупным кругом
        gray = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)
        dark = (gray < np.median(gray) * 0.7).astype(np.uint8)
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(2.5 * PX), int(2.5 * PX)))
        blobs = cv2.morphologyEx(dark, cv2.MORPH_OPEN, k)
        strip = int(12 * PX)
        left, right = blobs[:, :strip].mean(), blobs[:, W - strip:].mean()
        if max(left, right) > 0.002 and (left > right) != (side is Side.FRONT):
            out = cv2.rotate(out, cv2.ROTATE_180)
    return out


# ---------- линии ----------

def _masks(sheet: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(синее, чёрное) как веса 0…1."""
    f = sheet.astype(np.float32)
    b, g, r = f[..., 0], f[..., 1], f[..., 2]
    gray = 0.114 * b + 0.587 * g + 0.299 * r
    # уровень бумаги по окрестности: тень от руки или лампы не должна становиться «чернилами»
    paper = cv2.GaussianBlur(cv2.dilate(gray, np.ones((15, 15), np.uint8)), (0, 0), 25)
    rel = gray / np.maximum(paper, 1)
    blue = np.clip((b - r - 12) / 40, 0, 1) * (rel > 0.55)
    black = np.clip((0.68 - rel) / 0.25, 0, 1) * (np.abs(b - r) < 40)
    return blue, black


def _peaks(profile: np.ndarray, sep_px: float) -> list[tuple[float, float]]:
    """Линии в профиле: (центр с точностью до долей пикселя, сила). Соседние пики не ближе sep_px —
    так на обороте видны и своя клетка, и бледная клетка лицевой стороны, просвечивающая насквозь."""
    p = cv2.GaussianBlur(profile.reshape(1, -1).astype(np.float32), (0, 0), max(1.0, PX * 0.2)).ravel()
    p = p - np.percentile(p, 30)
    thr = 0.25 * np.percentile(p, 97)
    out, n, i = [], len(p), 1
    half = max(2, int(PX * 0.5))  # центр — по ±0,5 мм: линия тонкая, соседей не задеваем
    while i < n - 1:
        if p[i] > thr and p[i] >= p[i - 1] and p[i] >= p[i + 1]:
            a, b = max(0, i - half), min(n, i + half + 1)
            seg = np.clip(p[a:b], 0, None)
            if seg.sum() > 0:
                out.append((float((seg * np.arange(a, b)).sum() / seg.sum()), float(p[i])))
            i += max(1, int(sep_px))
            continue
        i += 1
    return out


def _fit(pairs: list[tuple[float, float]]) -> tuple[float, float, float]:
    """Прямая «нашлось = a + b·ожидалось», разброс в мм."""
    e = np.array([p[0] for p in pairs])
    f = np.array([p[1] for p in pairs])
    b, a = np.polyfit(e, f, 1)
    res = float(np.sqrt(np.mean((f - (a + b * e)) ** 2)))
    return float(a), float(b), res


def _blue_index(blue: list[tuple[float, float]], grid: list[float], cell: float) -> tuple[np.ndarray, np.ndarray]:
    """Синие линии с номерами клетки профиля: (где на фото, где по профилю).

    Общий сдвиг фото и неточность профиля (до полклетки) подбираются по «весу» совпавших линий: настоящая
    клетка этой стороны ярче, чем просвечивающая с другой. Дальше у каждой линии профиля — самая сильная
    синяя линия рядом."""
    if len(blue) < 4:
        return np.array([]), np.array([])
    b = np.array([p for p, _ in blue])
    w = np.array([h for _, h in blue])
    g = np.array(grid)
    tol = cell * 0.12
    best = (-1.0, 0.0)
    for d in np.arange(-cell / 2, cell / 2, 0.05):
        near = np.min(np.abs(b[:, None] - (g[None, :] + d)), axis=1) < tol
        score = float(w[near].sum())
        if score > best[0]:
            best = (score, d)
    d = best[1]
    phys, prof = [], []
    for gl in g:
        idx = np.where(np.abs(b - (gl + d)) < tol * 1.5)[0]
        if len(idx):
            k = idx[np.argmax(w[idx])]
            phys.append(b[k])
            prof.append(gl)
    return np.array(phys), np.array(prof)


def fit_axis(bands: list[tuple[list, list]], grid: list[float], drawn: list[float],
             off: float, scale: float, cell: float, extent: float) -> AxisFit:
    """Новые off и scale по одной оси.

    bands — для нескольких полос листа: (синие линии, чёрные линии), каждая линия — (мм на фото, сила). В каждой
    полосе чёрные линии переводятся в «координаты клетки» по соседним синим — так изгиб бумаги, наклон камеры и
    искажения объектива сокращаются: важно только, где чёрное легло относительно синего рядом с ним.
    Если лист прошёл через принтер чуть наискосок, сдвиг в полосах разный: берём середину листа.
    grid — линии клетки по профилю бумаги; drawn — где (в профиле, до поправок) нарисованы чёрные линии.
    """
    us = []  # для каждой полосы: чёрные линии в координатах клетки
    for blue, black in bands:
        phys, prof = _blue_index(blue, grid, cell)
        if len(phys) < 4:
            us.append(np.array([]))
            continue
        k = np.array(sorted(p for p, _ in black))
        k = k[(k >= phys[0]) & (k <= phys[-1])]
        us.append(np.interp(k, phys, prof) if len(k) else np.array([]))
    if sum(len(u) > 0 for u in us) < 2:
        raise PhotoError("Не разглядел синюю клетку. Снимите при ровном свете, без бликов и тени.")
    if sum(len(u) for u in us) < 6:
        raise PhotoError("Не нашёл чёрные линии. Проверьте, что лист напечатался, и снимите его ещё раз.")
    # Принтер положил линию x в клетку u ≈ off + s·x + сдвиг. Сдвиг неизвестен и может быть больше клетки:
    # подбираем такой, при котором предсказанные линии совпадают с найденными, а лишних и пропавших меньше
    # всего — пропуски в рисунке не дают спутать клетки
    printed = np.array([off + scale * x for x in drawn])
    lo, hi = EDGE_MM + 1.0, extent - EDGE_MM - 1.0
    best = None
    for shift in np.arange(-40.0, 40.01, 0.25):
        score = 0
        for u in us:
            if len(u) == 0:
                continue
            pred = printed + shift
            pred = pred[(pred > max(lo, u.min() - 1)) & (pred < min(hi, u.max() + 1))]
            if len(pred) == 0:
                continue
            near = np.abs(u[:, None] - pred[None, :]) <= cell * 0.2
            hit = int(near.any(axis=0).sum())
            score += hit - (len(pred) - hit) - int((~near.any(axis=1)).sum())
        if best is None or score > best[0] or (score == best[0] and abs(shift) < abs(best[1])):
            best = (score, shift)
    shift = best[1]
    rows = []  # (полоса, x, u)
    for bi, u in enumerate(us):
        if len(u) == 0:
            continue
        for x, p in zip(drawn, printed):
            j = int(np.argmin(np.abs(u - (p + shift))))
            if abs(u[j] - (p + shift)) <= cell * 0.2:
                rows.append((bi, x, float(u[j])))
    used = sorted({r[0] for r in rows})
    if len(rows) < 8 or len(used) < 2:
        raise PhotoError("Чёрных линий нашлось слишком мало. Снимите лист целиком и ровнее.")
    # u = a_полосы + b·x: общий «растяг» b и свой сдвиг в каждой полосе (лист мог пойти чуть наискосок)
    col = {bi: i for i, bi in enumerate(used)}
    A = np.zeros((len(rows), len(used) + 1))
    for r, (bi, x, _) in enumerate(rows):
        A[r, col[bi]] = 1.0
        A[r, -1] = x
    y = np.array([u for _, _, u in rows])
    sol, *_ = np.linalg.lstsq(A, y, rcond=None)
    intercepts, b = sol[:-1], float(sol[-1])
    res = float(np.sqrt(np.mean((y - A @ sol) ** 2)))
    a = float(np.mean(intercepts))  # середина листа
    skew = float(intercepts.max() - intercepts.min())
    new_scale = scale / b
    new_off = off - a * scale / b
    mid = float(np.mean([x for _, x, _ in rows]))
    miss = a + b * mid - mid  # насколько сейчас промахивается середина листа
    return AxisFit(round(new_off, 2), round(new_scale, 4), round(miss, 2), len({x for _, x, _ in rows}),
                   round(res, 3), mid, round(skew, 2))


BANDS = 5
SCALE_MIN = 0.006  # по одному фото меньше — шум
SCALE_MIN_PAIR = 0.004  # по двум фото (лицевая и оборот — одна и та же клетка) шум меньше


def combine(front: "PhotoResult", back: "PhotoResult") -> tuple[PrinterOffset, PrinterOffset]:
    """Поправки обеих сторон по двум фото. Клетка блока одна и та же, принтер тот же — масштаб усредняем:
    так он надёжнее, чем по одному снимку."""
    out = []
    sx = (front.x.scale + back.x.scale) / 2
    sy = (front.y.scale + back.y.scale) / 2
    sx = round(sx, 4) if abs(sx - 1) > SCALE_MIN_PAIR else 1.0
    sy = round(sy, 4) if abs(sy - 1) > SCALE_MIN_PAIR else 1.0
    for r in (front, back):
        out.append(PrinterOffset(r.x.with_scale(sx), r.y.with_scale(sy), sx, sy))
    return out[0], out[1]
SKEW_WARN_MM = 1.0  # лист заметно пошёл наискосок


def measure(path, paper: PaperProfile, side: Side, current: PrinterOffset,
            drawn_x: list[float], drawn_y: list[float]) -> PhotoResult:
    """Поправки по фото листа, на котором чёрные линии нарисованы в drawn_x (вертикальные) и drawn_y
    (горизонтальные), в координатах профиля, с текущими поправками current."""
    img = imread(path)
    sheet = warp_sheet(img, find_sheet(img), paper, side)
    blue, black = _masks(sheet)
    H, W = blue.shape
    e = int(EDGE_MM * PX)
    inner = np.zeros_like(blue)
    inner[e:H - e, e:W - e] = 1
    blue, black = blue * inner, black * inner

    def pos(profile, sep_mm):
        return [(p / PX, h) for p, h in _peaks(profile, sep_mm * PX)]

    def bands(axis):
        n = H if axis == 0 else W  # полосы — поперёк измеряемых линий
        edges = np.linspace(e, n - e, BANDS + 1).astype(int)
        out = []
        for a, b in zip(edges[:-1], edges[1:]):
            bl = blue[a:b, :] if axis == 0 else blue[:, a:b]
            bk = black[a:b, :] if axis == 0 else black[:, a:b]
            out.append((pos(bl.sum(axis=axis), 0.6), pos(bk.sum(axis=axis), paper.cell_mm * 0.6)))
        return out

    fx = fit_axis(bands(0), paper.vertical_lines(side), drawn_x, current.dx_mm, current.sx, paper.cell_mm,
                  paper.width_mm)
    fy = fit_axis(bands(1), paper.horizontal_lines(), drawn_y, current.dy_mm, current.sy, paper.cell_mm,
                  paper.height_mm)
    for f in (fx, fy):
        if f.residual > 0.3:
            raise PhotoError("Не получилось точно разглядеть линии. Снимите ещё раз: лист целиком, сверху, "
                             "без тени от телефона и бликов.")
    # Масштаб по одному фото гуляет на ±0,4% (проверено на снимках одного листа): берём его, только если
    # отклонение явное, иначе масштаб 1 и сдвиг для середины листа — там ошибка меньше всего
    sx, dx = (fx.scale, fx.off) if abs(fx.scale - 1) > SCALE_MIN else (1.0, fx.without_scale())
    sy, dy = (fy.scale, fy.off) if abs(fy.scale - 1) > SCALE_MIN else (1.0, fy.without_scale())
    debug = sheet.copy()
    debug[black > 0.5] = (0, 0, 255)
    debug[blue > 0.5] = (255, 120, 0)
    return PhotoResult(PrinterOffset(dx, dy, sx, sy), fx, fy, debug)
