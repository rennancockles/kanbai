"""Tests for the global hosted credentials store."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest
from kanbai import credentials
from kanbai.errors import KanbaiError


def test_load_returns_none_when_nothing_is_saved() -> None:
    assert credentials.load_token("https://a.example") is None


def test_save_then_load_round_trips_and_ignores_a_trailing_slash() -> None:
    credentials.save_token("https://a.example/", "tok-a")

    assert credentials.load_token("https://a.example") == "tok-a"
    assert credentials.load_token("https://a.example/") == "tok-a"


def test_tokens_are_kept_per_server() -> None:
    credentials.save_token("https://a.example", "tok-a")
    credentials.save_token("https://b.example", "tok-b")
    credentials.save_token("https://a.example", "tok-a2")

    assert credentials.load_token("https://a.example") == "tok-a2"
    assert credentials.load_token("https://b.example") == "tok-b"


def test_the_file_is_private_to_the_user() -> None:
    path = credentials.save_token("https://a.example", "tok-a")

    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_special_characters_survive_the_round_trip() -> None:
    credentials.save_token('https://a.example/p"x', 'to"k\\en')

    assert credentials.load_token('https://a.example/p"x') == 'to"k\\en'


def test_a_corrupt_file_reads_as_empty_but_is_never_overwritten(tmp_path: Path) -> None:
    path = credentials.credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not [valid toml")

    assert credentials.load_token("https://a.example") is None
    with pytest.raises(KanbaiError, match="Could not read"):
        credentials.save_token("https://a.example", "tok")
    assert path.read_text() == "not [valid toml"


def test_refresh_only_replaces_an_existing_entry() -> None:
    credentials.refresh_token("https://a.example", "tok-new")
    assert credentials.load_token("https://a.example") is None  # never creates one

    credentials.save_token("https://a.example", "tok-old")
    credentials.refresh_token("https://a.example", "tok-new")
    assert credentials.load_token("https://a.example") == "tok-new"
