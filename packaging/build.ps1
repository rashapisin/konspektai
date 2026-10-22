# Сборка KonspektAI: папка build\dist\KonspektAI (KonspektAI.exe + _internal) и установщик
# build\installer\KonspektAI-Setup-<версия>.exe. Запуск из корня проекта:
#   powershell -ExecutionPolicy Bypass -File packaging\build.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
& .\.venv\Scripts\python.exe packaging\make_icon.py
& .\.venv\Scripts\pyinstaller.exe packaging\launcher.py `
    --name KonspektAI --onedir --windowed --noconfirm --clean `
    --icon "$root\assets\brand\icon.ico" `
    --paths "$root" `
    --distpath build\dist --workpath build\work --specpath build `
    --add-data "$root\assets;assets" `
    --collect-data pyphen --collect-data docx --collect-data rapidocr --collect-submodules rapidocr `
    --exclude-module tkinter --exclude-module unittest --exclude-module pytest
if ($LASTEXITCODE -ne 0) { throw "PyInstaller не собрал программу" }
# Лишнее для программы (самопроверка ниже и песочница подтверждают, что без этого всё работает):
$i = "build\dist\KonspektAI\_internal"
foreach ($f in @("$i\cv2\opencv_videoio_ffmpeg*.dll",            # видео в OpenCV
                 "$i\PySide6\opengl32sw.dll",                    # программный OpenGL: окна рисуются без него
                 "$i\rapidocr\models\*.onnx",                    # свои модели RapidOCR: русские — в assets\ocr
                 "$i\PySide6\translations",                      # переводы Qt не загружаются
                 "$i\PySide6\Qt6Network.dll", "$i\PySide6\QtNetwork.pyd",   # сеть Qt не нужна: запросы — urllib
                 "$i\PySide6\plugins\tls", "$i\PySide6\plugins\networkinformation",
                 "$i\libcrypto-3-x64.dll", "$i\libssl-3-x64.dll", # OpenSSL из Git для сети Qt; Python — свой
                 "$i\PySide6\plugins\platforms\qdirect2d.dll", "$i\PySide6\plugins\platforms\qminimal.dll",
                 "$i\PySide6\plugins\generic",                   # сенсорные панели
                 "$i\PySide6\plugins\imageformats\qicns.dll", "$i\PySide6\plugins\imageformats\qtga.dll",
                 "$i\PySide6\plugins\imageformats\qwbmp.dll",
                 "$i\PIL\_avif*.pyd", "$i\PIL\_imagingtk*.pyd")) {   # AVIF и Tk в Pillow не используются
    Remove-Item $f -Recurse -Force -ErrorAction SilentlyContinue
}
# переносы нужны только русские: из словарей на десятки языков оставляем один
Get-ChildItem "$i\pyphen\dictionaries" -File | Where-Object { $_.Name -ne "hyph_ru_RU.dic" } |
    Remove-Item -Force -ErrorAction SilentlyContinue
"Размер программы: {0:N0} МБ" -f ((Get-ChildItem "build\dist\KonspektAI" -Recurse -File | Measure-Object Length -Sum).Sum / 1MB)
# Самопроверка собранной программы: без Python, без окна. Не больше минуты, чтобы сборка не зависала.
$out = Join-Path $env:TEMP "konspektai_selftest"
Remove-Item -Recurse -Force $out -ErrorAction SilentlyContinue
$p = Start-Process -FilePath "build\dist\KonspektAI\KonspektAI.exe" -ArgumentList "--selftest", $out -PassThru
if (-not $p.WaitForExit(60000)) { $p.Kill(); throw "Самопроверка EXE зависла" }
if ($p.ExitCode -ne 0) { throw ("Самопроверка EXE не прошла:`n" + (Get-Content "$out\selftest.txt" -Raw)) }
Write-Host "Программа собрана: build\dist\KonspektAI\KonspektAI.exe, самопроверка пройдена"
& .\.venv\Scripts\python.exe packaging\installer\build_installer.py
if ($LASTEXITCODE -ne 0) { throw "Установщик не собран" }
