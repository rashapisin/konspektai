"""Калибровка по фото: искусственное «фото» листа с известным промахом принтера должно дать точные поправки."""

import cv2
import numpy as np
import pytest

from stv.calib_photo import PhotoError, measure
from stv.engine.calibration import photo_lines
from stv.engine.paper import Side, paper
from stv.engine.settings import PrinterOffset

K = 12.0  # пикселей на мм в «фото» до перспективы
SH = 4    # дробные координаты для cv2.line
HOLE = (1, 2, 3)  # цвет-метка отверстий: в них потом «виден» стол


def _pt(x_mm, y_mm):
    return int(round(x_mm * K * (1 << SH))), int(round(y_mm * K * (1 << SH)))


def fake_photo(path, side: Side, cur: PrinterOffset, e0=(0.0, 0.0), g=(1.0, 1.0), grid_pitch=(1.0, 1.0),
               grid_shift=(0.0, 0.0), angle=0.0, seed=0, barrel=0.0, lines=photo_lines, dashed=False,
               title=False, face=None, holes=True, shadow=False):
    """Лист блока: синяя клетка (с ошибкой профиля grid_shift и шагом grid_pitch), чёрные линии с моделью
    принтера «на бумаге = e0 + g·(off + s·x)», отверстия, перспектива, стол, шум.

    title — надпись над рисунком, как на настоящем листе; face — сторона листа, на которой оказалась печать
    (другая — принтер напечатал не на той стороне); holes=False — отверстий не видно (белый стол);
    shadow — тень от руки на углу листа."""
    pp = paper("block_a5_grid")
    face = face or side
    W, H = int(pp.width_mm * K), int(pp.height_mm * K)
    sheet = np.full((H, W, 3), (235, 240, 242), np.uint8)
    blue = (215, 170, 120)
    for x in pp.vertical_lines(face):
        xb = grid_shift[0] + grid_pitch[0] * x
        cv2.line(sheet, _pt(xb, 0), _pt(xb, pp.height_mm), blue, 2, cv2.LINE_AA, SH)
    for y in pp.horizontal_lines():
        yb = grid_shift[1] + grid_pitch[1] * y
        cv2.line(sheet, _pt(0, yb), _pt(pp.width_mm, yb), blue, 2, cv2.LINE_AA, SH)
    xs, ys = lines(pp, side)
    ext = 0.0 if dashed else 2.5

    def px(x):
        return e0[0] + g[0] * (cur.dx_mm + cur.sx * x)

    def py(y):
        return e0[1] + g[1] * (cur.dy_mm + cur.sy * y)
    def seg(x0, y0, x1, y1):
        if not dashed:
            cv2.line(sheet, _pt(x0, y0), _pt(x1, y1), (40, 40, 40), 3, cv2.LINE_AA, SH)
            return
        n = int(max(abs(x1 - x0), abs(y1 - y0)) / 2.5)
        for k in range(n):  # штрих 1,5 мм, просвет 1 мм
            t0, t1 = k * 2.5, k * 2.5 + 1.5
            L = max(abs(x1 - x0), abs(y1 - y0))
            a, b = t0 / L, min(t1 / L, 1.0)
            cv2.line(sheet, _pt(x0 + (x1 - x0) * a, y0 + (y1 - y0) * a), _pt(x0 + (x1 - x0) * b, y0 + (y1 - y0) * b),
                     (40, 40, 40), 3, cv2.LINE_AA, SH)
    if title:  # «буквы» надписи: строка мелких прямоугольников по центру, 6 мм от верха
        for k in range(30):
            x0 = pp.width_mm / 2 - 30 + 2.0 * k
            cv2.rectangle(sheet, _pt(px(x0), py(6.0)), _pt(px(x0 + 1.4), py(8.2)), (40, 40, 40), -1, cv2.LINE_AA, SH)
    for x in xs:
        seg(px(x), py(ys[0] - ext), px(x), py(ys[-1] + ext))
    for y in ys:
        seg(px(xs[0] - ext), py(y), px(xs[-1] + ext), py(y))
    hx = 6.0 if face is Side.FRONT else pp.width_mm - 6.0
    for k in range(4 if holes else 0):
        cv2.circle(sheet, _pt(hx, 30 + 47 * k), int(2.6 * K * (1 << SH)), HOLE, -1, cv2.LINE_8, SH)
    # стол и перспектива
    rng = np.random.default_rng(seed)
    out_w, out_h = 2400, 3000
    desk = np.zeros((out_h, out_w, 3), np.uint8)
    desk[:] = (40, 90, 150)
    src = np.float32([(0, 0), (W, 0), (W, H), (0, H)])
    c = np.float32([(420, 380), (2000, 300), (2100, 2650), (330, 2720)])
    if angle:
        m = cv2.getRotationMatrix2D((out_w / 2, out_h / 2), angle, 1.0)
        c = cv2.transform(c.reshape(-1, 1, 2), m).reshape(-1, 2)
    t = cv2.getPerspectiveTransform(src, c)
    warped = cv2.warpPerspective(sheet, t, (out_w, out_h), flags=cv2.INTER_LINEAR)
    mask = cv2.warpPerspective(np.full((H, W), 255, np.uint8), t, (out_w, out_h))
    holes = cv2.warpPerspective(np.all(sheet == HOLE, axis=2).astype(np.uint8) * 255, t, (out_w, out_h))
    img = np.where(((mask > 128) & (holes < 128))[..., None], warped, desk)
    if shadow:  # тень на нижнем левом углу листа: бумага в ней не светлее стола
        tri = np.int32([c[3] + (-200, 150), c[3] + (700, 150), c[3] + (-200, -800)])
        dark = np.zeros(img.shape[:2], np.uint8)
        cv2.fillPoly(dark, [tri], 255)
        img[dark > 0] = (img[dark > 0] * 0.5).astype(np.uint8)
    if barrel:  # «бочка» объектива телефона: прямые линии у краёв кадра выгибаются
        yy, xx = np.indices(img.shape[:2], dtype=np.float32)
        cx, cy = out_w / 2, out_h / 2
        r2 = ((xx - cx) ** 2 + (yy - cy) ** 2) / (cx ** 2 + cy ** 2)
        f = 1 + barrel * r2
        img = cv2.remap(img, cx + (xx - cx) * f, cy + (yy - cy) * f, cv2.INTER_LINEAR, borderValue=(40, 90, 150))
    img = cv2.GaussianBlur(img, (5, 5), 1.2)
    img = np.clip(img.astype(np.int16) + rng.normal(0, 4, img.shape), 0, 255).astype(np.uint8)
    cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 90])[1].tofile(str(path))  # путь с кириллицей
    return pp, xs, ys


