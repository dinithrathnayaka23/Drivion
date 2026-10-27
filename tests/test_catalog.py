"""The allowlist of apps, websites and folders, and its [commands] config."""

import pytest

from drivion.config import ConfigError, load_config
from drivion.intents.catalog import Catalog, TargetKind


def test_catalog_resolves_aliases_and_filler_words():
    catalog = Catalog({"vscode": ["vs code", "visual studio code"]}, {"github": "https://github.com"},
                      {"downloads": "~/Downloads"})
    assert catalog.resolve("visual studio code").id == "vscode"
    assert catalog.resolve("the vscode app").id == "vscode"
    assert catalog.resolve("my downloads folder").kind is TargetKind.FOLDER
    assert catalog.resolve("the github website").kind is TargetKind.WEBSITE
    assert catalog.resolve("spotify") is None


def test_one_name_for_two_things_is_rejected():
    with pytest.raises(ValueError, match="both"):
        Catalog({"chrome": ["browser"], "edge": ["browser"]}, {}, {})


def write(tmp_path, text):
    path = tmp_path / "settings.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_commands_section_replaces_defaults(tmp_path):
    config = load_config(write(tmp_path, '[commands.apps]\nspotify = ["music"]\n'))
    assert config.commands.apps == {"spotify": ["music"]}
    assert "youtube" in config.commands.websites  # other lists keep their defaults


@pytest.mark.parametrize(
    "toml_text, fragment",
    [
        ('[commands.websites]\nevil = "http://example.com"\n', "https://"),
        ('[commands.websites]\nevil = "javascript:alert(1)"\n', "https://"),
        ('[commands.apps]\n"Bad Id" = []\n', "ids must be"),
        ('[commands.apps]\nchrome = ["browser"]\nedge = ["browser"]\n', "both"),
        ('[commands.apps]\ngoogle = []\n', "both"),  # clashes with the default "google" website
    ],
)
def test_invalid_command_lists_are_rejected(tmp_path, toml_text, fragment):
    with pytest.raises(ConfigError, match=fragment):
        load_config(write(tmp_path, toml_text))
