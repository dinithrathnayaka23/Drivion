"""Closing and moving windows, typing, shortcuts, media, radios and dark mode."""

import threading

import pytest
from pydantic import ValidationError

from action_fakes import FakeBrightness, FakeDesktop, FakePower, FakeRadios, FakeScreen, FakeTheme, FakeVolume
from audio_fakes import FakeSource, silent_frames
from drivion.actions.handlers import Backends, PowerScheduler, build_registry
from drivion.actions.window_finder import AppWindow, find_windows, keyboard_refusal
from drivion.config.settings import ActionsSettings, CommandsSettings
from drivion.core.activity import DeviceState
from drivion.intents import schemas as s
from drivion.intents.catalog import Catalog
from drivion.intents.parser import IntentParser, Invalid, Understood
from drivion.intents.responder import AssistantResponder
from drivion.intents.system import KEY_ACTIONS
from drivion.llm.assistant import parse_reply
from drivion.speech.listener import CommandListenerService
from drivion.speech.recorder import RecorderSettings
from drivion.speech.tts import SilentSpeaker

SPOTIFY = AppWindow(1, "Spotify.exe", "Some Song - Artist")
WORD = AppWindow(2, "WINWORD.EXE", "Report - Word")
CHROME_1 = AppWindow(3, "chrome.exe", "How to use Word - Google Chrome")
CHROME_2 = AppWindow(4, "chrome.exe", "GitHub - Google Chrome")
NOTEPAD = AppWindow(5, "Notepad.exe", "notes - Notepad")
PAINT = AppWindow(6, "mspaint.exe", "drawing - Paint")
TERMINAL = AppWindow(7, "WindowsTerminal.exe", "PowerShell")
CATALOG = Catalog.from_settings(CommandsSettings())


@pytest.fixture
def parser():
    return IntentParser(CATALOG)


def understood(parser, text):
    result = parser.parse(text)
    assert isinstance(result, Understood), (text, result)
    return result.intent


# ----- finding windows ------------------------------------------------------------------------


def test_the_program_name_beats_a_title_that_mentions_it():
    tab_about_spotify = AppWindow(8, "chrome.exe", "Spotify tips - Google Chrome")
    assert find_windows([tab_about_spotify, SPOTIFY], "spotify").windows == (SPOTIFY,)


def test_a_program_name_that_differs_from_the_app_name_asks_when_titles_clash():
    # WINWORD.EXE isn't the word "word", so only titles match, and two apps fit.
    assert find_windows([CHROME_1, WORD], "word").options == ("Google Chrome", "Word")


def test_a_title_is_used_when_no_program_matches():
    assert find_windows([WORD, SPOTIFY], "word").windows == (WORD,)


def test_your_app_list_says_exactly_which_program():
    assert find_windows([CHROME_1, CHROME_2, WORD], "chrome", "chrome.exe").windows == (CHROME_1, CHROME_2)


def test_several_different_apps_are_named_instead_of_guessed():
    windows = [AppWindow(1, "a.exe", "Budget - Notes"), AppWindow(2, "b.exe", "Budget - Sheets")]
    found = find_windows(windows, "budget")
    assert found.windows == () and found.options == ("Notes", "Sheets")


def test_nothing_matching_finds_nothing():
    assert find_windows([WORD], "spotify").windows == ()
    assert find_windows([WORD], "the app").windows == ()


@pytest.mark.parametrize("window", [
    TERMINAL, AppWindow(1, "cmd.exe", "Command Prompt"), AppWindow(1, "powershell.exe", "x"),
    AppWindow(1, "pwsh.exe", "x"), AppWindow(1, "SearchHost.exe", "Search"),
    AppWindow(1, "explorer.exe", "Run"), AppWindow(1, "Taskmgr.exe", "Create new task"),
    AppWindow(1, "wsl.exe", "x"), AppWindow(1, "regedit.exe", "Registry Editor"),
])
def test_command_windows_never_get_keys(window):
    assert "command windows" in keyboard_refusal(window)


def test_unknown_windows_never_get_keys():
    assert keyboard_refusal(None) is not None


def test_normal_windows_get_keys():
    assert keyboard_refusal(WORD) is None


# ----- understanding ------------------------------------------------------------------------


@pytest.mark.parametrize("text, target", [
    ("close spotify", "spotify"), ("quit spotify", "spotify"), ("exit spotify", "spotify"),
    ("close this", "this"), ("close this window", "this"), ("close the current window", "this"),
    ("close chrome", "chrome"),
])
def test_closing(parser, text, target):
    assert understood(parser, text) == s.CloseApp(target=target)


