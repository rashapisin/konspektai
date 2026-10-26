"""Обновления: разбор ответа GitHub, сравнение версий, загрузка — без настоящего интернета."""

import io
import json

import pytest

from stv import updater


class _Resp(io.BytesIO):
    def __init__(self, data: bytes):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def _fake_github(monkeypatch, release: dict, files: dict | None = None):
    def get(url, timeout):
        if url.startswith("https://api.github.com/"):
            return _Resp(json.dumps(release).encode())
        return _Resp(files[url])
    monkeypatch.setattr(updater, "_get", get)
    monkeypatch.setenv("KONSPEKTAI_REPO", "someone/konspektai")


def test_versions():
    assert updater.parse_version("v1.0.0") == (1, 0, 0)
    assert updater.parse_version("1.2") == (1, 2)
    assert updater.parse_version("1.0.0-beta") == (1, 0, 0)
    assert updater.parse_version("1.10.0") > updater.parse_version("1.9.9")


def test_latest_release_and_download(monkeypatch, tmp_path):
    url = "https://github.com/someone/konspektai/releases/download/v9.0.0/KonspektAI-Setup-9.0.0.exe"
    _fake_github(monkeypatch, {"tag_name": "v9.0.0", "html_url": "https://github.com/x", "body": "Новое",
                               "assets": [{"name": "README.txt", "browser_download_url": "https://github.com/r"},
                                          {"name": "KonspektAI-Setup-9.0.0.exe", "browser_download_url": url,
                                           "size": 5}]},
                 {url: b"MZ123"})
    monkeypatch.setattr(updater.tempfile, "gettempdir", lambda: str(tmp_path))
    rel = updater.latest()
    assert rel.version == "9.0.0" and rel.url == url and updater.is_newer(rel)
    seen = []
    path = updater.download(rel, lambda a, b: seen.append((a, b)))
    assert path.read_bytes() == b"MZ123" and seen[-1] == (5, 5)


def test_foreign_download_link_is_ignored(monkeypatch):
    _fake_github(monkeypatch, {"tag_name": "v9.0.0", "assets": [
        {"name": "KonspektAI-Setup-9.0.0.exe", "browser_download_url": "https://evil.example/setup.exe"}]})
    assert updater.latest() is None


def test_older_release_is_not_offered(monkeypatch):
    _fake_github(monkeypatch, {"tag_name": "v0.0.1", "assets": [
        {"name": "KonspektAI-Setup-0.0.1.exe", "browser_download_url": "https://github.com/a/b.exe"}]})
    assert not updater.is_newer(updater.latest())


def test_disabled_without_repo(monkeypatch):
    monkeypatch.delenv("KONSPEKTAI_REPO", raising=False)
    monkeypatch.setattr(updater, "GITHUB_REPO", "")
    assert not updater.enabled() and updater.latest() is None


def test_no_network(monkeypatch):
    def get(url, timeout):
        raise OSError("нет сети")
    monkeypatch.setattr(updater, "_get", get)
    monkeypatch.setenv("KONSPEKTAI_REPO", "someone/konspektai")
    with pytest.raises(updater.UpdateError):
        updater.latest()


def test_portable_keeps_data_next_to_exe(tmp_path, monkeypatch):
    import sys
    from stv import brand
    from stv.app import project
    exe = tmp_path / "KonspektAI" / "KonspektAI.exe"
    exe.parent.mkdir()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    assert brand.portable_root() is None  # без метки — обычная установленная программа
    (exe.parent / brand.PORTABLE_MARK).write_text("x", encoding="utf-8")
    assert brand.data_dir() == exe.parent / "Данные" / "Настройки"
    assert project.documents_dir() == exe.parent / "Данные" / "Тетради"


def test_network_failure_is_explained(monkeypatch):
    """На рабочем компьютере браузер ходит через прокси, а программа напрямую: вместо «нет связи» — причина
    и совет скачать в браузере."""
    import socket
    import ssl
    import urllib.error

    import pytest
    for reason, words in ((ssl.SSLCertVerificationError(1, "CERTIFICATE_VERIFY_FAILED"), "подменяет"),
                          (socket.gaierror(11001, "getaddrinfo failed"), "github.com"),
                          (TimeoutError("timed out"), "прокси"),
                          (ConnectionResetError(10054, "reset"), "оборвала")):
        def get(url, timeout, r=reason):
            raise urllib.error.URLError(r)
        monkeypatch.setattr(updater, "_get", get)
        with pytest.raises(updater.UpdateError, match=words) as e:
            updater.latest()
        assert "в браузере" in str(e.value)
    assert updater.releases_page().endswith("/releases/latest")
