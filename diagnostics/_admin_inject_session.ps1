# ============================================================
# Windsurf safeStorage Session Injection — for Administrator
# ============================================================
# Run this in Administrator's Windsurf terminal (pwsh)
# Zero dependencies — uses .NET built-in DPAPI + AES-GCM
# ============================================================

$ErrorActionPreference = "Stop"

Write-Host "=" * 60
Write-Host "  Windsurf safeStorage Session Injection"
Write-Host "  Running as: $env:USERNAME"
Write-Host "=" * 60

# --- Configuration ---
$AdminLocalState = "C:\Users\Administrator\AppData\Roaming\Windsurf\Local State"
$AdminDB = "C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb"

# Session data decrypted from ai user (plaintext)
$sessions_plaintext = '[{"id":"21765441-1ff8-4e3c-a1ae-4a8b14f01a47","accessToken":"sk-ws-01-ZjtRvwZuPanGJdfQm40IrdA9IIouTc4oXe1dNHw2xK8sVZbAspyBmDMtZ38GQXcjiEH3s-l3-b-FGwDrzsEqf0eJ7Ane8Q","account":{"label":"Miller Harper","id":"Miller Harper"},"scopes":[]}]'
$apiServerUrl_plaintext = 'https://server.self-serve.windsurf.com'

# --- Step 1: Extract AES key from Local State (DPAPI) ---
Write-Host "`n  [Step 1] Extracting AES key from Local State..."

Add-Type -AssemblyName System.Security

$localState = Get-Content $AdminLocalState -Raw | ConvertFrom-Json
$encryptedKeyB64 = $localState.os_crypt.encrypted_key
$encryptedKey = [Convert]::FromBase64String($encryptedKeyB64)

Write-Host "    encrypted_key: $($encryptedKey.Length) bytes"

# Strip "DPAPI" prefix (5 bytes: 0x44,0x50,0x41,0x50,0x49)
if ([System.Text.Encoding]::ASCII.GetString($encryptedKey, 0, 5) -eq "DPAPI") {
    $dpapiBlob = $encryptedKey[5..($encryptedKey.Length - 1)]
    Write-Host "    Stripped DPAPI prefix, blob: $($dpapiBlob.Length) bytes"
} else {
    $dpapiBlob = $encryptedKey
    Write-Host "    No DPAPI prefix found"
}

# DPAPI decrypt
try {
    $aesKey = [System.Security.Cryptography.ProtectedData]::Unprotect(
        $dpapiBlob,
        $null,
        [System.Security.Cryptography.DataProtectionScope]::CurrentUser
    )
    Write-Host "    AES key: $($aesKey.Length) bytes ($([BitConverter]::ToString($aesKey[0..3]).Replace('-',''))...)"
} catch {
    Write-Host "    DPAPI decrypt FAILED: $_"
    Write-Host "    Make sure you are running AS Administrator"
    exit 1
}

# --- Step 2: AES-256-GCM encrypt session data ---
Write-Host "`n  [Step 2] Encrypting session data with AES-256-GCM..."

function Encrypt-V10 {
    param([string]$Plaintext, [byte[]]$Key)
    
    $ptBytes = [System.Text.Encoding]::UTF8.GetBytes($Plaintext)
    
    # Generate random 12-byte nonce
    $nonce = New-Object byte[] 12
    [System.Security.Cryptography.RandomNumberGenerator]::Fill($nonce)
    
    # AES-GCM encrypt
    $aesGcm = [System.Security.Cryptography.AesGcm]::new($Key)
    $ciphertext = New-Object byte[] $ptBytes.Length
    $tag = New-Object byte[] 16  # GCM tag is 16 bytes
    
    $aesGcm.Encrypt($nonce, $ptBytes, $ciphertext, $tag)
    $aesGcm.Dispose()
    
    # Build v10 format: "v10" + nonce + ciphertext + tag
    $v10Prefix = [System.Text.Encoding]::ASCII.GetBytes("v10")
    $result = New-Object byte[] ($v10Prefix.Length + $nonce.Length + $ciphertext.Length + $tag.Length)
    [Array]::Copy($v10Prefix, 0, $result, 0, 3)
    [Array]::Copy($nonce, 0, $result, 3, 12)
    [Array]::Copy($ciphertext, 0, $result, 15, $ciphertext.Length)
    [Array]::Copy($tag, 0, $result, 15 + $ciphertext.Length, 16)
    
    return $result
}

function To-ElectronBuffer {
    param([byte[]]$Data)
    $arr = $Data | ForEach-Object { [int]$_ }
    $json = @{ type = "Buffer"; data = $arr } | ConvertTo-Json -Compress
    return $json
}

