"""D18 : macro `rel_time` -- la date exacte sans JavaScript, un <time> lisible par shell.js."""
from __future__ import annotations

from patrick.webapp.app import templates


def _render(value):
    tpl = templates.env.from_string('{% from "_components.html" import rel_time %}{{ rel_time(v) }}')
    return tpl.render(v=value)


def test_a_sqlite_utc_timestamp_becomes_an_iso_time_element_with_the_exact_date_as_fallback():
    html = _render("2026-11-24 18:31:06")
    assert 'class="rel-time"' in html and 'datetime="2026-11-24T18:31:06Z"' in html
    assert ">2026-11-24 18:31:06</time>" in html and 'title="2026-11-24 18:31:06 UTC"' in html


def test_an_offset_is_not_doubled_and_an_empty_value_is_a_dash():
    assert 'datetime="2026-11-24T18:31:06+00:00"' in _render("2026-11-24T18:31:06+00:00")
    assert _render(None).strip() == "—" and _render("").strip() == "—"
