"""The frontend is four pages of inline JavaScript, plus the 3D town in
`web/town3d.js`, with no build step.

That is a deliberate trade — no toolchain, no dependencies, open the file and read it
— but it removes the one thing a build step reliably gives you: somebody noticing that
the script does not parse. A syntax error here does not raise anywhere. The page loads,
the script never runs, and the town silently falls back to its demo snapshot, which
looks like a backend problem and is not.

That happened. Two strings were written one under the other without a `+`,
Python-style, and the whole page went dark. These tests are the guard.
"""

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parent.parent / "web"
PAGES = ["index.html", "sectors.html", "indices.html", "traders.html"]

NODE = shutil.which("node")


def scripts(name: str) -> list[str]:
    html = (WEB / name).read_text()
    return re.findall(r"<script>(.*?)</script>", html, re.S)


@pytest.mark.parametrize("page", PAGES)
def test_page_exists_and_has_a_script(page):
    assert (WEB / page).is_file()
    blocks = scripts(page)
    assert blocks, f"{page} has no script block"
    assert sum(len(b) for b in blocks) > 1000


@pytest.mark.parametrize("page", PAGES)
def test_brackets_balance_outside_strings_and_comments(page):
    """The parse guard below needs node. This one does not.

    `test_inline_javascript_parses` is the only thing standing between a typo and a
    page whose script never runs — and it skips silently when node is missing, which
    on a fresh machine is the normal case. A skipped guard is no guard, so the
    cheapest structural half of it runs unconditionally: brackets have to balance.
    It would have caught the unterminated call this very session introduced while
    routing state writes through a helper.
    """
    for i, block in enumerate(scripts(page)):
        stripped = strip_strings_and_comments(block)
        for opener, closer in ("()", "[]", "{}"):
            assert stripped.count(opener) == stripped.count(closer), (
                f"{page}, block {i}: {opener}{closer} unbalanced "
                f"({stripped.count(opener)} open, {stripped.count(closer)} closed)")


def strip_strings_and_comments(source: str) -> str:
    """Remove string and template literals, regexes and comments.

    Crude on purpose — it only has to be good enough to count brackets, and being
    wrong here means a false failure, which is visible, rather than a false pass.
    """
    out, i, n = [], 0, len(source)
    while i < n:
        char = source[i]
        if char in "\"'`":
            quote, i = char, i + 1
            while i < n and source[i] != quote:
                i += 2 if source[i] == "\\" else 1
            i += 1
        elif source.startswith("//", i):
            i = source.find("\n", i)
            if i == -1:
                break
        elif source.startswith("/*", i):
            i = source.find("*/", i)
            if i == -1:
                break
            i += 2
        else:
            out.append(char)
            i += 1
    return "".join(out)


@pytest.mark.skipif(NODE is None, reason="node not available")
@pytest.mark.parametrize("page", PAGES)
def test_inline_javascript_parses(page):
    for i, block in enumerate(scripts(page)):
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                         encoding="utf-8") as handle:
            handle.write(block)
            path = handle.name
        result = subprocess.run([NODE, "--check", path],
                                capture_output=True, text=True)
        assert result.returncode == 0, (
            f"{page}, block {i} is not valid JavaScript:\n{result.stderr[:600]}")


@pytest.mark.parametrize("page", PAGES)
def test_no_python_style_string_concatenation(page):
    """Two adjacent string literals are valid Python and a syntax error in
    JavaScript. Caught by the parse test above, but named here so the failure
    message says what to look for."""
    for block in scripts(page):
        offenders = re.findall(r'"\s*\n\s*"[^:,)]', block)
        assert not offenders, (
            f"{page}: strings joined without + — {offenders[:2]}")


def test_the_town_reads_the_explanation_endpoint():
    """The panel that answers "what does this tell me" has to be wired to the
    endpoint that answers it."""
    html = (WEB / "index.html").read_text()
    assert "/api/explain" in html
    assert 'id="reading"' in html
    assert "paintReading" in html


def test_the_analysis_page_offers_the_guided_experiments():
    html = (WEB / "sectors.html").read_text()
    for needle in ("/api/lessons", "renderLessons", "checkLesson", "/api/explain"):
        assert needle in html, f"missing from sectors.html: {needle}"


