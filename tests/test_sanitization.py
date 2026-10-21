import pytest

pytest.importorskip(
    "nh3", reason="Sanitization requires the nh3 package; install project dependencies"
)

from app.utils.validation import sanitize_html  # noqa: E402


@pytest.mark.parametrize(
    "payload",
    [
        "<script>alert(1)</script><p>Safe</p>",
        "<img src=x onerror=alert(1)>",
        '<a href="javascript:alert(1)">bad</a>',
        "<svg onload=alert(1)>bad</svg>",
        '<iframe src="https://evil.example"></iframe>',
        '<p style="background:url(javascript:alert(1))">text</p>',
        '<img src="data:image/svg+xml,bad">',
        '<a href="//evil.example">bad</a>',
    ],
)
def test_xss_removed(payload: str) -> None:
    result = sanitize_html(payload)
    for forbidden in (
        "<script",
        "onerror",
        "onload",
        "javascript:",
        "<svg",
        "<iframe",
        "style=",
        "data:",
        "//evil.example",
    ):
        assert forbidden not in result


def test_article_elements_and_affiliate_links() -> None:
    html = '<table><tr><th scope="col">Product</th><td>Good</td></tr></table><img src="https://example.com/a.png" alt="Laptop"><a href="https://shop.example/item?affiliate=1" rel="sponsored nofollow" target="_blank">Buy</a><pre><code>print(1)</code></pre>'
    result = sanitize_html(html)
    for expected in (
        "<table>",
        "<img ",
        "affiliate=1",
        "sponsored",
        "nofollow",
        "noopener",
        "noreferrer",
        "<pre><code>",
    ):
        assert expected in result


def test_rel_insertion_preserves_quoted_attributes() -> None:
    from html.parser import HTMLParser

    class Check(HTMLParser):
        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            assert all(not key.startswith("on") for key, _ in attrs)
            if tag == "a":
                assert {"noopener", "noreferrer"} <= set(dict(attrs)["rel"].split())

    result = sanitize_html(
        '<a title="&gt; rel=anything &quot; onmouseover=bad" href="https://example.com">Link</a>'
    )
    Check().feed(result)
