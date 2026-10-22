"""Дизайн-система KonspektAI: палитры, шрифт, стили виджетов, иконки.

Направление — как у Claude и ChatGPT: спокойный тёплый фон, много воздуха, мягкие скругления,
тонкие рамки, один акцент. Акцент — «синие чернила», потому что программа про письмо ручкой.
"""

from dataclasses import dataclass

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QGuiApplication, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtSvg import QSvgRenderer

from ...resources import asset


@dataclass(frozen=True)
class Palette:
    name: str
    bg: str           # фон окна
    surface: str      # карточки, поля ввода
    surface_alt: str  # полоска навигации, выделенные области
    hover: str
    border: str
    border_strong: str
    text: str
    text_muted: str
    accent: str
    accent_soft: str  # фон выделенного
    accent_text: str  # текст на акценте
    success: str
    warning: str
    danger: str
    shadow: str


LIGHT = Palette("light", bg="#F7F5F0", surface="#FFFFFF", surface_alt="#EFECE5", hover="#ECE8E0",
                border="#E3DFD6", border_strong="#CFC9BE", text="#1F1E1C", text_muted="#6E6A63",
                accent="#2F55D4", accent_soft="#E5EBFB", accent_text="#FFFFFF", success="#2E7D4F",
                warning="#A8650A", danger="#C0392B", shadow="#00000022")
DARK = Palette("dark", bg="#1F1E1C", surface="#2A2926", surface_alt="#252421", hover="#34332F",
               border="#3A3834", border_strong="#4A4843", text="#EDEBE6", text_muted="#A5A19A",
               accent="#7C9BFF", accent_soft="#2C3552", accent_text="#11131A", success="#6CCB8F",
               warning="#E0A63F", danger="#F07A6B", shadow="#00000066")

FONT_FAMILY = "Inter"
_current: Palette = LIGHT
_listeners = []


def current() -> Palette:
    return _current


def on_change(fn):
    """Подписка на смену темы (иконки и нарисованные вручную элементы перерисовываются)."""
    _listeners.append(fn)


def load_font():
    global FONT_FAMILY
    fid = QFontDatabase.addApplicationFont(str(asset("fonts", "inter", "Inter-Variable.ttf")))
    fams = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
    FONT_FAMILY = fams[0] if fams else "Segoe UI"
    f = QFont(FONT_FAMILY)
    f.setPointSizeF(10)
    f.setHintingPreference(QFont.PreferNoHinting)
    QGuiApplication.setFont(f)


def _is_dark(choice: str) -> bool:
    if choice == "Тёмная":
        return True
    if choice == "Светлая":
        return False
    return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark


def apply(app, choice: str = "Как в Windows"):
    """Применить тему ко всему приложению."""
    global _current
    _current = DARK if _is_dark(choice) else LIGHT
    p = _current
    pal = QPalette()
    for role, col in ((QPalette.Window, p.bg), (QPalette.Base, p.surface), (QPalette.AlternateBase, p.surface_alt),
                      (QPalette.Text, p.text), (QPalette.WindowText, p.text), (QPalette.ButtonText, p.text),
                      (QPalette.Button, p.surface), (QPalette.Highlight, p.accent),
                      (QPalette.HighlightedText, p.accent_text), (QPalette.ToolTipBase, p.text),
                      (QPalette.ToolTipText, p.bg), (QPalette.PlaceholderText, p.text_muted),
                      (QPalette.Link, p.accent)):
        pal.setColor(role, QColor(col))
    app.setPalette(pal)
    app.setStyleSheet(stylesheet(p))
    _icon_cache.clear()
    for fn in list(_listeners):
        fn()


def _rgba(color: str, alpha: float) -> str:
    c = QColor(color)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {alpha})"


