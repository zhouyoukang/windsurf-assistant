Add-Type -AssemblyName System.Windows.Forms
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win32 {
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern IntPtr FindWindow(string lpClassName, string lpWindowName);
}
"@
# Find Windsurf window with "一生二" in title
$procs = Get-Process -Name "Windsurf" -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle -like "*一生二*" }
if ($procs) {
    $hwnd = $procs[0].MainWindowHandle
    [Win32]::SetForegroundWindow($hwnd) | Out-Null
    Start-Sleep -Milliseconds 500
    [System.Windows.Forms.SendKeys]::SendWait("^+p")
    Start-Sleep -Milliseconds 800
    [System.Windows.Forms.SendKeys]::SendWait("reload window")
    Start-Sleep -Milliseconds 500
    [System.Windows.Forms.SendKeys]::SendWait("{ENTER}")
    Write-Output "Reload sent to: $($procs[0].MainWindowTitle)"
} else {
    Write-Output "Windsurf window not found"
    Get-Process -Name "Windsurf" | Select-Object Id, MainWindowTitle | Format-Table
}
