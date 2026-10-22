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
        raise UpdateError(f"GitHub ответил ошибкой {e.code}") from None
    except (OSError, ValueError) as e:
        raise UpdateError("Нет связи с GitHub. Проверьте интернет.") from e
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