def _landing_error(res, side, pp, e0, g, grid_pitch, grid_shift):
    """Насколько с новыми поправками линии клетки профиля лягут мимо настоящих синих, мм (максимум)."""
    o = res.offset
    err = 0.0
    for x in pp.vertical_lines(side)[3:-3]:
        err = max(err, abs(e0[0] + g[0] * (o.dx_mm + o.sx * x) - (grid_shift[0] + grid_pitch[0] * x)))
    for y in pp.horizontal_lines()[3:-3]:
        err = max(err, abs(e0[1] + g[1] * (o.dy_mm + o.sy * y) - (grid_shift[1] + grid_pitch[1] * y)))
    return err


@pytest.mark.parametrize("side,e0,g,pitch,gshift,angle", [
    (Side.FRONT, (0.4, -2.4), (1.0, 1.0), (1.0, 1.0), (0.0, 0.0), 0),       # как на фото пользователя
    (Side.FRONT, (3.1, 6.7), (1.0, 1.0), (1.0, 1.0), (0.6, -0.8), 3),       # больше клетки и ошибка профиля
    (Side.BACK, (-1.2, 0.9), (1.0, 1.003), (1.0, 0.992), (0.0, 0.3), -2),   # оборот, растяжение и мелкая клетка
    (Side.FRONT, (12.0, -9.0), (1.0, 1.0), (1.0, 0.993), (0.0, 0.0), 8),     # линии заходят на отверстия
    (Side.FRONT, (-31.0, 2.0), (1.0, 1.0), (1.0, 1.0), (0.0, 0.0), 0),      # как с A4 вместо A5
    (Side.BACK, (-24.0, -21.0), (1.0, 1.0), (1.0, 1.0), (-0.7, 0.0), 0),
    (Side.FRONT, (1.0, 1.5), (1.0, 1.0), (1.0, 1.0), (0.0, 0.0), 180),       # снято вверх ногами
    (Side.BACK, (0.5, -0.5), (1.0, 1.0), (1.0, 1.0), (0.0, 0.0), 90),        # снято боком
])
def test_photo_calibration_recovers_shift(tmp_path, side, e0, g, pitch, gshift, angle):
    cur = PrinterOffset(1.0, 1.0)
    f = tmp_path / "фото.jpg"
    pp, xs, ys = fake_photo(f, side, cur, e0, g, pitch, gshift, angle)
    res = measure(f, pp, side, cur, xs, ys)
    assert _landing_error(res, side, pp, e0, g, pitch, gshift) < 0.25


def test_photo_with_lens_distortion(tmp_path):
    """Как на настоящем снимке телефоном: снято под углом, объектив выгибает линии к краям кадра."""
    cur = PrinterOffset(2.0, 1.0)
    f = tmp_path / "телефон.jpg"
    e0, pitch = (0.3, -2.0), (1.0, 0.99)
    pp, xs, ys = fake_photo(f, Side.FRONT, cur, e0, (1.0, 1.0), pitch, (0.0, 0.0), 4, barrel=0.06)
    res = measure(f, pp, Side.FRONT, cur, xs, ys)
    assert _landing_error(res, Side.FRONT, pp, e0, (1.0, 1.0), pitch, (0.0, 0.0)) < 0.3


