from pathlib import Path


def test_frontend_does_not_use_inner_html():
    """Dataset-controlled values must never be parsed as HTML."""
    app_js = Path(__file__).parents[2] / "web" / "vanilla" / "app.js"
    source = app_js.read_text()

    assert ".innerHTML" not in source
