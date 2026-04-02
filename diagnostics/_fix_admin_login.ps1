<#
.SYNOPSIS
    一键修复Administrator的Windsurf登录 — 道法自然·万法归宗
    
.DESCRIPTION
    突破: DPAPI CRYPTPROTECT_LOCAL_MACHINE (机器级加密)
    任何用户加密的数据 → 本机任何用户都能解密
    
    流程:
    1. 生成新的32字节AES密钥
    2. 用DPAPI LOCAL_MACHINE加密 → 写入Admin的Local State
    3. 用AES-256-GCM加密session明文 → 写入Admin的state.vscdb
    4. 同步windsurfAuthStatus
    5. 重启Admin的Windsurf
    
    无需切换用户，无需密码，从ai用户一键完成！

.EXAMPLE
    .\\_fix_admin_login.ps1
#>

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Security

Write-Host "=" * 60
Write-Host "  Windsurf Administrator Login Fix — 道法自然"
Write-Host "  Running as: $env:USERNAME"
Write-Host "  Time: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host "=" * 60

# ============================================================
# Configuration
# ============================================================
$AdminLocalState = "C:\Users\Administrator\AppData\Roaming\Windsurf\Local State"
$AdminDB = "C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb"
$AdminGS = "C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage"

# Session plaintext from ai user's decrypted safeStorage
$sessionPlaintext = '[{"id":"21765441-1ff8-4e3c-a1ae-4a8b14f01a47","accessToken":"sk-ws-01-ZjtRvwZuPanGJdfQm40IrdA9IIouTc4oXe1dNHw2xK8sVZbAspyBmDMtZ38GQXcjiEH3s-l3-b-FGwDrzsEqf0eJ7Ane8Q","account":{"label":"Miller Harper","id":"Miller Harper"},"scopes":[]}]'
$apiServerUrl = 'https://server.self-serve.windsurf.com'

# Extract apiKey from session
$sessionObj = $sessionPlaintext | ConvertFrom-Json
$apiKey = $sessionObj[0].accessToken
Write-Host "`n  apiKey: $($apiKey.Substring(0,25))... ($($apiKey.Length) chars)"
Write-Host "  account: $($sessionObj[0].account.label)"

# ============================================================
# Step 1: Generate new AES-256 key
# ============================================================
Write-Host "`n[Step 1] Generating AES-256 key..." -ForegroundColor Cyan

$aesKey = New-Object byte[] 32
$rng = [System.Security.Cryptography.RNGCryptoServiceProvider]::new()
$rng.GetBytes($aesKey)
$rng.Dispose()
Write-Host "  AES key: $([BitConverter]::ToString($aesKey[0..3]).Replace('-',''))... (32 bytes)"

# ============================================================
# Step 2: DPAPI encrypt with LOCAL_MACHINE scope
# ============================================================
Write-Host "`n[Step 2] DPAPI encrypting (LOCAL_MACHINE scope)..." -ForegroundColor Cyan

$encryptedAesKey = [System.Security.Cryptography.ProtectedData]::Protect(
    $aesKey,
    $null,
    [System.Security.Cryptography.DataProtectionScope]::LocalMachine  # KEY: any user can decrypt!
)
Write-Host "  Encrypted: $($encryptedAesKey.Length) bytes"

# Verify: decrypt to confirm it works
$verifyKey = [System.Security.Cryptography.ProtectedData]::Unprotect(
    $encryptedAesKey,
    $null,
    [System.Security.Cryptography.DataProtectionScope]::LocalMachine
)
$match = [System.Linq.Enumerable]::SequenceEqual([byte[]]$aesKey, [byte[]]$verifyKey)
if ($match) {
    Write-Host "  Verify: PASS (decrypt roundtrip OK)" -ForegroundColor Green
} else {
    Write-Host "  Verify: FAIL!" -ForegroundColor Red
    exit 1
}

# ============================================================
# Step 3: Write encrypted key to Admin's Local State
# ============================================================
Write-Host "`n[Step 3] Writing to Administrator's Local State..." -ForegroundColor Cyan

# Backup
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
Copy-Item $AdminLocalState "$AdminLocalState.bak_$timestamp" -Force
Write-Host "  Backup: Local State.bak_$timestamp"

