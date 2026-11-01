"""Проверки окна без показа на экране: тетрадь собирается, предпросмотр догоняет текст, проект сохраняется."""

import time

import pytest

pytest.importorskip("PySide6.QtWidgets")


@pytest.fixture(scope="module")
def monkeypatch_module():
    mp = pytest.MonkeyPatch()
    yield mp
    mp.undo()


@pytest.fixture(scope="module")
def window(qt_app, tmp_path_factory, monkeypatch_module):
    from stv.app import project
    tmp = tmp_path_factory.mktemp("stv")
    monkeypatch_module.setenv("APPDATA", str(tmp / "appdata"))
    monkeypatch_module.setattr(project, "documents_dir", lambda: tmp)
    from stv.app.main_window import MainWindow
    w = MainWindow()
    w.resize(1360, 860)
    yield w
    w.close()


def _wait(qt_app, cond, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        qt_app.processEvents()
        if cond():
            return True
        time.sleep(0.05)
    return False


def test_entry_text_reaches_preview(qt_app, window, sample_text):
    j = window.work.journal
    window.nav.setCurrentRow(1)
    j.date.setText("01.01.26")
    j._date_edited("01.01.26")
    j.topic.setText("Первичные средства пожаротушения")
    j._edited()
    j.editor.edit.setPlainText(sample_text.split("[лист проверки]")[0])
    assert _wait(qt_app, lambda: window.work.preview.images and j.results)
    assert "Стр. 1 из" in window.work.preview.label.text()


def test_second_entry_gets_next_date_and_new_page(qt_app, window):
    j = window.work.journal
    j.add_entry()
    assert j.entries[1].date == "05.01.26"
    j.topic.setText("Пожарные краны")
    j._edited()
    j.editor.edit.setPlainText("Пожарный кран состоит из клапана, рукава и ствола.")
    second = j.entries[1].id
    assert _wait(qt_app, lambda: second in j.results)
    assert j.results[second].first_page >= 1


def test_settings_change_rerenders(qt_app, window):
    pv = window.work.preview
    i = pv.index  # рисуется только страница на экране
    before = pv.images[i]
    assert before is not None
    window.work.settings.weight.set_value(0.2)
    window.work.settings._emit()
    assert _wait(qt_app, lambda: len(pv.images) > i and pv.images[i] is not None and pv.images[i] is not before)


def test_unchanged_pages_are_not_redrawn(qt_app, window):
    """Правка одного конспекта не перерисовывает страницы других: они берутся готовыми."""
    pv, j = window.work.preview, window.work.journal
    assert _wait(qt_app, lambda: pv.is_current() and pv.images)
    pv.show_page(0)
    first = pv.images[0]
    j.list.setCurrentRow(len(j.entries) - 1)
    old = pv.doc
    j.editor.edit.setPlainText(j.editor.text() + " ещё слово")
    # новая вёрстка готова; первая страница (другой конспект) — та же готовая картинка, не перерисована
    assert _wait(qt_app, lambda: pv.doc is not old and pv.is_current() and pv.images)
    pv.show_page(0)
    assert pv.images[0] is first


def test_project_roundtrip(qt_app, window):
    from stv.app.project import Project
    window.work.title.setText("Проверка сохранения")
    window.save()
    p = Project.load(window.project.path)
    assert p.title == "Проверка сохранения"
    assert [e.date for e in p.entries] == ["01.01.26", "05.01.26"]
    assert abs(p.hand_settings().stroke_mm - 0.2) < 1e-9


def test_old_project_is_migrated(tmp_path):
    import json
    from stv.app.project import Project
    f = tmp_path / "old.stv"
    f.write_text(json.dumps({"version": 1, "title": "Старый", "text": "Текст",
                             "page": {"margin_inner_mm": 22, "margin_outer_mm": 17, "date": "01.02.26"}}),
                 encoding="utf-8")
    p = Project.load(f)
    assert p.entries[0].text == "Текст" and p.entries[0].kind == "free"
    assert p.page_settings().margin_inner_mm == 17


def test_screenshot(qt_app, window, tmp_path):
    img = window.grab()
    assert img.width() > 1000


def test_onboarding_sets_mode_and_hides_mchs_tools(qt_app, window):
    from stv.app.onboarding import Onboarding
    from stv.app.project import AppSettings
    ob = Onboarding(window.centralWidget())
    ob._choose("mode", "study")
    ob._choose("print", "pdf")
    ob._choose("ai", "off")
    ob._finish()
    assert _wait(qt_app, lambda: AppSettings.get("mode") == "study" and not window.findChildren(Onboarding), 5)
    window.apply_prefs()
    j = window.work.journal
    assert j.sched_btn.isHidden() and j.kind.isHidden() and j.prompt_btn.isHidden()
    assert window.work.print_btn.text() == "Сохранить PDF"
    AppSettings.set("mode", "mchs")
    AppSettings.set("print", "printer")
    AppSettings.set("ai", "chat")
    window.apply_prefs()
    assert not j.sched_btn.isHidden() and not j.prompt_btn.isHidden()


def test_calibration_wizard_turns_tick_numbers_into_offsets(qt_app, window):
    from stv.app.calibration_wizard import CalibrationWizard
    from stv.engine import printers
    w = CalibrationWizard("Тестовый принтер")
    w._start("manual")
    w.qs["fx"].group.button(5).click()  # риска «6» = +0,5 мм
    w.qs["fy"].group.button(4).click()  # «5» — ровно
    w.qs["bx"].group.button(2).click()  # «3» = −1,0 мм
    w.qs["by"].group.button(8).click()  # «9» = +2,0 мм
    w._go(len(w.pages) - 1)
    prof = printers.load()["Тестовый принтер"]
    assert prof.direct_calibrated
    assert (prof.direct_front.dx_mm, prof.direct_front.dy_mm) == (0.5, 0.0)
    assert (prof.direct_back.dx_mm, prof.direct_back.dy_mm) == (-1.0, 2.0)
    assert "правее" in w.result.text() and "выше" not in w.result.text()
    w.close()


def test_calibration_wizard_by_photo(qt_app, window, tmp_path):
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
    from test_calib_photo import fake_photo
    from stv.app.calibration_wizard import CalibrationWizard
    from stv.engine import printers
    from stv.engine.paper import Side
    w = CalibrationWizard("Фото-принтер")
    w._start("photo")
    for side, e0 in ((Side.FRONT, (0.6, -2.3)), (Side.BACK, (-1.1, 1.4))):
        f = tmp_path / f"{side.name}.jpg"
        fake_photo(f, side, w._page().offset(side), e0)
        step = w.photos[side]
        step.analyze(str(f))
        assert _wait(qt_app, lambda: step.result is not None, 30), step.status.text()
    w._go(len(w.pages) - 1)
    prof = printers.load()["Фото-принтер"]
    assert prof.direct_calibrated
    # фото без ошибок профиля: поправка = −промах принтера
    assert abs(prof.direct_front.dx_mm + 0.6) < 0.15 and abs(prof.direct_front.dy_mm - 2.3) < 0.15
    assert abs(prof.direct_back.dx_mm - 1.1) < 0.15 and abs(prof.direct_back.dy_mm + 1.4) < 0.15
    w.close()


def test_calibration_check_by_photo(qt_app, window, tmp_path):
    """Проверка по фото: точная печать — калибровка завершена; неточная — поправки доводятся."""
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
    from test_calib_photo import fake_photo
    from stv.app.calibration_wizard import CalibrationWizard
    from stv.engine import printers
    from stv.engine.calibration import check_lines
    from stv.engine.paper import Side
    w = CalibrationWizard("Проверка-принтер")
    w._start("photo")
    w.mode = "photo"
    for step in w.photos.values():  # калибровку считаем пройденной: подставим готовые поправки
        step.result = None
    w.front, w.back = printers.PrinterOffset(1.0, 2.0), printers.PrinterOffset(-0.5, 1.5)
    w.saved = True
    w._store()

    def run_check(residual):
        w._start_verify()
        for side in (Side.FRONT, Side.BACK):
            cur = w._page().offset(side)
            e0 = (-cur.dx_mm + residual[0], -cur.dy_mm + residual[1])  # на бумаге промах = residual
            f = tmp_path / f"check_{side.name}_{residual[0]}.jpg"
            fake_photo(f, side, cur, e0, lines=check_lines, dashed=True)
            step = w.checks[side]
            step.analyze(str(f))
            assert _wait(qt_app, lambda: step.result is not None, 30), step.status.text()
        w._go(len(w.pages) - 1)

    run_check((0.9, -0.7))
    assert not w.again.isHidden() and printers.load()["Проверка-принтер"].direct_check_mm < 0
    run_check((0.1, -0.05))
    prof = printers.load()["Проверка-принтер"]
    assert w.again.isHidden() and 0 <= prof.direct_check_mm <= 0.3
    assert prof.status()[0] == "ok"
    w.close()

    # две неудачные проверки подряд: вторая доводит поправки и завершает, третьей не предлагает
    w = CalibrationWizard("Проверка-принтер")
    w._start("photo")
    w.saved = True
    run_check((1.0, 0.8))
    assert not w.again.isHidden()
    run_check((0.7, -0.6))
    assert w.again.isHidden() and "завершена" in w.verdict_title.text()
    w.close()

    # большой промах и на второй проверке: «завершена» не пишем, точность не записываем, проверить можно ещё
    w = CalibrationWizard("Проверка-принтер")
    w._start("photo")
    w.saved = True
    run_check((1.0, 0.8))
    run_check((2.4, -0.6))
    prof = printers.load()["Проверка-принтер"]
    assert not w.again.isHidden() and "завершена" not in w.verdict_title.text()
    assert "направляющие" in w.verdict.text()
    assert prof.direct_check_mm < 0 and prof.status()[0] == "warn"
    w.close()


def test_printer_status_is_honest():
    """«Настроен точно» — только если проверка по фото показала маленький промах."""
    from stv.engine import printers
    from stv.engine.settings import PrinterOffset
    p = printers.PrinterProfile("X")
    p.set_offsets(printers.DIRECT, PrinterOffset(), PrinterOffset(), how="photo", check_mm=5.0)
    level, text = p.status()
    assert level == "warn" and "5,0" in text
    p.set_offsets(printers.DIRECT, PrinterOffset(), PrinterOffset(), how="photo", check_mm=0.2)
    assert p.status()[0] == "ok"


def test_verify_only_and_wrong_side(qt_app, window, tmp_path):
    """«Пройти проверку» сразу открывает проверку; печать не на той стороне — подсказка меняется и
    запоминается для принтера."""
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
    from test_calib_photo import fake_photo
    from stv.app.calibration_wizard import CalibrationWizard, PhotoStep
    from stv.engine import printers
    from stv.engine.calibration import check_lines
    from stv.engine.paper import Side
    w = CalibrationWizard("Обратный-принтер", verify=True)
    assert w.verify_from == 1 and w.stack.currentIndex() == 1 and "отверстиями влево" in w.load_views[0][1].text()
    step = w.checks[Side.FRONT]
    assert isinstance(step, PhotoStep)
    f = tmp_path / "wrong.jpg"
    fake_photo(f, Side.FRONT, w._page().offset(Side.FRONT), (0.3, 0.2), lines=check_lines, dashed=True,
               title=True, face=Side.BACK)
    step.analyze(str(f))
    assert _wait(qt_app, lambda: "отверстиями вправо" in step.status.text(), 30), step.status.text()
    assert step.result is None and step.phone_stage == "error"
    assert printers.load()["Обратный-принтер"].flip_feed
    assert "отверстиями вправо" in w.load_views[0][1].text() and not w.load_views[0][2].holes_left
    w.close()


def test_first_notebook_follows_study_mode(qt_app, window):
    """Первая тетрадь создаётся до выбора режима — у студента в ней не должно быть шапки МЧС."""
    from stv.app.main_window import MainWindow
    from stv.app.project import AppSettings
    old = AppSettings.get("mode")
    AppSettings.set("mode", "study")
    try:
        w = MainWindow()
        assert w.project.entries[0].kind == "study" and w.project.entries[0].date == ""
        w.close()
    finally:
        AppSettings.set("mode", old)


def test_gigachat_button_compresses_and_keeps_source(qt_app, window, monkeypatch):
    from stv.app import ai_ui

    class Fake:
        def complete(self, prompt):
            assert "Материал:" in prompt
            return "**Конспект:**\n- первое главное положение темы\n- второе главное положение темы"
    monkeypatch.setattr(ai_ui, "client", lambda: Fake())
    j = window.work.journal
    j.set_mode("study", "api")
    assert not j.ai_btn.isHidden() and j.prompt_btn.isHidden()
    j.add_entry()
    long_text = "Длинный исходный материал по теме. " * 30
    j.editor.edit.setPlainText(long_text)
    e = j.current()
    j.ai_compress()
    assert _wait(qt_app, lambda: e.text.startswith("Конспект"), 10)
    assert "**" not in e.text and e.source.strip() == long_text.strip()
    assert j.ai_btn.isEnabled()


def test_page_viewer_pages_and_zoom(qt_app):
    from stv.app.preview import PageViewer
    from stv.engine.layout import typeset
    doc = typeset("Первая страница\n[страница]\nВторая страница")
    v = PageViewer(doc, 0)
    v.resize(900, 700)
    v.show()
    qt_app.processEvents()
    small = v.image.pixmap().width()
    v.go(1)
    assert "Стр. 2 из 2" in v.label.text() and not v.next_btn.isEnabled()
    v.set_zoom(2.0)
    assert v.image.pixmap().width() > small * 1.6  # перерисован крупнее, а не растянут
    v.set_zoom(99)
    assert v.zoom == v.MAX_ZOOM
    v.close()


def test_notebook_undo_redo(qt_app, window, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    j = window.work.journal
    j.set_entries([__import__("stv.engine.journal", fromlist=["Entry"]).Entry(topic="Первый", text="Текст 1")], 4)
    assert not j.undo_btn.isEnabled()
    j.add_entry()
    j.topic.setText("Второй")
    j._edited()
    assert [e.topic for e in j.entries] == ["Первый", "Второй"]
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    j._remove()
    assert [e.topic for e in j.entries] == ["Первый"]
    j.undo()  # вернулся удалённый конспект
    assert [e.topic for e in j.entries] == ["Первый", "Второй"]
    j.redo()
    assert [e.topic for e in j.entries] == ["Первый"]
    j.undo()
    j.list.setCurrentRow(0)
    j._replace_text(j.current(), "Ответ нейросети")
    j.undo()  # замена текста отменена
    assert j.entries[0].text == "Текст 1" and j.editor.text() == "Текст 1"


def test_write_from_topic_keeps_sources_out_of_notebook(qt_app, window, monkeypatch):
    from stv.app import ai_ui

    class Fake:
        def complete(self, prompt, temperature=0.3):
            assert "Тема: Реформы Петра I" in prompt and "ИСТОЧНИКИ:" in prompt
            return ("Пётр I провёл реформы управления, армии и культуры.\n- создан Сенат\n- учреждены коллегии\n"
                    "ИСТОЧНИКИ:\n- Учебник истории России, 8 класс")
    monkeypatch.setattr(ai_ui, "client", lambda: Fake())
    j = window.work.journal
    j.set_mode("study", "api")
    j.add_entry()
    j.topic.setText("Реформы Петра I")
    j._edited()
    e = j.current()
    j.ai_write()
    assert _wait(qt_app, lambda: e.text.startswith("Пётр"), 10)
    assert "ИСТОЧНИКИ" not in e.text and "Учебник истории" in e.source


def test_typing_keeps_cursor_and_order(qt_app, window):
    """Набор в поле конспекта: буквы идут по порядку, курсор не прыгает в начало, предпросмотр не уходит
    на первую страницу конспекта после каждой буквы."""
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtWidgets import QApplication

    def type_text(w, text):  # QTest.keyClicks не умеет кириллицу
        for ch in text:
            QApplication.sendEvent(w, QKeyEvent(QEvent.KeyPress, 0, Qt.NoModifier, ch))
            qt_app.processEvents()
    j = window.work.journal
    j.add_entry()
    ed = j.editor.edit
    ed.setFocus()
    type_text(ed, "Тема вторая")
    qt_app.processEvents()
    first = j.editor.text()
    jumps = []
    j.selected.connect(jumps.append)
    type_text(ed, " ок")
    qt_app.processEvents()
    text = j.editor.text()
    _wait(qt_app, lambda: window.work.preview.is_current() and window.work.preview.images, 30)
    assert first == "Тема вторая" and text == "Тема вторая ок" and not jumps, (first, text, jumps)


def test_ai_note_is_shortened_until_it_fits(qt_app, window, monkeypatch):
    """«Уместить на страницу»: нейросеть написала длиннее, чем помещается даже мелким почерком (оценка по знакам
    ошиблась) — программа по вёрстке просит сократить до точного объёма, и конспект встаёт на одну страницу."""
    import re
    from stv.app import ai_ui
    asked = []
    sentence = "Пожарный автомобиль доставляет к месту пожара личный состав, воду и пожарно-техническое вооружение. "

    class Fake:
        def complete(self, prompt, temperature=0.3):
            m = re.search(r"Сократи этот конспект до (\d+)", prompt)
            if m:
                asked.append(int(m.group(1)))
                return (sentence * 60)[:int(m.group(1))].rsplit(" ", 1)[0] + "."
            return (sentence * 60).strip() + "\nИСТОЧНИКИ:\n- нет"
    monkeypatch.setattr(ai_ui, "client", lambda: Fake())
    j = window.work.journal
    j.set_mode("mchs", "api")
    j.add_entry()
    j.topic.setText("Пожарные автомобили")
    j._edited()
    e = j.current()
    assert e.fit
    monkeypatch.setattr(j, "capacity_fn", lambda: 8000)  # оценка по знакам сильно ошиблась
    j.ai_write()
    assert _wait(qt_app, lambda: asked and e.id in j.results and not j.results[e.id].overflow_rows
                 and j.results[e.id].text_hash == hash(e.text) and not j._fit_ai, 60), (asked, j.status.text())
    assert j.results[e.id].pages == 1 and len(e.text) < len(sentence * 60)


def test_topic_is_a_clear_field_with_write_button(qt_app, window, monkeypatch):
    """Тема — поле с подписью, «Написать конспект» рядом; Enter в пустом конспекте сразу пишет."""
    from stv.app import ai_ui

    class Fake:
        def complete(self, prompt, temperature=0.3):
            return "Пожарные автомобили делятся на основные и специальные.\nИСТОЧНИКИ:\n- нет"
    monkeypatch.setattr(ai_ui, "client", lambda: Fake())
    j = window.work.journal
    j.set_mode("mchs", "api")
    j.add_entry()
    assert j.topic_label.text() == "Тема" and j.write_btn.parent() is j.topic.parent()
    j.topic.setText("Пожарные автомобили")
    j._edited()
    e = j.current()
    j.topic.returnPressed.emit()
    assert _wait(qt_app, lambda: e.text.startswith("Пожарные автомобили делятся"), 10)
