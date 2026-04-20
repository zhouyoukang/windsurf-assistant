$ErrorActionPreference = 'Stop'
$dir = 'e:\道\道生一\一生二\github项目同步\windsurf-assistant\bundled-origin'
# 把 anchor.py 同步到 锚.py (中文名 fallback)
Copy-Item "$dir\anchor.py" "$dir\锚.py" -Force
# 重算 VERSION
$lines = @('17.34.0')
$names = @('源.js','锚.py','anchor.py','_dao_81.txt')
foreach ($n in $names) {
    $p = Join-Path $dir $n
    if (Test-Path $p) {
        $bytes = [System.IO.File]::ReadAllBytes($p)
        $sha = [System.Security.Cryptography.SHA256]::Create().ComputeHash($bytes)
        $hex16 = ([BitConverter]::ToString($sha) -replace '-','').Substring(0,16)
        $lines += "$n`tsha256-16=$hex16  size=$($bytes.Length)"
    }
}
$lines += ''
$out = ($lines -join "`n")
[System.IO.File]::WriteAllText("$dir\VERSION", $out, (New-Object System.Text.UTF8Encoding $false))
Write-Host '=== VERSION ==='
Get-Content "$dir\VERSION"