def test_scale_from_both_sides(tmp_path):
    """Клетка мельче на 0,5%: по одному фото это на грани шума, по двум — уверенно учитывается."""
    from stv.calib_photo import combine
    pitch = (1.0, 0.995)
    res = {}
    for side, e0 in ((Side.FRONT, (0.5, -1.5)), (Side.BACK, (-0.8, 0.7))):
        cur = PrinterOffset(1.0, 1.0)
        f = tmp_path / f"{side.name}.jpg"
        pp, xs, ys = fake_photo(f, side, cur, e0, (1.0, 1.0), pitch, (0.0, 0.0), 2)
        res[side] = (measure(f, pp, side, cur, xs, ys), e0)
    front, back = combine(res[Side.FRONT][0], res[Side.BACK][0])
    assert abs(front.sy - 0.995) < 0.002 and front.sx == 1.0
    for side, o in ((Side.FRONT, front), (Side.BACK, back)):
        r, e0 = res[side]
        r.offset = o
        assert _landing_error(r, side, pp, e0, (1.0, 1.0), pitch, (0.0, 0.0)) < 0.3


def test_check_sheet_measures_remaining_error(tmp_path):
    """Проверочный лист (пунктир по клетке): после хорошей калибровки промах почти ноль, после плохой —
    виден и правильно исправляется."""
    from stv.engine.calibration import check_lines
    for e0, expect in (((0.05, -0.1), 0.15), ((0.9, -1.3), 1.4)):
        cur = PrinterOffset()  # промах на бумаге = e0
        f = tmp_path / f"check{expect}.jpg"
        pp, _, _ = fake_photo(f, Side.FRONT, cur, e0, lines=check_lines, dashed=True)
        xs, ys = check_lines(pp, Side.FRONT)
        res = measure(f, pp, Side.FRONT, cur, xs, ys)
        miss = max(abs(res.x.shift_mm), abs(res.y.shift_mm))
        assert abs(miss - max(abs(v) for v in e0)) < 0.15
        assert _landing_error(res, Side.FRONT, pp, e0, (1.0, 1.0), (1.0, 1.0), (0.0, 0.0)) < 0.25


def test_photo_without_sheet_is_reported(tmp_path):
    f = tmp_path / "пусто.jpg"
    cv2.imencode(".jpg", np.full((800, 600, 3), (40, 90, 150), np.uint8))[1].tofile(str(f))
    pp = paper("block_a5_grid")
    xs, ys = photo_lines(pp, Side.FRONT)
    with pytest.raises(PhotoError):
        measure(f, pp, Side.FRONT, PrinterOffset(), xs, ys)


def test_shadowed_corner(tmp_path):
    """Тень от руки на углу: бумага в тени не светлее стола, но угол листа всё равно находится."""
    cur = PrinterOffset(1.0, 1.0)
    f = tmp_path / "тень.jpg"
    e0 = (0.7, -1.2)
    pp, xs, ys = fake_photo(f, Side.BACK, cur, e0, shadow=True, title=True)
    res = measure(f, pp, Side.BACK, cur, xs, ys)
    assert _landing_error(res, Side.BACK, pp, e0, (1.0, 1.0), (1.0, 1.0), (0.0, 0.0)) < 0.25


def test_print_on_wrong_side_is_reported(tmp_path):
    """Принтер напечатал лицевую не на той стороне листа: надпись читается, а отверстия справа."""
    from stv.calib_photo import WrongSide
    cur = PrinterOffset(1.0, 1.0)
    f = tmp_path / "не та сторона.jpg"
    pp, xs, ys = fake_photo(f, Side.FRONT, cur, (0.5, 0.5), title=True, face=Side.BACK)
    with pytest.raises(WrongSide, match="отверстия справа"):
        measure(f, pp, Side.FRONT, cur, xs, ys)
    # та же печать на своей стороне — измеряется как обычно
    pp, xs, ys = fake_photo(f, Side.FRONT, cur, (0.5, 0.5), title=True)
    assert _landing_error(measure(f, pp, Side.FRONT, cur, xs, ys), Side.FRONT, pp, (0.5, 0.5), (1.0, 1.0),
                          (1.0, 1.0), (0.0, 0.0)) < 0.25


def test_upside_down_photo_without_visible_holes(tmp_path):
    """Отверстий на фото не видно (белый стол), лист снят вверх ногами — переворачиваем по надписи."""
    cur = PrinterOffset(1.0, 1.0)
    f = tmp_path / "без отверстий.jpg"
    e0 = (-0.8, 1.1)
    pp, xs, ys = fake_photo(f, Side.FRONT, cur, e0, title=True, holes=False, angle=180)
    res = measure(f, pp, Side.FRONT, cur, xs, ys)
    assert _landing_error(res, Side.FRONT, pp, e0, (1.0, 1.0), (1.0, 1.0), (0.0, 0.0)) < 0.25