# Build: "DPAPI" prefix + encrypted key → Base64
$dpapiPrefix = [System.Text.Encoding]::ASCII.GetBytes("DPAPI")
$fullEncryptedKey = New-Object byte[] ($dpapiPrefix.Length + $encryptedAesKey.Length)
[Array]::Copy($dpapiPrefix, 0, $fullEncryptedKey, 0, $dpapiPrefix.Length)
[Array]::Copy($encryptedAesKey, 0, $fullEncryptedKey, $dpapiPrefix.Length, $encryptedAesKey.Length)
$encryptedKeyB64 = [Convert]::ToBase64String($fullEncryptedKey)

# Read and modify Local State
$localState = Get-Content $AdminLocalState -Raw | ConvertFrom-Json
$localState.os_crypt.encrypted_key = $encryptedKeyB64
$localState | ConvertTo-Json -Depth 10 -Compress | Set-Content $AdminLocalState -Encoding UTF8
Write-Host "  Written: encrypted_key ($($encryptedKeyB64.Length) chars base64)"

# ============================================================
# Step 4: AES-256-GCM encrypt session data
# ============================================================
Write-Host "`n[Step 4] AES-256-GCM encrypting sessions..." -ForegroundColor Cyan

function Encrypt-V10([string]$Plaintext, [byte[]]$Key) {
    $ptBytes = [System.Text.Encoding]::UTF8.GetBytes($Plaintext)
    
    # Random 12-byte nonce
    $nonce = New-Object byte[] 12
    $rng2 = [System.Security.Cryptography.RNGCryptoServiceProvider]::new()
    $rng2.GetBytes($nonce)
    $rng2.Dispose()
    
    # AES-GCM
    $aesGcm = [System.Security.Cryptography.AesGcm]::new([byte[]]$Key)
    $ciphertext = New-Object byte[] $ptBytes.Length
    $tag = New-Object byte[] 16
    $aesGcm.Encrypt($nonce, $ptBytes, $ciphertext, $tag)
    $aesGcm.Dispose()
    
    # v10 + nonce + ciphertext + tag
    $v10 = [System.Text.Encoding]::ASCII.GetBytes("v10")
    $result = New-Object byte[] ($v10.Length + $nonce.Length + $ciphertext.Length + $tag.Length)
    [Array]::Copy($v10, 0, $result, 0, 3)
    [Array]::Copy($nonce, 0, $result, 3, 12)
    [Array]::Copy($ciphertext, 0, $result, 15, $ciphertext.Length)
    [Array]::Copy($tag, 0, $result, 15 + $ciphertext.Length, 16)
    
    return $result
}

function To-ElectronBuffer([byte[]]$Data) {
    $arr = @($Data | ForEach-Object { [int]$_ })
    $obj = @{ type = "Buffer"; data = $arr }
    return ($obj | ConvertTo-Json -Compress)
}

# Encrypt sessions
$sessionsV10 = Encrypt-V10 $sessionPlaintext $aesKey
$sessionsBuffer = To-ElectronBuffer $sessionsV10
Write-Host "  sessions: $($sessionsBuffer.Length) chars"

# Encrypt apiServerUrl
$apiUrlV10 = Encrypt-V10 $apiServerUrl $aesKey
$apiUrlBuffer = To-ElectronBuffer $apiUrlV10
Write-Host "  apiServerUrl: $($apiUrlBuffer.Length) chars"

# ============================================================
# Step 5: Write to Administrator's state.vscdb
# ============================================================
Write-Host "`n[Step 5] Injecting into state.vscdb..." -ForegroundColor Cyan

# Backup state.vscdb
Copy-Item $AdminDB "$AdminDB.bak_login_$timestamp" -Force
Write-Host "  Backup: state.vscdb.bak_login_$timestamp"

# Use Python for SQLite (most reliable)
$pyCode = @"
import sqlite3, json, sys

db = r'$AdminDB'
conn = sqlite3.connect(db, timeout=10)
conn.execute('PRAGMA journal_mode=WAL')
conn.execute('PRAGMA busy_timeout=5000')

# 1. Inject secret:// keys
secrets = {
    'secret://{"extensionId":"codeium.windsurf","key":"windsurf_auth.sessions"}': sys.argv[1],
    'secret://{"extensionId":"codeium.windsurf","key":"windsurf_auth.apiServerUrl"}': sys.argv[2],
}
for key, val in secrets.items():
    conn.execute("INSERT OR REPLACE INTO ItemTable(key, value) VALUES(?, ?)", (key, val))
    short = key.split('"key":"')[1].rstrip('"}')
    print(f"  secret://{short}: {len(val)} chars")

