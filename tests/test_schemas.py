"""Intent schemas: only registered intents with valid parameters can exist."""

import pytest
from pydantic import ValidationError

from drivion.intents import schemas as s


def test_valid_intent_from_plain_data():
    assert s.INTENT_ADAPTER.validate_python({"kind": "SET_VOLUME", "percent": 40}) == s.SetVolume(percent=40)
    assert s.INTENT_ADAPTER.validate_json('{"kind": "LOCK_COMPUTER"}') == s.LockComputer()


@pytest.mark.parametrize(
    "data",
    [
        {"kind": "SET_VOLUME", "percent": 101},
        {"kind": "SET_VOLUME", "percent": -1},
        {"kind": "SET_VOLUME"},                                # missing parameter
        {"kind": "CHANGE_VOLUME", "direction": "sideways"},
        {"kind": "SET_VOLUME", "percent": 40, "then": "format c:"},  # unknown field
        {"kind": "RUN_SHELL", "command": "del /s *"},          # not a registered intent
        {"kind": "OPEN_APP", "app": ""},
        {"kind": "ASK_QUESTION", "question": "x" * 501},
        {"percent": 40},                                       # no kind at all
    ],
)
def test_anything_else_is_rejected(data):
    with pytest.raises(ValidationError):
        s.INTENT_ADAPTER.validate_python(data)


def test_intents_are_immutable():
    intent = s.SetVolume(percent=40)
    with pytest.raises(ValidationError):
        intent.percent = 100


def test_every_intent_type_is_in_the_union_and_registry():
    union_kinds = {m.model_fields["kind"].default for m in s.INTENT_TYPES.values()}
    assert union_kinds == set(s.INTENT_TYPES)
    for kind, model in s.INTENT_TYPES.items():
        sample = {"kind": kind}
        for name, field in model.model_fields.items():
            if field.is_required():
                sample[name] = {"percent": 10, "direction": "up", "question": "why"}.get(name, "chrome")
        assert s.INTENT_ADAPTER.validate_python(sample).kind == kind


def test_describe():
    assert s.describe(s.SetVolume(percent=40)) == "set the volume to 40%"
    assert s.describe(s.OpenApp(app="vscode"), lambda i: "VS Code") == "open VS Code"
    assert s.describe(s.SleepComputer()) == "put the computer to sleep"
