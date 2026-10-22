"""Проект конспекта: текст и все настройки оформления в одном файле .konspekt (JSON)."""

import datetime as dt
import json
import time
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from ..brand import APP_NAME, FILE_EXT, OLD_FILE_EXT, data_dir  # noqa: F401
from ..engine.journal import DATE_FMT, Entry
from ..engine.settings import HandSettings, PageSettings

FORMAT_VERSION = 3


def documents_dir() -> Path:
    from ..brand import portable_root
    root = portable_root()
    d = root / "Тетради" if root is not None else Path.home() / "Documents" / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def _app_data() -> Path:
    return data_dir()


# Поля страницы, которые сохраняются в проекте (бумага и поправки принтера — отдельно)
PAGE_FIELDS = ("margin_inner_mm", "margin_outer_mm", "margin_top_mm", "margin_bottom_mm", "line_step_cells",
               "first_line_indent_cells", "margin_line", "margin_line_offset_mm", "margin_line_color",
               "margin_line_width_mm", "date")


@dataclass
class Project:
    """Тетрадь: набор конспектов и общее оформление."""
    title: str = "Новая тетрадь"
    entries: list[Entry] = field(default_factory=lambda: [Entry(date=dt.date.today().strftime(DATE_FMT),
                                                                date_auto=False)])
    step_days: int = 4  # график «сутки через трое»
    page: dict = field(default_factory=dict)
    hand: dict = field(default_factory=dict)
    printer: str = ""  # имя принтера Windows; пусто — принтер по умолчанию
    path: str = ""  # где лежит файл; не сохраняется внутрь

    def page_settings(self) -> PageSettings:
        from ..engine.paper import paper
        ps = PageSettings(paper=paper(self.page.get("paper", "block_a5_grid")))
        for k, v in self.page.items():
            if k in PAGE_FIELDS:
                setattr(ps, k, v)
        return ps

    def hand_settings(self) -> HandSettings:
        names = {f.name for f in fields(HandSettings)}
        return HandSettings(**{k: v for k, v in self.hand.items() if k in names})

    def set_settings(self, ps: PageSettings, hs: HandSettings):
        self.page = {k: getattr(ps, k) for k in PAGE_FIELDS}
        self.page["paper"] = ps.paper.id
        self.hand = asdict(hs)

    def save(self, path: str | Path | None = None):
        path = Path(path or self.path or documents_dir() / f"{_safe(self.title)}{FILE_EXT}")
        data = {"version": FORMAT_VERSION, "title": self.title, "entries": [asdict(e) for e in self.entries],
                "step_days": self.step_days, "page": self.page, "hand": self.hand, "printer": self.printer}
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)  # атомарная запись: при сбое старый файл не испортится
        self.path = str(path)
        Recent.add(path, self.title)

    @classmethod
    def load(cls, path: str | Path) -> "Project":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data.get("version", 1) < 2:
            # в версии 1 красная линия была у колец: поля меняем местами
            pg = data.get("page", {})
            if "margin_inner_mm" in pg and "margin_outer_mm" in pg:
                pg["margin_inner_mm"], pg["margin_outer_mm"] = pg["margin_outer_mm"], pg["margin_inner_mm"]
        if "entries" in data:
            names = {f.name for f in fields(Entry)}
            entries = [Entry(**{k: v for k, v in d.items() if k in names}) for d in data["entries"]]
        else:
            # до версии 3 проект был одним текстом — превращаем его в один конспект без шапки
            entries = [Entry(kind="free", text=data.get("text", ""), date=data.get("page", {}).get("date", ""),
                             date_auto=False, fit=False)]
        p = cls(title=data.get("title", Path(path).stem), entries=entries or [Entry()],
                step_days=data.get("step_days", 4), page=data.get("page", {}), hand=data.get("hand", {}),
                printer=data.get("printer", ""), path=str(path))
        Recent.add(path, p.title)
        return p


def _safe(name: str) -> str:
    bad = '<>:"/\\|?*'
    name = "".join("_" if c in bad else c for c in name).strip(" .") or "Конспект"
    return name[:80]


class Recent:
    """Список недавних проектов для главного экрана."""

    @staticmethod
    def _file() -> Path:
        return _app_data() / "recent.json"

    @classmethod
    def items(cls) -> list[dict]:
        try:
            data = json.loads(cls._file().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return [d for d in data if Path(d.get("path", "")).exists()]

    @classmethod
    def add(cls, path, title: str):
        items = [d for d in cls.items() if Path(d["path"]) != Path(path)]
        items.insert(0, {"path": str(path), "title": title, "opened": time.time()})
        try:
            cls._file().write_text(json.dumps(items[:20], ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass


class AppSettings:
    """Настройки программы (тема и т. п.)."""

    @staticmethod
    def _file() -> Path:
        return _app_data() / "settings.json"

    @classmethod
    def get(cls, key: str, default=None):
        try:
            return json.loads(cls._file().read_text(encoding="utf-8")).get(key, default)
        except (OSError, ValueError):
            return default

    @classmethod
    def set(cls, key: str, value):
        try:
            data = json.loads(cls._file().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        data[key] = value
        cls._file().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
