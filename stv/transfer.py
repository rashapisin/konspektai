"""Перенос на другой компьютер одним файлом .kpack: калибровки принтеров, свои почерки, настройки программы
и тетради. Дома подготовили конспекты — на работе загрузили файл и печатаете из программы, как обычно.

Внутри — обычный ZIP. Ключи нейросетей не переносятся: они зашифрованы для этой учётной записи Windows
(keystore) и на другом компьютере всё равно не расшифруются; там ключ вводится заново.
При загрузке ничего не стирается: принтеры и почерки с тем же именем обновляются, а тетрадь, которая на этом
компьютере уже есть и отличается, сохраняется рядом под новым именем.
"""

import datetime as dt
import glob
import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from .brand import APP_NAME, FILE_EXT, OLD_FILE_EXT, VERSION, data_dir

FORMAT = 1
# Что не переносим из настроек: относится к этому компьютеру, а не к человеку
LOCAL_SETTINGS = {"update_checked"}


class TransferError(Exception):
    pass


@dataclass
class Contents:
    printers: list[str] = field(default_factory=list)
    hands: list[str] = field(default_factory=list)
    notebooks: list[str] = field(default_factory=list)  # имена файлов (в архиве) или пути (после загрузки)
    settings: bool = False
    created: str = ""
    version: str = ""

    def describe(self) -> str:
        parts = []
        if self.notebooks:
            parts.append(f"тетради: {len(self.notebooks)}")
        if self.printers:
            parts.append("принтеры: " + ", ".join(self.printers))
        if self.hands:
            parts.append("свои почерки: " + ", ".join(self.hands))
        if self.settings:
            parts.append("настройки программы")
        return "; ".join(parts) or "ничего"


def _hand_name(data: bytes, fallback: str) -> str:
    try:
        return json.loads(data.decode("utf-8")).get("name", fallback)
    except ValueError:
        return fallback


