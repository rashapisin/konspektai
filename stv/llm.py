"""Нейросети для «Сжать через AI»: GigaChat и любые сервисы со стандартным (OpenAI-совместимым) API.

У большинства сервисов один и тот же формат запросов: POST {адрес}/chat/completions с ключом в заголовке
«Authorization: Bearer …». Поэтому достаточно адреса, ключа и названия модели. GigaChat устроен иначе (ключ
меняется на токен, свой сертификат) — он в stv/gigachat.py, а здесь только общий список.
"""

import json
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass

TIMEOUT = 90.0


class LLMError(Exception):
    pass


@dataclass(frozen=True)
class Provider:
    id: str
    title: str
    base_url: str      # пусто — человек вписывает свой адрес
    note: str
    needs_key: bool = True
    tested: bool = False


PROVIDERS = (
    Provider("gigachat", "GigaChat (Сбер) — бесплатно", "",
             "365 млн бесплатных токенов на год для физических лиц. Проверено с KonspektAI.", tested=True),
    Provider("deepseek", "DeepSeek", "https://api.deepseek.com/v1",
             "Ключ — на platform.deepseek.com. Платно, но недорого."),
    Provider("openrouter", "OpenRouter — сотни моделей", "https://openrouter.ai/api/v1",
             "Один ключ для многих моделей, есть бесплатные (с пометкой «:free»). Ключ — на openrouter.ai."),
    Provider("openai", "OpenAI (ChatGPT)", "https://api.openai.com/v1",
             "Ключ — на platform.openai.com. Из России может быть недоступен."),
    Provider("gemini", "Google Gemini", "https://generativelanguage.googleapis.com/v1beta/openai",
             "Ключ — в Google AI Studio. Из России может быть недоступен."),
    Provider("ollama", "Ollama — на своём компьютере", "http://localhost:11434/v1",
             "Бесплатно и без интернета: модель работает у вас (нужен мощный компьютер и программа Ollama).",
             needs_key=False),
    Provider("custom", "Другой сервис (свой адрес)", "",
             "Любой сервис с OpenAI-совместимым API: впишите адрес, ключ и модель из его документации."),
)
BY_ID = {p.id: p for p in PROVIDERS}


def _call(url: str, key: str, body: dict | None, timeout: float) -> dict:
    headers = {"Accept": "application/json", "User-Agent": "KonspektAI"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        msg = {401: "Ключ не подошёл. Проверьте, что скопировали его целиком.",
               403: "Доступ запрещён: у ключа нет прав или сервис недоступен из вашей страны.",
               402: "На счёте сервиса закончились деньги или бесплатный лимит.",
               404: "Не найдено: проверьте адрес сервиса и название модели.",
               429: "Слишком много запросов или исчерпан лимит. Подождите и попробуйте ещё раз."}.get(e.code)
        raise LLMError(msg or f"Сервис ответил ошибкой {e.code}.") from None
    except (OSError, ValueError) as e:
        raise LLMError("Нет связи с сервисом. Проверьте интернет и адрес.") from e


class OpenAICompatible:
    def __init__(self, base_url: str, key: str, model: str):
        self.base = base_url.rstrip("/")
        self.key, self.model = key.strip(), model.strip()

    def check(self) -> list[str]:
        """Ключ работает? Возвращает модели, которые сервис предлагает."""
        data = _call(f"{self.base}/models", self.key, None, 20)
        return sorted(m.get("id", "") for m in data.get("data", []) if m.get("id"))

    def complete(self, prompt: str, temperature: float = 0.3) -> str:
        if not self.model:
            raise LLMError("Не выбрана модель. Укажите её в Настройках.")
        data = _call(f"{self.base}/chat/completions", self.key,
                     {"model": self.model, "temperature": temperature,
                      "messages": [{"role": "user", "content": prompt}]}, TIMEOUT)
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise LLMError("Сервис прислал пустой ответ. Попробуйте ещё раз.") from None
