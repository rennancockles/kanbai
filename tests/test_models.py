"""Tests for the pure helpers in ``kanbai.models``."""

from __future__ import annotations

import pytest
from kanbai.models import ticket_key, tickets_match


@pytest.mark.parametrize(
    ("reference", "expected"),
    [
        ("PROJ-123", "PROJ-123"),
        ("  proj-123  ", "PROJ-123"),  # a bare key is matched ignoring case
        ("https://jira.example.com/browse/PROJ-123", "PROJ-123"),
        ("https://jira.example.com/browse/PROJ-123?focusedId=9", "PROJ-123"),
        ("https://jira.example.com/browse/ABC-1/links/PROJ-123", "PROJ-123"),  # the last key wins
        ("https://example.com/my-page-1", None),  # a lower-case slug is not a key
        ("email from Ana", None),
        ("", None),
    ],
)
def test_ticket_key(reference: str, expected: str | None) -> None:
    assert ticket_key(reference) == expected


@pytest.mark.parametrize(
    ("card_ticket", "wanted"),
    [
        ("PROJ-123", "PROJ-123"),
        ("PROJ-123", "proj-123"),
        ("https://jira.example.com/browse/PROJ-123", "PROJ-123"),
        ("PROJ-123", "https://other.example.com/browse/PROJ-123"),
        ("Teams thread", "teams thread"),  # no key: compared as text
    ],
)
def test_tickets_match(card_ticket: str, wanted: str) -> None:
    assert tickets_match(card_ticket, wanted)


@pytest.mark.parametrize(
    ("card_ticket", "wanted"),
    [
        ("PROJ-12", "PROJ-123"),  # never a prefix match
        ("PROJ-1234", "PROJ-123"),
        ("OTHER-123", "PROJ-123"),
        ("", "PROJ-123"),
        ("PROJ-123", ""),
        ("", ""),
        ("Teams thread", "PROJ-123"),
    ],
)
def test_tickets_do_not_match(card_ticket: str, wanted: str) -> None:
    assert not tickets_match(card_ticket, wanted)