def test_both_pages_are_reachable_from_each_other():
    """The analysis page carries the validation and the guided experiments. Without
    a link from the town nobody finds it, which is how it was until a test asked."""
    assert 'href="/sectors"' in (WEB / "index.html").read_text()
    assert 'href="/"' in (WEB / "sectors.html").read_text()


ROUTES = {"index.html": "/", "sectors.html": "/sectors",
          "indices.html": "/indices", "traders.html": "/traders"}


@pytest.mark.parametrize("page", PAGES)
def test_every_page_reaches_every_other_page(page):
    """Four views of one simulation. A view nobody can navigate to is a view
    nobody uses — the analysis page went unfound for exactly that reason, and two
    more pages is the point at which the link has to become a nav rather than a
    single button in a corner."""
    html = (WEB / page).read_text()
    for other, route in ROUTES.items():
        if other == page:
            continue
        assert f'href="{route}"' in html, f"{page} does not link {route}"


# ------------------------------------------------------------- the index board
def test_the_index_board_draws_from_the_index_endpoint():
    html = (WEB / "indices.html").read_text()
    for needle in ("/api/indices", "function draw(", "renderLegend", "renderTable"):
        assert needle in html, f"missing from indices.html: {needle}"


def test_the_index_board_asks_for_a_window_and_a_point_count_separately():
    """One number for both silently returns the whole run thinned to that count,
    drawn under a label that says five days. It did exactly that once."""
    html = (WEB / "indices.html").read_text()
    assert "points=" in html and "n=${back}" in html, \
        "the request does not separate window length and point count"


def test_the_index_board_says_which_period_its_figures_cover():
    """A legend reporting the whole run beside a line showing five days is worse
    than no legend: the eye reads the two together and believes the number."""
    html = (WEB / "indices.html").read_text()
    assert "function windowChange(" in html
    assert "DATA.points" in html and "DATA.window" in html


def test_the_index_board_states_how_the_index_is_built():
    """The weighting is a modelling choice and the page it appears on has to own
    it, not leave it in a docstring nobody opens."""
    html = (WEB / "indices.html").read_text()
    for claim in ("index_weight", "Chained, not a ratio of sums", "Beta is a claim, not a setting",
                  "bit-identical"):
        assert claim in html, f"unstated in indices.html: {claim}"


# ---------------------------------------------------------------- the roster
def test_the_roster_reads_the_trader_endpoints():
    html = (WEB / "traders.html").read_text()
    for needle in ("/api/traders", "renderRows", "renderGroups", "loadDetail"):
        assert needle in html, f"missing from traders.html: {needle}"


def test_the_roster_sorts_and_filters_on_the_server():
    """Six hundred rows with a position per instrument is not a payload to send in
    full so the browser can sort it."""
    html = (WEB / "traders.html").read_text()
    script = html.split("<script>")[-1]
    assert "function url(" in script
    for parameter in ("sort", "order", "limit", "offset", "kind", "symbol"):
        assert f'"{parameter}"' in script, f"parameter missing from the request: {parameter}"


def test_the_roster_does_not_rebuild_the_table_on_every_poll():
    """It repaints every 1.5 s. Rebuilding six hundred rows each time drops the
    hover, the selection and the scroll position with it."""
    html = (WEB / "traders.html").read_text()
    assert "signature" in html and "column.update" in html, \
        "the rows are not updated in place"


def test_the_roster_can_hand_a_trader_to_the_town():
    """Two views of one population that cannot pass a member between them are two
    programs that happen to share a port."""
    assert '"/?agent=" + trader.aid' in (WEB / "traders.html").read_text()
    town = (WEB / "index.html").read_text()
    assert "get('agent')" in town, "the town does not read the agent from the URL"
    assert "selectAgent(Number(wanted))" in town


# ------------------------------------------------------- controls that do nothing
# The five footer buttons of the town were `<div>` elements with `cursor:pointer`
# and no handler of any kind. They looked exactly like working controls, which is
# the most misleading thing a control can be — and nothing failed, because nothing
# asked. These tests ask.

def clickable_ids(page: str) -> set[str]:
    """Every id on an element that a reader would try to click."""
    html = (WEB / page).read_text()
    ids = set()
    for tag in re.findall(r"<(?:button|div|span|a)\b[^>]*>", html):
        if "id=" not in tag:
            continue
        clickable = ("<button" in tag or "iconbtn" in tag or "class=\"act" in tag
                     or "class=\"mode" in tag or "class=\"spd" in tag)
        if clickable:
            ids.add(re.search(r'id="([^"]+)"', tag).group(1))
    return ids


