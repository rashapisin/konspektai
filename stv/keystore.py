"""Ключи API на этом компьютере: шифруются средствами Windows (DPAPI) для текущего пользователя.

Расшифровать файл может только та же учётная запись на том же компьютере: скопированный файл бесполезен.
Ключ не попадает ни в EXE, ни в тетради, ни в настройки, которые можно переслать.
"""

import base64
import ctypes
import ctypes.wintypes as wt

from .brand import data_dir


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> _Blob:
    buf = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))


def _out(b: _Blob) -> bytes:
    try:
        return ctypes.string_at(b.pbData, b.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(b.pbData)


def protect(data: bytes) -> bytes:
    out = _Blob()
    if not ctypes.windll.crypt32.CryptProtectData(ctypes.byref(_blob(data)), "KonspektAI", None, None, None, 0,
                                                  ctypes.byref(out)):
        raise OSError("Windows не смогла зашифровать ключ")
    return _out(out)


def unprotect(data: bytes) -> bytes:
    out = _Blob()
    if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(_blob(data)), None, None, None, None, 0,
                                                    ctypes.byref(out)):
        raise OSError("ключ зашифрован другой учётной записью Windows")
    return _out(out)


def _path(name: str):
    return data_dir() / f"{name}.key"


def save(name: str, secret: str):
    _path(name).write_bytes(base64.b64encode(protect(secret.encode("utf-8"))))


def load(name: str) -> str | None:
    try:
        return unprotect(base64.b64decode(_path(name).read_bytes())).decode("utf-8")
    except (OSError, ValueError):
        return None


def delete(name: str):
    _path(name).unlink(missing_ok=True)
