<#
.SYNOPSIS
    Windsurf 多实例隔离启动器 v1.0
    
.DESCRIPTION
    根因: Windsurf多开时所有实例共享同一 user-data-dir 和 .codeium 目录,
    导致 code.lock PID锁冲突 + SQLite数据库腐败 + Codeium认证锁竞争。
    
    解决方案: 三层完全隔离
    ┌─────────────────────────────────────────────────────────┐
    │ Layer 1: --user-data-dir     → Electron/VS Code 状态隔离 │
    │ Layer 2: USERPROFILE override → .codeium 目录隔离        │
    │ Layer 3: Extensions sharing   → 扩展共享(节省磁盘)       │
    └─────────────────────────────────────────────────────────┘
    
    实例1: 使用默认路径(无变化)
    实例N: 独立 user-data-dir + 独立 .codeium + 共享扩展
    
.PARAMETER InstanceId
    实例编号(2-9)。实例1是默认Windsurf，无需此脚本。

.PARAMETER WorkspaceFolder
    可选，要打开的工作区文件夹路径。

.PARAMETER SyncAuth
    从主实例同步认证token到指定实例(不启动)。

.PARAMETER Status
    显示所有实例状态。

.PARAMETER Clean
    清理指定实例的数据目录(实例必须未运行)。

.EXAMPLE
    .\windsurf-multi.ps1 -InstanceId 2
    .\windsurf-multi.ps1 -InstanceId 2 -WorkspaceFolder "E:\道\道生一\一生二"
    .\windsurf-multi.ps1 -Status
    .\windsurf-multi.ps1 -SyncAuth 2
    .\windsurf-multi.ps1 -Clean 3
#>
param(
    [int]$InstanceId,
    [string]$WorkspaceFolder,
    [int]$SyncAuth,
    [switch]$Status,
    [int]$Clean
)

# ═══════════════════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════════════════
$WINDSURF_EXE = "D:\Windsurf\Windsurf.exe"
$INSTANCES_ROOT = "D:\WindsurfInstances"
$PRIMARY_USERPROFILE = $null  # auto-detect

# Auto-detect primary user profile (the user running Windsurf instance 1)
function Get-PrimaryUserProfile {
    # Check running Windsurf processes for the primary instance's user-data-dir
    $mainProcs = Get-CimInstance Win32_Process -Filter "Name='Windsurf.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and $_.CommandLine.Trim() -eq "`"$WINDSURF_EXE`"" }
    
    if ($mainProcs) {
        # Get the owner of the first main process
        $proc = @($mainProcs)[0]
        $owner = (Get-CimInstance Win32_Process -Filter "ProcessId=$($proc.ProcessId)" | 
            Invoke-CimMethod -MethodName GetOwner -ErrorAction SilentlyContinue)
        if ($owner -and $owner.User) {
            $userDir = "C:\Users\$($owner.User)"
            if (Test-Path $userDir) { return $userDir }
        }
    }
    
    # Fallback: find which user has the most recent .codeium/windsurf/
    foreach ($dir in @("C:\Users\Administrator", "C:\Users\ai", $env:USERPROFILE)) {
        if (Test-Path "$dir\.codeium\windsurf\installation_id") {
            return $dir
        }
    }
    return $env:USERPROFILE
}

# ═══════════════════════════════════════════════════════════
# 实例路径计算
# ═══════════════════════════════════════════════════════════
function Get-InstancePaths([int]$id) {
    $base = "$INSTANCES_ROOT\instance-$id"
    return @{
        Base         = $base
        Home         = "$base\home"
        UserDataDir  = "$base\data"
        CodeiumDir   = "$base\home\.codeium\windsurf"
        ExtensionsDir = "$base\home\.windsurf\extensions"
        AppData      = "$base\home\AppData\Roaming"
        WindsurfData = "$base\data"  # explicit user-data-dir
        LockFile     = "$base\data\code.lock"
    }
}

