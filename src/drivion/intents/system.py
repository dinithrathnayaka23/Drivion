"""Parts of Windows that Drivion may open: fixed lists, never free text.

Opening a settings page only shows it, so nothing changes until you change it.
``SHELL_SURFACES`` are parts of the Windows interface, each opened by one
fixed keyboard shortcut (see ``actions/windows/desktop.py``).
"""

from __future__ import annotations

from drivion.intents.normalize import normalize

# id -> (ms-settings address, name for replies, what you can call it)
SETTINGS_PAGES: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "home": ("ms-settings:", "Settings", ("windows", "pc", "computer", "system")),
    "display": ("ms-settings:display", "display settings", ("display", "screen", "monitor")),
    "sound": ("ms-settings:sound", "sound settings", ("sound", "audio", "volume")),
    "notifications": ("ms-settings:notifications", "notification settings", ("notification", "notifications")),
    "power": ("ms-settings:powersleep", "power settings", ("power", "sleep", "power and sleep", "power and battery")),
    "battery": ("ms-settings:batterysaver", "battery settings", ("battery", "battery saver")),
    "storage": ("ms-settings:storagesense", "storage settings", ("storage", "disk")),
    "bluetooth": ("ms-settings:bluetooth", "Bluetooth settings", ("bluetooth", "devices")),
    "printers": ("ms-settings:printers", "printer settings", ("printer", "printers")),
    "mouse": ("ms-settings:mousetouchpad", "mouse settings", ("mouse", "touchpad")),
    "wifi": ("ms-settings:network-wifi", "Wi-Fi settings", ("wifi", "wi fi", "wireless")),
    "network": ("ms-settings:network", "network settings", ("network", "internet", "ethernet")),
    "vpn": ("ms-settings:network-vpn", "VPN settings", ("vpn",)),
    "personalization": ("ms-settings:personalization", "personalization settings",
                        ("personalization", "personalisation")),
    "background": ("ms-settings:personalization-background", "background settings",
                   ("background", "wallpaper", "desktop background")),
    "colors": ("ms-settings:personalization-colors", "color settings", ("color", "colors", "colour", "colours",
                                                                        "dark mode", "light mode")),
    "themes": ("ms-settings:themes", "theme settings", ("theme", "themes")),
    "lock_screen": ("ms-settings:lockscreen", "lock screen settings", ("lock screen",)),
    "taskbar": ("ms-settings:taskbar", "taskbar settings", ("taskbar",)),
    "apps": ("ms-settings:appsfeatures", "app settings", ("app", "apps", "installed apps")),
    "default_apps": ("ms-settings:defaultapps", "default app settings", ("default app", "default apps")),
    "startup": ("ms-settings:startupapps", "startup settings", ("startup", "startup apps")),
    "accounts": ("ms-settings:yourinfo", "account settings", ("account", "accounts")),
    "sign_in": ("ms-settings:signinoptions", "sign-in settings", ("sign in", "signin", "login")),
    "date_time": ("ms-settings:dateandtime", "date and time settings", ("date and time", "date", "time", "clock")),
    "language": ("ms-settings:regionlanguage", "language settings", ("language", "region")),
    "accessibility": ("ms-settings:easeofaccess", "accessibility settings", ("accessibility", "ease of access")),
    "privacy": ("ms-settings:privacy", "privacy settings", ("privacy", "privacy and security")),
    "camera": ("ms-settings:privacy-webcam", "camera privacy settings", ("camera", "webcam", "camera privacy")),
    "microphone": ("ms-settings:privacy-microphone", "microphone privacy settings",
                   ("microphone", "mic", "microphone privacy")),
    "update": ("ms-settings:windowsupdate", "Windows Update", ("update", "updates", "windows update")),
    "about": ("ms-settings:about", "system information", ("about", "about this pc")),
}

# id -> name for replies
SHELL_SURFACES: dict[str, str] = {
    "start_menu": "the Start menu",
    "search": "Windows search",
    "desktop": "the desktop",
    "notifications": "your notifications",
    "quick_settings": "quick settings",
    "task_view": "task view",
}

_PAGE_ALIASES = {normalize(alias): page for page, (_, _, aliases) in SETTINGS_PAGES.items() for alias in aliases}


def settings_page(spoken: str) -> str | None:
    """Which page a spoken name means ("wi-fi" -> "wifi"), or None."""
    name = normalize(spoken)
    for prefix in ("the ", "my ", "your ", "this "):
        name = name.removeprefix(prefix)
    return _PAGE_ALIASES.get(name) or _PAGE_ALIASES.get(name.removeprefix("windows "))