@pytest.mark.parametrize("page", PAGES)
def test_every_clickable_element_is_mentioned_by_the_script(page):
    """Deliberately loose about *how* a handler is attached — delegation and loops
    are fine. What it refuses is an id the script never names at all, which is what
    every one of the five dead footer buttons looked like."""
    html = (WEB / page).read_text()
    script = html.split("<script>")[-1]
    orphans = sorted(name for name in clickable_ids(page) if f"#{name}" not in script)
    assert not orphans, f"{page}: looks clickable, never named by the script — {orphans}"


def test_the_town_footer_actions_are_wired():
    """Each of the five reaches a backend capability, by name."""
    html = (WEB / "index.html").read_text()
    for element, endpoint in [
        ("actScenario", "/api/scenarios"),
        ("actLesson", "/api/lessons"),
        ("actNews", "/api/news"),
        ("actParams", "/api/params"),
        ("actReset", "'reset'"),
    ]:
        assert f'id="{element}"' in html, f"button missing: {element}"
        assert f"$('#{element}').onclick" in html, f"{element} has no handler"
        assert endpoint in html, f"{element} does not reach {endpoint}"


def test_the_town_offers_a_first_run_explanation():
    """A newcomer got no statement of what the thing is or what to try."""
    html = (WEB / "index.html").read_text()
    assert 'id="help"' in html
    assert "What is this?" in html
    assert "What to try first" in html
    assert "localStorage" in html, "the explanation has to open by itself on the first visit"


def test_the_town_documents_its_keyboard_shortcuts():
    """The shortcuts existed and nothing on screen said so."""
    html = (WEB / "index.html").read_text()
    shortcuts = html[html.index("<h3>Keys</h3>"):]
    for key in ("Space", "<kbd>]</kbd>", "<kbd>1</kbd>", "<kbd>C</kbd>", "<kbd>?</kbd>"):
        assert key in shortcuts, f"not documented: {key}"


def test_the_town_reports_a_stopped_clock_and_the_warm_up():
    html = (WEB / "index.html").read_text()
    assert "warmProgress" in html, "no progress shown while warming up"
    assert "S.failure" in html, "a stopped simulation has to say so"


# ------------------------------------------------------------- fake figures
# Numbers that were literals in the markup while the backend sent a live value for
# the same thing. They were left over from the demo snapshots and the page showed
# them for as long as it was open: a central bank permanently at 104.70, a suburb
# of exactly 200 and a depot taking in €27,000 forever.
STALE_LITERALS = [
    ("104.70", "central bank label: bind bankRate"),
    ("104,70", "central bank label: bind bankRate"),
    ("+€27,000", "ETF label: bind etfFlow"),
    ("+27 000", "ETF label: bind etfFlow"),
    ("Lv 12", "unit card: bind unitKind"),
    ("#118 AdaptiveTrader", "unit card: bind unit"),
    ("SIX DISTRICTS", "the subtitle is built from markets/agents/seed"),
    ("SECHS VIERTEL", "the subtitle is built from markets/agents/seed"),
]


def test_no_hardcoded_demo_figures_in_the_town_markup():
    """Only the markup, not the generated snapshot — that one is real data."""
    html = (WEB / "index.html").read_text()
    markup = html.split("<script>")[0]
    offenders = [(needle, why) for needle, why in STALE_LITERALS if needle in markup]
    assert not offenders, f"fixed figures in the markup: {offenders}"


def test_every_landmark_on_the_plate_carries_a_live_binding():
    """Each map label reads its number out of the snapshot."""
    html = (WEB / "index.html").read_text()
    labels = html[html.index("const LABELS = ["):html.index("const LABEL_COLOUR")]
    for field in ("bankRate", "noiseN", "etfFlow", "mkrN", "cmpN", "lev"):
        assert f"'{field}'" in labels, f"label without a live field: {field}"


