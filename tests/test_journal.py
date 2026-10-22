from stv.engine.fonts import FONTS
from stv.engine.journal import Entry, build, recompute_dates
from stv.engine.paper import Side
from stv.engine.settings import HandSettings, PageSettings

PARA = ("Первичные средства пожаротушения предназначены для борьбы с пожаром в начальной стадии его развития. "
        "К ним относятся огнетушители, пожарные краны, ящики с песком и покрывала для изоляции очага. ")
BASE = FONTS["caveat"].x_height_mm


def _build(entries):
    return build(entries, PageSettings(), HandSettings(), BASE)


def test_dates_every_four_days_and_manual_override():
    es = [Entry(date="01.01.26", date_auto=False), Entry(), Entry(kind="service", date="10.01.26"), Entry()]
    recompute_dates(es)
    assert [e.date for e in es] == ["01.01.26", "05.01.26", "10.01.26", "09.01.26"]
    es[1].date, es[1].date_auto = "06.01.26", False  # подмена: сдвинули одну дату
    recompute_dates(es)
    assert es[3].date == "10.01.26"


def test_each_entry_starts_new_page_with_header_and_date():
    es = [Entry(topic="Огнетушители", text=PARA, date="01.01.26"), Entry(topic="Пожарные краны", text=PARA,
                                                                        date="05.01.26")]
    doc, res = _build(es)
    assert [r.first_page for r in res] == [0, 1]
    assert doc.pages[0].date == "01.01.26" and doc.pages[1].date == "05.01.26"
    assert doc.pages[1].side is Side.BACK
    first_line = "".join(g.char for g in doc.pages[0].lines[0].glyphs)
    assert first_line == "Самостоятельнаяподготовка"


def test_service_header_only_on_first_entry_of_day():
    es = [Entry(kind="service", topic="А", text=PARA, date="03.02.26"),
          Entry(kind="service", topic="Б", text=PARA, date="03.02.26")]
    doc, res = _build(es)
    second = doc.pages[res[1].first_page]
    assert second.date == ""
    assert "".join(g.char for g in second.lines[0].glyphs).startswith("Тема")


def test_fit_fills_one_page():
    e = Entry(topic="Тема", text=PARA * 6)
    doc, res = _build([e])
    assert res[0].pages == 1
    assert res[0].fill > 0.8, res[0].fill


def test_overflow_is_reported():
    e = Entry(topic="Длинная тема", text=PARA * 30)
    doc, res = _build([e])
    assert res[0].pages > 1 and res[0].overflow_rows > 0
    assert doc.pages[0].note_bottom and "Продолжение" in doc.pages[1].note
    assert doc.pages[1].date == ""


def test_unchecked_entries_are_not_printed():
    es = [Entry(topic="Писать", text=PARA), Entry(topic="Только изучить", text=PARA, write=False)]
    doc, res = _build(es)
    assert len(res) == 1 and len(doc.pages) == 1
