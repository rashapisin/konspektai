import re

import pytest

from stv.engine.fonts import FONTS, load_font
from stv.engine.layout import CHECKSHEET_COLUMNS, typeset
from stv.engine.markup import parse
from stv.engine.paper import Side
from stv.engine.render import export_pdf, split_for_manual_duplex
from stv.engine.settings import HandSettings, PageSettings

RUSSIAN = "абвгдеёжзийклмнопрстуфхцчшщъыьэюяАБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ"
PUNCT = "0123456789.,:;!?()-–—«»\"№%/+="
EPS = 0.01


@pytest.mark.parametrize("font_id", list(FONTS))
def test_font_covers_russian(font_id):
    f = load_font(font_id)
    missing = [c for c in RUSSIAN + PUNCT if not f.supports(c)]
    assert not missing, f"{font_id}: нет символов {missing}"


def _docs(text):
    for font_id in FONTS:
        for seed in (1, 2, 3):
            yield typeset(text, PageSettings(date="21.10.26"), HandSettings(font_id=font_id, seed=seed))


def test_baselines_lie_on_grid(sample_text):
    for doc in _docs(sample_text):
        grid = set(doc.page.paper.horizontal_lines())
        for page in doc.pages:
            for ln in page.lines:
                assert ln.baseline_mm in grid


def test_text_stays_inside_margins(sample_text):
    for doc in _docs(sample_text):
        ps = doc.page
        for page in doc.pages:
            left, right = ps.text_left_mm(page.side), ps.text_right_mm(page.side)
            for ln in page.lines:
                for g in ln.glyphs:
                    r = g.bbox()
                    assert r.left() >= left - EPS and r.right() <= right + EPS, (page.index, g.char, r)
                    assert r.top() >= ps.margin_top_mm - EPS, (page.index, g.char, r)
                    assert r.bottom() <= ps.paper.height_mm - ps.margin_bottom_mm + EPS, (page.index, g.char, r)


def test_date_inside_margin_strip(sample_text):
    for doc in _docs(sample_text):
        ps = doc.page
        for page in doc.pages:
            if not page.date:
                continue
            assert page.date_glyphs, f"нет даты на странице {page.index + 1}"
            line_x = ps.margin_line_x_mm(page.side)
            for g in page.date_glyphs:
                r = g.bbox()
                # дата — на внешнем поле за красной линией, а не у колец
                if page.side is Side.FRONT:
                    assert r.left() >= line_x and r.right() <= ps.paper.width_mm
                else:
                    assert r.left() >= 0 and r.right() <= line_x


def test_adjacent_lines_do_not_overlap(sample_text):
    for doc in _docs(sample_text):
        for page in doc.pages:
            for a, b in zip(page.lines, page.lines[1:]):
                if b.baseline_mm - a.baseline_mm > doc.page.paper.cell_mm * 1.5:
                    continue
                for ga in a.glyphs:
                    ra = ga.bbox()
                    for gb in b.glyphs:
                        rb = gb.bbox()
                        # рамки могут пересекаться (хвост «р» над «б»), а чернила — нет
                        if ra.intersects(rb):
                            assert not ga.path.intersects(gb.path), (page.index, ga.char, gb.char)


def test_long_text_has_no_unresolved_collisions(sample_text):
    text = sample_text.replace("[лист проверки]", "") * 4
    for font_id in FONTS:
        doc = typeset(text, hand=HandSettings(font_id=font_id))
        assert not [w for w in doc.warnings if "касается" in w], font_id


def test_no_text_lost(sample_text):
    expected = "".join(
        b.text for b in parse(sample_text) if b.kind in ("para", "heading", "list")
    ).replace(" ", "")
    expected += "".join(t for t, _ in CHECKSHEET_COLUMNS).replace(" ", "")
    for doc in _docs(sample_text):
        got = "".join(g.char for p in doc.pages for ln in p.lines for g in ln.glyphs if not g.soft)
        assert got == expected


