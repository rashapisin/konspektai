"""Перенос на другой компьютер: два «компьютера» — две папки данных; файл с одного загружается на другой."""

import json
import zipfile

import pytest

from stv import transfer


def _computer(tmp_path, monkeypatch, name):
    d = tmp_path / name
    (d / "data").mkdir(parents=True)
    (d / "docs").mkdir()
    monkeypatch.setattr(transfer, "data_dir", lambda: d / "data")
    return d / "data", d / "docs"


def test_everything_moves_and_nothing_is_lost(tmp_path, monkeypatch):
    # дома: откалиброван Canon, свой почерк, настройки, ключ нейросети и две тетради
    data, docs = _computer(tmp_path, monkeypatch, "дом")
    (data / "printers.json").write_text(json.dumps([
        {"name": "Canon G3010 series", "direct_calibrated": True, "direct_front": {"dx_mm": 1.5}},
        {"name": "HP дома", "direct_calibrated": False}], ensure_ascii=False), encoding="utf-8")
    (data / "hands").mkdir()
    (data / "hands" / "moi.json").write_text(json.dumps({"name": "Мой почерк"}, ensure_ascii=False),
                                             encoding="utf-8")
    (data / "settings.json").write_text(json.dumps({"mode": "mchs", "ai": "api", "update_checked": 123}),
                                        encoding="utf-8")
    (data / "gigachat.key").write_text("секрет", encoding="utf-8")
    (docs / "Самоподготовка.konspekt").write_text('{"title": "дома"}', encoding="utf-8")
    (docs / "Другая.konspekt").write_text('{"title": "другая"}', encoding="utf-8")
    pack = tmp_path / "перенос.kpack"
    got = transfer.export_pack(pack, [docs / "Самоподготовка.konspekt", docs / "Другая.konspekt"])
    assert got.notebooks == ["Самоподготовка.konspekt", "Другая.konspekt"] and got.hands == ["Мой почерк"]
    names = zipfile.ZipFile(pack).namelist()
    assert not any(n.endswith(".key") for n in names)  # ключ не переносится
    assert "update_checked" not in zipfile.ZipFile(pack).read("settings.json").decode()

    # на работе: свой откалиброванный HP с тем же именем, своя тема и уже есть тетрадь с другим текстом
    data2, docs2 = _computer(tmp_path, monkeypatch, "работа")
    (data2 / "printers.json").write_text(json.dumps([
        {"name": "HP дома", "direct_calibrated": True, "note": "здешний"},
        {"name": "Kyocera", "direct_calibrated": True}], ensure_ascii=False), encoding="utf-8")
    (data2 / "settings.json").write_text(json.dumps({"theme": "Тёмная", "update_checked": 999}),
                                         encoding="utf-8")
    (docs2 / "Самоподготовка.konspekt").write_text('{"title": "на работе"}', encoding="utf-8")
    info = transfer.read_pack(pack)
    assert "тетради: 2" in info.describe() and "Canon G3010 series" in info.describe()
    got = transfer.import_pack(pack, docs2)

    printers = {p["name"]: p for p in json.loads((data2 / "printers.json").read_text(encoding="utf-8"))}
    assert printers["Canon G3010 series"]["direct_front"]["dx_mm"] == 1.5      # пришёл
    assert printers["HP дома"].get("note") == "здешний"                         # неоткалиброванный не затёр
    assert "Kyocera" in printers                                                 # свой остался
    assert (data2 / "hands" / "moi.json").exists()
    s = json.loads((data2 / "settings.json").read_text(encoding="utf-8"))
    assert s["mode"] == "mchs" and s["theme"] == "Тёмная" and s["update_checked"] == 999
    # своя тетрадь не перезаписана, пришедшая — рядом под новым именем
    assert json.loads((docs2 / "Самоподготовка.konspekt").read_text(encoding="utf-8"))["title"] == "на работе"
    moved = [p for p in got.notebooks if "перенос" in p]
    assert len(moved) == 1 and json.loads(open(moved[0], encoding="utf-8").read())["title"] == "дома"
    assert (docs2 / "Другая.konspekt").exists()
    # тот же файл второй раз — копии не множатся
    again = transfer.import_pack(pack, docs2)
    assert sorted(again.notebooks) == sorted(got.notebooks)


def test_bad_files_are_refused(tmp_path, monkeypatch):
    data, docs = _computer(tmp_path, monkeypatch, "пк")
    f = tmp_path / "не то.kpack"
    f.write_text("просто текст", encoding="utf-8")
    with pytest.raises(transfer.TransferError):
        transfer.read_pack(f)
    # архив с путями наружу: «../» не выходит за папки программы
    evil = tmp_path / "злой.kpack"
    with zipfile.ZipFile(evil, "w") as z:
        z.writestr("manifest.json", json.dumps({"app": "KonspektAI", "format": 1}))
        z.writestr("hands/../../../снаружи.json", "{}")
        z.writestr("notebooks/../../снаружи.konspekt", "{}")
    transfer.import_pack(evil, docs)
    assert not list(tmp_path.rglob("снаружи*"))


def test_import_from_window(qt_app, tmp_path, monkeypatch):
    """«Загрузить из файла» в окне: тетрадь открывается, почерк и принтер сразу доступны."""
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
    from PySide6.QtWidgets import QMessageBox

    from stv.app import project
    from stv.engine.journal import Entry
    data, docs = _computer(tmp_path, monkeypatch, "дом")
    p = project.Project(title="Пожарные автомобили", entries=[Entry(topic="Пожарные автомобили", text="Текст")])
    p.save(docs / "Пожарные автомобили.konspekt")
    pack = tmp_path / "перенос.kpack"
    transfer.export_pack(pack, [docs / "Пожарные автомобили.konspekt"])

    work = tmp_path / "работа"
    monkeypatch.setenv("APPDATA", str(work / "appdata"))
    monkeypatch.setattr(transfer, "data_dir", lambda: work / "appdata" / "KonspektAI")
    monkeypatch.setattr(project, "documents_dir", lambda: work / "docs")
    (work / "docs").mkdir(parents=True)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    from stv.app import main_window
    monkeypatch.setattr(main_window, "documents_dir", lambda: work / "docs")
    w = main_window.MainWindow()
    try:
        w.import_pack(str(pack))
        assert w.project.title == "Пожарные автомобили" and w.project.entries[0].text == "Текст"
        assert (work / "docs" / "Пожарные автомобили.konspekt").exists()
    finally:
        w.work.preview.shutdown()
        w.close()
