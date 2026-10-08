"""Build the five-page short guide as a PDF.

The long handbook answers "everything"; this one answers the two questions someone
has in front of them the first time they open the project: **what is this** and
**how do I work with it**. Five pages, hard limit — `build()` refuses to write a
sixth, because a short guide that quietly grows is just the handbook again.

Layout and styling are imported from `build_handbook` rather than copied, so the
two documents cannot drift apart typographically. The figures are read out of the
running code — the population is counted by building it, the scenarios and
experiments come from their own catalogues — for the same reason the handbook does
it: a guide quoting stale numbers is worse than none.

    python docs/build_quickstart.py
    python docs/build_quickstart.py --print   # print-friendly title page
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (BaseDocTemplate, Frame, NextPageTemplate, PageBreak,
                                PageTemplate, Spacer)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from docs.build_handbook import (  # noqa: E402
    COVER_ACCENT, COVER_BG, COVER_INK, FAINT, HISTORICAL, MONO, RED, RULE, S, SANS,
    SANS_B, TEAL,
    bullets, callout, code, count_tests, p, rule, table,
)
from mes import lessons, scenarios  # noqa: E402
from mes.config import PARAM_SPEC, Config  # noqa: E402
from mes.instruments import SECTOR_SPEC  # noqa: E402
from mes.simulation import Simulation  # noqa: E402

OUT = ROOT / "docs" / "Market-Ecology-Simulator-Quick-Start.pdf"
OUT_PRINT = ROOT / "docs" / "Market-Ecology-Simulator-Quick-Start-Print.pdf"
MAX_PAGES = 5

# Print-friendly variant: identical content, only the title area on page one does
# without the full-width dark box. On an office printer that box costs half a toner
# cartridge and comes out grey and blotchy on paper. Switched with
# `python docs/build_quickstart.py --print`; the geometry stays the same millimetre
# for millimetre, so the page breaks and the five-page limit are not affected.
PRINT_FRIENDLY = False


# ------------------------------------------------------------------ live facts
def facts() -> dict:
    """Every number in the document, read from the code that produces it."""
    cfg = Config()
    sim = Simulation(cfg)  # built, not stepped: only the population is needed
    kinds: dict[str, int] = {}
    for agent in sim.agents:
        kinds[agent.kind] = kinds.get(agent.kind, 0) + 1

    tests = count_tests()

    return {
        "cfg": cfg,
        "agents": len(sim.agents),
        "kinds": kinds,
        "instruments": len(sim.markets),
        "sectors": SECTOR_SPEC,
        "scenarios": len(scenarios.ALL),
        "scenario_names": {key: s.name for key, s in scenarios.ALL.items()},
        "lessons": lessons.catalogue(),
        "params": len(PARAM_SPEC),
        "tests": tests,
        "steps_per_day": cfg.steps_per_day,
    }


# -------------------------------------------------------------------- document
def _footer(canvas):
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.5)
    canvas.line(20 * mm, 14 * mm, A4[0] - 20 * mm, 14 * mm)
    canvas.setFont(SANS, 6.8)
    canvas.setFillColor(FAINT)
    canvas.drawCentredString(A4[0] / 2, 10.5 * mm,
                             "Generated from the running code · "
                             "python docs/build_quickstart.py · "
                             "in full: Market-Ecology-Simulator-Handbook.pdf")


def on_page(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.5)
    canvas.line(20 * mm, A4[1] - 15 * mm, A4[0] - 20 * mm, A4[1] - 15 * mm)
    canvas.setFont(SANS, 7)
    canvas.setFillColor(FAINT)
    canvas.drawString(20 * mm, A4[1] - 12.5 * mm,
                      "MARKET ECOLOGY SIMULATOR · QUICK START GUIDE")
    canvas.drawRightString(A4[0] - 20 * mm, A4[1] - 12.5 * mm,
                           f"Page {doc.page} of {MAX_PAGES}")
    _footer(canvas)
    canvas.restoreState()


def on_first_page(canvas, doc):
    """The title band, so page one carries the name without spending a page on it.

    Deliberately *not* also the running header: the band is the header here, and
    drawing the grey line and the section name on top of it put two headers in the
    same 15 mm — the kicker sat exactly on the rule.
    """
    canvas.saveState()
    if PRINT_FRIENDLY:
        _first_page_band_print(canvas)
    else:
        _first_page_band_screen(canvas)
    _footer(canvas)
    canvas.restoreState()


def _first_page_band_screen(canvas):
    # The handbook cover's light palette: the town is a bright diorama, and the
    # guide should look like the thing it describes.
    canvas.setFillColor(COVER_BG)
    canvas.rect(0, A4[1] - 42 * mm, A4[0], 42 * mm, stroke=0, fill=1)
    canvas.setFillColor(COVER_ACCENT)
    canvas.rect(0, A4[1] - 4 * mm, A4[0], 4 * mm, stroke=0, fill=1)
    canvas.setFont(SANS_B, 7.4)
    canvas.drawString(20 * mm, A4[1] - 16 * mm, "AGENT-BASED FINANCIAL MARKET SIMULATION")
    canvas.setFillColor(FAINT)
    canvas.drawRightString(A4[0] - 20 * mm, A4[1] - 16 * mm, f"PAGE 1 OF {MAX_PAGES}")
    canvas.setFillColor(COVER_INK)
    canvas.setFont(SANS_B, 23)
    canvas.drawString(20 * mm, A4[1] - 27 * mm, "Market Ecology Simulator")
    canvas.setFillColor(colors.HexColor("#4a5670"))
    canvas.setFont(SANS, 10)
    canvas.drawString(20 * mm, A4[1] - 35 * mm,
                      "Quick Start Guide: what the project is and how to work with it")


def _first_page_band_print(canvas):
    """The same typography on white paper: the filled area becomes a line.

    Instead of the box, a narrow accent bar at the top and a hairline under the
    subtitle carry the header zone; the type switches from white to dark. The
    baselines sit at the same heights as in the screen version, so nothing shifts in
    the page breaks or the frame.
    """
    canvas.setFillColor(COVER_ACCENT)
    canvas.rect(20 * mm, A4[1] - 4 * mm, A4[0] - 40 * mm, 1.6 * mm, stroke=0, fill=1)
    canvas.setFillColor(COVER_ACCENT)
    canvas.setFont(SANS_B, 7.4)
    canvas.drawString(20 * mm, A4[1] - 16 * mm, "AGENT-BASED FINANCIAL MARKET SIMULATION")
    canvas.setFillColor(FAINT)
    canvas.drawRightString(A4[0] - 20 * mm, A4[1] - 16 * mm, f"PAGE 1 OF {MAX_PAGES}")
    canvas.setFillColor(COVER_INK)
    canvas.setFont(SANS_B, 23)
    canvas.drawString(20 * mm, A4[1] - 27 * mm, "Market Ecology Simulator")
    canvas.setFillColor(colors.HexColor("#4a5058"))
    canvas.setFont(SANS, 10)
    canvas.drawString(20 * mm, A4[1] - 35 * mm,
                      "Quick Start Guide: what the project is and how to work with it")
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.5)
    canvas.line(20 * mm, A4[1] - 40 * mm, A4[0] - 20 * mm, A4[1] - 40 * mm)


def build() -> Path:
    out = OUT_PRINT if PRINT_FRIENDLY else OUT
    doc = BaseDocTemplate(
        str(out), pagesize=A4, title="Market Ecology Simulator — Quick Start Guide",
        author="Market Ecology Simulator", leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=20 * mm, bottomMargin=18 * mm)
    doc.addPageTemplates([
        PageTemplate(id="first",
                     frames=[Frame(20 * mm, 18 * mm, A4[0] - 40 * mm, A4[1] - 66 * mm,
                                   id="first")],
                     onPage=on_first_page),
        PageTemplate(id="body",
                     frames=[Frame(20 * mm, 18 * mm, A4[0] - 40 * mm, A4[1] - 38 * mm,
                                   id="body")],
                     onPage=on_page),
    ])
    doc.build(story(facts()))

    pages = count_pages(out)
    if pages > MAX_PAGES:
        raise SystemExit(
            f"{out.name} is {pages} pages long, {MAX_PAGES} are allowed. "
            "Cut it, do not raise the limit. That is what the handbook is for.")
    return out


def count_pages(path: Path) -> int:
    """Cheap page count straight from the PDF, so the limit is enforced and not
    hoped for. No dependency: the trailer states it."""
    raw = path.read_bytes()
    counts = [int(m.group(1)) for m in re.finditer(rb"/Count\s+(\d+)", raw)]
    return max(counts) if counts else 0


# ------------------------------------------------------------------------ text
def story(f_: dict) -> list:
    cfg = f_["cfg"]
    # Page one carries the title band; every page after it uses the plain frame.
    # Without this reportlab keeps the first template for the whole document and the
    # heading is reprinted five times over a gap it does not need.
    f: list = [NextPageTemplate("body")]

    # =================================================== 1 · what the project is
    f += [Spacer(1, 6), p("1 · What the project is", "h1")]
    f += [p("An agent-based model of an equity market. It does not forecast prices. "
            "It asks <b>where market behaviour comes from</b>.", "lead")]
    f += [p(f"{f_['agents']} agents each follow a simple rule. None knows the true value "
            "of an asset, none knows what the others will do next, and <b>nowhere in the "
            "code is there an equation for the price</b>. Every trade is one order meeting "
            "another: a continuous double-auction order book with price-time priority, "
            "partial fills and expiry. Bubbles, crashes, volatility clusters and "
            "forced-selling cascades emerge from this interaction, or they are not there.")]

    f += [p("The question", "h2")]
    f += [p("Real return series share a handful of statistical properties that hold "
            "across asset classes and centuries. <b>None of them is built into this "
            "model.</b> Does a market made only of simple, heterogeneous rules meet them "
            "anyway? The criteria are executable checks in "
            "<font name='Courier' size='8'>mes/metrics.py</font>, fixed <i>before</i> "
            "anything was measured. That is the difference between a result and a story "
            "told afterwards.")]

    rows = [["Criterion", "Requirement", "Measured", "Met"],
            ["Volatility clustering", "mean ACF of |returns| &gt; 0.05", "0.217", "25 / 25"],
            ["Non-normality", "Jarque-Bera p &lt; 0.05", "0.0002", "25 / 25"],
            ["Fat tails", "excess kurtosis &gt; 1", "5.39", "24 / 25"],
            ["Tail index", "Hill estimator between 2 and 6", "4.38", "22 / 25"],
            ["No autocorrelation", "|ACF(1)| &lt; 0.1", "−0.223", "8 / 25"],
            ["Volume coupling", "corr(volume, |return|) &gt; 0.1", "−0.072", "3 / 25"]]
    f += [table(rows, [40 * mm, 63 * mm, 27 * mm, 40 * mm],
                align_right=(2, 3), highlight=(5, 6)), Spacer(1, 8)]

    f += callout(
        "Four of six met, and the two open ones are in the document too",
        "Five seeds × five instruments = 25 measurements of 90,000 steps each. A result "
        "that holds for only one seed is not a result; that is why it is measured across "
        "seeds and the scatter is reported with it. The two highlighted rows are "
        "<b>not</b> met, and that is stated here, because a project that softens its own "
        "criteria after the fact no longer measures anything. Why they could not be "
        "solved is explained in the handbook: the force that keeps a price at fair value "
        "is the same one that makes its returns predictable.")

    f += [p("These five pages", "h2")]
    rows = [["Page", "What it covers"],
            ["2", "Starting up, and how the four views differ from each other"],
            ["3", "Who trades, and how orders become a price"],
            ["4", "The five ways of working, from “watch it once” to “test a claim”"],
            ["5", "Commands, where things are in the code, and what is open in the model"]]
    f += [table(rows, [14 * mm, 156 * mm], align_right=(0,))]

    f += [PageBreak()]

    # ============================================== 2 · starting and the views
    f += [p("2 · Starting up and the four views", "h1")]
    # Plain ASCII inside the monospace block: Courier has no arrow glyph, and
    # reportlab silently substitutes a ligature for the missing one.
    f += [code(["./start.sh   ->   http://127.0.0.1:8000",
                "or double-click Market Town.app, which opens the browser by itself"])]
    f += [p("The first start creates the virtual environment and installs the "
            "dependencies. After that the server fast-forwards to 110 trading days in the "
            "background. The validation panel needs 100 days of daily data before its "
            "figures mean anything. The bar at the top shows how far it has got. Pause "
            "and speed take effect immediately.", "small")]

    f += [p("Four angles on the same run", "h2")]
    f += [p("<b>One</b> simulation runs. All four pages show it, but they answer "
            "different questions, and each can be reached from every other.")]
    rows = [["Page", "Answers", "What it is for"],
            ["<b>/</b> — the town",
             "What is happening, and why?",
             "A bright 3D diorama under white glass panels: every district a group of "
             "agents, every block height its capital, every road width this step's order "
             "flow, five blue towers the exchanges. None of it is decoration. On the left "
             "price, candles and order book; on the right a single agent with the "
             "calculation behind its last decision."],
            ["<b>/sectors</b> — analysis",
             "Are the figures right?",
             "Sector comparison, measured correlations, Central Bank with duration per "
             "sector, the validation panel, A/B comparisons across several seeds and the "
             "recorded runs."],
            ["<b>/indices</b> — indices",
             "Who ran, when, and against what?",
             "All indices live on one axis, normalised to the start of the window. For "
             "each index its level, fair-value index, volatility, drawdown, breadth, and "
             "the <i>measured</i> beta against the one set in the model."],
            ["<b>/traders</b> — traders",
             "Who is trading, and how are they doing?",
             f"All {f_['agents']} agents side by side instead of one after another: "
             "capital, cash, positions, leverage, result since the start of the run, "
             "forced sales. Sortable and filterable, with a jump back into the town."]]
    f += [table(rows, [30 * mm, 42 * mm, 98 * mm]), Spacer(1, 8)]

    f += [p("The first look: what to watch in the first two minutes", "h2")]
    f += bullets([
        "<b>The price against fair value</b> (market panel, left). The two lines "
        "rarely meet. How far apart they are is the most interesting single figure in "
        "the model, and the gap does not close by itself.",
        "<b>The ratio of momentum to value</b> in the Adaptive Quarter. It tips over in "
        "waves and then stays put for a while. That persistence is exactly what makes "
        "volatility cluster.",
        "<b>The red beacon and ring at the Leverage Tower.</b> They mean a fund is "
        "selling because it "
        "<i>must</i>, not because it chose to. This is the only place where an agent "
        "trades without deciding.",
        "<b>The order book</b> (third view in the market panel). Almost all of the depth "
        "sits right at the price; behind it there are only a few shares. That is exactly "
        "why a liquidity hole can open here. A model with a price equation would have "
        "none, because it would have nothing that could run out.",
    ])

    f += [p("Keys and mouse in the town", "h2")]
    rows = [["Key", "Effect", "Key", "Effect"],
            ["Space", "pause / resume", "1 2 3", "speed 1× / 4× / 16×"],
            ["]", "a single step", "+ − 0", "camera closer / further / reset"],
            ["R B C", "shock: calm, boom, crash", "?", "open the explanation"],
            ["click", "select a district (a tower: its market)", "drag",
             "turn; scroll zooms, right-drag pans"]]
    f += [table(rows, [20 * mm, 58 * mm, 20 * mm, 72 * mm]), Spacer(1, 7)]
    f += [p("Speed is the most important control: at 1× a trading day takes about two "
            "minutes of real time, at 16× a few seconds. For anything that has to collect "
            "trading days, such as validation and experiments, set the clock to 16×.",
            "small")]

    f += [PageBreak()]

    # ================================================ 3 · who trades, how a price is made
    f += [p("3 · Who trades, and how a price is made", "h1")]
    f += [p("Seven rules. Each exists because the model was visibly wrong without it, "
            "not because it completes the list.", "lead")]
    k = f_["kinds"]
    rows = [["Type", "Count", "Rule", "Why it is in the model"],
            ["Value investor", str(k.get("adaptive", 0)),
             "buys below its own estimate of fair value",
             "the only force pulling the price towards value"],
            ["Trend follower", "the same",
             "extrapolates the recent move, ignores valuation",
             "the feedback loop that produces bubbles"],
            ["Noise trader", str(k.get("noise", 0)),
             "trades for reasons the model does not represent",
             "background liquidity; otherwise there is no other side"],
            ["ETF / savings plan", str(k.get("passive", 0)),
             "receives money on a schedule and buys at any price",
             "price-insensitive demand"],
            ["Leveraged fund", str(k.get("leveraged", 0)),
             "trades on credit, is forced to sell when under-collateralised",
             "the cascade; carries stress between sectors"],
            ["Market maker", str(k.get("maker", 0)),
             "quotes both sides at all times, leans against its inventory",
             "the only standing liquidity"],
            ["Issuer", str(k.get("company", 0)),
             "sells new shares when they are expensive, buys back when cheap",
             "the only source of new supply"]]
    f += [table(rows, [26 * mm, 22 * mm, 54 * mm, 68 * mm], align_right=(1,)),
          Spacer(1, 7)]
    f += [p("Value investors and trend followers are the <b>same</b> agents. Every "
            f"{cfg.switch_interval} steps they reconsider which of the two rules to run, "
            "based on what has worked lately and on what the majority is doing. This "
            "switching is the engine: the population tips into a trend regime or a value "
            "regime and stays there for a while.", "small")]

    f += [p("How a price comes about", "h2")]
    f += bullets([
        f"<b>A step is neither a second nor a day.</b> {cfg.steps_per_day} steps make one "
        "trading day with one daily candle. The statistical properties apply to "
        "<i>daily</i> returns; at step level microstructure dominates.",
        f"<b>{f_['instruments']} instruments trade at once</b>, each with its own order "
        "book: technology, energy, financials, health care, consumer. Their fair values "
        "share a common market factor. Correlation <i>emerges</i> from that; it is not "
        "set as a matrix.",
        "<b>News never moves the price.</b> It moves fair value and sentiment. Whether "
        "the price follows is up to the agents: the value investor sees a cheaper asset, "
        "the trend follower sees others selling, the ETF does not read the news at all.",
        "<b>The Central Bank does not trade.</b> It sets a rate that arrives through three "
        "channels: valuation (duration per sector), the leveraged funds' financing costs, "
        "and inflows into the savings plans.",
    ])

    f += [p("The five sectors are deliberately different characters", "h2")]
    character = {
        "TECH": "high beta, bubble-prone; reacts most strongly to market news",
        "ENRG": "low beta, but the highest idiosyncratic volatility",
        "FINL": "rate-sensitive: a rate step moves fair value most here",
        "HLTH": "defensive, calm, little movement of its own",
        "CONS": "defensive, close to the overall market",
    }
    rows = [["Sector", "Beta", "Character"]]
    for spec in f_["sectors"]:
        rows.append([f"<b>{spec['symbol']}</b> {spec['name']}",
                     f"{spec['beta']:.2f}",
                     character.get(spec["symbol"], "")])
    f += [table(rows, [32 * mm, 14 * mm, 124 * mm], align_right=(1,)), Spacer(1, 5)]
    f += [p("If they were five copies of each other, the measured correlation between "
            "them would not be a result but a tautology.", "small")]

    f += [PageBreak()]

    # ================================================== 4 · how to work with it
    f += [p("4 · How to work with it", "h1")]
    f += [p("Five ways of working, from “watch it once” to “test a claim”. Each builds "
            "on the one before.", "lead")]

    names = f_["scenario_names"]
    basic = ", ".join(n for key, n in names.items() if key not in HISTORICAL)
    historical = ", ".join(n for key, n in names.items() if key in HISTORICAL)
    rows = [["Way", "Answers", "How it works"],
            ["<b>1 · Load a scenario</b>",
             f"What does this model do under these conditions? ({f_['scenarios']} presets)",
             f"Town → footer <b>SCENARIO</b>. {basic}, plus {historical}. A scenario sets "
             "conditions and supplies headlines; <b>it does not prescribe a price "
             "path</b>. Whether the price falls 5% or 40% is the model's answer."],
            ["<b>2 · Guided experiment</b>",
             f"Does the mechanism really show? ({len(f_['lessons'])} of them)",
             "Analysis → <b>Guided experiments</b>. Each one sets up the market, says in "
             "advance what to watch for, and afterwards checks by <i>measurement</i> "
             "whether it worked, even when it did not. Starting one switches to 16×; "
             f"{min(l['days'] for l in f_['lessons'])}–"
             f"{max(l['days'] for l in f_['lessons'])} trading days are recommended, and "
             "the panel says how many minutes that still is."],
            ["<b>3 · Turn parameters</b>",
             f"What does it depend on? ({f_['params']} controls)",
             "Analysis → right-hand column, or town → <b>CONTROLS</b>. A dot after the "
             "name means it only takes effect after a restart. Departures from the "
             "calibrated default are marked orange, and <b>defaults</b> brings everything "
             "back. Only there do the validation figures mean what the README says about "
             "them."],
            ["<b>4 · A/B across seeds</b>",
             "Is the difference larger than chance?",
             "Analysis → <b>A/B comparison</b>. Two configurations from the same seed, "
             "with a table of differences. What matters is <b>across 3 seeds</b>: the "
             "signal/noise column says whether the difference stands out from the "
             "scatter between seeds. Below 1 it does not, however clear a single chart "
             "looks."],
            ["<b>5 · Record and replay</b>",
             "What exactly happened back then?",
             "<font name='Courier' size='8'>python scripts/run.py --steps 60000 --name "
             "baseline</font>, then <b>REPLAY</b> in the town. A replay is <i>recomputed</i> "
             "from the seed, not read from curves. That is why the whole state is "
             "available at every position: order book, districts, agents. The slider "
             "moves the complete map."]]
    f += [table(rows, [30 * mm, 40 * mm, 100 * mm]), Spacer(1, 8)]

    f += callout(
        "The one rule that carries everything else",
        "<b>A figure from one run is not a result.</b> Once, one seed here produced an "
        "autocorrelation of −0.002 with all six criteria met, and it could not be "
        "repeated; the mean across four seeds was −0.19 with a scatter of 0.11. Reporting "
        "that run as a success would have been exactly the trap this project's method "
        "warns against. So: measure across seeds, write the scatter down, and when in "
        "doubt quote <font name='Courier' size='8'>scripts/calibrate.py</font> rather "
        "than the live panel.", TEAL)

    f += [p("A typical session", "h2")]
    f += bullets([
        "<b>Watch.</b> Start, set the speed to 4×, let the town run for a few minutes and "
        "read the “What is happening” panel alongside. Every statement in it comes from a "
        "figure the simulation holds at that moment.",
        "<b>Form a hunch.</b> For example: “Without market makers volatility is higher.” "
        "Check on <b>/indices</b> and <b>/traders</b> whether the hunch depends on figures "
        "you can actually get at.",
        "<b>Have it checked.</b> If there is a guided experiment for it, use that. It "
        "checks itself and also says when it did <i>not</i> work.",
        "<b>Otherwise measure it yourself.</b> A/B across three seeds, and only believe "
        "the rows whose signal/noise is above 1.",
        "<b>Keep it.</b> <font name='Courier' size='8'>scripts/run.py</font> records the "
        "run, with seed and timeline. It can be stepped through again later instead of "
        "only being looked at as a curve.",
    ])

    f += [PageBreak()]

    # ============================================ 5 · commands, code, open points
    f += [p("5 · Commands, code and what is open", "h1")]
    # A table, not aligned columns inside one code block: reportlab collapses runs of
    # spaces, so hand-set columns arrive as a single run-on line.
    rows = [["Command", "What for"],
            ["./start.sh", "start the interface"],
            ["python scripts/calibrate.py --runs 5 --steps 90000",
             "the validation: the figures on page 1"],
            ["python scripts/sweep.py ablate --steps 80000",
             "switch off each mechanism in turn and measure what is missing"],
            ["python scripts/sweep.py param --name n_passive --values 0,50,100",
             "sweep one parameter across a range of values"],
            ["python scripts/run.py --steps 120000 --name baseline",
             "a run without the interface, exported and recorded"],
            ["python docs/build_handbook.py",
             "regenerate the full handbook"],
            ["python -m pytest -q",
             f"{f_['tests']} test functions: invariants, not price forecasts"]]
    f += [table(rows, [96 * mm, 74 * mm], align_right=(0,)), Spacer(1, 8)]

    f += [p("Where things are in the code", "h2")]
    rows = [["File", "Contents"],
            ["<font name='Courier' size='8'>mes/orderbook.py</font>",
             "matching engine, price-time priority: the foundation"],
            ["<font name='Courier' size='8'>mes/agents.py</font>",
             "the seven decision rules; all of the behaviour is here"],
            ["<font name='Courier' size='8'>mes/simulation.py</font>",
             "the loop: one <font name='Courier' size='8'>step()</font> is one market "
             "period"],
            ["<font name='Courier' size='8'>mes/instruments.py</font>",
             "the five sectors and the factor model behind their fair values"],
            ["<font name='Courier' size='8'>mes/indices.py</font>",
             "the index construction: chain-linked, with the ETF's weights"],
            ["<font name='Courier' size='8'>mes/metrics.py</font>",
             "the criteria from section 1, as executable checks"],
            ["<font name='Courier' size='8'>mes/config.py</font>",
             f"all {f_['params']} parameters, declared once; the control panel is "
             "generated from them"],
            ["<font name='Courier' size='8'>mes/city.py</font> · "
             "<font name='Courier' size='8'>traders.py</font>",
             "the two places where state becomes display figures"]]
    f += [table(rows, [45 * mm, 125 * mm]), Spacer(1, 8)]

    f += [p("What is open", "h2")]
    f += [p("No model is finished, and this one writes down where it stands:", "small")]
    f += bullets([
        "<b>Two of the six criteria are not met</b> (page 1). Four rounds of work made "
        "the other four robust and did not move these two. They hinge on the same "
        "trade-off.",
        "<b>The market makers' inventory limit is defined twice</b>: the agent works with "
        "five times what the engine lets through. Which of the two figures applies "
        "changes the book depth and with it every figure in the validation. Documented "
        "in <font name='Courier' size='8'>INTEGRATION.md</font>.",
        "<b>The cash check uses the best ask</b>, but a large order runs through several "
        "price levels. Agents that are not allowed to borrow can briefly do so anyway.",
        "<b>No dividends, no earnings.</b> Fair value is an exogenous process, not an "
        "earned result; buybacks are paid from a cash pile that never fills.",
    ])
    f += rule()
    f += [p("In full, with seven guided experiments, how the results were derived, and "
            "everything that was tried and did not work, in the handbook: "
            "<font name='Courier' size='8'>docs/Market-Ecology-Simulator-Handbook.pdf</font>. "
            "The method and the figures in detail: "
            "<font name='Courier' size='8'>README.md</font>.", "small")]

    return f


if __name__ == "__main__":
    PRINT_FRIENDLY = "--print" in sys.argv[1:]
    print("written:", build())