# Encrypt sessions
$sessionsV10 = Encrypt-V10 -Plaintext $sessions_plaintext -Key $aesKey
$sessionsBuffer = To-ElectronBuffer -Data $sessionsV10
Write-Host "    sessions: $($sessionsBuffer.Length) chars"

# Encrypt apiServerUrl
$apiUrlV10 = Encrypt-V10 -Plaintext $apiServerUrl_plaintext -Key $aesKey
$apiUrlBuffer = To-ElectronBuffer -Data $apiUrlV10
Write-Host "    apiServerUrl: $($apiUrlBuffer.Length) chars"

# --- Step 3: Backup and write to state.vscdb ---
Write-Host "`n  [Step 3] Writing to state.vscdb..."

# Backup
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backup = Join-Path (Split-Path $AdminDB) "state.vscdb.bak_session_$timestamp"
Copy-Item $AdminDB $backup
Write-Host "    Backup: $(Split-Path $backup -Leaf)"

# SQLite operations via System.Data.SQLite or direct ADO.NET
# Use Python for SQLite since PowerShell's SQLite support varies
$pythonScript = @"
import sqlite3, json, sys

db_path = r'$AdminDB'
conn = sqlite3.connect(db_path, timeout=10)
conn.execute('PRAGMA journal_mode=WAL')
conn.execute('PRAGMA busy_timeout=5000')

# Inject secret:// keys
secrets = {
    'secret://{"extensionId":"codeium.windsurf","key":"windsurf_auth.sessions"}': sys.argv[1],
    'secret://{"extensionId":"codeium.windsurf","key":"windsurf_auth.apiServerUrl"}': sys.argv[2],
}

for key, value in secrets.items():
    conn.execute("INSERT OR REPLACE INTO ItemTable(key, value) VALUES(?, ?)", (key, value))
    print(f"  Injected: {key.split('key\":\"')[1][:30]}... ({len(value)} chars)")

# Also ensure windsurfAuthStatus has the correct apiKey
sessions_json = json.loads(r'''$sessions_plaintext''')
if sessions_json and isinstance(sessions_json, list):
    access_token = sessions_json[0].get('accessToken', '')
    if access_token:
        row = conn.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()
        if row:
            try:
                auth = json.loads(row[0])
                if auth and isinstance(auth, dict):
                    auth['apiKey'] = access_token
                    conn.execute("INSERT OR REPLACE INTO ItemTable(key, value) VALUES(?, ?)",
                                ('windsurfAuthStatus', json.dumps(auth)))
                    print(f"  windsurfAuthStatus.apiKey synced")
            except:
                # Create fresh auth status
                auth = {'apiKey': access_token}
                conn.execute("INSERT OR REPLACE INTO ItemTable(key, value) VALUES(?, ?)",
                            ('windsurfAuthStatus', json.dumps(auth)))
                print(f"  windsurfAuthStatus created with apiKey")

conn.commit()
conn.close()
print("  Done!")
"@

# Save Python script temporarily
$pyScript = Join-Path $env:TEMP "_ws_inject.py"
$pythonScript | Out-File -FilePath $pyScript -Encoding UTF8

# Run Python with the encrypted buffers as arguments
python $pyScript $sessionsBuffer $apiUrlBuffer

if ($LASTEXITCODE -eq 0) {
    Write-Host "`n  Session injection complete!"
    Write-Host "  Now restart Windsurf: Ctrl+Shift+P -> 'Reload Window'"
    Write-Host "  Or close and reopen Windsurf"
} else {
    Write-Host "`n  Python script failed. Trying direct SQLite..."
    
    # Fallback: write a Python one-liner
    $sessionsBufferEsc = $sessionsBuffer.Replace('"', '\"')
    $apiUrlBufferEsc = $apiUrlBuffer.Replace('"', '\"')
    
    python -c @"
import sqlite3
conn = sqlite3.connect(r'$AdminDB', timeout=10)
conn.execute('PRAGMA journal_mode=WAL')
conn.execute('PRAGMA busy_timeout=5000')
conn.execute('INSERT OR REPLACE INTO ItemTable(key,value) VALUES(?,?)', 
    ('secret://{\"extensionId\":\"codeium.windsurf\",\"key\":\"windsurf_auth.sessions\"}', 
     r'''$sessionsBuffer'''))
conn.execute('INSERT OR REPLACE INTO ItemTable(key,value) VALUES(?,?)',
    ('secret://{\"extensionId\":\"codeium.windsurf\",\"key\":\"windsurf_auth.apiServerUrl\"}',
     r'''$apiUrlBuffer'''))
conn.commit()
conn.close()
print('Direct injection done!')
"@
}

# Cleanup
Remove-Item $pyScript -ErrorAction SilentlyContinue

Write-Host "`n  ============================================="
Write-Host "  NEXT: Restart Windsurf on Administrator"
Write-Host "  Windsurf should now show logged-in status!"
Write-Host "  ============================================="
