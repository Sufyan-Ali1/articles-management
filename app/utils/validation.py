import html
import json
import re
import unicodedata
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit

SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def slugify(value: str, limit: int) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")[:limit].rstrip("-")
    if not slug:
        raise ValueError("Supply an ASCII slug for this name/title")
    return slug


def validate_slug(value: str) -> str:
    if not SLUG.fullmatch(value):
        raise ValueError("Slug must contain lowercase letters, digits and single hyphens")
    return value


def safe_url(value: str) -> str:
    parsed = urlsplit(value)
    if any(ord(c) < 33 for c in value) or "\\" in value:
        raise ValueError("Invalid URL")
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ValueError("Only absolute HTTP(S) URLs without credentials are allowed")
    try:
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("Invalid URL port") from exc
    return value


class MarkupDetector(HTMLParser):
    found = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.found = True

    def handle_endtag(self, tag: str) -> None:
        self.found = True

    def handle_comment(self, data: str) -> None:
        self.found = True

    def handle_decl(self, decl: str) -> None:
        self.found = True


def plain_text(value: str) -> str:
    if any(unicodedata.category(c) == "Cc" and c not in "\n\r\t" for c in value):
        raise ValueError("Control characters are not permitted")
    decoded = value
    for _ in range(4):
        new = html.unescape(decoded)
        if new == decoded:
            break
        decoded = new
    parser = MarkupDetector(convert_charrefs=True)
    parser.feed(decoded)
    parser.close()
    if parser.found or re.search(r"<\s*/?\s*(?:script|iframe|svg)\b", decoded, re.I):
        raise ValueError("HTML and scripts are not permitted")
    return value.strip()


TAGS = {
    "p",
    "br",
    "hr",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "strong",
    "em",
    "b",
    "i",
    "u",
    "s",
    "blockquote",
    "pre",
    "code",
    "ul",
    "ol",
    "li",
    "a",
    "img",
    "figure",
    "figcaption",
    "table",
    "thead",
    "tbody",
    "tfoot",
    "tr",
    "th",
    "td",
    "caption",
    "sup",
    "sub",
    "details",
    "summary",
}
ATTRS = {
    "a": {"href", "title", "rel", "target"},
    "img": {"src", "alt", "title", "width", "height", "loading"},
    "th": {"scope", "colspan", "rowspan"},
    "td": {"colspan", "rowspan"},
    "ol": {"start"},
    "code": {"class"},
}


def html_attribute(tag: str, attribute: str, value: str) -> str | None:
    if attribute in {"href", "src"}:
        if value.startswith("/") and not value.startswith("//") and "\\" not in value:
            return value if not any(ord(c) < 32 for c in value) else None
        if tag == "a" and value.startswith("#"):
            return value
        try:
            return safe_url(value)
        except ValueError:
            return None
    if attribute == "rel":
        tokens = {t.lower() for t in value.split()} & {
            "nofollow",
            "sponsored",
            "ugc",
            "noopener",
            "noreferrer",
        }
        return " ".join(sorted(tokens | {"noopener", "noreferrer"}))
    if attribute == "target":
        return value if value in {"_blank", "_self"} else None
    return value


def sanitize_html(value: str) -> str:
    import nh3

    cleaned = nh3.clean(
        value,
        tags=TAGS,
        attributes=ATTRS,
        attribute_filter=html_attribute,
        clean_content_tags={"script", "style", "iframe", "object", "svg", "math"},
        url_schemes={"https", "http"},
        link_rel=None,
        strip_comments=True,
    )
    protector = LinkProtector(convert_charrefs=False)
    protector.feed(cleaned)
    protector.close()
    return "".join(protector.parts)


class LinkProtector(HTMLParser):
    """Add missing rel attributes without regex rewriting sanitized HTML attributes."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            self.parts.append(self.get_starttag_text() or "")
            return
        values = dict(attrs)
        values["rel"] = " ".join(
            sorted(set((values.get("rel") or "").split()) | {"noopener", "noreferrer"})
        )
        attributes = "".join(
            f' {key}="{html.escape(value or "", quote=True)}"' for key, value in values.items()
        )
        self.parts.append(f"<a{attributes}>")

    def handle_endtag(self, tag: str) -> None:
        self.parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def handle_entityref(self, name: str) -> None:
        self.parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self.parts.append(f"&#{name};")


def validate_jsonld(value: dict[str, Any]) -> dict[str, Any]:
    if value.get("@context") not in (
        "https://schema.org",
        "https://schema.org/",
        "http://schema.org",
        "http://schema.org/",
    ):
        raise ValueError("JSON-LD requires a Schema.org context")

    def visit(node: Any, depth: int = 0) -> None:
        if depth > 16:
            raise ValueError("JSON-LD is too deeply nested")
        if isinstance(node, dict):
            if "@context" in node and node["@context"] != value["@context"]:
                raise ValueError("Nested remote contexts are not supported")
            for key, child in node.items():
                if key == "@type":
                    types = child if isinstance(child, list) else [child]
                    if not types or not all(
                        isinstance(t, str)
                        and re.fullmatch(r"(?:https?://schema\.org/)?[A-Za-z][A-Za-z0-9]*", t)
                        for t in types
                    ):
                        raise ValueError("Invalid Schema.org type")
                if key in {
                    "@id",
                    "url",
                    "image",
                    "contentUrl",
                    "thumbnailUrl",
                    "sameAs",
                    "embedUrl",
                    "mainEntityOfPage",
                    "logo",
                }:
                    for url in child if isinstance(child, list) else [child]:
                        if isinstance(url, str):
                            safe_url(url)
                if key.startswith("@") and key not in {
                    "@context",
                    "@type",
                    "@id",
                    "@graph",
                    "@value",
                    "@language",
                    "@list",
                    "@set",
                }:
                    raise ValueError("Unsupported JSON-LD keyword")
                visit(child, depth + 1)
        elif isinstance(node, list):
            for child in node:
                visit(child, depth + 1)
        elif isinstance(node, str):
            plain_text(node)
            if re.match(r"^(?:javascript|data|vbscript|file):", node.strip(), re.I):
                raise ValueError("Unsafe JSON-LD value")
        elif not isinstance(node, (int, float, bool, type(None))):
            raise ValueError("Invalid JSON-LD value")

    if "@graph" in value:
        graph = value["@graph"]
        if (
            not isinstance(graph, list)
            or not graph
            or not all(isinstance(n, dict) and "@type" in n for n in graph)
        ):
            raise ValueError("JSON-LD graph must contain typed objects")
    elif "@type" not in value:
        raise ValueError("JSON-LD requires @type or @graph")
    visit(value)
    if len(json.dumps(value, allow_nan=False).encode()) > 65536:
        raise ValueError("JSON-LD exceeds 64 KiB")
    return value


def generated_slug(value: str, limit: int) -> str:
    from app.core.errors import APIError

    try:
        return slugify(value, limit)
    except ValueError:
        raise APIError(
            422, "invalid_slug", "Supply an ASCII slug containing letters or digits"
        ) from None
