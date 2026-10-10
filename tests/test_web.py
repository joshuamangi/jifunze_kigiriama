"""Static front end: served publicly, installable, and held to the project's design rules."""

import json
import re
import struct
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
JS_FILES = sorted((WEB / "js").rglob("*.js"))
TEXT_FILES = [*JS_FILES, *sorted((WEB / "css").glob("*.css")), WEB / "index.html", WEB / "sw.js"]


@pytest.fixture
def anon(app):
    return TestClient(app)


def test_shell_is_public_and_apis_are_not(anon):
    page = anon.get("/")
    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    assert '<script type="module" src="/js/app.js">' in page.text
    assert 'rel="manifest"' in page.text
    assert anon.get("/css/app.css").status_code == 200
    assert anon.get("/api/entries").status_code == 401
    assert anon.get("/api/me").status_code == 401


def test_unknown_path_is_404_not_the_app(anon):
    assert anon.get("/nope").status_code == 404


def test_path_traversal_is_refused(anon):
    for path in ("/../app/config.py", "/%2e%2e/app/config.py", "/js/../../app/config.py"):
        response = anon.get(path)
        assert "SESSION_SECRET" not in response.text


def test_manifest_is_installable():
    manifest = json.loads((WEB / "manifest.webmanifest").read_text())
    assert manifest["display"] == "standalone"
    assert manifest["start_url"] and manifest["name"] and manifest["short_name"]
    sizes = {(i["sizes"], i["purpose"]) for i in manifest["icons"]}
    assert ("192x192", "any") in sizes
    assert ("512x512", "any") in sizes
    assert ("512x512", "maskable") in sizes
    for icon in manifest["icons"]:
        data = (WEB / icon["src"].lstrip("/")).read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n"
        width, height = struct.unpack(">II", data[16:24])
        assert f"{width}x{height}" == icon["sizes"]


def test_manifest_is_served_with_its_mime_type(anon):
    assert (
        anon.get("/manifest.webmanifest")
        .headers["content-type"]
        .startswith("application/manifest+json")
    )


def test_service_worker_precaches_only_files_that_exist_and_never_the_api():
    source = (WEB / "sw.js").read_text()
    shell = re.search(r"const SHELL = \[(.*?)\];", source, re.S).group(1)
    paths = re.findall(r"'(/[^']*)'", shell)
    assert "/" in paths
    for path in paths:
        target = WEB / path.lstrip("/")
        assert path == "/" or target.is_file(), path
    assert not [p for p in paths if p.startswith("/api")]
    # the fetch handler returns early (no respondWith) for API traffic and non-GET requests
    assert "url.pathname.startsWith('/api/')" in source
    assert "request.method !== 'GET'" in source
    assert "isApi(url)) return;" in source


def test_every_js_file_is_in_the_precache_list_and_imports_resolve():
    source = (WEB / "sw.js").read_text()
    for js in JS_FILES:
        assert "/" + js.relative_to(WEB).as_posix() in source, js
    for js in JS_FILES:
        for target in re.findall(
            r"""from\s+['"](\.{1,2}/[^'"]+)['"]|import\(\s*['"](\.{1,2}/[^'"]+)['"]\s*\)""",
            js.read_text(),
        ):
            relative = next(t for t in target if t)
            assert (js.parent / relative).resolve().is_file(), f"{js}: {relative}"


def test_theme_copy_matches_the_design_tokens():
    assert (WEB / "css/theme.css").read_text() == (ROOT / "docs/theme.css").read_text()


@pytest.mark.parametrize("path", JS_FILES, ids=lambda p: p.name)
def test_user_text_is_never_set_as_markup(path):
    source = path.read_text()
    for banned in (
        "innerHTML",
        "outerHTML",
        "insertAdjacentHTML",
        "document.write",
        "eval(",
        "new Function",
    ):
        assert banned not in source, f"{path.name} uses {banned}"


COLOUR = re.compile(r"#[0-9a-fA-F]{3,8}\b|\b(?:rgb|rgba|hsl|hsla|oklch|oklab|lab|lch)\(")


@pytest.mark.parametrize(
    "path", [p for p in TEXT_FILES if p.name not in {"theme.css", "sw.js"}], ids=lambda p: p.name
)
def test_no_hard_coded_colours_outside_the_theme(path):
    assert not COLOUR.search(path.read_text()), (
        f"{path.name} hard-codes a colour; use a theme variable"
    )


@pytest.mark.parametrize("path", TEXT_FILES, ids=lambda p: p.name)
def test_no_emoji_and_no_inline_styles(path):
    source = path.read_text()
    assert not re.search("[\U0001f300-\U0001faff☀-➿️]", source), f"{path.name} contains emoji"
    if path.suffix in {".js", ".html"}:
        assert not re.search(r"(?<![-\w])style\s*[=:]", source), f"{path.name} uses an inline style"


def test_touch_targets_use_the_44px_variable_and_fonts_are_self_hosted():
    css = (WEB / "css/app.css").read_text()
    assert "--tap: 44px" in css
    assert css.count("var(--tap)") >= 8
    for sheet in (WEB / "css").glob("*.css"):
        assert "googleapis" not in sheet.read_text()
    assert "googleapis" not in (WEB / "index.html").read_text()
    for weight in (400, 500, 600, 700):
        assert (WEB / f"fonts/kodchasan-latin-{weight}.woff2").is_file()


def test_documented_spelling_in_the_interface():
    # CLAUDE.md: Kigiriama / Giriama, except Taylor's 1891 title, quoted as published.
    for path in TEXT_FILES:
        text = (
            path.read_text()
            .replace("Giryama Vocabulary and Collections", "")
            .replace("giryamavocabula01taylgoog", "")
        )
        assert not re.search(r"Kigiryama|Giryama", text), path.name


def test_bottom_nav_has_five_items_and_login_has_none():
    app_js = (WEB / "js/app.js").read_text()
    nav = re.search(r"const NAV = \[(.*?)\n\];", app_js, re.S).group(1)
    assert len(re.findall(r"\['/", nav)) == 5
    for label in ("Home", "Add", "Learn", "Culture", "Settings"):
        assert f"'{label}'" in nav
    assert "'/review'" not in nav  # Review is reached from Settings
    assert "const showNav = path !== '/login'" in app_js


def test_form_fields_are_at_least_16px_so_ios_does_not_zoom_on_focus():
    # iOS Safari zooms the whole page when a field with text under 16px gets focus, and the zoom
    # stays after the single-page app navigates. 1rem is 16px at the default browser size.
    css = (WEB / "css/app.css").read_text()
    rule = re.search(r"\.input \{(.*?)\}", css, re.S).group(1)
    size = re.search(r"font-size:\s*([\d.]+)(rem|px)", rule)
    assert size, ".input must set its own font-size"
    value, unit = float(size.group(1)), size.group(2)
    assert value >= 1 if unit == "rem" else value >= 16, f".input font-size is {value}{unit}"
    # the search box and every other input reuse .input; none may override it with a smaller size
    for source in (WEB / "js").rglob("*.js"):
        assert not re.search(r"font-size", source.read_text()), source.name
