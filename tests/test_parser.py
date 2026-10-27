import pytest

from drivion.config.settings import CommandsSettings
from drivion.intents import schemas as s
from drivion.intents.catalog import Catalog
from drivion.intents.parser import IntentParser, Invalid, NotUnderstood, Understood


@pytest.fixture(scope="module")
def parser():
    c = CommandsSettings()
    return IntentParser(Catalog(c.apps, c.websites, c.folders))


def parsed(parser, text):
    result = parser.parse(text)
    assert isinstance(result, Understood), f"{text!r} -> {result}"
    return result.intent


@pytest.mark.parametrize(
    "text, intent",
    [
        # apps, websites, folders (aliases and filler words)
        ("Open Chrome.", s.OpenApp(app="chrome")),
        ("Launch Google Chrome, please.", s.OpenApp(app="chrome")),
        ("Could you open the browser?", s.OpenApp(app="chrome")),
        ("Open VS Code.", s.OpenApp(app="vscode")),
        ("Start Visual Studio Code.", s.OpenApp(app="vscode")),
        ("Open File Explorer.", s.OpenApp(app="explorer")),
        ("Run the calculator app.", s.OpenApp(app="calculator")),
        ("Go to YouTube.", s.OpenWebsite(site="youtube")),
        ("Open the GitHub website.", s.OpenWebsite(site="github")),
        ("Open Google.", s.OpenWebsite(site="google")),  # the website, not Google Chrome
        ("Open my downloads folder.", s.OpenFolder(folder="downloads")),
        ("Show me my documents.", s.OpenFolder(folder="documents")),
        # volume
        ("Set the volume to 40%.", s.SetVolume(percent=40)),
        ("Set volume to forty five percent.", s.SetVolume(percent=45)),
        ("Volume 75.", s.SetVolume(percent=75)),
        ("Turn the volume to max.", s.SetVolume(percent=100)),
        ("Set the sound to zero.", s.SetVolume(percent=0)),
        ("Turn the volume up.", s.ChangeVolume(direction="up", amount=10)),
        ("Turn up the volume by 20 percent.", s.ChangeVolume(direction="up", amount=20)),
        ("Turn it up.", s.ChangeVolume(direction="up")),
        ("Louder.", s.ChangeVolume(direction="up")),
        ("Lower the volume.", s.ChangeVolume(direction="down")),
        ("Volume down by 5.", s.ChangeVolume(direction="down", amount=5)),
        ("A bit quieter, please.", s.ChangeVolume(direction="down")),
        ("Mute.", s.Mute()),
        ("Turn off the sound.", s.Mute()),
        ("Unmute.", s.Unmute()),
        ("Turn the sound back on.", s.Unmute()),
        # brightness
        ("Set the brightness to 70 percent.", s.SetBrightness(percent=70)),
        ("Set the screen brightness to half.", s.SetBrightness(percent=50)),
        ("Increase brightness by 30.", s.ChangeBrightness(direction="up", amount=30)),
        ("Make the screen darker.", s.ChangeBrightness(direction="down")),
        ("Dim the screen.", s.ChangeBrightness(direction="down")),
        ("Brighter.", s.ChangeBrightness(direction="up")),
        # windows of apps
        ("Minimize Chrome.", s.MinimizeApp(app="chrome")),
        ("Hide VS Code.", s.MinimizeApp(app="vscode")),
        ("Bring back Chrome.", s.RestoreApp(app="chrome")),
        ("Restore Visual Studio Code.", s.RestoreApp(app="vscode")),
        # Windows
        ("Lock the computer.", s.LockComputer()),
        ("Lock the screen.", s.LockComputer()),
        ("Lock.", s.LockComputer()),
        ("Take a screenshot.", s.TakeScreenshot()),
        ("Screenshot.", s.TakeScreenshot()),
        ("Put my computer to sleep.", s.SleepComputer()),
        ("Put the PC into sleep mode.", s.SleepComputer()),
        ("Restart the computer.", s.RestartComputer()),
        ("Reboot.", s.RestartComputer()),
        ("Shut down the computer.", s.ShutdownComputer()),
        ("Turn off the laptop.", s.ShutdownComputer()),
        # built-ins
        ("Drivion, go to sleep.", s.GoToSleep()),
        ("Go to sleep.", s.GoToSleep()),
        ("Go back to sleep.", s.GoToSleep()),
        ("Stop listening.", s.GoToSleep()),
        ("That's all.", s.GoToSleep()),
        ("Goodbye.", s.GoToSleep()),
        ("Help.", s.Help()),
        ("What can you do?", s.Help()),
        ("What can I say?", s.Help()),
        ("Repeat that.", s.Repeat()),
        ("Say that again.", s.Repeat()),
        ("What did you say?", s.Repeat()),
        ("Cancel.", s.Cancel()),
        ("Never mind.", s.Cancel()),
        ("Stop.", s.Cancel()),
        ("Yes.", s.Confirm()),
        ("Okay.", s.Confirm()),
        ("Go ahead.", s.Confirm()),
        ("No.", s.Deny()),
        ("Nope.", s.Deny()),
        ("Hey Drivion.", s.Greet()),
        ("Hello.", s.Greet()),
    ],
)
def test_understands(parser, text, intent):
    assert parsed(parser, text) == intent