def stylesheet(p: Palette) -> str:
    return f"""
* {{ font-family: "{FONT_FAMILY}"; }}
QWidget {{ color: {p.text}; }}
QMainWindow, QDialog, #Page {{ background: {p.bg}; }}
QToolTip {{ background: {p.surface}; color: {p.text}; border: 1px solid {p.border_strong}; border-radius: 8px; padding: 6px 10px; }}

QLabel[role="h1"] {{ font-size: 22pt; font-weight: 600; }}
QLabel[role="h2"] {{ font-size: 14pt; font-weight: 600; }}
QLabel[role="muted"] {{ color: {p.text_muted}; }}
QLabel[role="badge"] {{ background: {p.accent_soft}; color: {p.accent}; border-radius: 9px; padding: 1px 8px; }}
QLabel[role="warn"] {{ color: {p.danger}; }}

QPushButton {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: 10px;
              padding: 7px 14px; }}
QPushButton:hover {{ background: {p.hover}; border-color: {p.border_strong}; }}
QPushButton:pressed {{ background: {p.border}; }}
QPushButton:disabled {{ color: {p.text_muted}; }}
QPushButton[kind="primary"] {{ background: {p.accent}; color: {p.accent_text}; border: none; font-weight: 600;
                               padding: 9px 18px; }}
QPushButton[kind="primary"]:hover {{ background: {QColor(p.accent).lighter(112).name()}; }}
QPushButton[kind="ghost"] {{ background: transparent; border: none; color: {p.text_muted}; padding: 6px 10px; }}
QPushButton[kind="ghost"]:hover {{ background: {p.hover}; color: {p.text}; }}
QPushButton[kind="chip"] {{ border-radius: 14px; padding: 5px 12px; }}
QPushButton[kind="chip"]:checked {{ background: {p.accent_soft}; border-color: {p.accent}; color: {p.accent}; }}

QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background: {p.surface}; border: 1px solid {p.border}; border-radius: 10px; padding: 6px 10px;
    selection-background-color: {p.accent_soft}; selection-color: {p.text}; }}
QPlainTextEdit, QTextEdit {{ padding: 10px 12px; }}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border: 1px solid {p.accent}; }}
QLineEdit[flat="true"] {{ background: transparent; border: 1px solid transparent; font-size: 15pt;
                          font-weight: 600; padding: 4px 6px; }}
QLineEdit[flat="true"]:hover {{ border-color: {p.border}; }}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox::down-arrow {{ image: url({_icon_file("chevron-down", p.text_muted)}); width: 14px; height: 14px; }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{ border: none; background: transparent; width: 22px; }}
QAbstractSpinBox::up-button {{ subcontrol-position: top right; }}
QAbstractSpinBox::down-button {{ subcontrol-position: bottom right; }}
QAbstractSpinBox::up-arrow {{ image: url({_icon_file("chevron-up", p.text_muted)}); width: 11px; height: 11px; }}
QAbstractSpinBox::down-arrow {{ image: url({_icon_file("chevron-down", p.text_muted)}); width: 11px; height: 11px; }}
QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {{ background: {p.hover};
                                                                      border-radius: 6px; }}
QComboBox QAbstractItemView {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: 8px;
                               selection-background-color: {p.accent_soft}; selection-color: {p.text};
                               padding: 4px; outline: none; }}

QListWidget {{ background: transparent; border: none; outline: none; }}
QListWidget::item {{ border-radius: 10px; padding: 8px 10px; margin: 1px 0; }}
QListWidget::item:hover {{ background: {p.hover}; }}
QListWidget::item:selected {{ background: {p.accent_soft}; color: {p.text}; }}

QScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {p.border_strong}; border-radius: 3px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {p.text_muted}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {p.border_strong}; border-radius: 3px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QSlider::groove:horizontal {{ height: 4px; background: {p.border}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {p.accent}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {p.surface}; border: 2px solid {p.accent}; width: 14px; height: 14px;
                              margin: -7px 0; border-radius: 9px; }}

QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 6px; border: 1px solid {p.border_strong};
                        background: {p.surface}; }}
QCheckBox::indicator:checked {{ background: {p.accent}; border-color: {p.accent};
                                image: url({_icon_file("check", p.accent_text)}); }}

QGroupBox {{ border: 1px solid {p.border}; border-radius: 14px; margin-top: 18px; padding: 14px 12px 10px 12px;
             background: {p.surface}; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; top: 2px; padding: 0 4px; color: {p.text_muted};
                    font-weight: 600; }}
QSplitter::handle {{ background: transparent; }}
QSplitter::handle:horizontal {{ width: 6px; }}
QSplitter::handle:vertical {{ height: 6px; }}
QTableWidget {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: 12px; gridline-color: {p.border};
                alternate-background-color: {p.bg}; padding: 4px; }}
QTableWidget::item {{ padding: 4px 8px; }}
QHeaderView::section {{ background: {p.surface_alt}; border: none; padding: 6px; font-weight: 600; }}
QProgressBar {{ background: {p.border}; border: none; border-radius: 4px; height: 8px; text-align: center; }}
QProgressBar::chunk {{ background: {p.accent}; border-radius: 4px; }}

#Rail {{ background: {p.surface_alt}; border-right: 1px solid {p.border}; }}
#Card {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: 16px; }}
#Card[selected="true"] {{ border: 2px solid {p.accent}; background: {p.accent_soft}; }}
QLabel[role="pill_ok"] {{ background: {_rgba(p.success, 0.13)}; color: {p.success}; border-radius: 10px;
                         padding: 3px 10px; font-weight: 600; }}
QLabel[role="pill_warn"] {{ background: {_rgba(p.warning, 0.13)}; color: {p.warning}; border-radius: 10px;
                           padding: 3px 10px; font-weight: 600; }}
QLabel[role="pill_none"] {{ background: {p.surface_alt}; color: {p.text_muted}; border-radius: 10px;
                           padding: 3px 10px; font-weight: 600; }}
QLabel[role="step"] {{ background: {p.accent_soft}; color: {p.accent}; border-radius: 15px; font-weight: 700;
                      min-width: 30px; max-width: 30px; min-height: 30px; max-height: 30px; }}
#Drawer {{ background: {p.surface}; border-left: 1px solid {p.border}; }}
"""


# ---------- иконки ----------

_icon_cache: dict = {}
_check_file = None


def _svg(name: str, color: str) -> bytes:
    raw = asset("ui", "icons", f"{name}.svg").read_text(encoding="utf-8")
    return raw.replace("currentColor", color).encode("utf-8")


def pixmap(name: str, size: int = 20, color: str | None = None) -> QPixmap:
    color = color or current().text
    dpr = QGuiApplication.primaryScreen().devicePixelRatio() if QGuiApplication.primaryScreen() else 1.0
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.fill(Qt.transparent)
    r = QSvgRenderer(QByteArray(_svg(name, color)))
    p = QPainter(pm)
    r.render(p)
    p.end()
    pm.setDevicePixelRatio(dpr)
    return pm


def icon(name: str, color: str | None = None, size: int = 20) -> QIcon:
    key = (name, color or current().text, size)
    if key not in _icon_cache:
        _icon_cache[key] = QIcon(pixmap(name, size, key[1]))
    return _icon_cache[key]


def _icon_file(name: str, color: str) -> str:
    """Иконка для QSS (галочка, стрелки списков и полей): QSS понимает только файл, поэтому пишем
    перекрашенную иконку во временную папку."""
    import tempfile
    from pathlib import Path
    f = Path(tempfile.gettempdir()) / f"konspektai_{name}_{color.lstrip('#')}.svg"
    try:
        f.write_bytes(_svg(name, color))
    except OSError:
        return ""
    return f.as_posix()
