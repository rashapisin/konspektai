# Выполняется ВНУТРИ Windows Sandbox: чистая Windows, без Python, без интернета.
# Ставит KonspektAI установщиком без окна, проверяет программу, удаляет её и проверяет, что всё убрано.
# Отчёт пишется в общую папку out (видна на основном компьютере). В конце открывается окно установщика.
$ErrorActionPreference = "Continue"
$desk = "C:\Users\WDAGUtilityAccount\Desktop"
# Копия на диск песочницы: иначе песочница держит файл на основном компьютере и мешает пересборке
$orig = Get-ChildItem (Join-Path $desk "installer") -Filter "KonspektAI-Setup-*.exe" | Select-Object -First 1
Copy-Item $orig.FullName $env:TEMP
$setup = Get-Item (Join-Path $env:TEMP $orig.Name)
$dir = Join-Path $env:LOCALAPPDATA "Programs\KonspektAI"
$app = Join-Path $dir "KonspektAI.exe"
$out = Join-Path $desk "out"
$report = Join-Path $out "отчёт.txt"
$key = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\KonspektAI"
$lnkDesk = Join-Path ([Environment]::GetFolderPath("Desktop")) "KonspektAI.lnk"
$lnkStart = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\KonspektAI.lnk"
function yes($b) { if ($b) { "да" } else { "НЕТ" } }
$lines = @()
$lines += "Проверка установщика KonspektAI в Windows Sandbox: $(Get-Date -Format 'dd.MM.yyyy HH:mm:ss')"
$lines += "Windows: $((Get-CimInstance Win32_OperatingSystem).Caption) $((Get-CimInstance Win32_OperatingSystem).Version)"
$lines += "Python в системе: $(if (Get-Command python -ErrorAction SilentlyContinue) { 'есть (проверка нечистая!)' } else { 'нет' })"
$lines += "Установщик: $($setup.Name), $([int]($setup.Length/1MB)) МБ"

# 1. Установка без окна
$sw = [Diagnostics.Stopwatch]::StartNew()
$p = Start-Process -FilePath $setup.FullName -ArgumentList "--silent" -PassThru
$p.WaitForExit(300000) | Out-Null
$lines += "УСТАНОВКА: код $($p.ExitCode), $([math]::Round($sw.Elapsed.TotalSeconds,1)) с"
$lines += "  программа на месте: $(yes (Test-Path $app)); ярлык на рабочем столе: $(yes (Test-Path $lnkDesk)); в «Пуске»: $(yes (Test-Path $lnkStart))"
$lines += "  в «Установленных приложениях»: $(yes (Test-Path $key)); Uninstall.exe: $(yes (Test-Path (Join-Path $dir 'Uninstall.exe')))"
$lines += "  связь .konspekt: $(yes (Test-Path 'HKCU:\Software\Classes\.konspekt'))"

# 2. Самопроверка установленной программы
$st = Join-Path $out "selftest"
$sw = [Diagnostics.Stopwatch]::StartNew()
$p = Start-Process -FilePath $app -ArgumentList "--selftest", $st -PassThru
if (-not $p.WaitForExit(180000)) { $p.Kill(); $lines += "САМОПРОВЕРКА: зависла" }
else {
    $lines += "САМОПРОВЕРКА: код $($p.ExitCode), $([math]::Round($sw.Elapsed.TotalSeconds,1)) с"
    $lines += "  " + ((Get-Content (Join-Path $st "selftest.txt") -Raw -ErrorAction SilentlyContinue) -replace "`r?`n", " | ")
}

# 3. Окно программы через ярлык
$g = Start-Process -FilePath $lnkDesk -PassThru -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1
$proc = $null; $title = ""
for ($i = 0; $i -lt 60 -and -not $title; $i++) {
    Start-Sleep -Milliseconds 500
    $proc = Get-Process KonspektAI -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle } | Select-Object -First 1
    if ($proc) { $title = $proc.MainWindowTitle }
}
$lines += if ($title) { "ОКНО через ярлык: открылось, заголовок «$title»" } else { "ОКНО через ярлык: НЕ появилось за 30 с" }
Get-Process KonspektAI -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 1

# 4. Удаление без окна
$u = Start-Process -FilePath (Join-Path $dir "Uninstall.exe") -ArgumentList "--uninstall", $dir, "--silent" -PassThru
$u.WaitForExit(120000) | Out-Null
# Uninstall.exe копирует себя во временную папку и удаляет оттуда — ждём копию
for ($i = 0; $i -lt 240 -and (Get-Process "KonspektAI-uninstall" -ErrorAction SilentlyContinue); $i++) { Start-Sleep -Milliseconds 500 }
$lines += "УДАЛЕНИЕ: код запуска $($u.ExitCode)"
$lines += "  папка убрана: $(yes (-not (Test-Path $dir))); ярлыки убраны: $(yes (-not (Test-Path $lnkDesk) -and -not (Test-Path $lnkStart)))"
$lines += "  запись убрана: $(yes (-not (Test-Path $key))); связь .konspekt убрана: $(yes (-not (Test-Path 'HKCU:\Software\Classes\.konspekt')))"
$lines += "Дальше открыт обычный установщик — можно пройти установку руками."
$lines | Out-File -FilePath $report -Encoding utf8
Start-Process -FilePath $setup.FullName
