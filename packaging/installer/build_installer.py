r"""Сборка установщика: build\installer\KonspektAI-Setup-<версия>.exe.

1. PyInstaller собирает маленький EXE окна установки (onefile, только Qt Widgets и SVG).
2. Готовая программа build\dist\KonspektAI упаковывается в zip (LZMA); Uninstall.exe при установке
   вырезается из начала самого установщика — его размер записан в архиве.
3. Установщик = EXE окна + zip, дописанный в конец файла. Python читает такой zip как обычный архив,
   а загрузчик PyInstaller ищет свои данные с конца файла и дописанный хвост ему не мешает
   (проверено на PyInstaller 6.22).
"""

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
from stv.brand import APP_NAME, PORTABLE_MARK, VERSION  # noqa: E402

PORTABLE_README = f"""Переносная версия {APP_NAME} {VERSION} — без установки.

Запуск: {APP_NAME}.exe. Права администратора не нужны.
Настройки, калибровки принтеров, почерки и тетради хранятся рядом, в папке «Данные»:
можно носить на флешке, на компьютере ничего не остаётся.

Обновление: скачайте новый ZIP со страницы релизов и распакуйте поверх — папка «Данные» сохранится.
Этот файл не удаляйте: по нему программа понимает, что она переносная.
"""

BUILD = ROOT / "build"
APP = BUILD / "dist" / APP_NAME
OUT = BUILD / "installer"


def build_stub() -> Path:
    py = Path(sys.executable).parent / "pyinstaller.exe"
    data = [("assets/brand", "assets/brand"), ("assets/fonts/inter", "assets/fonts/inter"),
            ("assets/fonts/caveat", "assets/fonts/caveat"), ("assets/ui/icons", "assets/ui/icons")]
    cmd = [str(py), str(ROOT / "packaging" / "installer" / "setup.py"), "--name", f"{APP_NAME}-Setup-stub",
           "--onefile", "--windowed", "--noconfirm", "--clean", "--icon", str(ROOT / "assets" / "brand" / "icon.ico"),
           "--paths", str(ROOT), "--distpath", str(OUT / "stub"), "--workpath", str(BUILD / "work-installer"),
           "--specpath", str(BUILD), "--log-level", "WARN"]
    for src, dst in data:
        cmd += ["--add-data", f"{ROOT / src};{dst}"]
    for mod in ("tkinter", "unittest", "pytest", "numpy", "cv2", "PySide6.QtNetwork", "PySide6.QtPdf",
                "PySide6.QtPrintSupport", "PySide6.QtOpenGL", "PySide6.QtQml"):
        cmd += ["--exclude-module", mod]
    subprocess.run(cmd, check=True)
    return OUT / "stub" / f"{APP_NAME}-Setup-stub.exe"


def main():
    if not (APP / f"{APP_NAME}.exe").exists():
        sys.exit(f"Сначала соберите программу: нет {APP / (APP_NAME + '.exe')}")
    OUT.mkdir(parents=True, exist_ok=True)
    stub = build_stub()
    payload = OUT / "payload.zip"
    print("Упаковываю программу…")
    with zipfile.ZipFile(payload, "w", zipfile.ZIP_LZMA) as z:  # плотнее deflate; распаковывает установщик
        for f in sorted(APP.rglob("*")):
            if f.is_file():
                z.write(f, "app/" + f.relative_to(APP).as_posix())
        z.writestr("stub_size", str(stub.stat().st_size))  # Uninstall.exe вырезается из самого установщика
    setup = OUT / f"{APP_NAME}-Setup-{VERSION}.exe"
    with open(setup, "wb") as out:
        for part in (stub, payload):
            with open(part, "rb") as src:
                shutil.copyfileobj(src, out, 1 << 20)
    payload.unlink()
    print(f"Установщик готов: {setup} ({setup.stat().st_size / 1e6:.0f} МБ)")
    portable = OUT / f"{APP_NAME}-{VERSION}-portable.zip"
    print("Упаковываю переносную версию…")
    with zipfile.ZipFile(portable, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:  # обычный ZIP: открывается Проводником
        for f in sorted(APP.rglob("*")):
            if f.is_file():
                z.write(f, f"{APP_NAME}/" + f.relative_to(APP).as_posix())
        z.writestr(f"{APP_NAME}/{PORTABLE_MARK}", PORTABLE_README)
    print(f"Переносная версия готова: {portable} ({portable.stat().st_size / 1e6:.0f} МБ)")


if __name__ == "__main__":
    main()
