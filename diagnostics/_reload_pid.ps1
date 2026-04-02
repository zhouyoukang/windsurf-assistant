Add-Type -AssemblyName System.Windows.Forms
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class W32 {
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
}
"@

$proc = Get-Process -Id 10720 -ErrorAction Stop
$hwnd = $proc.MainWindowHandle
Write-Output "Window: $($proc.MainWindowTitle)"
Write-Output "HWND: $hwnd"

[W32]::ShowWindow($hwnd, 9) | Out-Null   # SW_RESTORE
[W32]::SetForegroundWindow($hwnd) | Out-Null
Start-Sleep -Milliseconds 700

[System.Windows.Forms.SendKeys]::SendWait("^+p")
Start-Sleep -Milliseconds 900
[System.Windows.Forms.SendKeys]::SendWait("reload window")
Start-Sleep -Milliseconds 600
[System.Windows.Forms.SendKeys]::SendWait("{ENTER}")
Write-Output "Reload command sent!"
