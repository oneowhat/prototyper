"""Tests for single-component rendering (task: single-component HTML/CSS rendering).

The renderer turns one HTML/CSS template plus one data row (a {header: value}
mapping, as produced by the CSV loader) into the substituted HTML for a single
component. These tests pin down the substitution contract and the strict,
print-safe error handling the rest of the tool relies on.
"""

import pytest

from prototyper.render import RenderError, render_component


def _write_template(tmp_path, text, name="card.html"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_substitutes_a_field(tmp_path):
    path = _write_template(tmp_path, "<h1>{{ name }}</h1>")
    assert render_component(path, {"name": "Guard"}) == "<h1>Guard</h1>"


def test_substitutes_multiple_fields(tmp_path):
    path = _write_template(tmp_path, "<h1>{{ name }}</h1><p>Cost: {{ cost }}</p>")
    html = render_component(path, {"name": "Archer", "cost": "2"})
    assert html == "<h1>Archer</h1><p>Cost: 2</p>"


def test_passes_css_and_markup_through(tmp_path):
    # The template's own HTML/CSS is untouched; only placeholders change.
    template = "<style>.card{width:2.5in}</style><div class=card>{{ name }}</div>"
    path = _write_template(tmp_path, template)
    html = render_component(path, {"name": "Guard"})
    assert "<style>.card{width:2.5in}</style>" in html
    assert '<div class=card>Guard</div>' in html


def test_values_are_used_verbatim(tmp_path):
    path = _write_template(tmp_path, "{{ cost }}")
    # A numeric-looking string stays exactly as given (CSV values are strings).
    assert render_component(path, {"cost": "10"}) == "10"


def test_unicode_values_preserved(tmp_path):
    path = _write_template(tmp_path, "<p>{{ name }}</p>")
    assert render_component(path, {"name": "Güard"}) == "<p>Güard</p>"


def test_special_characters_are_escaped(tmp_path):
    # Data may contain HTML metacharacters; escaping keeps output well-formed.
    path = _write_template(tmp_path, "<p>{{ text }}</p>")
    html = render_component(path, {"text": "Deal 3 & gain <1>"})
    assert html == "<p>Deal 3 &amp; gain &lt;1&gt;</p>"


def test_jinja_conditionals_and_filters_work(tmp_path):
    path = _write_template(tmp_path, "{% if cost %}Cost {{ cost }}{% endif %}")
    assert render_component(path, {"cost": "3"}) == "Cost 3"


def test_default_filter_supplies_optional_field(tmp_path):
    # A designer can mark a placeholder optional; StrictUndefined does not
    # break the standard `default` filter.
    path = _write_template(tmp_path, "{{ subtitle | default('') }}")
    assert render_component(path, {"name": "Guard"}) == ""


def test_missing_template_file_raises(tmp_path):
    with pytest.raises(RenderError, match="No template file"):
        render_component(tmp_path / "nope.html", {"name": "Guard"})


def test_unknown_field_raises(tmp_path):
    # A typo'd placeholder must fail loudly, not print a blank card.
    path = _write_template(tmp_path, "<h1>{{ nmae }}</h1>")
    with pytest.raises(RenderError, match="nmae"):
        render_component(path, {"name": "Guard"})


def test_template_syntax_error_raises(tmp_path):
    path = _write_template(tmp_path, "<h1>{{ name </h1>")
    with pytest.raises(RenderError, match="syntax"):
        render_component(path, {"name": "Guard"})


def test_accepts_pathlike_and_str(tmp_path):
    path = _write_template(tmp_path, "{{ name }}")
    assert render_component(str(path), {"name": "Guard"}) == "Guard"


def test_include_resolves_relative_to_template(tmp_path):
    _write_template(tmp_path, "<footer>{{ name }}</footer>", name="_footer.html")
    path = _write_template(
        tmp_path, "<div>{{ name }}</div>{% include '_footer.html' %}"
    )
    html = render_component(path, {"name": "Guard"})
    assert html == "<div>Guard</div><footer>Guard</footer>"
