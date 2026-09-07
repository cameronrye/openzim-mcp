"""``section <name> of <path>`` must split at the right " of ".

v3.3.1 field report, in the simple-mode list::

    `section <name> of <path>` splits on the first `" of "`, so any section
    whose name contains "of" is unreachable — including "Table of Contents".

The quoted spelling was fixed: ``section "Table of Contents" of X`` works.
The bare one — the spelling a person or a small model actually types, and
the spelling the tool's own `view='toc'` output invites by printing the
heading unquoted — still split at the first connector::

    section Table of Contents of iep.utm.edu/aristotle/
      -> section_name='table'
         entry_path='contents of iep.utm.edu/aristotle/'

Neither "first" nor "last" is right on its own. Last-wins breaks
``section History of A/The History of Rome``, where the *path* carries the
second " of "; first-wins breaks every heading with "of" in it. So the
split is chosen by which tail actually looks like an entry path, and falls
back to the historical first-connector behaviour when none does — the
genuinely ambiguous ``section Symptoms of Diabetes``, where "Diabetes" is
as likely a title as a section.
"""

from __future__ import annotations

import pytest

from openzim_mcp.intent_parser import IntentParser


def _params(query: str) -> dict:
    intent, params, _ = IntentParser.parse_intent(query)
    assert intent == "get_section", (intent, params)
    return params


# ---------------------------------------------------------------------------
# The reported case, and its family
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "query,name,path",
    [
        (
            "section Table of Contents of iep.utm.edu/aristotle/",
            "Table of Contents",
            "iep.utm.edu/aristotle/",
        ),
        (
            "section History of Science of A/Page",
            "History of Science",
            "A/Page",
        ),
        (
            "section Effects of Climate Change of A/Climate_change",
            "Effects of Climate Change",
            "A/Climate_change",
        ),
        (
            "section Table of Contents in iep.utm.edu/aristotle/",
            "Table of Contents",
            "iep.utm.edu/aristotle/",
        ),
        (
            "get section Table of Contents of medlineplus.gov/asthma.html",
            "Table of Contents",
            "medlineplus.gov/asthma.html",
        ),
    ],
)
def test_a_section_name_containing_of_is_reachable(query, name, path):
    params = _params(query)

    assert params["section_name"].lower() == name.lower(), params
    assert params["entry_path"] == path, params


def test_the_reported_query_no_longer_leaks_of_into_the_path():
    """The exact evidence line: the connector ended up inside the path."""
    params = _params("section Table of Contents of iep.utm.edu/aristotle/")

    assert " of " not in params["entry_path"], params
    assert params["section_name"].lower() != "table", params


# ---------------------------------------------------------------------------
# ...without breaking the cases the old split got right
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "query,name,path",
    [
        ("section Causes of A/Page", "Causes", "A/Page"),
        (
            "section Treatment of medlineplus.gov/asthma.html",
            "Treatment",
            "medlineplus.gov/asthma.html",
        ),
        # M8's case: an apostrophe in the name.
        ("section Earth's atmosphere of Earth", "Earth's atmosphere", "Earth"),
    ],
)
def test_a_single_connector_splits_where_it_always_did(query, name, path):
    params = _params(query)

    assert params["section_name"].lower() == name.lower(), params
    assert params["entry_path"].lower() == path.lower(), params


def test_a_path_that_carries_the_second_of_keeps_it():
    """Last-wins would break this: the trailing " of Rome" belongs to the
    PATH, not to the section name. "Rome" is not path-shaped, so the split
    stays at the connector whose tail is."""
    params = _params("section History of A/The History of Rome")

    assert params["entry_path"] == "A/The History of Rome", params
    assert params["section_name"].lower() == "history", params


def test_an_ambiguous_pair_keeps_its_historical_reading():
    """Neither tail looks like a path here, so nothing has changed: the
    first connector wins, as it always has."""
    params = _params("section Symptoms of Diabetes")

    assert params["section_name"].lower() == "symptoms", params
    assert params["entry_path"].lower() == "diabetes", params


# ---------------------------------------------------------------------------
# fid 46's audit residue: the quote widening had no test at all
# ---------------------------------------------------------------------------


def test_a_heading_carrying_the_archives_own_quotes_extracts():
    """Audit residue on fid 46. The name class was widened from
    ``_QUOTE_NOT_APOS`` to ``.`` so a heading the tool itself printed —
    IEP's ``2. Analytics or "Logic"`` — could be asked for at all; reverting
    that edit passed the whole suite, so nothing guarded it.
    """
    params = _params('section 2. Analytics or "Logic" of iep.utm.edu/aristotle/')

    assert params["entry_path"] == "iep.utm.edu/aristotle/", params
    assert "logic" in params["section_name"].lower(), params
    assert '"' in params["section_name"], params


def test_curly_quotes_inside_a_name_survive_too():
    """warc2zim keeps the site's own typography, so the quotes an archive
    prints are as often curly as straight."""
    params = _params("section “Smart” Quotes of A/Page")

    assert params["entry_path"] == "A/Page", params
    assert "smart" in params["section_name"].lower(), params


def test_a_deliberately_quoted_name_is_still_peeled():
    """Control: the quoted forms run before the widened one, so a name the
    caller quoted on purpose loses its quotes as it always did."""
    params = _params('section "Table of Contents" of iep.utm.edu/aristotle/')

    assert params["section_name"].lower() == "table of contents", params
    assert '"' not in params["section_name"], params
    assert params["entry_path"] == "iep.utm.edu/aristotle/", params
