"""Обновления из релизов GitHub: узнать последнюю версию, скачать установщик, запустить его.

Установщик запускается с --update: ждёт, пока программа закроется, ставит новую версию поверх старой
(тетради и настройки не трогает) и сам открывает программу снова.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .brand import APP_NAME, GITHUB_REPO, VERSION

API = "https://api.github.com/repos/{repo}/releases/latest"
TRUSTED = ("https://github.com/",)  # ссылки на файлы релизов GitHub; оттуда он сам перенаправит на своё хранилище


class UpdateError(Exception):
    pass


RELEASES = "https://github.com/{repo}/releases/latest"
PROXY_TEXT = ("Сеть пускает в интернет только через прокси с паролем (так бывает на работе) — программа так не умеет. "
              "Скачайте обновление в браузере.")


def network_reason(e: BaseException) -> str:
    """Почему не дошли до GitHub — понятными словами. На рабочих компьютерах браузер часто ходит через
    прокси или проверку соединений, а программа напрямую: тогда браузер работает, а программа — нет."""
    import socket
    import ssl
    r = getattr(e, "reason", e)
    if isinstance(r, ssl.SSLCertVerificationError) or "CERTIFICATE_VERIFY_FAILED" in str(r):
        return ("Сеть подменяет защищённое соединение с GitHub (проверка трафика на работе или антивирус), "
                "поэтому программа ему не доверяет. Скачайте обновление в браузере.")
    if isinstance(r, socket.gaierror):
        return ("Не удалось найти github.com: нет интернета или сеть закрывает GitHub. "
                "Если в браузере GitHub открывается — скачайте обновление там.")
    if isinstance(r, (TimeoutError, socket.timeout)) or "timed out" in str(r):
        return ("GitHub не ответил вовремя: на работе сеть часто пускает в интернет только браузер (через прокси). "
                "Скачайте обновление в браузере.")
    if isinstance(r, ConnectionError):
        return "Сеть оборвала соединение с GitHub (так бывает за рабочим прокси). Скачайте обновление в браузере."
    return f"Нет связи с GitHub ({r}). Скачайте обновление в браузере."


def releases_page() -> str:
    return RELEASES.format(repo=repo())


@dataclass
class Release:
    version: str
    url: str      # установщик
    size: int
    notes: str
    page: str     # страница релиза — «что нового»


def repo() -> str:
    return os.environ.get("KONSPEKTAI_REPO") or GITHUB_REPO


def enabled() -> bool:
    return bool(repo())


def parse_version(v: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", v.split("-")[0])
    return tuple(int(n) for n in nums[:3]) or (0,)


def _get(url: str, timeout: float):
    req = urllib.request.Request(url, headers={"User-Agent": f"{APP_NAME}/{VERSION}",
                                               "Accept": "application/vnd.github+json"})
    return urllib.request.urlopen(req, timeout=timeout)


def latest(timeout: float = 8.0) -> Release | None:
    """Последний релиз с установщиком или None, если релизов ещё нет."""
    if not enabled():
        return None
    try:
        with _get(API.format(repo=repo()), timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        if e.code == 407:
            raise UpdateError(PROXY_TEXT) from None
        if e.code == 403:
            raise UpdateError("GitHub временно не отвечает программе (лимит запросов или запрет в сети). "
                              "Скачайте обновление в браузере.") from None
        raise UpdateError(f"GitHub ответил ошибкой {e.code}") from None
    except (OSError, ValueError) as e:
        raise UpdateError(network_reason(e)) from e
    for a in data.get("assets", []):
        name, url = a.get("name", ""), a.get("browser_download_url", "")
        if name.lower().endswith(".exe") and "setup" in name.lower() and url.startswith(TRUSTED):
            return Release(data.get("tag_name", "").lstrip("vV"), url, int(a.get("size", 0)),
                           data.get("body") or "", data.get("html_url", ""))
    return None


def is_newer(rel: Release | None) -> bool:
    return rel is not None and parse_version(rel.version) > parse_version(VERSION)


def download(rel: Release, progress=None, cancelled=None) -> Path:
    """Скачать установщик во временную папку. progress(получено, всего); cancelled() → True — прервать."""
    dest = Path(tempfile.gettempdir()) / f"{APP_NAME}-Setup-{rel.version}.exe"
    part = dest.with_suffix(".part")
    try:
        with _get(rel.url, 30.0) as r, open(part, "wb") as out:
            total = int(r.headers.get("Content-Length") or rel.size or 0)
            got = 0
            while True:
                if cancelled and cancelled():
                    raise UpdateError("Загрузка отменена.")
                chunk = r.read(1 << 18)
                if not chunk:
                    break
                out.write(chunk)
                got += len(chunk)
                if progress:
                    progress(got, total)
        if total and got != total:
            raise UpdateError("Файл скачался не полностью. Попробуйте ещё раз.")
        part.replace(dest)
    except OSError as e:
        part.unlink(missing_ok=True)
        raise UpdateError("Не удалось скачать обновление. Проверьте интернет.") from e
    except UpdateError:
        part.unlink(missing_ok=True)
        raise
    return dest


def run_installer(path: Path):
    """Запустить установщик в режиме обновления; программа после этого должна закрыться сама."""
    if not getattr(sys, "frozen", False):
        raise UpdateError("Обновление ставится только в установленную программу, а не при запуске из исходников.")
    subprocess.Popen([str(path), "--update"], close_fds=True,
                     creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