# ═══════════════════════════════════════════════════════════
# 认证同步: 从主实例复制必要的认证文件
# ═══════════════════════════════════════════════════════════
function Sync-AuthFromPrimary([int]$id) {
    $primary = Get-PrimaryUserProfile
    $paths = Get-InstancePaths $id
    $srcCodeium = "$primary\.codeium\windsurf"
    $dstCodeium = $paths.CodeiumDir
    
    if (-not (Test-Path $srcCodeium)) {
        Write-Host "[ERROR] Primary .codeium not found at: $srcCodeium" -ForegroundColor Red
        return $false
    }
    
    # Create target dirs
    New-Item -Path $dstCodeium -ItemType Directory -Force | Out-Null
    
    # Files to sync (auth-critical)
    $authFiles = @(
        "installation_id",
        "user_settings.pb",
        "native_storage_migrations.lock"
    )
    
    foreach ($f in $authFiles) {
        $src = "$srcCodeium\$f"
        $dst = "$dstCodeium\$f"
        if (Test-Path $src) {
            Copy-Item $src $dst -Force
            Write-Host "  [SYNC] $f" -ForegroundColor Green
        }
    }
    
    # Sync MCP config (important for Cascade functionality)
    $mcpFiles = @("mcp_config.json", "hooks.json")
    foreach ($f in $mcpFiles) {
        $src = "$srcCodeium\$f"
        $dst = "$dstCodeium\$f"
        if (Test-Path $src) {
            Copy-Item $src $dst -Force
            Write-Host "  [SYNC] $f" -ForegroundColor Green
        }
    }
    
    # Create subdirs that Codeium expects
    $subDirs = @("brain", "cascade", "code_tracker", "codemaps", "context_state", 
                 "database", "implicit", "memories", "windsurf")
    foreach ($d in $subDirs) {
        $dir = "$dstCodeium\$d"
        if (-not (Test-Path $dir)) {
            New-Item -Path $dir -ItemType Directory -Force | Out-Null
        }
    }
    
    # Sync extensions directory (use junction to save space)
    $srcExt = "$primary\.windsurf\extensions"
    $dstExtParent = "$($paths.Home)\.windsurf"
    $dstExt = "$dstExtParent\extensions"
    
    if ((Test-Path $srcExt) -and -not (Test-Path $dstExt)) {
        New-Item -Path $dstExtParent -ItemType Directory -Force | Out-Null
        # Use junction (not symlink) - no admin required for dirs
        cmd /c mklink /J "$dstExt" "$srcExt" 2>$null
        if ($?) {
            Write-Host "  [JUNCTION] extensions -> $srcExt" -ForegroundColor Cyan
        } else {
            # Fallback: copy
            Copy-Item $srcExt $dstExt -Recurse -Force
            Write-Host "  [COPY] extensions (junction failed)" -ForegroundColor Yellow
        }
    }
    
    # Also sync VS Code user settings from primary data dir
    $srcSettings = "$primary\AppData\Roaming\Windsurf\User\settings.json"
    $dstSettingsDir = "$($paths.WindsurfData)\User"
    if (Test-Path $srcSettings) {
        New-Item -Path $dstSettingsDir -ItemType Directory -Force | Out-Null
        Copy-Item $srcSettings "$dstSettingsDir\settings.json" -Force
        Write-Host "  [SYNC] VS Code settings.json" -ForegroundColor Green
    }
    
    # Sync globalStorage for auth state
    $srcGlobalStorage = "$primary\AppData\Roaming\Windsurf\User\globalStorage"
    $dstGlobalStorage = "$dstSettingsDir\globalStorage"
    if ((Test-Path $srcGlobalStorage) -and -not (Test-Path $dstGlobalStorage)) {
        Copy-Item $srcGlobalStorage $dstGlobalStorage -Recurse -Force
        Write-Host "  [SYNC] globalStorage (auth state)" -ForegroundColor Green
    }
    
    Write-Host "[OK] Auth synced for instance $id" -ForegroundColor Green
    return $true
}

