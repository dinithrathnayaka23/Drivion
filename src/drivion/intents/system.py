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

MEDIA_ACTIONS: dict[str, tuple[int, str]] = {  # id -> (Windows media key, reply)
    "play_pause": (0xB3, "Okay."),
    "next": (0xB0, "Next track."),
    "previous": (0xB1, "Previous track."),
    "stop": (0xB2, "Stopped."),
}

_CTRL, _SHIFT, _ALT = 0x11, 0x10, 0x12
_LEFT, _RIGHT, _UP, _DOWN = 0x25, 0x27, 0x26, 0x28
_PAGE_UP, _PAGE_DOWN, _END, _HOME = 0x21, 0x22, 0x23, 0x24
_TAB, _ENTER, _ESCAPE, _BACKSPACE, _SPACE = 0x09, 0x0D, 0x1B, 0x08, 0x20
_F5, _F11, _PLUS, _MINUS = 0x74, 0x7A, 0xBB, 0xBD

# id -> (keys pressed together, reply). A fixed list: anything else can't be pressed.
KEY_ACTIONS: dict[str, tuple[tuple[int, ...], str]] = {
    "enter": ((_ENTER,), "Pressed enter."),
    "tab": ((_TAB,), "Pressed tab."),
    "escape": ((_ESCAPE,), "Pressed escape."),
    "backspace": ((_BACKSPACE,), "Pressed backspace."),
    "space": ((_SPACE,), "Pressed space."),
    "arrow_up": ((_UP,), "Up."),
    "arrow_down": ((_DOWN,), "Down."),
    "arrow_left": ((_LEFT,), "Left."),
    "arrow_right": ((_RIGHT,), "Right."),
    "scroll_up": ((_PAGE_UP,), "Scrolling up."),
    "scroll_down": ((_PAGE_DOWN,), "Scrolling down."),
    "top": ((_CTRL, _HOME), "Going to the top."),
    "bottom": ((_CTRL, _END), "Going to the bottom."),
    "save": ((_CTRL, ord("S")), "Saving."),
    "copy": ((_CTRL, ord("C")), "Copied."),
    "paste": ((_CTRL, ord("V")), "Pasted."),
    "cut": ((_CTRL, ord("X")), "Cut."),
    "undo": ((_CTRL, ord("Z")), "Undone."),
    "redo": ((_CTRL, ord("Y")), "Redone."),
    "select_all": ((_CTRL, ord("A")), "Selected everything."),
    "find": ((_CTRL, ord("F")), "Opening find."),
    "new_tab": ((_CTRL, ord("T")), "New tab."),
    "close_tab": ((_CTRL, ord("W")), "Closing the tab."),
    "reopen_tab": ((_CTRL, _SHIFT, ord("T")), "Reopening the tab."),
    "next_tab": ((_CTRL, _TAB), "Next tab."),
    "previous_tab": ((_CTRL, _SHIFT, _TAB), "Previous tab."),
    "address_bar": ((_CTRL, ord("L")), "Address bar."),
    "back": ((_ALT, _LEFT), "Going back."),
    "forward": ((_ALT, _RIGHT), "Going forward."),
    "refresh": ((_F5,), "Refreshing."),
    "zoom_in": ((_CTRL, _PLUS), "Zooming in."),
    "zoom_out": ((_CTRL, _MINUS), "Zooming out."),
    "full_screen": ((_F11,), "Full screen."),
}

RADIOS = {"bluetooth": "Bluetooth", "wifi": "Wi-Fi"}
THIS_WINDOW = "this"  # the target meaning "the window I'm using"

_PAGE_ALIASES = {normalize(alias): page for page, (_, _, aliases) in SETTINGS_PAGES.items() for alias in aliases}


def settings_page(spoken: str) -> str | None:
    """Which page a spoken name means ("wi-fi" -> "wifi"), or None."""
    name = normalize(spoken)
    for prefix in ("the ", "my ", "your ", "this "):
        name = name.removeprefix(prefix)
    return _PAGE_ALIASES.get(name) or _PAGE_ALIASES.get(name.removeprefix("windows "))