@pytest.mark.parametrize("text, action, target", [
    ("minimize spotify", "minimize", "spotify"), ("minimize this", "minimize", "this"),
    ("maximize this window", "maximize", "this"), ("maximize chrome", "maximize", "chrome"),
    ("restore spotify", "restore", "spotify"), ("switch to spotify", "switch", "spotify"),
    ("switch to chrome", "switch", "chrome"), ("snap this left", "snap_left", "this"),
    ("snap this to the right", "snap_right", "this"), ("move spotify to the left", "snap_left", "spotify"),
])
def test_window_commands(parser, text, action, target):
    assert understood(parser, text) == s.ControlWindow(action=action, target=target)


def test_your_app_list_keeps_its_exact_commands(parser):
    assert understood(parser, "minimize chrome") == s.MinimizeApp(app="chrome")
    assert understood(parser, "bring back chrome") == s.RestoreApp(app="chrome")


@pytest.mark.parametrize("text, radio, on", [
    ("turn off bluetooth", "bluetooth", False), ("turn bluetooth off", "bluetooth", False),
    ("disable bluetooth", "bluetooth", False), ("bluetooth off", "bluetooth", False),
    ("turn on bluetooth", "bluetooth", True), ("switch bluetooth on", "bluetooth", True),
    ("turn off wi-fi", "wifi", False), ("turn wifi on", "wifi", True), ("enable wifi", "wifi", True),
])
def test_radios(parser, text, radio, on):
    assert understood(parser, text) == s.SetRadio(radio=radio, on=on)


@pytest.mark.parametrize("text, dark", [
    ("turn on dark mode", True), ("dark mode", True), ("switch to dark mode", True),
    ("turn off dark mode", False), ("light mode", False), ("switch to light mode", False),
])
def test_dark_mode(parser, text, dark):
    assert understood(parser, text) == s.SetDarkMode(dark=dark)


@pytest.mark.parametrize("text, action", [
    ("pause", "play_pause"), ("play", "play_pause"), ("pause the music", "play_pause"),
    ("resume", "play_pause"), ("next song", "next"), ("skip", "next"), ("next track", "next"),
    ("previous song", "previous"), ("stop the music", "stop"),
])
def test_media(parser, text, action):
    assert understood(parser, text) == s.MediaControl(action=action)


def test_stop_alone_still_means_cancel(parser):
    assert understood(parser, "stop").kind == "CANCEL"


@pytest.mark.parametrize("transcript, text", [
    ("Type hello team.", "hello team"), ("type Hello, Team!", "Hello, Team!"),
    ("Drivian, type this is a test.", "this is a test"), ("type this: hello", "hello"), ("Please write Dear John", "Dear John"),
    ("dictate meet at 5 pm", "meet at 5 pm"), ("type out my name", "my name"),
])
def test_typing_keeps_your_words_and_capitals(parser, transcript, text):
    assert understood(parser, transcript) == s.TypeText(text=text)


def test_type_with_nothing_asks_what(parser):
    assert isinstance(parser.parse("type"), Invalid)


def test_too_much_to_type_is_refused(parser):
    assert isinstance(parser.parse("type " + "a" * 501), Invalid)


@pytest.mark.parametrize("text, action", [
    ("press enter", "enter"), ("hit enter", "enter"), ("press the tab key", "tab"), ("press escape", "escape"),
    ("save", "save"), ("save this", "save"), ("copy that", "copy"), ("paste", "paste"), ("undo", "undo"),
    ("undo that", "undo"), ("select all", "select_all"), ("new tab", "new_tab"), ("close this tab", "close_tab"),
    ("next tab", "next_tab"), ("go back", "back"), ("go forward", "forward"), ("refresh", "refresh"),
    ("refresh the page", "refresh"), ("scroll down", "scroll_down"), ("scroll up", "scroll_up"),
    ("zoom in", "zoom_in"), ("find", "find"), ("full screen", "full_screen"), ("go to the top", "top"),
])
def test_keys_and_shortcuts(parser, text, action):
    assert understood(parser, text) == s.PressKeys(action=action)


def test_older_phrases_keep_their_meaning(parser):
    assert understood(parser, "go back to sleep").kind == "GO_TO_SLEEP"
    assert understood(parser, "close the dashboard").kind == "GO_TO_SLEEP"
    assert understood(parser, "take a screenshot").kind == "TAKE_SCREENSHOT"
    assert understood(parser, "turn off the sound").kind == "MUTE"
    assert understood(parser, "shut down the computer").kind == "SHUTDOWN_COMPUTER"


