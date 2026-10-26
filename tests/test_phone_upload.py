"""Фото с телефона: страница по ключу, приём JPEG, отказ без ключа и не-картинкам. Локально, без сети."""

import urllib.error
import urllib.request

import pytest

from stv.phone_upload import PhoneUpload, qr_png

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 2000


@pytest.fixture
def server():
    got = []
    s = PhoneUpload(got.append, "Калибровка", "Снимите лист", ip="127.0.0.1")
    s.start()
    yield s, got
    s.stop()


def _post(url, data):
    req = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": "image/jpeg"})
    return urllib.request.urlopen(req, timeout=5)


def test_page_and_upload(server):
    s, got = server
    page = urllib.request.urlopen(s.url, timeout=5).read().decode("utf-8")
    assert "Калибровка" in page and 'capture="environment"' in page
    assert _post(s.url + "upload", JPEG).status == 200
    assert len(got) == 1 and open(got[0], "rb").read() == JPEG


def test_wrong_token_and_not_image_are_refused(server):
    s, got = server
    base = s.url.rsplit("/", 2)[0]
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(base + "/guessed/", timeout=5)
    assert e.value.code == 404
    with pytest.raises(urllib.error.HTTPError) as e:
        _post(s.url + "upload", b"<html>not a photo</html>")
    assert e.value.code == 415 and not got


def test_qr_is_png():
    assert qr_png("http://192.168.1.5:1234/abc/")[:8] == b"\x89PNG\r\n\x1a\n"


def test_live_state_follows_the_program():
    """Калибровка: телефон видит, что фото распознаётся, итог и кнопку «Дальше» — без нового QR-кода."""
    import json
    got, nexts = [], []
    s = PhoneUpload(got.append, "Калибровка", "Снимите лист", ip="127.0.0.1", live=True,
                    on_next=lambda: nexts.append(1))
    s.start()
    try:
        state = lambda: json.loads(urllib.request.urlopen(s.url + "state", timeout=5).read())  # noqa: E731
        assert state()["stage"] == "wait"
        assert _post(s.url + "upload", JPEG).status == 200
        assert state()["stage"] == "busy" and len(got) == 1
        s.set_state(stage="error", msg="Не нашёл лист на фото")
        st = state()
        assert st["stage"] == "error" and "лист" in st["msg"]
        assert _post(s.url + "upload", JPEG).status == 200  # переснять можно на той же странице
        s.set_state(stage="ok", msg="✓ Лист распознан", next=True)
        assert state()["next"] is True
        assert _post(s.url + "next", b"").status == 200 and nexts == [1]
        # текст состояния не может закрыть <script> страницы
        s.set_state(msg="</script><b>")
        assert "</script><b>" not in urllib.request.urlopen(s.url, timeout=5).read().decode("utf-8")
    finally:
        s.stop()
