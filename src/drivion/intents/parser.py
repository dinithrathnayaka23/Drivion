"""Rule-based, offline command parser: transcript -> validated intent.

How it works:
1. ``normalize`` the transcript ("Could you set the volume to 40%?" ->
   "set the volume to 40 percent").
2. Try each rule in order. A rule is a set of regular expressions that must
   match the *whole* sentence (``fullmatch``), so "don't open chrome" can never
   be mistaken for "open chrome", and extra words make a rule not apply
   rather than apply wrongly.
3. Build the intent through pydantic, so out-of-range values become a clear
   ``Invalid`` result ("The volume must be between 0 and 100 percent.").
4. Nothing matched: questions become ``AskQuestion`` (answered by the LLM in
   Milestone 8); anything else is ``NotUnderstood``.

Order matters where phrases overlap: built-ins first ("go to sleep" is
Drivion's standby), then "put the computer to sleep" (Windows sleep), and
the generic "open/go to <target>" rule last.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import ValidationError

from drivion.intents import schemas as s
from drivion.intents.catalog import Catalog, TargetKind
from drivion.intents.installed import InstalledApps
from drivion.intents.normalize import ASSISTANT_NAME, normalize
from drivion.intents.system import THIS_WINDOW, settings_page


@dataclass(frozen=True)
class Understood:
    intent: s.Intent


@dataclass(frozen=True)
class Invalid:
    """Recognised the kind of command, but it can't be done as asked."""

    reason: str


@dataclass(frozen=True)
class NotUnderstood:
    text: str


ParseResult = Understood | Invalid | NotUnderstood

# ----- reusable pattern pieces --------------------------------------------------------

THE = r"(?:the |my |your |this )?"
VOLUME = rf"{THE}(?:volume|sound|audio)"
BRIGHTNESS = rf"{THE}(?:screen )?brightness(?: level)?"
LEVEL = r"(?P<n>\d+|half|max|maximum|full|min|minimum)"
PCT = r"(?: percent| per cent)?"
BY = rf"(?: by {LEVEL}{PCT})?"
SET = r"(?:set|change|put|turn|adjust|make)"
COMPUTER = rf"{THE}(?:computer|pc|laptop|system|machine|windows|device)"
OPEN = r"(?:open up|open|launch|start|run|go to|show me|show|bring up|pull up|take me to|navigate to|visit|load|fire up)"

_QUESTION = re.compile(
    r"(?:what|who|whom|whose|why|how|when|where|which|is|are|am|was|were|"
    r"(?:do|does|did)(?! not\b)|"  # "do you know..." is a question, "do not..." isn't
    r"can|could|should|would|will|tell me|explain|define|describe|give me|calculate)\b"
)

_TYPE = re.compile(r"\b(?:type|write|dictate)\b(?:\s+out)?(?:\s+(?:this|that)\s*:)?[\s,:]*(?P<text>.*)", re.IGNORECASE | re.DOTALL)
_TYPE_START = re.compile(r"(?:type|write|dictate)\b")
_THIS = r"(?:this|that|it|this window|this app|(?:the )?current window|(?:the )?active window)"
ON_WORDS = r"(?:turn|switch|put|enable)"
OFF_WORDS = r"(?:turn|switch|disable)"
BLUETOOTH = r"blue ?tooth"
WIFI = r"(?:wifi|wi fi|wireless)"
PRESS = r"(?:press|hit|tap)(?: the)?"

