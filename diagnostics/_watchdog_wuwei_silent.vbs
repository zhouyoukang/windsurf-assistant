Set ws = CreateObject("WScript.Shell")
ws.Run "node """ & Replace(WScript.ScriptFullName, "_watchdog_wuwei_silent.vbs", "_watchdog_wuwei.js") & """", 0, False