# ═══════════════════════════════════════════════════════════
# 初始化实例
# ═══════════════════════════════════════════════════════════
function Initialize-Instance([int]$id) {
    $paths = Get-InstancePaths $id
    
    Write-Host "`n[INIT] Setting up instance $id..." -ForegroundColor Cyan
    Write-Host "  Base: $($paths.Base)"
    
    # Create directory structure
    $dirsToCreate = @(
        $paths.Home,
        $paths.UserDataDir,
        $paths.AppData,
        "$($paths.Home)\AppData\Local\Temp"
    )
    foreach ($d in $dirsToCreate) {
        New-Item -Path $d -ItemType Directory -Force | Out-Null
    }
    
    # Sync auth
    $ok = Sync-AuthFromPrimary $id
    if (-not $ok) {
        Write-Host "[WARN] Auth sync failed, instance may need manual login" -ForegroundColor Yellow
    }
    
    # Generate unique machine ID for this instance
    $machineIdFile = "$($paths.WindsurfData)\machineid"
    if (-not (Test-Path $machineIdFile)) {
        [guid]::NewGuid().ToString() | Set-Content $machineIdFile -NoNewline
        Write-Host "  [GEN] machineid" -ForegroundColor Green
    }
    
    # Symlink critical dotfiles from real home (Git, SSH, npm, etc.)
    # Without these, USERPROFILE override would break git/ssh/npm
    $primary = Get-PrimaryUserProfile
    $dotfiles = @(".gitconfig", ".ssh", ".npmrc", ".gnupg")
    foreach ($df in $dotfiles) {
        $src = "$primary\$df"
        $dst = "$($paths.Home)\$df"
        if ((Test-Path $src) -and -not (Test-Path $dst)) {
            $srcItem = Get-Item $src -Force
            if ($srcItem.PSIsContainer) {
                # Directory junction
                cmd /c mklink /J "$dst" "$src" 2>$null | Out-Null
                Write-Host "  [JUNCTION] $df" -ForegroundColor Cyan
            } else {
                # File symlink (may need admin) or copy
                try {
                    New-Item -ItemType SymbolicLink -Path $dst -Target $src -ErrorAction Stop | Out-Null
                    Write-Host "  [SYMLINK] $df" -ForegroundColor Cyan
                } catch {
                    Copy-Item $src $dst -Force
                    Write-Host "  [COPY] $df (symlink failed)" -ForegroundColor Yellow
                }
            }
        }
    }
    
    Write-Host "[OK] Instance $id initialized`n" -ForegroundColor Green
}