def test_drivion_standby_and_windows_sleep_are_never_confused(parser):
    for text in ["Go to sleep.", "Drivion, go to sleep.", "Sleep.", "Go to standby."]:
        assert parsed(parser, text) == s.GoToSleep()
    for text in ["Put my computer to sleep.", "Put the laptop to sleep.", "Sleep the computer."]:
        assert parsed(parser, text) == s.SleepComputer()


@pytest.mark.parametrize(
    "text, reason_fragment",
    [
        ("Set the volume to 150%.", "between 0 and 100"),
        ("Set the brightness to 101 percent.", "between 0 and 100"),
        ("Turn the volume up by 0.", "1 to 100"),
        ("Open Spotify.", "“spotify”"),
        ("Go to example.com.", "list of apps"),  # arbitrary sites are never opened
        ("Open.", "Open what"),
        ("Minimize YouTube.", "only minimize apps"),
        ("Restore the downloads folder.", "only restore apps"),
    ],
)
def test_understood_but_invalid(parser, text, reason_fragment):
    result = parser.parse(text)
    assert isinstance(result, Invalid), result
    assert reason_fragment in result.reason


def test_negated_command_is_a_correction_not_the_command(parser):
    assert parsed(parser, "Don't open Chrome.") == s.Cancel()
    assert parsed(parser, "Do not shut down the computer.") == s.Cancel()


def test_extra_words_make_a_rule_not_apply(parser):
    # Whole-sentence matching: no rule fires on part of a sentence.
    for text in ["Open Chrome and then delete my files.", "I said lock the computer yesterday."]:
        result = parser.parse(text)
        assert not (isinstance(result, Understood) and result.intent.kind in {"OPEN_APP", "LOCK_COMPUTER"})


@pytest.mark.parametrize(
    "text",
    ["What time is it?", "Tell me a joke.", "How far away is the moon?", "Do you know Python?",
     "Can you explain recursion?"],
)
def test_questions_become_ask_question(parser, text):
    intent = parsed(parser, text)
    assert intent == s.AskQuestion(question=text)


@pytest.mark.parametrize("text", ["Banana.", "Purple elephant.", "", "...", "um"])
def test_not_understood(parser, text):
    assert isinstance(parser.parse(text), NotUnderstood)


def test_custom_catalog_is_used(parser):
    custom = IntentParser(Catalog({"spotify": ["music"]}, {}, {"projects": "C:/Projects"}))
    assert parsed(custom, "Open the music app.") == s.OpenApp(app="spotify")
    assert parsed(custom, "Open my projects folder.") == s.OpenFolder(folder="projects")
    assert isinstance(custom.parse("Open Chrome."), Invalid)  # not in this allowlist
