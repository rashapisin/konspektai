# Создаёт конфигурацию Windows Sandbox для проверки установщика с путями этого компьютера.
#   powershell -ExecutionPolicy Bypass -File packaging\sandbox\make_wsb.ps1
# Затем двойной щелчок по packaging\sandbox\KonspektAI_проверка.wsb (файл в git не попадает).
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$sb = "C:\Users\WDAGUtilityAccount\Desktop"
New-Item -ItemType Directory -Force (Join-Path $PSScriptRoot "out") | Out-Null
$xml = @"
<?xml version="1.0" encoding="utf-8"?>
<!-- Чистая Windows для проверки установщика KonspektAI: без интернета, без видеокарты. -->
<Configuration>
  <Networking>Disable</Networking>
  <VGpu>Disable</VGpu>
  <MappedFolders>
    <MappedFolder><HostFolder>$root\build\installer</HostFolder><SandboxFolder>$sb\installer</SandboxFolder><ReadOnly>true</ReadOnly></MappedFolder>
    <MappedFolder><HostFolder>$PSScriptRoot</HostFolder><SandboxFolder>$sb\check</SandboxFolder><ReadOnly>true</ReadOnly></MappedFolder>
    <MappedFolder><HostFolder>$PSScriptRoot\out</HostFolder><SandboxFolder>$sb\out</SandboxFolder><ReadOnly>false</ReadOnly></MappedFolder>
  </MappedFolders>
  <LogonCommand>
    <Command>powershell.exe -NoProfile -ExecutionPolicy Bypass -File $sb\check\check.ps1</Command>
  </LogonCommand>
</Configuration>
"@
$out = Join-Path $PSScriptRoot "KonspektAI_проверка.wsb"
[IO.File]::WriteAllText($out, $xml, (New-Object Text.UTF8Encoding $false))
Write-Host "Готово: $out"
