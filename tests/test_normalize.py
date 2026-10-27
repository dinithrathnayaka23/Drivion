import pytest

from drivion.intents.normalize import normalize, words_to_numbers


@pytest.mark.parametrize(
    "words, digits",
    [
        ("forty five percent", "45 percent"),
        ("a hundred", "100"),
        ("one hundred", "100"),
        ("one hundred and five", "105"),
        ("one hundred forty five", "145"),
        ("zero", "0"),
        ("ten", "10"),
        ("nineteen", "19"),
        ("seventy", "70"),
        ("twenty thirty", "20 30"),
        ("one two three", "1 2 3"),
        ("set volume to fifty", "set volume to 50"),
        ("a cup", "a cup"),
    ],
)
def test_words_to_numbers(words, digits):
    assert words_to_numbers(words) == digits


@pytest.mark.parametrize(
    "transcript, expected",
    [
        ("Hey Drivion, could you set the volume to Forty-five %, please?", "set the volume to 45 percent"),
        ("Open Chrome.", "open chrome"),
        ("Can you please open VS Code for me, thanks.", "open vs code"),
        ("What’s the time?", "what is the time"),         # curly apostrophe from Whisper
        ("Don't open Chrome.", "do not open chrome"),
        ("Drivion, go to sleep.", "go to sleep"),
        ("Go to sleep, Drivion.", "go to sleep"),
        ("Okay.", "okay"),                                 # alone it means "yes"
        ("Okay, open Chrome.", "open chrome"),             # otherwise it's filler
        ("Set the volume to 40%.", "set the volume to 40 percent"),
        ("   ", ""),
        ("...", ""),
    ],
)
def test_normalize(transcript, expected):
    assert normalize(transcript) == expected


@pytest.mark.parametrize(
    "transcript, expected",
    [
        # How Whisper actually spelled "Drivion" in testing:
        ("Dr. Vian, go to sleep.", "go to sleep"),
        ("Go to sleep, Dravian.", "go to sleep"),
        ("Drivian, open Chrome.", "open chrome"),
        ("Driven, open Chrome.", "open chrome"),
        ("Hey, Drivian.", "drivion"),           # just the name: a greeting
        ("Drivion.", "drivion"),
        # Real words that look similar must survive:
        ("Driving directions to London", "driving directions to london"),
        ("Drive in the rain", "drive in the rain"),
        ("Division of labour", "division of labour"),
        ("Derivative of x squared", "derivative of x squared"),
    ],
)
def test_assistant_name_is_recognised_however_whisper_spells_it(transcript, expected):
    assert normalize(transcript) == expected