# ═══════════════════════════════════════════════════════════
# 启动实例
# ═══════════════════════════════════════════════════════════
function Start-Instance([int]$id, [string]$workspace) {
    $paths = Get-InstancePaths $id
    
    # Check if already running
    if (Test-Path $paths.LockFile) {
        $lockPid = (Get-Content $paths.LockFile -ErrorAction SilentlyContinue).Trim()
        if ($lockPid -and (Get-Process -Id $lockPid -ErrorAction SilentlyContinue)) {
            Write-Host "[WARN] Instance $id already running (PID $lockPid)" -ForegroundColor Yellow
            if ($workspace) {
                Write-Host "  Opening workspace in existing instance..." -ForegroundColor Cyan
                $env_backup = $env:USERPROFILE
                $env:USERPROFILE = $paths.Home
                & $WINDSURF_EXE --user-data-dir $paths.WindsurfData $workspace
                $env:USERPROFILE = $env_backup
            }
            return
        }
    }
    
    # Initialize if needed
    if (-not (Test-Path $paths.CodeiumDir)) {
        Initialize-Instance $id
    } else {
        # Always re-sync auth tokens (they may have been refreshed)
        Write-Host "[SYNC] Refreshing auth tokens..." -ForegroundColor Cyan
        Sync-AuthFromPrimary $id | Out-Null
    }
    
    # Build launch arguments
    $args = @(
        "--user-data-dir", $paths.WindsurfData
    )
    if ($workspace) {
        $args += $workspace
    }
    
    # Launch with isolated environment
    Write-Host "[LAUNCH] Starting Windsurf instance $id..." -ForegroundColor Green
    Write-Host "  user-data-dir: $($paths.WindsurfData)"
    Write-Host "  USERPROFILE:   $($paths.Home)"
    $wsDisplay = if ($workspace) { $workspace } else { '(none)' }
    Write-Host "  workspace:     $wsDisplay"
    
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $WINDSURF_EXE
    $psi.Arguments = $args -join ' '
    $psi.UseShellExecute = $false
    
    # Override environment for the child process
    # This is the KEY: USERPROFILE override isolates .codeium/windsurf/
    $psi.EnvironmentVariables["USERPROFILE"] = $paths.Home
    $psi.EnvironmentVariables["APPDATA"] = $paths.AppData
    $psi.EnvironmentVariables["LOCALAPPDATA"] = "$($paths.Home)\AppData\Local"
    $psi.EnvironmentVariables["TEMP"] = "$($paths.Home)\AppData\Local\Temp"
    $psi.EnvironmentVariables["TMP"] = "$($paths.Home)\AppData\Local\Temp"
    # Preserve critical env vars
    $psi.EnvironmentVariables["PATH"] = $env:PATH
    $psi.EnvironmentVariables["SystemRoot"] = $env:SystemRoot
    $psi.EnvironmentVariables["SystemDrive"] = $env:SystemDrive
    $psi.EnvironmentVariables["COMPUTERNAME"] = $env:COMPUTERNAME
    $psi.EnvironmentVariables["PROCESSOR_ARCHITECTURE"] = $env:PROCESSOR_ARCHITECTURE
    $psi.EnvironmentVariables["ProgramFiles"] = $env:ProgramFiles
    $psi.EnvironmentVariables["ProgramData"] = $env:ProgramData
    $psi.EnvironmentVariables["windir"] = $env:windir
    $psi.EnvironmentVariables["HOMEDRIVE"] = "D:"
    $psi.EnvironmentVariables["HOMEPATH"] = "\WindsurfInstances\instance-$id\home"
    # Preserve proxy settings
    if ($env:HTTP_PROXY) { $psi.EnvironmentVariables["HTTP_PROXY"] = $env:HTTP_PROXY }
    if ($env:HTTPS_PROXY) { $psi.EnvironmentVariables["HTTPS_PROXY"] = $env:HTTPS_PROXY }
    if ($env:NO_PROXY) { $psi.EnvironmentVariables["NO_PROXY"] = $env:NO_PROXY }
    # Git: explicitly point to real .gitconfig so USERPROFILE override doesn't break git
    $primary = Get-PrimaryUserProfile
    $realGitConfig = "$primary\.gitconfig"
    if (Test-Path $realGitConfig) {
        $psi.EnvironmentVariables["GIT_CONFIG_GLOBAL"] = $realGitConfig
    }
    # SSH: point to real .ssh dir
    $realSshDir = "$primary\.ssh"
    if (Test-Path $realSshDir) {
        $psi.EnvironmentVariables["GIT_SSH_COMMAND"] = "ssh -o UserKnownHostsFile=`"$realSshDir\known_hosts`" -i `"$realSshDir\id_rsa`""
    }
    if ($env:GIT_AUTHOR_NAME) { $psi.EnvironmentVariables["GIT_AUTHOR_NAME"] = $env:GIT_AUTHOR_NAME }
    if ($env:GIT_AUTHOR_EMAIL) { $psi.EnvironmentVariables["GIT_AUTHOR_EMAIL"] = $env:GIT_AUTHOR_EMAIL }
    
    # Instance identifier for debugging
    $psi.EnvironmentVariables["WINDSURF_INSTANCE_ID"] = "$id"
    
    $proc = [System.Diagnostics.Process]::Start($psi)
    
    Write-Host "[OK] Instance $id launched (PID $($proc.Id))" -ForegroundColor Green
    Write-Host ""
    Write-Host "  To open another workspace in this instance:" -ForegroundColor DarkGray
    Write-Host "    .\windsurf-multi.ps1 -InstanceId $id -WorkspaceFolder `"<path>`"" -ForegroundColor DarkGray
}

# ═══════════════════════════════════════════════════════════
# 状态查询
# ═══════════════════════════════════════════════════════════
function Show-Status {
    Write-Host "`n═══ Windsurf Multi-Instance Status ═══`n" -ForegroundColor Cyan
    
    # Primary instance
    $primaryProfile = Get-PrimaryUserProfile
    $primaryLock = "$primaryProfile\AppData\Roaming\Windsurf\code.lock"
    $primaryPid = if (Test-Path $primaryLock) { (Get-Content $primaryLock).Trim() } else { "N/A" }
    $primaryRunning = if ($primaryPid -ne "N/A" -and (Get-Process -Id $primaryPid -ErrorAction SilentlyContinue)) { "RUNNING" } else { "STOPPED" }
    
    Write-Host "Instance 1 (Primary):" -ForegroundColor White
    Write-Host "  Profile:  $primaryProfile" -ForegroundColor Gray
    Write-Host "  Data:     $primaryProfile\AppData\Roaming\Windsurf" -ForegroundColor Gray
    Write-Host "  Codeium:  $primaryProfile\.codeium\windsurf" -ForegroundColor Gray
    Write-Host "  PID:      $primaryPid" -ForegroundColor $(if ($primaryRunning -eq "RUNNING") { "Green" } else { "Red" })
    Write-Host "  Status:   $primaryRunning`n" -ForegroundColor $(if ($primaryRunning -eq "RUNNING") { "Green" } else { "Red" })
    
    # Secondary instances
    if (Test-Path $INSTANCES_ROOT) {
        $instances = Get-ChildItem $INSTANCES_ROOT -Directory -Filter "instance-*" | Sort-Object Name
        foreach ($inst in $instances) {
            $id = [int]($inst.Name -replace 'instance-', '')
            $paths = Get-InstancePaths $id
            $lockFile = $paths.LockFile
            $pid = if (Test-Path $lockFile) { (Get-Content $lockFile -ErrorAction SilentlyContinue).Trim() } else { "N/A" }
            $running = if ($pid -ne "N/A" -and (Get-Process -Id $pid -ErrorAction SilentlyContinue)) { "RUNNING" } else { "STOPPED" }
            
            Write-Host "Instance ${id}:" -ForegroundColor White
            Write-Host "  Home:     $($paths.Home)" -ForegroundColor Gray
            Write-Host "  Data:     $($paths.WindsurfData)" -ForegroundColor Gray
            Write-Host "  Codeium:  $($paths.CodeiumDir)" -ForegroundColor Gray
            Write-Host "  PID:      $pid" -ForegroundColor $(if ($running -eq "RUNNING") { "Green" } else { "Red" })
            Write-Host "  Status:   $running`n" -ForegroundColor $(if ($running -eq "RUNNING") { "Green" } else { "Red" })
        }
    } else {
        Write-Host "(No secondary instances created yet)" -ForegroundColor DarkGray
    }
    
    # Running Windsurf main processes
    Write-Host "═══ Running Main Processes ═══`n" -ForegroundColor Cyan
    $mains = Get-CimInstance Win32_Process -Filter "Name='Windsurf.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and $_.CommandLine.Trim() -match '^"?D:\\Windsurf\\Windsurf\.exe"?\s*$' }
    foreach ($m in $mains) {
        Write-Host "  PID $($m.ProcessId) (parent $($m.ParentProcessId))" -ForegroundColor Yellow
    }
    
    $isolated = Get-CimInstance Win32_Process -Filter "Name='Windsurf.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and $_.CommandLine -match '--user-data-dir' -and $_.CommandLine -notmatch '--type=' }
    foreach ($m in $isolated) {
        $udDir = if ($m.CommandLine -match '--user-data-dir[= ]+"?([^"]+)"?') { $Matches[1] } else { "?" }
        Write-Host "  PID $($m.ProcessId) → $udDir" -ForegroundColor Green
    }
    Write-Host ""
}

