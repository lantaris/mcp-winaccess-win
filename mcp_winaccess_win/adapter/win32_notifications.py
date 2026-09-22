"""Windows notifications via WinRT UserNotificationListener (list) with UIA fallback for clearing."""

from __future__ import annotations

import os
import subprocess
import tempfile

_AWAIT = r"""
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
})[0]
function Await($WinRtTask, $ResultType) {
    $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
    $netTask = $asTask.Invoke($null, @($WinRtTask))
    $netTask.Wait(-1) | Out-Null
    $netTask.Result
}
"""

_LIST_SCRIPT = (
    _AWAIT
    + r"""
[Windows.UI.Notifications.Management.UserNotificationListener, Windows.UI.Notifications, ContentType=WindowsRuntime] | Out-Null
[Windows.UI.Notifications.NotificationKinds, Windows.UI.Notifications, ContentType=WindowsRuntime] | Out-Null
[Windows.UI.Notifications.KnownNotificationBindings, Windows.UI.Notifications, ContentType=WindowsRuntime] | Out-Null
$listener = [Windows.UI.Notifications.Management.UserNotificationListener]::Current
$accessType = [Windows.UI.Notifications.Management.UserNotificationListenerAccessStatus]
$status = Await $listener.RequestAccessAsync() $accessType
if ($status.ToString() -ne "Allowed") { Write-Output "DENIED"; exit }
$kinds = [Windows.UI.Notifications.NotificationKinds]::Toast
$vecType = [System.Collections.Generic.IReadOnlyList[Windows.UI.Notifications.UserNotification]]
$list = Await $listener.GetNotificationsAsync($kinds) $vecType
foreach ($n in $list) {
    $app = $n.AppInfo.DisplayInfo.DisplayName
    $texts = @()
    try {
        $binding = $n.Notification.Visual.GetBinding([Windows.UI.Notifications.KnownNotificationBindings]::ToastGeneric)
        if ($binding) { foreach ($t in $binding.GetTextElements()) { $texts += $t.Text } }
    } catch {}
    Write-Output ($app + " | " + ($texts -join " / "))
}
"""
)

_CLEAR_SCRIPT = (
    _AWAIT
    + r"""
[Windows.UI.Notifications.Management.UserNotificationListener, Windows.UI.Notifications, ContentType=WindowsRuntime] | Out-Null
$listener = [Windows.UI.Notifications.Management.UserNotificationListener]::Current
$accessType = [Windows.UI.Notifications.Management.UserNotificationListenerAccessStatus]
$status = Await $listener.RequestAccessAsync() $accessType
if ($status.ToString() -ne "Allowed") { Write-Output "DENIED"; exit }
try { $listener.ClearNotifications(); Write-Output "cleared" } catch { Write-Output ("error=" + $_.Exception.HResult) }
"""
)


def _run(script: str) -> str:
    handle, path = tempfile.mkstemp(suffix=".ps1")
    with os.fdopen(handle, "w", encoding="utf-8-sig") as stream:
        stream.write(script)
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", path],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=40,
        )
        return result.stdout or ""
    except Exception:
        return ""
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def list_notifications() -> list[str]:
    output = _run(_LIST_SCRIPT)
    if "DENIED" in output:
        return []
    items = []
    for line in output.splitlines():
        line = line.strip()
        if not line or "|" not in line:
            continue
        app, _, text = line.partition("|")
        app = app.strip()
        text = text.strip()
        if text:
            items.append(f"{app + ': ' if app else ''}{text}")
    return items


def clear_via_api() -> bool:
    return "cleared" in _run(_CLEAR_SCRIPT)
