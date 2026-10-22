"""GigaChat API (Сбер): бесплатный для физических лиц (Freemium — 365 млн токенов на 12 месяцев).

Ключ авторизации человек получает сам на developers.sber.ru (Личное пространство → GigaChat API → «Получить
ключ»). По ключу берётся токен на 30 минут, им подписываются запросы к модели. Серверы подписаны сертификатом
Минцифры: доверяем ему только здесь, через свой SSL-контекст, в систему ничего не ставим.
"""

import json
import ssl
import time
import urllib.error
import urllib.request
import uuid

from .resources import asset

OAUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
API_URL = "https://api.giga.chat/v1"  # новый адрес с 17.07.2026; старый gigachat.devices.sberbank.ru выводят
SCOPE = "GIGACHAT_API_PERS"
KEY_NAME = "gigachat"
# Pro по умолчанию: на проверке Lite склеил два правила в одно неверное, Pro пересказал точно.
# 40 млн бесплатных токенов Pro — это порядка 13 тысяч конспектов.
MODELS = (("GigaChat-2-Pro", "Pro — точная, рекомендуем (40 млн бесплатных токенов)"),
          ("GigaChat-2", "Lite — быстрая, но чаще ошибается (250 млн бесплатных токенов)"),
          ("GigaChat-2-Max", "Max — самая сильная (25 млн бесплатных токенов)"))
TIMEOUT = 60.0


class GigaChatError(Exception):
    pass


def _ssl() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.load_verify_locations(cafile=str(asset("certs", "russian_trusted_ca.pem")))
    return ctx


def normalize_key(key: str) -> str:
    """Человек может вставить ключ как есть, с «Basic » в начале или в кавычках."""
    key = key.strip().strip('"').strip("'").strip()
    if key.lower().startswith("basic "):
        key = key[6:].strip()
    return key


def _request(url: str, data: bytes | None, headers: dict, timeout: float = TIMEOUT) -> dict:
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl()) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")[:300]
        except OSError:
            pass
        if e.code in (400, 401, 403) and "oauth" in url:
            raise GigaChatError("Ключ не подошёл. Скопируйте «Ключ авторизации» заново на developers.sber.ru.") from None
        if e.code == 401:
            raise GigaChatError("Доступ отклонён: ключ устарел. Сохраните ключ ещё раз.") from None
        if e.code == 402:
            raise GigaChatError("Закончились токены GigaChat. Проверьте баланс на developers.sber.ru.") from None
        if e.code == 429:
            raise GigaChatError("Слишком много запросов подряд. Подождите минуту и попробуйте ещё раз.") from None
        if e.code == 413:
            raise GigaChatError("Материал слишком большой для одного запроса. Сократите исходник.") from None
        raise GigaChatError(f"GigaChat ответил ошибкой {e.code}. {body}".strip()) from None
    except ssl.SSLError as e:
        raise GigaChatError(f"Не удалось проверить сертификат GigaChat: {e}") from None
    except (OSError, ValueError) as e:
        raise GigaChatError("Нет связи с GigaChat. Проверьте интернет.") from e


class GigaChat:
    def __init__(self, auth_key: str, model: str = "GigaChat-2-Pro"):
        self.auth_key = normalize_key(auth_key)
        self.model = model
        self._token = ""
        self._expires = 0.0

    def token(self) -> str:
        if self._token and time.time() < self._expires - 60:  # с запасом: токен живёт 30 минут
            return self._token
        data = _request(OAUTH_URL, f"scope={SCOPE}".encode(),
                        {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json",
                         "RqUID": str(uuid.uuid4()), "Authorization": f"Basic {self.auth_key}"}, timeout=20)
        self._token = data.get("access_token", "")
        if not self._token:
            raise GigaChatError("GigaChat не выдал токен. Проверьте ключ.")
        exp = float(data.get("expires_at", 0) or 0)
        self._expires = exp / 1000 if exp > 1e12 else (exp or time.time() + 1800)  # бывает в мс
        return self._token

    def check(self) -> list[str]:
        """Проверка ключа: получить токен и список моделей."""
        data = _request(f"{API_URL}/models", None,
                        {"Accept": "application/json", "Authorization": f"Bearer {self.token()}"}, timeout=20)
        return [m.get("id", "") for m in data.get("data", [])]

    def complete(self, prompt: str, temperature: float = 0.3) -> str:
        body = json.dumps({"model": self.model, "temperature": temperature,
                           "messages": [{"role": "user", "content": prompt}]}, ensure_ascii=False).encode("utf-8")
        data = _request(f"{API_URL}/chat/completions", body,
                        {"Content-Type": "application/json", "Accept": "application/json",
                         "Authorization": f"Bearer {self.token()}"})
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise GigaChatError("GigaChat прислал пустой ответ. Попробуйте ещё раз.") from None