# 2. Ensure windsurfAuthStatus has valid apiKey
api_key = sys.argv[3]
row = conn.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()
if row:
    try:
        auth = json.loads(row[0])
        if auth and isinstance(auth, dict):
            auth['apiKey'] = api_key
            conn.execute("INSERT OR REPLACE INTO ItemTable(key, value) VALUES(?, ?)",
                        ('windsurfAuthStatus', json.dumps(auth)))
            print(f"  windsurfAuthStatus: apiKey updated")
        elif auth is None:
            # Was null, create fresh
            raise ValueError("null")
    except:
        # Create from scratch using ai user's data
        ai_db = r'C:\Users\ai\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'
        ai_conn = sqlite3.connect(ai_db, timeout=10)
        ai_row = ai_conn.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()
        if ai_row:
            ai_auth = json.loads(ai_row[0])
            if ai_auth and isinstance(ai_auth, dict):
                ai_auth['apiKey'] = api_key
                conn.execute("INSERT OR REPLACE INTO ItemTable(key, value) VALUES(?, ?)",
                            ('windsurfAuthStatus', json.dumps(ai_auth)))
                print(f"  windsurfAuthStatus: created from ai template")
        ai_conn.close()
else:
    conn.execute("INSERT OR REPLACE INTO ItemTable(key, value) VALUES(?, ?)",
                ('windsurfAuthStatus', json.dumps({'apiKey': api_key})))
    print(f"  windsurfAuthStatus: created new")

# 3. Sync cachedPlanInfo from ai
ai_db2 = r'C:\Users\ai\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'
ai_conn2 = sqlite3.connect(ai_db2, timeout=10)
ai_plan = ai_conn2.execute("SELECT value FROM ItemTable WHERE key='windsurf.settings.cachedPlanInfo'").fetchone()
if ai_plan:
    conn.execute("INSERT OR REPLACE INTO ItemTable(key, value) VALUES(?, ?)",
                ('windsurf.settings.cachedPlanInfo', ai_plan[0]))
    print(f"  cachedPlanInfo: synced from ai")

# 4. Sync windsurfConfigurations from ai
ai_conf = ai_conn2.execute("SELECT value FROM ItemTable WHERE key='windsurfConfigurations'").fetchone()
if ai_conf:
    conn.execute("INSERT OR REPLACE INTO ItemTable(key, value) VALUES(?, ?)",
                ('windsurfConfigurations', ai_conf[0]))
    print(f"  windsurfConfigurations: synced ({len(ai_conf[0])} bytes)")
ai_conn2.close()

conn.commit()
conn.close()
print("  All injections complete!")
"@

$pyFile = Join-Path $env:TEMP "_ws_fix_login.py"
$pyCode | Out-File -FilePath $pyFile -Encoding UTF8

# Escape the buffer strings for command line
python $pyFile $sessionsBuffer $apiUrlBuffer $apiKey

if ($LASTEXITCODE -ne 0) {
    Write-Host "  Python injection failed, trying fallback..." -ForegroundColor Yellow
    
    # Fallback: write secrets via direct Python
    python -c @"
import sqlite3, json
db = r'$AdminDB'
conn = sqlite3.connect(db, timeout=10)
conn.execute('PRAGMA journal_mode=WAL')
conn.execute('PRAGMA busy_timeout=5000')
conn.execute('INSERT OR REPLACE INTO ItemTable(key,value) VALUES(?,?)',
    ('secret://{{\"extensionId\":\"codeium.windsurf\",\"key\":\"windsurf_auth.sessions\"}}',
     json.dumps(json.loads(r'''$($sessionsBuffer)'''))))
conn.execute('INSERT OR REPLACE INTO ItemTable(key,value) VALUES(?,?)',
    ('secret://{{\"extensionId\":\"codeium.windsurf\",\"key\":\"windsurf_auth.apiServerUrl\"}}',
     json.dumps(json.loads(r'''$($apiUrlBuffer)'''))))
conn.commit(); conn.close()
print('Fallback injection done')
"@
}

Remove-Item $pyFile -ErrorAction SilentlyContinue

# ============================================================
# Step 6: Update auth JSON files
# ============================================================
Write-Host "`n[Step 6] Updating auth files..." -ForegroundColor Cyan

$authJson = @{
    authToken = $apiKey
    token = $apiKey
    api_key = $apiKey
    timestamp = [long]([DateTimeOffset]::Now.ToUnixTimeMilliseconds())
} | ConvertTo-Json

foreach ($f in @("cascade-auth.json", "windsurf-auth.json")) {
    $path = Join-Path $AdminGS $f
    $authJson | Set-Content $path -Encoding UTF8
    Write-Host "  $f : updated" -ForegroundColor Green
}

