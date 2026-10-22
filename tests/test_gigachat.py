"""GigaChat без настоящего интернета: токен, ответ модели, ошибки, хранение ключа."""

import io
import json
import time
import urllib.error

import pytest

from stv import gigachat, keystore
from stv.gigachat import GigaChat, GigaChatError, normalize_key


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def _server(monkeypatch, answer="Конспект: главное по теме.", fail=None):
    calls = []

    def urlopen(req, timeout=None, context=None):
        calls.append(req)
        if fail and fail[0] in req.full_url:
            raise urllib.error.HTTPError(req.full_url, fail[1], "err", {}, io.BytesIO(b"{}"))
        if req.full_url.endswith("/oauth"):
            assert req.get_header("Authorization") == "Basic S0VZ"
            assert req.data == b"scope=GIGACHAT_API_PERS" and req.get_header("Rquid")
            return _Resp(json.dumps({"access_token": "TOKEN",
                                     "expires_at": int((time.time() + 1800) * 1000)}).encode())
        assert req.get_header("Authorization") == "Bearer TOKEN"
        if req.full_url.endswith("/models"):
            return _Resp(json.dumps({"data": [{"id": "GigaChat-2"}, {"id": "GigaChat-2-Pro"}]}).encode())
        body = json.loads(req.data.decode("utf-8"))
        assert body["model"] == "GigaChat-2-Pro" and body["messages"][0]["role"] == "user"
        return _Resp(json.dumps({"choices": [{"message": {"role": "assistant", "content": answer}}]}).encode())

    monkeypatch.setattr(gigachat.urllib.request, "urlopen", urlopen)
    return calls


def test_key_is_accepted_in_any_form():
    assert normalize_key("  Basic S0VZ ") == "S0VZ"
    assert normalize_key('"S0VZ"') == "S0VZ"


def test_token_is_reused_and_answer_returned(monkeypatch):
    calls = _server(monkeypatch)
    gc = GigaChat("S0VZ")
    assert gc.check() == ["GigaChat-2", "GigaChat-2-Pro"]
    assert gc.complete("Сожми материал") == "Конспект: главное по теме."
    assert sum(c.full_url.endswith("/oauth") for c in calls) == 1  # токен живёт 30 минут, второй раз не просим
    assert all(c.full_url.startswith(("https://ngw.devices.sberbank.ru:9443", "https://api.giga.chat/v1"))
               for c in calls)


@pytest.mark.parametrize("where,code,words", [
    ("/oauth", 401, "Ключ не подошёл"),
    ("/chat/completions", 402, "Закончились токены"),
    ("/chat/completions", 429, "Подождите минуту"),
])
def test_errors_are_explained(monkeypatch, where, code, words):
    _server(monkeypatch, fail=(where, code))
    with pytest.raises(GigaChatError, match=words):
        GigaChat("S0VZ").complete("x")


def test_no_network(monkeypatch):
    def urlopen(req, timeout=None, context=None):
        raise OSError("сеть недоступна")
    monkeypatch.setattr(gigachat.urllib.request, "urlopen", urlopen)
    with pytest.raises(GigaChatError, match="интернет"):
        GigaChat("S0VZ").check()


def test_ssl_context_trusts_bundled_ca():
    ctx = gigachat._ssl()
    names = [dict(x[0] for x in c["subject"]).get("commonName") for c in ctx.get_ca_certs()]
    assert "Russian Trusted Root CA" in names and "Russian Trusted Sub CA" in names


def test_key_is_encrypted_on_disk(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    keystore.save("test", "секретный-ключ")
    raw = (tmp_path / "KonspektAI" / "test.key").read_bytes()
    assert "секретный".encode() not in raw and b"secret" not in raw
    assert keystore.load("test") == "секретный-ключ"
    keystore.delete("test")
    assert keystore.load("test") is None


def test_any_openai_compatible_service(monkeypatch):
    from stv import llm
    seen = []

    def urlopen(req, timeout=None, context=None):
        seen.append(req)
        assert req.get_header("Authorization") == "Bearer sk-test"
        if req.full_url.endswith("/models"):
            return _Resp(json.dumps({"data": [{"id": "deepseek-chat"}, {"id": "deepseek-reasoner"}]}).encode())
        body = json.loads(req.data.decode("utf-8"))
        assert body["model"] == "deepseek-chat"
        return _Resp(json.dumps({"choices": [{"message": {"content": "Готовый конспект"}}]}).encode())
    monkeypatch.setattr(llm.urllib.request, "urlopen", urlopen)
    c = llm.OpenAICompatible("https://api.deepseek.com/v1/", "sk-test", "deepseek-chat")
    assert c.check() == ["deepseek-chat", "deepseek-reasoner"]
    assert c.complete("Сожми") == "Готовый конспект"
    assert seen[-1].full_url == "https://api.deepseek.com/v1/chat/completions"


def test_service_errors_are_explained(monkeypatch):
    from stv import llm

    def urlopen(req, timeout=None, context=None):
        raise urllib.error.HTTPError(req.full_url, 401, "x", {}, io.BytesIO(b""))
    monkeypatch.setattr(llm.urllib.request, "urlopen", urlopen)
    with pytest.raises(llm.LLMError, match="Ключ не подошёл"):
        llm.OpenAICompatible("https://x/v1", "bad", "m").complete("x")


def test_topic_line_is_dropped():
    from stv.ai import clean_answer
    assert clean_answer("Первичные средства.\n\n- огнетушители", "Первичные средства") == "- огнетушители"