_KEY_PHRASES: dict[str, list[str]] = {
    "enter": [rf"{PRESS} (?:enter|return)(?: key)?"],
    "tab": [rf"{PRESS} tab(?: key)?"],
    "escape": [rf"{PRESS} (?:escape|esc)(?: key)?"],
    "backspace": [rf"{PRESS} backspace(?: key)?"],
    "space": [rf"{PRESS} (?:space|spacebar|space bar)"],
    "arrow_up": [rf"{PRESS} (?:up|up arrow|arrow up)"],
    "arrow_down": [rf"{PRESS} (?:down|down arrow|arrow down)"],
    "arrow_left": [rf"{PRESS} (?:left|left arrow|arrow left)"],
    "arrow_right": [rf"{PRESS} (?:right|right arrow|arrow right)"],
    "scroll_up": [r"scroll up", r"page up"],
    "scroll_down": [r"scroll down", r"page down"],
    "top": [r"(?:go|scroll) to (?:the )?top"],
    "bottom": [r"(?:go|scroll) to (?:the )?bottom"],
    "save": [r"save(?: this| it| that| the file| my work)?"],
    "copy": [r"copy(?: this| that| it)?"],
    "paste": [r"paste(?: this| that| it)?"],
    "cut": [r"cut(?: this| that| it)?"],
    "undo": [r"undo(?: this| that| it)?"],
    "redo": [r"redo(?: this| that| it)?"],
    "select_all": [r"select (?:all|everything)"],
    "find": [r"find(?: on (?:this |the )?page)?"],
    "new_tab": [r"(?:open )?(?:a )?new tab"],
    "close_tab": [r"close (?:this |the )?tab"],
    "reopen_tab": [r"reopen (?:that |the )?(?:closed )?tab"],
    "next_tab": [r"next tab", r"switch tabs?"],
    "previous_tab": [r"previous tab", r"last tab"],
    "address_bar": [r"(?:go to|focus|open) (?:the )?address bar"],
    "back": [r"go back", r"back"],
    "forward": [r"go forward", r"forward"],
    "refresh": [r"(?:refresh|reload)(?: this| the)?(?: page)?"],
    "zoom_in": [r"zoom in"],
    "zoom_out": [r"zoom out"],
    "full_screen": [r"(?:go |make it )?full ?screen"],
}

_LEVEL_WORDS = {"half": 50, "max": 100, "maximum": 100, "full": 100, "min": 0, "minimum": 0}


def _level(match: re.Match, default: int | None = None) -> int | None:
    raw = match.groupdict().get("n")
    if raw is None:
        return default
    return int(raw) if raw.isdigit() else _LEVEL_WORDS[raw]


Builder = Callable[[re.Match], "dict | ParseResult"]


@dataclass(frozen=True)
class _Rule:
    name: str
    patterns: tuple[re.Pattern, ...]
    build: Builder


def _rule(name: str, patterns: list[str], build: Builder) -> _Rule:
    return _Rule(name, tuple(re.compile(p) for p in patterns), build)


def _fixed(model: type) -> Builder:
    return lambda _match: {"kind": model.model_fields["kind"].default}