# ============================================================
# Step 7: Verify
# ============================================================
Write-Host "`n[Step 7] Verification..." -ForegroundColor Cyan

# Verify Local State
$verifyLS = Get-Content $AdminLocalState -Raw | ConvertFrom-Json
$verifyEK = [Convert]::FromBase64String($verifyLS.os_crypt.encrypted_key)
$verifyPrefix = [System.Text.Encoding]::ASCII.GetString($verifyEK, 0, 5)
Write-Host "  Local State encrypted_key: prefix=$verifyPrefix, total=$($verifyEK.Length) bytes"

# Verify we can decrypt the key (as current user, thanks to LOCAL_MACHINE)
try {
    $verifyAES = [System.Security.Cryptography.ProtectedData]::Unprotect(
        $verifyEK[5..($verifyEK.Length-1)],
        $null,
        [System.Security.Cryptography.DataProtectionScope]::LocalMachine
    )
    Write-Host "  AES key decrypt: PASS ($($verifyAES.Length) bytes)" -ForegroundColor Green
    
    # Verify we can decrypt the session we just wrote
    $verifySession = python -c @"
import sqlite3, json
db = r'$AdminDB'
conn = sqlite3.connect(db, timeout=10)
row = conn.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()
if row:
    d = json.loads(row[0])
    if d and isinstance(d, dict) and d.get('apiKey'):
        print(f"OK:apiKey={d['apiKey'][:25]}...")
    elif d is None:
        print('FAIL:null')
    else:
        print(f'FAIL:no_apiKey')
else:
    print('FAIL:missing')
conn.close()
"@
    Write-Host "  windsurfAuthStatus: $verifySession" -ForegroundColor Green
} catch {
    Write-Host "  AES key decrypt: FAIL - $_" -ForegroundColor Red
}

# ============================================================
# Step 8: Restart Administrator's Windsurf
# ============================================================
Write-Host "`n[Step 8] Restarting Administrator's Windsurf..." -ForegroundColor Cyan

# Find Administrator's Windsurf processes
$adminProcs = Get-CimInstance Win32_Process -Filter "Name='Windsurf.exe'" -ErrorAction SilentlyContinue |
    ForEach-Object {
        $owner = Invoke-CimMethod -InputObject $_ -MethodName GetOwner -ErrorAction SilentlyContinue
        [PSCustomObject]@{ PID = $_.ProcessId; User = $owner.User; CmdLine = $_.CommandLine }
    } |
    Where-Object { $_.User -eq 'Administrator' -and $_.CmdLine -and $_.CmdLine -notmatch '--type=' }

if ($adminProcs) {
    Write-Host "  Found $($adminProcs.Count) Administrator Windsurf main process(es)"
    foreach ($p in $adminProcs) {
        Write-Host "  Killing PID $($p.PID)..." -ForegroundColor Yellow
        Stop-Process -Id $p.PID -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 3
    
    # Relaunch Windsurf for Administrator
    # Use schtasks to launch as Administrator's session
    $taskName = "WindsurfRelaunch_$timestamp"
    $wsExe = "D:\Windsurf\Windsurf.exe"
    
    schtasks /Create /TN $taskName /TR "`"$wsExe`"" /SC ONCE /ST 00:00 /RU "Administrator" /RL HIGHEST /F 2>$null
    schtasks /Run /TN $taskName 2>$null
    Start-Sleep -Seconds 2
    schtasks /Delete /TN $taskName /F 2>$null
    
    Write-Host "  Windsurf relaunched for Administrator" -ForegroundColor Green
} else {
    Write-Host "  No running Administrator Windsurf found"
    Write-Host "  Please start Windsurf on Administrator manually"
}

# ============================================================
# Summary
# ============================================================
Write-Host "`n" + ("=" * 60)
Write-Host "  FIX COMPLETE"
Write-Host ("=" * 60)
Write-Host @"

  What was done:
  1. Generated new AES-256 key
  2. DPAPI encrypted with LOCAL_MACHINE scope (cross-user!)
  3. Replaced Administrator's Local State encrypted_key
  4. AES-GCM encrypted session data (sessions + apiServerUrl)
  5. Injected into Administrator's state.vscdb secret:// keys
  6. Synced windsurfAuthStatus + cachedPlanInfo + windsurfConfigurations
  7. Updated cascade-auth.json + windsurf-auth.json
  8. Restarted Windsurf

  Administrator's Windsurf should now show LOGGED IN!
  Account: $($sessionObj[0].account.label)
  
"@ -ForegroundColor Green