def export_pack(dest: str | Path, notebooks: list[str | Path]) -> Contents:
    """Собрать файл переноса. notebooks — пути тетрадей, которые положить внутрь (можно пусто)."""
    src = data_dir()
    out = Contents(created=dt.datetime.now().strftime("%d.%m.%Y %H:%M"), version=VERSION)
    dest = Path(dest)
    tmp = dest.with_name(dest.name + ".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        printers = src / "printers.json"
        if printers.exists():
            data = printers.read_bytes()
            z.writestr("printers.json", data)
            try:
                out.printers = [p["name"] for p in json.loads(data.decode("utf-8"))]
            except (ValueError, KeyError, TypeError):
                pass
        settings = src / "settings.json"
        if settings.exists():
            try:
                s = json.loads(settings.read_text(encoding="utf-8"))
            except ValueError:
                s = {}
            s = {k: v for k, v in s.items() if k not in LOCAL_SETTINGS}
            z.writestr("settings.json", json.dumps(s, ensure_ascii=False, indent=2))
            out.settings = True
        for f in sorted((src / "hands").glob("*.json")) if (src / "hands").is_dir() else []:
            data = f.read_bytes()
            z.writestr(f"hands/{f.name}", data)
            out.hands.append(_hand_name(data, f.stem))
        seen = set()
        for nb in notebooks:
            nb = Path(nb)
            if not nb.is_file() or nb.name in seen:
                continue
            seen.add(nb.name)
            z.writestr(f"notebooks/{nb.name}", nb.read_bytes())
            out.notebooks.append(nb.name)
        z.writestr("manifest.json", json.dumps({
            "app": APP_NAME, "format": FORMAT, "version": VERSION, "created": out.created,
            "printers": out.printers, "hands": out.hands, "notebooks": out.notebooks, "settings": out.settings},
            ensure_ascii=False, indent=2))
    tmp.replace(dest)
    return out


def _open(src: str | Path) -> tuple[zipfile.ZipFile, dict]:
    try:
        z = zipfile.ZipFile(src)
    except (OSError, zipfile.BadZipFile):
        raise TransferError("Это не файл переноса KonspektAI или он повреждён.") from None
    try:
        manifest = json.loads(z.read("manifest.json").decode("utf-8"))
    except (KeyError, ValueError):
        z.close()
        raise TransferError("Это не файл переноса KonspektAI: внутри нет описания.") from None
    if manifest.get("app") != APP_NAME:
        z.close()
        raise TransferError("Это не файл переноса KonspektAI.")
    if manifest.get("format", 0) > FORMAT:
        z.close()
        raise TransferError("Файл сделан более новой версией программы. Обновите KonspektAI и загрузите снова.")
    return z, manifest


def read_pack(src: str | Path) -> Contents:
    """Что лежит в файле — показать человеку перед загрузкой."""
    z, m = _open(src)
    z.close()
    return Contents(m.get("printers", []), m.get("hands", []), m.get("notebooks", []), bool(m.get("settings")),
                    m.get("created", ""), m.get("version", ""))


def _merge_printers(incoming: list[dict]) -> list[str]:
    """Профили по имени принтера: пришедший заменяет здешний, кроме случая, когда здесь принтер откалиброван,
    а в файле — нет (на том компьютере его просто не настраивали)."""
    path = data_dir() / "printers.json"
    try:
        local = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        local = []
    by_name = {p.get("name"): p for p in local if isinstance(p, dict)}
    taken = []
    for p in incoming:
        if not isinstance(p, dict) or not p.get("name"):
            continue
        old = by_name.get(p["name"])
        calibrated = lambda d: bool(d.get("direct_calibrated") or d.get("calibrated"))  # noqa: E731
        if old is not None and calibrated(old) and not calibrated(p):
            continue
        by_name[p["name"]] = p
        taken.append(p["name"])
    path.write_text(json.dumps(list(by_name.values()), ensure_ascii=False, indent=2), encoding="utf-8")
    return taken


def _free_name(folder: Path, name: str, stamp: str) -> Path:
    """Тетрадь с таким именем уже есть и отличается — кладём рядом: «Имя (перенос 28.10).konspekt»."""
    stem, suffix = Path(name).stem, Path(name).suffix
    for i in range(1, 100):
        extra = f" (перенос {stamp})" if i == 1 else f" (перенос {stamp}, {i})"
        p = folder / f"{stem}{extra}{suffix}"
        if not p.exists():
            return p
    raise TransferError("Не удалось подобрать имя для тетради.")


def import_pack(src: str | Path, notebooks_dir: str | Path) -> Contents:
    """Загрузить файл переноса. Возвращает, что загружено; notebooks — пути тетрадей на этом компьютере."""
    z, manifest = _open(src)
    out = Contents(created=manifest.get("created", ""), version=manifest.get("version", ""))
    dst = data_dir()
    folder = Path(notebooks_dir)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = dt.date.today().strftime("%d.%m")
    with z:
        names = set(z.namelist())
        if "printers.json" in names:
            try:
                out.printers = _merge_printers(json.loads(z.read("printers.json").decode("utf-8")))
            except ValueError:
                raise TransferError("Калибровки принтеров в файле повреждены.") from None
        if "settings.json" in names:
            try:
                incoming = json.loads(z.read("settings.json").decode("utf-8"))
            except ValueError:
                incoming = {}
            path = dst / "settings.json"
            try:
                local = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                local = {}
            local.update({k: v for k, v in incoming.items() if k not in LOCAL_SETTINGS})
            path.write_text(json.dumps(local, ensure_ascii=False, indent=2), encoding="utf-8")
            out.settings = True
        for n in sorted(names):
            # только известные места и только имя файла: путь вида «../../что-то» из архива не пройдёт
            base = Path(n).name
            if n == f"hands/{base}" and base.endswith(".json"):
                (dst / "hands").mkdir(parents=True, exist_ok=True)
                data = z.read(n)
                (dst / "hands" / base).write_bytes(data)
                out.hands.append(_hand_name(data, Path(base).stem))
            elif n == f"notebooks/{base}" and base.lower().endswith((FILE_EXT, OLD_FILE_EXT)):
                data = z.read(n)
                target = folder / base
                if target.exists() and target.read_bytes() != data:
                    # уже загружали этот же файл раньше — не плодим копии
                    same = [f for f in folder.glob(f"{glob.escape(Path(base).stem)} (перенос *{Path(base).suffix}")
                            if f.read_bytes() == data]
                    target = same[0] if same else _free_name(folder, base, stamp)
                if not target.exists():
                    target.write_bytes(data)
                out.notebooks.append(str(target))
    return out
