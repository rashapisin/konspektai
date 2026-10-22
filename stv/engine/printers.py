"""Профили принтеров: у каждого принтера свой сдвиг печати.

Профиль называется так же, как принтер в Windows, поэтому программа сама выбирает нужные поправки.
Драйвер не сообщает, насколько принтер сдвигает лист при ручной подаче, поэтому один раз
каждый принтер калибруется по проверочной сетке.
Профили хранятся в %APPDATA%\\KonspektAI\\printers.json и не теряются при обновлении программы.
"""

import copy
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .settings import PrinterOffset

PDF, DIRECT = "pdf", "direct"  # печать через PDF в программе просмотра / прямо из KonspektAI через драйвер


@dataclass
class PrinterProfile:
    """Поправки печати. У двух способов печати сдвиги разные: драйвер получает лист по-разному."""
    name: str
    front: PrinterOffset = field(default_factory=PrinterOffset)   # через PDF (Chrome, 100%, A5)
    back: PrinterOffset = field(default_factory=PrinterOffset)
    note: str = ""
    calibrated: bool = False
    direct_front: PrinterOffset = field(default_factory=PrinterOffset)  # прямая печать из KonspektAI
    direct_back: PrinterOffset = field(default_factory=PrinterOffset)
    direct_calibrated: bool = False
    # как прошла калибровка прямой печати: «photo» — по фото, «manual» — по шкалам на глаз, «edit» — числа вручную
    direct_method: str = ""
    direct_date: str = ""
    direct_check_mm: float = -1.0  # точность по фото проверочного листа, мм; −1 — не проверяли

    def offsets(self, method: str) -> tuple[PrinterOffset, PrinterOffset]:
        return (self.direct_front, self.direct_back) if method == DIRECT else (self.front, self.back)

    def is_calibrated(self, method: str) -> bool:
        return self.direct_calibrated if method == DIRECT else self.calibrated

    def set_offsets(self, method: str, front: PrinterOffset, back: PrinterOffset, how: str = "edit",
                    check_mm: float = -1.0):
        if method == DIRECT:
            import datetime as dt
            self.direct_front, self.direct_back, self.direct_calibrated = front, back, True
            self.direct_method, self.direct_date = how, dt.date.today().strftime("%d.%m.%Y")
            self.direct_check_mm = check_mm
        else:
            self.front, self.back, self.calibrated = front, back, True

    def status(self) -> tuple[str, str]:
        """(уровень ok | warn | none, текст) — насколько можно доверять печати из программы."""
        if not self.direct_calibrated:
            return "none", "не откалиброван — пройдите мастер калибровки (один лист)"
        when = f" {self.direct_date}" if self.direct_date else ""
        if self.direct_method == "photo" and self.direct_check_mm >= 0:
            acc = f"{self.direct_check_mm:.1f}".replace(".", ",")
            return "ok", f"✓ откалиброван по фото{when}, проверено: точность {acc} мм"
        if self.direct_method == "photo":
            return "warn", f"откалиброван по фото{when}, но проверка не пройдена — проверьте в мастере"
        if self.direct_method == "edit":
            return "warn", f"поправки введены вручную{when} — точность не проверена"
        return "warn", (f"откалиброван на глаз по шкалам{when} — возможна ошибка до 2 мм, "
                        "лучше пройти мастер по фото")


# Встроенных поправок нет: у каждого свой принтер. Поправки появляются после мастера калибровки
# и хранятся в личном файле пользователя.
DEFAULTS: dict = {}

NO_PROFILE = PrinterProfile("Без поправок")


def _path() -> Path:
    from ..brand import data_dir
    return data_dir() / "printers.json"


def load() -> dict[str, PrinterProfile]:
    profiles = copy.deepcopy(DEFAULTS)  # правки в программе не должны менять встроенные значения
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        for d in data:
            name = d["name"]
            if name in ("Без поправок", "Дом"):
                continue
            profiles[name] = PrinterProfile(
                name, PrinterOffset(**d["front"]), PrinterOffset(**d["back"]), d.get("note", ""),
                d.get("calibrated", True),
                PrinterOffset(**d.get("direct_front", {})), PrinterOffset(**d.get("direct_back", {})),
                d.get("direct_calibrated", False), d.get("direct_method", ""), d.get("direct_date", ""),
                float(d.get("direct_check_mm", -1.0)))
    except (OSError, ValueError, KeyError, TypeError):
        pass  # файла нет или он испорчен — работаем со встроенными профилями
    return profiles


def save(profiles: dict[str, PrinterProfile]):
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps([asdict(v) for v in profiles.values()], ensure_ascii=False, indent=2), encoding="utf-8")


def system_printers() -> tuple[list[str], str]:
    """Принтеры, установленные в Windows, и принтер по умолчанию."""
    try:
        from PySide6.QtPrintSupport import QPrinterInfo
        names = [n for n in QPrinterInfo.availablePrinterNames()
                 if n not in ("Microsoft Print to PDF", "Microsoft XPS Document Writer", "OneNote", "Fax")]
        default = QPrinterInfo.defaultPrinterName()
    except Exception:
        return [], ""
    return names, default if default in names else (names[0] if names else "")


def get(name: str) -> PrinterProfile:
    return load().get(name) or PrinterProfile(name)
