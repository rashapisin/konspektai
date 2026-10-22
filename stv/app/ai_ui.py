"""Нейросеть в интерфейсе: выбор сервиса и ключа в Настройках и фоновая работа (ответ идёт до минуты).

GigaChat — бесплатный и проверенный вариант по умолчанию; любой другой сервис подключается по адресу, ключу и
модели (stv/llm.py). Ключи шифруются средствами Windows и хранятся только на этом компьютере.
"""

from PySide6.QtCore import QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLineEdit, QPushButton, QVBoxLayout, QWidget

from .. import keystore
from ..gigachat import KEY_NAME, MODELS, GigaChat, GigaChatError
from ..llm import BY_ID, PROVIDERS, LLMError, OpenAICompatible
from .project import AppSettings
from .ui import theme
from .ui.motion import fade_in
from .ui.widgets import label

GIGACHAT_HELP = "https://developers.sber.ru/studio/workspaces"
SHORT_NAME = {"gigachat": "GigaChat", "deepseek": "DeepSeek", "openrouter": "OpenRouter", "openai": "ChatGPT",
              "gemini": "Gemini", "ollama": "Ollama"}


def provider() -> str:
    pid = AppSettings.get("ai_provider", "gigachat") or "gigachat"
    return pid if pid in BY_ID else "gigachat"


def provider_name() -> str:
    return SHORT_NAME.get(provider(), "AI")


def _key_name(pid: str) -> str:
    return KEY_NAME if pid == "gigachat" else f"ai_{pid}"


def model(pid: str | None = None) -> str:
    pid = pid or provider()
    if pid == "gigachat":
        return AppSettings.get("gigachat_model", MODELS[0][0]) or MODELS[0][0]
    return AppSettings.get(f"ai_{pid}_model", "") or ""


def base_url(pid: str | None = None) -> str:
    pid = pid or provider()
    return AppSettings.get(f"ai_{pid}_url", "") or BY_ID[pid].base_url


def client():
    """Готовый к работе клиент выбранного сервиса или None, если не хватает ключа, адреса или модели."""
    pid = provider()
    key = keystore.load(_key_name(pid))
    if pid == "gigachat":
        return GigaChat(key, model()) if key else None
    if (BY_ID[pid].needs_key and not key) or not base_url(pid) or not model(pid):
        return None
    return OpenAICompatible(base_url(pid), key or "", model(pid))


class Job(QThread):
    """fn() в фоне: done(результат) или failed(понятный текст ошибки)."""
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            self.done.emit(self.fn())
        except (GigaChatError, LLMError) as e:
            self.failed.emit(str(e))
        except Exception as e:  # неожиданное — сообщить, а не уронить программу
            self.failed.emit(f"Не получилось: {e}")