@pytest.mark.parametrize("text", ["stay awake", "keep listening", "work mode", "start work mode"])
def test_stay_awake(parser, text):
    assert understood(parser, text) == s.StayAwake()


def test_only_listed_keys_validate():
    with pytest.raises(ValidationError):
        s.INTENT_ADAPTER.validate_python({"kind": "PRESS_KEYS", "action": "run_box"})


def test_no_shortcut_opens_the_run_box_or_locks():
    VK_WIN = 0x5B
    assert all(VK_WIN not in keys for keys, _ in KEY_ACTIONS.values())


# ----- carrying out ---------------------------------------------------------------------------


class Rig:
    def __init__(self, windows=(), radios=None, theme=None):
        self.desktop = FakeDesktop()
        self.desktop.open_windows = list(windows)
        self.radios, self.theme = radios or FakeRadios(), theme or FakeTheme()
        self.locked = []
        backends = Backends(FakeVolume(), FakeBrightness(), self.desktop, FakeScreen(), FakePower(),
                            self.radios, self.theme)
        scheduler = PowerScheduler(FakePower(), 10, False, lambda text: None)
        self.registry = build_registry(backends, CommandsSettings(), ActionsSettings(), lambda t: t, scheduler,
                                       wait=lambda condition, _timeout: condition(),
                                       on_locked=lambda: self.locked.append(True))

    def run(self, intent):
        return self.registry.get(intent.kind).handler(intent)


def test_closing_an_open_app():
    rig = Rig([WORD, SPOTIFY])
    result = rig.run(s.CloseApp(target="spotify"))
    assert result.success and result.verified and rig.desktop.closed == [SPOTIFY.hwnd]


def test_close_this_uses_the_window_in_use():
    rig = Rig([WORD, SPOTIFY])
    assert rig.run(s.CloseApp(target="this")).success and rig.desktop.closed == [WORD.hwnd]


def test_an_app_asking_to_save_is_not_called_a_failure_or_forced():
    rig = Rig([WORD])
    rig.desktop.closes_ok = False
    result = rig.run(s.CloseApp(target="word"))
    assert result.success and not result.verified and "save" in result.message


def test_closing_something_not_open_says_so():
    rig = Rig([WORD])
    result = rig.run(s.CloseApp(target="spotify"))
    assert not result.success and "isn't open" in result.message and rig.desktop.closed == []


def test_closing_something_unclear_asks():
    rig = Rig([AppWindow(1, "a.exe", "Budget - Notes"), AppWindow(2, "b.exe", "Budget - Sheets")])
    result = rig.run(s.CloseApp(target="budget"))
    assert not result.success and "Which one" in result.message and rig.desktop.closed == []


def test_a_minimized_modern_app_is_found_by_its_title():
    rig = Rig([AppWindow(9, "ApplicationFrameHost.exe", "Calculator")])
    assert rig.run(s.CloseApp(target="calculator")).success and rig.desktop.closed == [9]


@pytest.mark.parametrize("action, attribute", [("maximize", "maximized"), ("switch", "focused")])
def test_window_actions(action, attribute):
    rig = Rig([WORD, SPOTIFY])
    assert rig.run(s.ControlWindow(action=action, target="spotify")).success
    assert getattr(rig.desktop, attribute) == [SPOTIFY.hwnd]


def test_snapping():
    rig = Rig([WORD])
    assert rig.run(s.ControlWindow(action="snap_left", target="this")).success
    assert rig.desktop.snapped == [(WORD.hwnd, True)]


def test_a_refused_switch_is_reported():
    rig = Rig([WORD])
    rig.desktop.can_focus = False
    assert not rig.run(s.ControlWindow(action="switch", target="word")).success


def test_typing_reaches_a_normal_window():
    rig = Rig([WORD])
    assert rig.run(s.TypeText(text="hello")).success and rig.desktop.typed == ["hello"]


@pytest.mark.parametrize("intent", [s.TypeText(text="del *"), s.PressKeys(action="enter")])
def test_nothing_is_typed_or_pressed_in_a_terminal(intent):
    rig = Rig([TERMINAL])
    result = rig.run(intent)
    assert not result.success and rig.desktop.typed == [] and rig.desktop.pressed == []


