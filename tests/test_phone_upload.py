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