def test_the_offline_snapshot_matches_the_shape_the_backend_sends():
    """The fallback drifted for months and nothing noticed.

    It is what the page draws for the first second of every session and whenever the
    server is not there, so a missing field means a stale figure on screen. Generated
    by `scripts/demo_state.py`; compared here against a live snapshot.
    """
    import sys

    sys.path.insert(0, str(WEB.parent))
    from mes.city import snapshot
    from mes.config import Config
    from mes.simulation import Simulation
    from scripts.demo_state import extract

    embedded = extract((WEB / "index.html").read_text())

    sim = Simulation(Config(seed=3))
    for _ in range(60):
        sim.step()
    live = snapshot(sim)
    live.update(running=False, speed="1x", warming=False, warmProgress=1.0,
                lesson=None, failure=None)

    missing = sorted(set(live) - set(embedded))
    assert not missing, (
        "The offline snapshot is stale. Regenerate it with "
        f"`python scripts/demo_state.py --write`. Missing: {missing}")
    # Rooms carry four fields now: name, figures, what it is for, a member to show.
    assert all(len(row) == 4 for row in embedded["rooms"])


# ------------------------------------------------- candles and the order book
# Both were answerable by the backend from the beginning — `/api/bars` and the
# `bids`/`asks` in `/api/sectors/{symbol}` — and neither page drew either, so the
# mechanism the whole model rests on was the least visible thing in it.

def test_the_town_offers_all_three_market_views():
    html = (WEB / "index.html").read_text()
    for view in ("line", "candles", "book"):
        assert f'data-view="{view}"' in html, f"view missing: {view}"
    for painter in ("paintLine", "paintCandles", "paintBook"):
        assert painter in html, f"painter missing: {painter}"
    assert "/api/bars" in html, "the candles fetch their data nowhere"


def test_the_town_book_reads_the_snapshot_not_a_second_request():
    """It rides along with /api/state, which the town already polls."""
    html = (WEB / "index.html").read_text()
    book = html[html.index("function paintBook"):html.index("async function pullSeries")]
    assert "state.ladder" in book
    assert "fetch(" not in book and "api(" not in book


def test_the_analysis_page_shows_one_instrument_up_close():
    html = (WEB / "sectors.html").read_text()
    for needle in ("renderCandles", "renderBook", 'id="instrument"',
                   "/api/sectors/", "Last traded"):
        assert needle in html, f"missing from sectors.html: {needle}"


def strip_comments(source: str) -> str:
    """Comments only. The prose in this project quotes the code it is about, so a
    grep for a call has to ignore the sentences describing it."""
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return re.sub(r"^\s*//.*$", "", source, flags=re.M)


@pytest.mark.parametrize("page", PAGES)
def test_numbers_use_the_projects_english_format(page):
    """`mes/city.py` writes 49,296 and 63.19 — comma thousands, point decimals. A
    German locale call or a thin-space grouping left in one page would make that page
    the one panel counting differently from every other number on screen."""
    for block in scripts(page):
        code = strip_comments(block)
        german = re.findall(r'toLocaleString\(\s*["\']de-DE["\']', code)
        assert not german, f"{page}: {len(german)}× German number format"
        assert " " not in code and "\\u2009" not in code, (
            f"{page}: groups thousands with a thin space")


@pytest.mark.parametrize("page", PAGES)
def test_no_decimal_comma_is_written_by_hand(page):
    """The German pages turned every decimal point into a comma with
    `.replace('.', ',')`. Left in an English page it turns 63.19 into 63,19."""
    for block in scripts(page):
        code = strip_comments(block)
        assert not re.search(r"""\.replace\(\s*['"]\.['"]\s*,\s*['"],['"]\s*\)""", code), (
            f"{page}: writes a decimal comma")


@pytest.mark.parametrize("page", ["sectors.html", "indices.html", "traders.html"])
def test_the_decimal_formatter_is_english(page):
    source = (WEB / page).read_text()
    assert re.search(r'toLocaleString\("en-US",', source), (
        f"{page}: no en-US decimal formatter found")


# ------------------------------------------------------------- the 3D town
TOWN3D = WEB / "town3d.js"
THREE = WEB / "vendor" / "three.min.js"


def test_the_town_loads_its_renderer_by_relative_path():
    """Relative, so the page still draws when it is opened straight from disk —
    which is also why three.js is a vendored classic script and not a CDN module."""
    html = (WEB / "index.html").read_text()
    assert '<script src="vendor/three.min.js"></script>' in html
    assert '<script src="town3d.js"></script>' in html
    assert (html.index('<script src="vendor/three.min.js">') < html.index('<script src="town3d.js">')
            < html.index("<script>\n"))
    assert THREE.is_file() and THREE.stat().st_size > 500_000
    assert (WEB / "vendor" / "THREE-LICENSE").is_file()