def test_back_side_mirrors_margins(sample_text):
    doc = typeset(sample_text)
    ps = doc.page
    backs = [p for p in doc.pages if p.side is Side.BACK]
    assert backs
    for ln in backs[0].lines:
        assert ln.left_mm == ps.margin_outer_mm
        assert ln.right_mm == ps.paper.width_mm - ps.margin_inner_mm
    # красная линия — на стороне, противоположной кольцам
    assert ps.margin_line_x_mm(Side.FRONT) == ps.paper.width_mm - ps.margin_line_offset_mm
    assert ps.margin_line_x_mm(Side.BACK) == ps.margin_line_offset_mm
    for side in Side:
        assert ps.text_right_mm(side) <= ps.margin_line_x_mm(side) or ps.text_left_mm(side) >= ps.margin_line_x_mm(side)


def test_deterministic_with_same_seed(sample_text):
    def fingerprint(doc):
        return [(g.char, round(g.bbox().x(), 4), round(g.bbox().y(), 4)) for p in doc.pages for g in p.all_glyphs()]
    a = typeset(sample_text, hand=HandSettings(seed=7))
    b = typeset(sample_text, hand=HandSettings(seed=7))
    c = typeset(sample_text, hand=HandSettings(seed=8))
    assert fingerprint(a) == fingerprint(b)
    assert fingerprint(a) != fingerprint(c)


def test_long_word_and_unknown_symbols():
    doc = typeset("Сверх" * 40 + " конец 😀 ✓")
    assert doc.warnings
    assert any("😀" in w for w in doc.warnings)
    total = sum(len(ln.glyphs) for p in doc.pages for ln in p.lines)
    assert total > 200


def test_empty_text_gives_one_page():
    doc = typeset("")
    assert len(doc.pages) == 1


def test_page_break_and_checksheet_start_new_pages():
    doc = typeset("Первая страница\n[страница]\nВторая\n[лист проверки]\n")
    assert len(doc.pages) == 3
    assert doc.pages[2].date == ""


def test_manual_duplex_split(sample_text):
    doc = typeset(sample_text)
    fronts, backs = split_for_manual_duplex(doc)
    assert [p.index for p in fronts] == list(range(0, len(doc.pages), 2))
    assert [p.index for p in backs] == list(range(1, len(doc.pages), 2))


def test_pdf_has_exact_paper_size(tmp_path, sample_text):
    doc = typeset(sample_text)
    out = tmp_path / "t.pdf"
    export_pdf(doc, out)
    data = out.read_bytes().decode("latin-1")
    boxes = re.findall(r"/MediaBox\s*\[\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*\]", data)
    assert len(boxes) == len(doc.pages)
    for _, _, w, h in boxes:
        assert abs(float(w) / 72 * 25.4 - 145.0) < 0.3
        assert abs(float(h) / 72 * 25.4 - 202.0) < 0.3


def test_cursive_joins_and_pressure():
    """Слитное письмо: связки только между подходящими строчными буквами, не символы текста; нажим разный."""
    from stv.engine.settings import HandSettings
    doc = typeset("линии шумели", hand=HandSettings(joins=True))
    glyphs = [g for p in doc.pages for g in p.all_glyphs()]
    joints = [g for g in glyphs if g.joiner]
    letters = [g for g in glyphs if not g.joiner]
    assert joints, "в «линии шумели» есть что соединять"
    assert "".join(g.char for g in letters).replace(" ", "") == "линиишумели"
    assert len({round(g.stroke_mm, 4) for g in letters}) > 3  # нажим не одинаковый
    plain = typeset("линии шумели", hand=HandSettings(joins=False))
    assert not any(g.joiner for p in plain.pages for g in p.all_glyphs())
    # вёрстка не зависит от связок: те же строки в тех же местах
    assert [ln.baseline_mm for ln in plain.pages[0].lines] == [ln.baseline_mm for ln in doc.pages[0].lines]


def test_no_join_into_letters_starting_on_top():
    from stv.engine.settings import HandSettings
    doc = typeset("гоготом", hand=HandSettings(joins=True))
    assert not any(g.joiner for p in doc.pages for g in p.all_glyphs())