# ═══════════════════════════════════════════════════════════
# 清理实例
# ═══════════════════════════════════════════════════════════
function Clean-Instance([int]$id) {
    $paths = Get-InstancePaths $id
    
    # Check if running
    if (Test-Path $paths.LockFile) {
        $pid = (Get-Content $paths.LockFile -ErrorAction SilentlyContinue).Trim()
        if ($pid -and (Get-Process -Id $pid -ErrorAction SilentlyContinue)) {
            Write-Host "[ERROR] Instance $id is still running (PID $pid). Close it first." -ForegroundColor Red
            return
        }
    }
    
    if (Test-Path $paths.Base) {
        # Remove junction first (don't delete source!)
        $extJunction = "$($paths.Home)\.windsurf\extensions"
        if (Test-Path $extJunction) {
            $item = Get-Item $extJunction -Force
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                cmd /c rmdir "$extJunction" 2>$null
                Write-Host "  [DEL] Junction: extensions" -ForegroundColor Yellow
            }
        }
        
        Remove-Item $paths.Base -Recurse -Force -ErrorAction SilentlyContinue
        Write-Host "[OK] Instance $id cleaned: $($paths.Base)" -ForegroundColor Green
    } else {
        Write-Host "[INFO] Instance $id doesn't exist" -ForegroundColor Gray
    }
}