@pytest.mark.skipif(NODE is None, reason="node not available")
def test_the_3d_town_parses():
    for path in (TOWN3D, THREE):
        result = subprocess.run([NODE, "--check", str(path)], capture_output=True, text=True)
        assert result.returncode == 0, (
            f"{path.name} is not valid JavaScript:\n{result.stderr[:600]}")


def test_the_3d_town_brackets_balance():
    stripped = strip_strings_and_comments(TOWN3D.read_text())
    for opener, closer in ("()", "[]", "{}"):
        assert stripped.count(opener) == stripped.count(closer), (
            f"town3d.js: {opener}{closer} unbalanced")


def test_the_3d_town_reads_only_the_model_the_page_builds():
    """Every number on the plate is decided in index.html, where these tests can see
    it. If the renderer started reading the snapshot itself, a height could come from
    somewhere no test looks."""
    source = strip_comments(TOWN3D.read_text())
    for forbidden in ("/api/", "fetch(", "S.capital", "S.flow", "S.runners"):
        assert forbidden not in source, f"town3d.js reads the backend directly: {forbidden}"
    html = (WEB / "index.html").read_text()
    model = html[html.index("function cityModel("):html.index("const LABELS = [")]
    for field in ("buildings(S)", "S.flow", "runners", "S.buyShare", "S.pips", "S.alarm",
                  "S.mood"):
        assert field in model, f"cityModel does not pass {field} to the town"


def test_crate_colours_come_from_the_side_of_the_orders():
    """Green buy, red sell — so the colour has to be the share of buys the backend
    measured, not a random draw."""
    source = TOWN3D.read_text()
    assert "R.buy" in source and "Math.round(n * buy)" in source


# --------------------------------------- what the last three rounds of work added
def test_the_experiments_state_what_they_cost_in_time():
    """Every lesson recommends 45–70 trading days. At 1× that is two to five hours,
    and the panel used to print only the days."""
    for page, source in (("index.html", "sheetLessons"), ("sectors.html", "renderLessons")):
        html = (WEB / page).read_text()
        assert "function duration(" in html, f"{page}: no time formatting"
        assert "seconds_per_step" in html, f"{page}: does not reckon with the clock"
        assert "seconds_left" in html, f"{page}: does not say how long is left"
        # The *definition*, not the first mention — the name also appears in the
        # sheet registry above it, and anchoring there made this depend on how many
        # characters happened to sit in between.
        start = html.index(f"function {source}(")
        block = html[start:start + 6000]
        assert "fastest" in block, f"{page}: does not switch to the fastest speed"


def test_the_town_can_scrub_a_recording():
    """`/api/replay/seek` returned the whole state at every position from the start
    and nothing drew it — a recorded run was readable only as a single price."""
    html = (WEB / "index.html").read_text()
    for needle in ('id="replayBar"', 'id="replayScrub"', 'id="actReplay"',
                   "/api/replay/seek", "function replaySeek", "enterReplay",
                   "leaveReplay"):
        assert needle in html, f"missing from index.html: {needle}"


def test_the_live_poll_leaves_a_replay_frame_alone():
    """Otherwise the recording is overwritten by the live market 700 ms later."""
    html = (WEB / "index.html").read_text()
    start = html.index("async function pull()")
    # Up to the next top-level function, whatever it is called.
    rest = html[start + 10:]
    end = start + 10 + min(
        (i for i in (rest.find("\nfunction "), rest.find("\nasync function "))
         if i != -1), default=len(rest))
    pull = html[start:end]
    assert "if (replayOn)" in pull, "pull() does not tell replay from live"


def test_the_map_offers_both_scales_and_names_them():
    """After a hundred days the spread between the largest and smallest block reaches
    135× and a single linear ladder puts 21 of 35 blocks on the minimum height."""
    html = (WEB / "index.html").read_text()
    assert 'data-scale="euro"' in html and 'data-scale="log"' in html
    assert "PX_PER_DECADE" in html
    # The comparison mode must say it is not euros — that is the whole licence for it.
    assert "not in euros" in html


def test_stacked_floors_are_measured_from_the_cumulative_amount():
    """The borrowed floors sit on the tower's own capital, so the roof belongs at the
    height of the total. Adding two converted heights works on a linear scale and is
    wrong on a logarithmic one."""
    html = (WEB / "index.html").read_text()
    assert "hpx((b.z0eur || 0) + b.eur)" in html, \
        "stacked floors are not measured from the total"