class AISettings(QWidget):
    """Какой нейросетью сжимать: сервис, адрес (для своего), ключ, модель, «Сохранить и проверить»."""

    def __init__(self):
        super().__init__()
        self.job = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.provider = QComboBox()
        for p in PROVIDERS:
            self.provider.addItem(p.title, p.id)
        self.provider.setCurrentIndex(max(0, self.provider.findData(provider())))
        self.provider.currentIndexChanged.connect(self._provider_changed)
        lay.addWidget(self.provider)
        self.note = label("", "muted")
        lay.addWidget(self.note)
        self.url = QLineEdit()
        self.url.setPlaceholderText("Адрес API, например https://…/v1")
        self.url.editingFinished.connect(lambda: AppSettings.set(f"ai_{self._pid()}_url", self.url.text().strip()))
        lay.addWidget(self.url)
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.Password)
        self.save_btn = QPushButton("Сохранить и проверить")
        self.save_btn.setProperty("kind", "primary")
        self.save_btn.clicked.connect(self._save)
        row = QHBoxLayout()
        row.addWidget(self.key, 1)
        row.addWidget(self.save_btn)
        lay.addLayout(row)
        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.setToolTip("Модель: выберите из списка после проверки ключа или впишите название")
        self.model.currentTextChanged.connect(self._model_changed)
        lay.addWidget(self.model)
        row2 = QHBoxLayout()
        self.help_btn = QPushButton("Открыть developers.sber.ru")
        self.help_btn.setProperty("kind", "ghost")
        self.help_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(GIGACHAT_HELP)))
        self.forget = QPushButton("Удалить ключ")
        self.forget.setProperty("kind", "ghost")
        self.forget.clicked.connect(self._forget)
        row2.addWidget(self.help_btn)
        row2.addWidget(self.forget)
        row2.addStretch(1)
        lay.addLayout(row2)
        self.status = label("")
        lay.addWidget(self.status)
        self._provider_changed()

    def _pid(self) -> str:
        return self.provider.currentData()

    def _provider_changed(self, *_):
        pid = self._pid()
        AppSettings.set("ai_provider", pid)
        p = BY_ID[pid]
        how = ("Как получить ключ: войдите на developers.sber.ru через Сбер ID → создайте проект GigaChat API → "
               "в его настройках нажмите «Получить ключ» и скопируйте «Ключ авторизации»."
               if pid == "gigachat" else "")
        self.note.setText(p.note + (" " + how if how else "")
                          + ("" if p.tested else " Подключается по стандарту OpenAI API."))
        self.url.setVisible(pid in ("custom", "ollama"))
        self.url.setText(base_url(pid))
        self.key.setVisible(p.needs_key)
        self.help_btn.setVisible(pid == "gigachat")
        self.model.blockSignals(True)
        self.model.clear()
        if pid == "gigachat":
            for mid, title in MODELS:
                self.model.addItem(mid)
                self.model.setItemData(self.model.count() - 1, title, 3)  # подсказка у пункта
        self.model.setEditText(model(pid))
        self.model.blockSignals(False)
        self.status.setText("")
        self._refresh()

    def _model_changed(self, text: str):
        pid = self._pid()
        AppSettings.set("gigachat_model" if pid == "gigachat" else f"ai_{pid}_model", text.strip())

    def _refresh(self):
        pid = self._pid()
        has = keystore.load(_key_name(pid)) is not None
        self.key.setPlaceholderText("Ключ сохранён — чтобы заменить, вставьте новый" if has else "Вставьте ключ API")
        self.forget.setVisible(has)
        self.save_btn.setText("Сохранить и проверить" if BY_ID[pid].needs_key else "Проверить")
        if has and not self.status.text():
            self._say("✓ Ключ сохранён на этом компьютере в зашифрованном виде.", "success", animate=False)

    def _save(self):
        pid = self._pid()
        text = self.key.text().strip() or (keystore.load(_key_name(pid)) or "")
        if BY_ID[pid].needs_key and not text:
            self._say("Вставьте ключ в поле.", "danger")
            return
        if pid != "gigachat":
            AppSettings.set(f"ai_{pid}_url", self.url.text().strip())
            if not base_url(pid):
                self._say("Впишите адрес API сервиса.", "danger")
                return
        self.save_btn.setEnabled(False)
        self._say("Проверяю…", "text_muted")
        checker = (GigaChat(text, self.model.currentText()) if pid == "gigachat"
                   else OpenAICompatible(base_url(pid), text, self.model.currentText()))
        self.job = Job(checker.check)
        self.job.done.connect(lambda models: self._ok(pid, text, models))
        self.job.failed.connect(self._fail)
        self.job.start()

    def _ok(self, pid: str, text: str, models):
        self.save_btn.setEnabled(True)
        if text:
            try:
                keystore.save(_key_name(pid), text)
            except OSError as e:
                self._say(f"Ключ работает, но сохранить не удалось: {e}", "danger")
                return
        self.key.clear()
        if pid != "gigachat" and models:
            current = self.model.currentText()
            self.model.blockSignals(True)
            self.model.clear()
            self.model.addItems(models)
            self.model.blockSignals(False)
            self.model.setEditText(current if current in models else models[0])
        self._refresh()
        self._say(f"✓ Работает. Доступно моделей: {len(models)}. Ключ хранится в зашифрованном виде.", "success")

    def _fail(self, msg: str):
        self.save_btn.setEnabled(True)
        self._say(msg, "danger")

    def _forget(self):
        keystore.delete(_key_name(self._pid()))
        self.status.setText("")
        self._refresh()
        self._say("Ключ удалён с этого компьютера.", "text_muted")

    def _say(self, text: str, color: str, animate: bool = True):
        self.status.setText(f"<span style='color:{getattr(theme.current(), color)}'>{text}</span>")
        if animate:
            fade_in(self.status, rise=4)