# ═══════════════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════════════

if ($Status) {
    Show-Status
    exit 0
}

if ($SyncAuth -gt 0) {
    if ($SyncAuth -lt 2 -or $SyncAuth -gt 9) {
        Write-Host "[ERROR] SyncAuth must be 2-9" -ForegroundColor Red
        exit 1
    }
    Sync-AuthFromPrimary $SyncAuth
    exit 0
}

if ($Clean -gt 0) {
    if ($Clean -lt 2 -or $Clean -gt 9) {
        Write-Host "[ERROR] Clean must be 2-9" -ForegroundColor Red
        exit 1
    }
    Clean-Instance $Clean
    exit 0
}

if ($InstanceId -gt 0) {
    if ($InstanceId -lt 2 -or $InstanceId -gt 9) {
        Write-Host "[ERROR] InstanceId must be 2-9 (instance 1 is default Windsurf)" -ForegroundColor Red
        exit 1
    }
    Start-Instance $InstanceId $WorkspaceFolder
    exit 0
}

# No args: show help
Write-Host @"

  Windsurf Multi-Instance Launcher v1.0
  ======================================
  
  道法自然 · 三层隔离 · 多实例共存
  
  Root cause of multi-instance failure:
    Layer 1: code.lock PID contention (user-data-dir)
    Layer 2: native_storage_migrations.lock (.codeium)
    Layer 3: SQLite database corruption (concurrent access)
  
  Solution: Per-instance isolation of USERPROFILE + user-data-dir
  
  Usage:
    .\windsurf-multi.ps1 -InstanceId 2                          # Launch instance 2
    .\windsurf-multi.ps1 -InstanceId 2 -WorkspaceFolder "E:\x"  # Launch with workspace
    .\windsurf-multi.ps1 -Status                                # Show all instances
    .\windsurf-multi.ps1 -SyncAuth 2                            # Sync auth tokens
    .\windsurf-multi.ps1 -Clean 3                               # Clean instance 3
  
  Instance 1 = default Windsurf (launch normally)
  Instances 2-9 = isolated via this launcher

"@ -ForegroundColor Cyan