class IntentParser:
    def __init__(self, catalog: Catalog, installed: InstalledApps | None = None) -> None:
        self.catalog = catalog
        self.installed = installed
        self._rules = self._build_rules()

    def parse(self, transcript: str) -> ParseResult:
        text = normalize(transcript)
        if not text:
            return NotUnderstood(transcript)
        if _TYPE_START.match(text):
            return self._type(transcript)
        for rule in self._rules:
            for pattern in rule.patterns:
                match = pattern.fullmatch(text)
                if match:
                    return self._finish(rule.build(match))
        if _QUESTION.match(text):
            return self._finish({"kind": "ASK_QUESTION", "question": transcript.strip()[:500]})
        return NotUnderstood(transcript)

    def _type(self, transcript: str) -> ParseResult:
        """From the original transcript, which keeps your capitals and punctuation."""
        found = _TYPE.search(transcript)
        text = found["text"].strip().rstrip(".") if found else ""
        if not text:
            return Invalid("Type what? For example, say “type hello team”.")
        return self._finish({"kind": "TYPE_TEXT", "text": text})

    @staticmethod
    def _finish(built: dict | ParseResult) -> ParseResult:
        if not isinstance(built, dict):
            return built
        try:
            return Understood(s.INTENT_ADAPTER.validate_python(built))
        except ValidationError:
            return Invalid(s.INTENT_TYPES[built["kind"]].invalid_message)

    # ----- rules -----------------------------------------------------------------

    def _build_rules(self) -> list[_Rule]:
        def change(kind: str, direction: str) -> Builder:
            return lambda m: {"kind": kind, "direction": direction, "amount": _level(m, 10)}

        def set_level(kind: str) -> Builder:
            return lambda m: {"kind": kind, "percent": _level(m)}

        return [
            # --- built-ins (exact phrases) ---
            _rule("go to sleep", [
                r"(?:go |you can |you can go )?(?:back )?to sleep(?: now)?",
                r"(?:go )?(?:to )?standby", r"sleep(?: now)?", r"stop listening",
                r"(?:that is|thats|that will be) all", r"good ?bye", r"bye(?: bye)?",
                r"dismiss", r"go away", r"close (?:the )?dashboard",
            ], _fixed(s.GoToSleep)),
            _rule("help", [
                r"help(?: me)?", r"what can (?:you do|i say|i ask)", r"what do you do",
                r"(?:list|show me|show|tell me) (?:the |your |all )?commands", r"commands",
                r"what commands (?:are there|do you know|can i use)",
                r"how (?:do i use you|does this work)",
            ], _fixed(s.Help)),
            _rule("repeat", [
                r"repeat(?: that| it| yourself)?", r"say (?:that|it) again", r"say again",
                r"what did you say", r"pardon(?: me)?", r"come again", r"again", r"one more time",
            ], _fixed(s.Repeat)),
            _rule("cancel", [
                r"cancel(?: that| it)?", r"never ?mind", r"forget (?:it|that|about it)",
                r"stop", r"abort", r"scratch that",
                # A negated command ("don't open chrome") is a correction, never the command.
                r"(?:do not|dont) .+",
            ], _fixed(s.Cancel)),
            _rule("greeting", [
                # normalize() turns a bare name ("Hey, Drivian.") into ASSISTANT_NAME.
                rf"(?:hey |hi |hello )?{ASSISTANT_NAME}", r"hey|hi|hello",
            ], _fixed(s.Greet)),
            _rule("confirm", [
                r"yes(?: please| do it)?", r"yeah", r"yep", r"yup", r"sure", r"ok", r"okay",
                r"confirm(?:ed)?", r"do it", r"go ahead", r"please do", r"affirmative", r"correct",
            ], _fixed(s.Confirm)),
            _rule("deny", [
                r"no(?: thanks| thank you)?", r"nope", r"nah", r"do not(?: do it)?",
                r"dont(?: do it)?", r"negative",
            ], _fixed(s.Deny)),

            # --- Windows power (always confirmed before running, in Milestone 7) ---
            _rule("sleep computer", [
                rf"(?:put|send|set) {COMPUTER} (?:to sleep|into sleep|in sleep|to sleep mode|"
                r"into sleep mode|in sleep mode)",
                rf"(?:sleep|suspend|hibernate) {COMPUTER}", rf"{COMPUTER} (?:go to )?sleep",
                r"suspend",
            ], _fixed(s.SleepComputer)),
            _rule("restart computer", [
                rf"(?:restart|reboot)(?: {COMPUTER})?",
            ], _fixed(s.RestartComputer)),
            _rule("shut down computer", [
                rf"(?:shut ?down|power (?:off|down))(?: {COMPUTER})?",
                rf"shut {COMPUTER} down", rf"(?:turn|switch) off {COMPUTER}",
                rf"(?:turn|switch) {COMPUTER} off",
            ], _fixed(s.ShutdownComputer)),
            _rule("lock", [
                rf"lock(?: {COMPUTER}| {THE}screen| {THE}workstation| it| up)?",
            ], _fixed(s.LockComputer)),
            _rule("screenshot", [
                r"(?:take|capture|grab|make|save) (?:a |the )?(?:screenshot|screen shot|"
                r"screen capture|picture of (?:the|my) screen)",
                r"screenshot", r"screen shot",
            ], _fixed(s.TakeScreenshot)),

            # --- volume ---
            _rule("set volume", [
                rf"{SET} {VOLUME} (?:to|at) {LEVEL}{PCT}",
                rf"{VOLUME} (?:to |at )?{LEVEL}{PCT}",
                rf"set {VOLUME} {LEVEL}{PCT}",
            ], set_level("SET_VOLUME")),
            _rule("volume up", [
                rf"(?:turn|crank|bring|pump) (?:up {VOLUME}|{VOLUME} up|it up){BY}",
                rf"(?:increase|raise|boost) {VOLUME}{BY}", rf"{VOLUME} up{BY}",
                r"(?:make it |a (?:bit|little) )?louder",
            ], change("CHANGE_VOLUME", "up")),
            _rule("volume down", [
                rf"(?:turn|bring) (?:down {VOLUME}|{VOLUME} down|it down){BY}",
                rf"(?:decrease|lower|reduce) {VOLUME}{BY}", rf"{VOLUME} down{BY}",
                r"(?:make it |a (?:bit|little) )?(?:quieter|softer)",
            ], change("CHANGE_VOLUME", "down")),
            _rule("mute", [
                rf"mute(?: {VOLUME}| it| everything)?",
                rf"(?:turn|switch) (?:off {VOLUME}|{VOLUME} off)",
            ], _fixed(s.Mute)),
            _rule("unmute", [
                rf"unmute(?: {VOLUME}| it)?",
                rf"(?:turn|switch) (?:on {VOLUME}|{VOLUME} (?:back )?on)", rf"{VOLUME} (?:back )?on",
            ], _fixed(s.Unmute)),

            # --- brightness ---
            _rule("set brightness", [
                rf"{SET} {BRIGHTNESS} (?:to|at) {LEVEL}{PCT}",
                rf"{BRIGHTNESS} (?:to |at )?{LEVEL}{PCT}",
            ], set_level("SET_BRIGHTNESS")),
            _rule("brightness up", [
                rf"(?:turn|bring) (?:up {BRIGHTNESS}|{BRIGHTNESS} up){BY}",
                rf"(?:increase|raise|boost) {BRIGHTNESS}{BY}", rf"{BRIGHTNESS} up{BY}",
                rf"(?:make {THE}screen |make it )?brighter",
            ], change("CHANGE_BRIGHTNESS", "up")),
            _rule("brightness down", [
                rf"(?:turn|bring) (?:down {BRIGHTNESS}|{BRIGHTNESS} down){BY}",
                rf"(?:decrease|lower|reduce|dim) {BRIGHTNESS}{BY}", rf"{BRIGHTNESS} down{BY}",
                rf"(?:make {THE}screen |make it )?(?:dimmer|darker)", rf"dim {THE}screen",
            ], change("CHANGE_BRIGHTNESS", "down")),

            # --- media, radios, dark mode ---
            *self._switches(),

            # --- the keyboard ---
            *[_rule(action, patterns, lambda _m, a=action: {"kind": "PRESS_KEYS", "action": a})
              for action, patterns in _KEY_PHRASES.items()],

            # --- a longer session, for working in other apps ---
            _rule("stay awake", [
                r"stay (?:awake|with me|on)", r"keep listening", r"(?:start )?work(?:ing)? mode",
            ], _fixed(s.StayAwake)),

            # --- parts of Windows: before settings ("quick settings") and minimize ---
            self._surface("start_menu", [
                rf"(?:(?:{OPEN}|press|click|hit) )?{THE}(?:windows )?start (?:menu|button)",
                rf"(?:open|show|press) {THE}start", rf"(?:open|press|hit) {THE}windows (?:key|button|menu)",
            ]),
            self._surface("search", [rf"{OPEN} {THE}(?:windows )?search", r"windows search"]),
            self._surface("desktop", [
                rf"(?:show|show me|go to) {THE}desktop", rf"minimi[sz]e (?:everything|all(?: {THE}windows)?)",
            ]),
            self._surface("notifications", [
                rf"{OPEN} {THE}notifications?(?: cent(?:er|re))?", r"notification cent(?:er|re)",
            ]),
            self._surface("quick_settings", [
                rf"(?:{OPEN} )?{THE}(?:quick settings|action cent(?:er|re))",
            ]),
            self._surface("task_view", [
                rf"(?:{OPEN} )?{THE}task view", rf"show (?:me )?all {THE}(?:windows|apps)",
            ]),

            # --- Windows Settings ---
            _rule("settings", [
                rf"(?:{OPEN} )?{THE}(?:(?P<page>.+?) )?settings(?: app| page| window)?",
                rf"{OPEN} windows update",
            ], self._settings),

            # --- windows of apps ---
            _rule("close", [r"(?:close|quit|exit) (?P<target>.+)"], self._close),
            _rule("minimize", [r"(?:minimi[sz]e|hide) (?P<target>.+)"], self._window("minimize")),
            _rule("maximize", [r"maximi[sz]e (?P<target>.+)"], self._window("maximize")),
            _rule("restore", [r"(?:restore|unminimi[sz]e|bring back) (?P<target>.+)"], self._window("restore")),
            _rule("switch", [r"(?:switch to|focus(?: on)?) (?P<target>.+)"], self._window("switch")),
            _rule("snap left", [r"(?:snap|move) (?P<target>.+?) (?:to )?(?:the )?left"], self._window("snap_left")),
            _rule("snap right", [r"(?:snap|move) (?P<target>.+?) (?:to )?(?:the )?right"],
                  self._window("snap_right")),

            # --- open: last, because "go to" / "show" are very general ---
            _rule("open", [
                r"(?:open up|open|launch|start|run|go to|show me|show|bring up|pull up|take me to|"
                r"navigate to|visit|browse to|load|fire up) (?P<target>.+)",
            ], self._open_target),
            _rule("open (no target)", [r"open|launch|start|run"],
                  lambda m: Invalid("Open what? For example, say “open Chrome”.")),
        ]

    def _open_target(self, match: re.Match) -> dict | ParseResult:
        spoken = match["target"]
        target = self.catalog.resolve(spoken)
        if target is None:
            return self._open_elsewhere(spoken)
        field = {TargetKind.APP: ("OPEN_APP", "app"),
                 TargetKind.WEBSITE: ("OPEN_WEBSITE", "site"),
                 TargetKind.FOLDER: ("OPEN_FOLDER", "folder")}[target.kind]
        return {"kind": field[0], field[1]: target.id}

    def _open_elsewhere(self, spoken: str) -> dict | ParseResult:
        """Not in your list: try the apps on this computer, then Settings pages."""
        found = self.installed.find(spoken) if self.installed is not None else None
        if found is not None and found.name:
            return {"kind": "OPEN_INSTALLED_APP", "name": found.name}
        if found is not None and found.options:
            return Invalid(f"I found {' and '.join(found.options)}. Which one do you want?")
        page = settings_page(spoken)
        if page is not None:
            return {"kind": "OPEN_SETTINGS", "page": page}
        if self.installed is None:
            return Invalid(f"I don't have “{spoken}” in your list of apps, websites or folders.")
        return Invalid(f"I couldn't find “{spoken}” on this computer.")

    @staticmethod
    def _surface(surface: str, patterns: list[str]) -> _Rule:
        return _rule(surface, patterns, lambda _match: {"kind": "OPEN_SURFACE", "surface": surface})

    @staticmethod
    def _settings(match: re.Match) -> dict | ParseResult:
        spoken = (match.groupdict().get("page") or "windows").strip()
        if match.string.endswith("windows update"):
            spoken = "update"
        page = settings_page(spoken)
        return {"kind": "OPEN_SETTINGS", "page": page} if page else Invalid(f"I can't open {spoken} settings.")

    @staticmethod
    def _switches() -> list[_Rule]:
        def radio(name: str, words: str) -> list[_Rule]:
            def build(on: bool) -> Builder:
                return lambda _m: {"kind": "SET_RADIO", "radio": name, "on": on}

            return [
                _rule(f"{name} on", [rf"{ON_WORDS} (?:on )?{THE}{words}(?: on)?", rf"{words} on"], build(True)),
                _rule(f"{name} off", [rf"{OFF_WORDS} (?:off )?{THE}{words}(?: off)?", rf"{words} off"], build(False)),
            ]

        def media(action: str) -> Builder:
            return lambda _m: {"kind": "MEDIA_CONTROL", "action": action}

        def theme(dark: bool) -> Builder:
            return lambda _m: {"kind": "SET_DARK_MODE", "dark": dark}

        music = r"(?:the )?(?:music|song|track|video|media)"
        return [
            *radio("bluetooth", BLUETOOTH), *radio("wifi", WIFI),
            _rule("dark mode", [
                r"(?:turn on|enable|use|switch to|go to) (?:the )?dark (?:mode|theme)", r"dark mode(?: on)?",
                r"(?:turn off|disable) (?:the )?light (?:mode|theme)",
            ], theme(True)),
            _rule("light mode", [
                r"(?:turn on|enable|use|switch to|go to) (?:the )?light (?:mode|theme)", r"light mode(?: on)?",
                r"(?:turn off|disable) (?:the )?dark (?:mode|theme)", r"dark mode off",
            ], theme(False)),
            _rule("play or pause", [rf"(?:play|pause|resume)(?: {music})?", rf"play some music"], media("play_pause")),
            _rule("next track", [r"next (?:song|track|video)", r"skip(?: this)?(?: song| track| video)?"], media("next")),
            _rule("previous track", [r"previous (?:song|track|video)", r"last (?:song|track|video)"], media("previous")),
            _rule("stop media", [rf"stop {music}", rf"stop playing(?: {music})?"], media("stop")),
        ]

    def _target_of(self, spoken: str) -> str:
        """``THIS_WINDOW``, the id of an app in your list, or the words you said."""
        if re.fullmatch(_THIS, spoken):
            return THIS_WINDOW
        target = self.catalog.resolve(spoken)
        return target.id if target is not None and target.kind is TargetKind.APP else spoken

    def _close(self, match: re.Match) -> dict | ParseResult:
        return {"kind": "CLOSE_APP", "target": self._target_of(match["target"])}

    def _window(self, action: str) -> Builder:
        verbs = {"minimize": "minimize", "restore": "restore"}

        def build(match: re.Match) -> dict | ParseResult:
            spoken = match["target"]
            target = self.catalog.resolve(spoken)
            if target is not None and target.kind is not TargetKind.APP:
                return Invalid(f"I can only {verbs.get(action, 'move')} apps.")
            if target is not None and action in verbs:  # your list says which program it is
                return {"kind": f"{action.upper()}_APP", "app": target.id}
            return {"kind": "CONTROL_WINDOW", "action": action, "target": self._target_of(spoken)}

        return build