def test_nothing_is_typed_with_no_window():
    rig = Rig([])
    assert not rig.run(s.TypeText(text="hello")).success


def test_blocked_keys_explain_administrator_windows():
    rig = Rig([WORD])
    rig.desktop.keys_blocked = True
    result = rig.run(s.TypeText(text="hello"))
    assert not result.success and "administrator" in result.message


def test_shortcuts_press_their_fixed_keys():
    rig = Rig([WORD])
    assert rig.run(s.PressKeys(action="save")).success
    assert rig.desktop.pressed == [KEY_ACTIONS["save"][0]]


def test_media_keys_need_no_window():
    rig = Rig([])
    assert rig.run(s.MediaControl(action="next")).success and rig.desktop.pressed == [(0xB0,)]


def test_a_radio_is_read_back():
    rig = Rig()
    result = rig.run(s.SetRadio(radio="bluetooth", on=False))
    assert result.success and result.verified and rig.radios.state["bluetooth"] is False


def test_a_radio_that_ignored_us_is_a_failure():
    rig = Rig(radios=FakeRadios(follows=False))
    assert not rig.run(s.SetRadio(radio="bluetooth", on=False)).success


def test_no_radio_is_explained():
    rig = Rig(radios=FakeRadios(present=False))
    result = rig.run(s.SetRadio(radio="wifi", on=False))
    assert not result.success and "Wi-Fi" in result.message


def test_dark_mode_is_read_back():
    rig = Rig()
    result = rig.run(s.SetDarkMode(dark=True))
    assert result.success and result.verified and rig.theme.dark


def test_locking_also_stops_drivion_listening():
    rig = Rig()
    rig.run(s.LockComputer())
    assert rig.locked == [True]


# ----- what the AI may do ---------------------------------------------------------------------


@pytest.mark.parametrize("action", [
    {"kind": "TYPE_TEXT", "text": "del *"}, {"kind": "PRESS_KEYS", "action": "enter"},
    {"kind": "CLOSE_APP", "target": "this"}, {"kind": "CONTROL_WINDOW", "action": "switch", "target": "this"},
    {"kind": "STAY_AWAKE"},
])
def test_the_ai_can_never_type_press_or_close(action):
    import json

    with pytest.raises(ValueError, match="not allowed"):
        parse_reply(json.dumps({"action": action}), CATALOG)


def test_the_ai_can_use_direct_controls():
    assert parse_reply('{"action": {"kind": "SET_DARK_MODE", "dark": true}}', CATALOG)
    assert parse_reply('{"action": {"kind": "MEDIA_CONTROL", "action": "next"}}', CATALOG)
    assert parse_reply('{"action": {"kind": "SET_RADIO", "radio": "bluetooth", "on": false}}', CATALOG)


# ----- staying awake --------------------------------------------------------------------------


def test_stay_awake_tells_the_app():
    calls = []
    responder = AssistantResponder(CATALOG, lambda: None, "Hey Drivion", on_stay_awake=lambda: calls.append(1))
    reply, _ = responder("stay awake")
    assert calls == [1] and "keep listening" in reply


class Ticking:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        self.now += 1.0
        return self.now


def listener(frames, on_timeout, clock):
    done = threading.Event()
    service = CommandListenerService(
        source_factory=lambda: FakeSource(frames), vad_factory=lambda: lambda frame: 0.0,
        transcriber_factory=lambda: None, speaker=SilentSpeaker(), recorder_settings=RecorderSettings(),
        command_timeout_s=5, on_command=lambda text: None, on_unclear=lambda: None,
        on_timeout=on_timeout, on_microphone=lambda state: state is not DeviceState.ACTIVE and done.set(),
        on_status=lambda status: None, clock=clock, frame_samples=1024,
    )
    return service, done


def test_a_session_normally_times_out_and_a_new_one_starts_short():
    timeouts = []
    service, done = listener(silent_frames(20), lambda: timeouts.append(1), Ticking())
    service.keep_listening(600)  # from an earlier session: must not carry over
    service.start()
    assert done.wait(5)
    service.stop()
    assert timeouts == [1]


@pytest.mark.parametrize("transcript, kind", [
    ("Open up settings", "OPEN_SETTINGS"), ("just to open start.", "OPEN_SURFACE"),
    ("Now, turn off bluetooth.", "SET_RADIO"), ("Try to close this.", "CLOSE_APP"),
])
def test_how_people_really_phrase_things(parser, transcript, kind):
    assert understood(parser, transcript).kind == kind
