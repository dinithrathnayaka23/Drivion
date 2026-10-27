"""Every command Drivion understands, as a validated data type.

Each intent is a small, frozen pydantic model with a ``kind`` tag and typed,
range-checked parameters (``SetVolume.percent`` must be 0..100). Together
they form the ``Intent`` union; nothing outside this list can be
represented, so nothing outside it can be executed.

``INTENT_ADAPTER`` validates an intent from plain data (e.g. JSON). The
rule-based parser builds intents through it, and in Milestone 8 the LLM's
output will be validated the same way: the model can only *choose* one of
these intents with valid parameters, never run arbitrary commands.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, ClassVar, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

Percent = Annotated[int, Field(ge=0, le=100)]
Step = Annotated[int, Field(ge=1, le=100)]
Direction = Literal["up", "down"]
Name = Annotated[str, Field(min_length=1, max_length=64)]


class _Intent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    # Plain-language explanation used when parameters fail validation.
    invalid_message: ClassVar[str] = "That command had an invalid value."


# ----- audio and display -----------------------------------------------------------


class SetVolume(_Intent):
    kind: Literal["SET_VOLUME"] = "SET_VOLUME"
    percent: Percent
    invalid_message: ClassVar[str] = "The volume must be between 0 and 100 percent."


class ChangeVolume(_Intent):
    kind: Literal["CHANGE_VOLUME"] = "CHANGE_VOLUME"
    direction: Direction
    amount: Step = 10
    invalid_message: ClassVar[str] = "I can change the volume by 1 to 100 percent at a time."


class Mute(_Intent):
    kind: Literal["MUTE"] = "MUTE"


class Unmute(_Intent):
    kind: Literal["UNMUTE"] = "UNMUTE"


class SetBrightness(_Intent):
    kind: Literal["SET_BRIGHTNESS"] = "SET_BRIGHTNESS"
    percent: Percent
    invalid_message: ClassVar[str] = "The brightness must be between 0 and 100 percent."


class ChangeBrightness(_Intent):
    kind: Literal["CHANGE_BRIGHTNESS"] = "CHANGE_BRIGHTNESS"
    direction: Direction
    amount: Step = 10
    invalid_message: ClassVar[str] = "I can change the brightness by 1 to 100 percent at a time."


# ----- apps, websites and folders (targets come from the allowlist) ---------------------


class OpenApp(_Intent):
    kind: Literal["OPEN_APP"] = "OPEN_APP"
    app: Name


class OpenWebsite(_Intent):
    kind: Literal["OPEN_WEBSITE"] = "OPEN_WEBSITE"
    site: Name


class OpenFolder(_Intent):
    kind: Literal["OPEN_FOLDER"] = "OPEN_FOLDER"
    folder: Name


class MinimizeApp(_Intent):
    kind: Literal["MINIMIZE_APP"] = "MINIMIZE_APP"
    app: Name


class RestoreApp(_Intent):
    kind: Literal["RESTORE_APP"] = "RESTORE_APP"
    app: Name


# ----- Windows ------------------------------------------------------------------------


class LockComputer(_Intent):
    kind: Literal["LOCK_COMPUTER"] = "LOCK_COMPUTER"


class TakeScreenshot(_Intent):
    kind: Literal["TAKE_SCREENSHOT"] = "TAKE_SCREENSHOT"


class SleepComputer(_Intent):
    """Windows sleep - not to be confused with GoToSleep (Drivion standby)."""

    kind: Literal["SLEEP_COMPUTER"] = "SLEEP_COMPUTER"


class RestartComputer(_Intent):
    kind: Literal["RESTART_COMPUTER"] = "RESTART_COMPUTER"


class ShutdownComputer(_Intent):
    kind: Literal["SHUTDOWN_COMPUTER"] = "SHUTDOWN_COMPUTER"


# ----- conversation --------------------------------------------------------------------


class AskQuestion(_Intent):
    kind: Literal["ASK_QUESTION"] = "ASK_QUESTION"
    question: Annotated[str, Field(min_length=1, max_length=500)]


class Help(_Intent):
    kind: Literal["HELP"] = "HELP"


class Repeat(_Intent):
    kind: Literal["REPEAT"] = "REPEAT"


class Cancel(_Intent):
    kind: Literal["CANCEL"] = "CANCEL"


class Confirm(_Intent):
    kind: Literal["CONFIRM"] = "CONFIRM"


class Deny(_Intent):
    kind: Literal["DENY"] = "DENY"


class Greet(_Intent):
    """Just the name or a hello ("Hey Drivion")."""

    kind: Literal["GREET"] = "GREET"


class GoToSleep(_Intent):
    """Drivion standby ("Drivion, go to sleep") - Windows keeps running."""

    kind: Literal["GO_TO_SLEEP"] = "GO_TO_SLEEP"


Intent = Annotated[
    Union[
        SetVolume, ChangeVolume, Mute, Unmute, SetBrightness, ChangeBrightness,
        OpenApp, OpenWebsite, OpenFolder, MinimizeApp, RestoreApp,
        LockComputer, TakeScreenshot, SleepComputer, RestartComputer, ShutdownComputer,
        AskQuestion, Help, Repeat, Cancel, Confirm, Deny, Greet, GoToSleep,
    ],
    Field(discriminator="kind"),
]

INTENT_ADAPTER: TypeAdapter[Intent] = TypeAdapter(Intent)

INTENT_TYPES: dict[str, type[_Intent]] = {
    model.model_fields["kind"].default: model
    for model in _Intent.__subclasses__()
}


def _plain(target_id: str) -> str:
    return target_id.replace("_", " ")


def describe(intent: _Intent, name_for: Callable[[str], str] = _plain) -> str:
    """A short phrase for replies, e.g. "set the volume to 40%".

    ``name_for`` turns an allowlist id ("vscode") into a spoken name ("vs code").
    """
    match intent:
        case SetVolume(percent=p):
            return f"set the volume to {p}%"
        case ChangeVolume(direction=d, amount=a):
            return f"turn the volume {d} by {a}%"
        case Mute():
            return "mute the sound"
        case Unmute():
            return "unmute the sound"
        case SetBrightness(percent=p):
            return f"set the brightness to {p}%"
        case ChangeBrightness(direction=d, amount=a):
            return f"turn the brightness {d} by {a}%"
        case OpenApp(app=a):
            return f"open {name_for(a)}"
        case OpenWebsite(site=site):
            return f"open the {name_for(site)} website"
        case OpenFolder(folder=f):
            return f"open your {name_for(f)} folder"
        case MinimizeApp(app=a):
            return f"minimize {name_for(a)}"
        case RestoreApp(app=a):
            return f"restore {name_for(a)}"
        case LockComputer():
            return "lock the computer"
        case TakeScreenshot():
            return "take a screenshot"
        case SleepComputer():
            return "put the computer to sleep"
        case RestartComputer():
            return "restart the computer"
        case ShutdownComputer():
            return "shut down the computer"
        case AskQuestion(question=q):
            return f"answer: {q}"
    return intent.kind.replace("_", " ").lower()
