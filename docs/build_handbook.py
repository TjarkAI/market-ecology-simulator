"""Build the project handbook as a PDF.

Kept as a script rather than a one-off so the document can be regenerated when the
figures change — a handbook quoting stale calibration numbers is worse than none.
Every number in here comes from `scripts/calibrate.py` and is labelled with the
sample it was measured on. The names of the guided experiments, the scenarios and
the controls are read from the code that defines them, so a renamed lesson cannot
leave the handbook quoting the old title.

    python docs/build_handbook.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (BaseDocTemplate, Frame, KeepTogether, NextPageTemplate,
                                PageBreak, PageTemplate, Paragraph, Spacer, Table,
                                TableStyle)

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mes import lessons, scenarios  # noqa: E402
from mes.config import PARAM_SPEC  # noqa: E402

OUT = Path(__file__).resolve().parent / "Market-Ecology-Simulator-Handbook.pdf"


def count_tests() -> int:
    """The tests pytest actually runs, parametrised cases included — the same number
    `pytest` prints and the README quotes. Counted rather than quoted; the quick start
    uses this too, so the documents cannot disagree about it. Falls back to counting
    test functions if pytest cannot be run."""
    import subprocess
    import sys
    try:
        out = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-o", "addopts="],
                             cwd=ROOT, capture_output=True, text=True, timeout=120).stdout
        found = re.search(r"(\d+) tests? collected", out)
        if found:
            return int(found.group(1))
    except (OSError, subprocess.SubprocessError):
        pass
    return sum(len(re.findall(r"^def test_", path.read_text(encoding="utf-8"), re.M))
               for path in sorted((ROOT / "tests").glob("test_*.py")))

INK = colors.HexColor("#1d2126")
DIM = colors.HexColor("#5f6873")
FAINT = colors.HexColor("#8d949d")
RULE = colors.HexColor("#d8dce1")
BAND = colors.HexColor("#f2f4f6")
AMBER = colors.HexColor("#b96219")
TEAL = colors.HexColor("#1d7a68")
RED = colors.HexColor("#b1372c")
DARK = colors.HexColor("#171a1f")
# The cover uses the town's own light palette: the interface is a bright diorama.
COVER_BG = colors.HexColor("#e9eef5")
COVER_INK = colors.HexColor("#172033")
COVER_ACCENT = colors.HexColor("#2f5bea")

MONO = "Courier"
SANS = "Helvetica"
SANS_B = "Helvetica-Bold"


# --------------------------------------------------------------------- styles
def styles() -> dict:
    base = getSampleStyleSheet()
    s = {}
    s["title"] = ParagraphStyle("title", parent=base["Normal"], fontName=SANS_B,
                                fontSize=27, leading=31, textColor=COVER_INK)
    s["subtitle"] = ParagraphStyle("subtitle", parent=base["Normal"], fontName=SANS,
                                   fontSize=12.5, leading=18,
                                   textColor=colors.HexColor("#4a5670"))
    s["kicker"] = ParagraphStyle("kicker", parent=base["Normal"], fontName=SANS_B,
                                 fontSize=8, leading=12, textColor=COVER_ACCENT)
    s["h1"] = ParagraphStyle("h1", parent=base["Normal"], fontName=SANS_B, fontSize=16,
                             leading=20, textColor=INK, spaceBefore=2, spaceAfter=7)
    s["h2"] = ParagraphStyle("h2", parent=base["Normal"], fontName=SANS_B, fontSize=11,
                             leading=15, textColor=INK, spaceBefore=13, spaceAfter=4)
    s["h3"] = ParagraphStyle("h3", parent=base["Normal"], fontName=SANS_B, fontSize=9,
                             leading=13, textColor=AMBER, spaceBefore=10, spaceAfter=3)
    s["body"] = ParagraphStyle("body", parent=base["Normal"], fontName=SANS, fontSize=9.3,
                               leading=14.2, textColor=INK, spaceAfter=6,
                               alignment=TA_LEFT)
    s["lead"] = ParagraphStyle("lead", parent=s["body"], fontSize=10.5, leading=16,
                               textColor=colors.HexColor("#33393f"), spaceAfter=9)
    s["small"] = ParagraphStyle("small", parent=s["body"], fontSize=8.1, leading=12,
                                textColor=DIM, spaceAfter=4)
    s["bullet"] = ParagraphStyle("bullet", parent=s["body"], leftIndent=11,
                                 bulletIndent=1, spaceAfter=3.5)
    s["code"] = ParagraphStyle("code", parent=base["Normal"], fontName=MONO, fontSize=8.4,
                               leading=12.6, textColor=colors.HexColor("#22262b"),
                               backColor=BAND, borderPadding=(6, 7, 6, 7),
                               spaceBefore=3, spaceAfter=8, leftIndent=1)
    s["cell"] = ParagraphStyle("cell", parent=base["Normal"], fontName=SANS, fontSize=8.2,
                               leading=11.4, textColor=INK)
    s["cellb"] = ParagraphStyle("cellb", parent=s["cell"], fontName=SANS_B)
    s["cellm"] = ParagraphStyle("cellm", parent=s["cell"], fontName=MONO, fontSize=8)
    s["head"] = ParagraphStyle("head", parent=s["cell"], fontName=SANS_B, fontSize=7.4,
                               textColor=DIM)
    s["quote"] = ParagraphStyle("quote", parent=s["body"], leftIndent=9, fontSize=9.3,
                                textColor=colors.HexColor("#33393f"), spaceBefore=3,
                                spaceAfter=8, borderPadding=(0, 0, 0, 0))
    s["footer"] = ParagraphStyle("footer", parent=base["Normal"], fontName=SANS,
                                 fontSize=7.2, textColor=FAINT, alignment=TA_CENTER)
    return s


S = styles()


# ----------------------------------------------------------------- components
def p(text, style="body"):
    """Accepts a style name or a ready-made ParagraphStyle."""
    return Paragraph(text, S[style] if isinstance(style, str) else style)


def bullets(items, style="bullet"):
    return [Paragraph(f"<bullet>&#8226;</bullet> {i}", S[style]) for i in items]


def code(lines):
    return Paragraph("<br/>".join(lines), S["code"])


def rule(space_before=4, space_after=8, colour=RULE):
    t = Table([[""]], colWidths=[165 * mm], rowHeights=[0.6])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colour),
                           ("TOPPADDING", (0, 0), (-1, -1), 0),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    return [Spacer(1, space_before), t, Spacer(1, space_after)]


def table(rows, widths, header=True, zebra=True, align_right=(), highlight=()):
    data = []
    for r, row in enumerate(rows):
        line = []
        for c, cell in enumerate(row):
            if isinstance(cell, Paragraph):
                line.append(cell)
            else:
                style = "head" if (header and r == 0) else (
                    "cellm" if c in align_right else "cell")
                line.append(Paragraph(str(cell), S[style]))
        data.append(line)

    # repeatRows: a table that breaks across pages carries its header along, and is
    # never split so that the header row is left alone at the foot of a page.
    t = Table(data, colWidths=widths, hAlign="LEFT", repeatRows=1 if header else 0)
    cmd = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, RULE),
    ]
    for c in align_right:
        cmd.append(("ALIGN", (c, 0), (c, -1), "RIGHT"))
    if header:
        cmd += [("BACKGROUND", (0, 0), (-1, 0), BAND),
                ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.HexColor("#c3c9d0"))]
    if zebra:
        start = 1 if header else 0
        for r in range(start, len(data)):
            if (r - start) % 2 == 1:
                cmd.append(("BACKGROUND", (0, r), (-1, r), colors.HexColor("#fafbfc")))
    for r in highlight:
        cmd.append(("BACKGROUND", (0, r), (-1, r), colors.HexColor("#fdf1e7")))
    t.setStyle(TableStyle(cmd))
    return t


def callout(title, text, colour=AMBER):
    inner = [Paragraph(title, ParagraphStyle("ct", parent=S["cellb"], fontSize=8.2,
                                             textColor=colour)),
             Paragraph(text, ParagraphStyle("cb", parent=S["cell"], fontSize=8.5,
                                            leading=12.4))]
    t = Table([[inner]], colWidths=[165 * mm], hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fbfcfd")),
        ("LINEBEFORE", (0, 0), (0, -1), 2.2, colour),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("RIGHTPADDING", (0, 0), (-1, -1), 9),
    ]))
    return [t, Spacer(1, 9)]


def verdict(ok: bool) -> Paragraph:
    mark, colour = ("met", TEAL) if ok else ("open", RED)
    return Paragraph(mark, ParagraphStyle("v", parent=S["cellb"], textColor=colour,
                                          fontSize=8))


# ------------------------------------------------------------------- document
def on_cover(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(COVER_BG)
    canvas.rect(0, 0, A4[0], A4[1], stroke=0, fill=1)
    canvas.setFillColor(COVER_ACCENT)
    canvas.rect(0, A4[1] - 6 * mm, A4[0], 6 * mm, stroke=0, fill=1)
    # A skyline, because the interface is a town: pale district blocks, and five
    # blue towers in the middle for the five exchanges.
    heights = [16, 34, 24, 46, 28, 58, 38, 20, 44, 30, 52, 26, 36, 22, 40]
    w = A4[0] / len(heights)
    canvas.setFillColor(colors.HexColor("#d3dbe7"))
    for i, h in enumerate(heights):
        canvas.rect(i * w, 0, w - 1.5, h * mm * 0.5, stroke=0, fill=1)
    canvas.setFillColor(colors.HexColor("#c2cddd"))
    for i, h in enumerate(heights):
        if i % 3:
            continue
        canvas.rect(i * w + 4, 0, 10, h * mm * 0.34, stroke=0, fill=1)
    canvas.setFillColor(colors.HexColor("#9db2f2"))
    for k, h in enumerate([40, 52, 64, 52, 40]):
        canvas.rect(A4[0] / 2 + (k - 2.5) * 13 * mm + 2 * mm, 0, 9 * mm, h * mm, stroke=0,
                    fill=1)
    canvas.restoreState()


def on_page(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.5)
    canvas.line(22 * mm, A4[1] - 16 * mm, A4[0] - 22 * mm, A4[1] - 16 * mm)
    canvas.setFont(SANS, 7.2)
    canvas.setFillColor(FAINT)
    canvas.drawString(22 * mm, A4[1] - 13.5 * mm, "MARKET ECOLOGY SIMULATOR · HANDBOOK")
    canvas.drawRightString(A4[0] - 22 * mm, A4[1] - 13.5 * mm, f"Page {doc.page - 1}")
    canvas.line(22 * mm, 15 * mm, A4[0] - 22 * mm, 15 * mm)
    canvas.setFont(SANS, 7)
    canvas.drawCentredString(A4[0] / 2, 11 * mm,
                             "All figures from scripts/calibrate.py · 5 seeds × 5 instruments × 90,000 steps")
    canvas.restoreState()


def build():
    doc = BaseDocTemplate(str(OUT), pagesize=A4, title="Market Ecology Simulator — Handbook",
                          author="Market Ecology Simulator", leftMargin=22 * mm,
                          rightMargin=22 * mm, topMargin=22 * mm, bottomMargin=20 * mm)
    frame_cover = Frame(22 * mm, 30 * mm, A4[0] - 44 * mm, A4[1] - 70 * mm, id="cover")
    frame_body = Frame(22 * mm, 20 * mm, A4[0] - 44 * mm, A4[1] - 42 * mm, id="body")
    doc.addPageTemplates([
        PageTemplate(id="cover", frames=[frame_cover], onPage=on_cover),
        PageTemplate(id="body", frames=[frame_body], onPage=on_page),
    ])
    doc.build(story())
    return OUT


# ----------------------------------------------------------------------- text
# The scenario presets fall into two families. Which family a key belongs to is a
# statement of this document; the names themselves come from `mes/scenarios.py`.
HISTORICAL = ("dotcom", "gfc2008", "covid", "memestock", "rates2022")

# What each guided experiment shows, keyed by its lesson key. The short label and
# the question are this document's; the title the app displays is read from
# `mes/lessons.py`.
LESSON_NOTES = {
    "bubble": ("Bubble",
               "Trend following is a feedback loop. Nobody recommends anything, nobody "
               "coordinates. The bubble follows from the rules."),
    "cascade": ("Cascade",
                "No. One trigger is enough. A fund below its margin threshold sells "
                "because it must, and pushes the next one below its own."),
    "etf": ("ETF",
            "A savings plan does not check what anything is worth. With enough of them "
            "the price loses its anchor, not because anyone is wrong but because nobody "
            "is checking."),
    "correlation": ("Correlation",
                    "From a common market factor and from shared balance sheets: a fund "
                    "in distress sells all its positions, not just the troubled one."),
    "rates": ("Rate turn",
              "Through three channels, at different speeds. The Central Bank overshoots "
              "because the effect arrives with a delay."),
    "regimes": ("Regimes",
                "None for good. Whichever wins attracts imitators and so makes itself "
                "unprofitable."),
    "predictable": ("Forecast",
                    "Unfortunately yes. This experiment shows the flaw on purpose instead "
                    "of hiding it."),
}


def _lesson_titles() -> dict:
    return {lesson["key"]: lesson["title"] for lesson in lessons.catalogue()}


def _scenario_names(historical: bool) -> str:
    names = [s.name for key, s in scenarios.ALL.items()
             if (key in HISTORICAL) == historical]
    return " · ".join(names)


def story():
    titles = _lesson_titles()
    tests = count_tests()
    f = []

    # ---------------------------------------------------------------- cover
    f += [Spacer(1, 52 * mm),
          p("AGENT-BASED FINANCIAL MARKET SIMULATION", "kicker"),
          Spacer(1, 5),
          p("Market Ecology<br/>Simulator", "title"),
          Spacer(1, 12),
          p("A handbook for working, learning and understanding: what the project "
            "can do, how to operate it, which questions it answers and where it is "
            "demonstrably wrong.", "subtitle"),
          Spacer(1, 30),
          p(f"{tests} tests · 7 agent types · 5 sectors · {len(titles)} guided experiments",
            ParagraphStyle("cm", parent=S["subtitle"], fontName=MONO, fontSize=9,
                           textColor=COVER_ACCENT)),
          NextPageTemplate("body"), PageBreak()]

    # ------------------------------------------------------------ 1 what it is
    f += [p("1 · What the project is", "h1")]
    f += [p("An agent-based simulation of an equity market. It does not forecast prices. "
            "It asks <b>where market behaviour comes from</b>.", "lead")]
    f += [p("Around 600 agents each follow a simple rule. None knows the true value of "
            "an asset, none knows what the others will do next, and nowhere in the code "
            "is there an equation for the price. Every trade is one order meeting "
            "another. Bubbles, crashes, volatility clusters and forced-selling cascades "
            "emerge from this interaction, or they are not there.")]

    f += callout("The actual question",
                 "Real return series share a handful of statistical properties that "
                 "hold across asset classes and centuries: fat tails, clustered "
                 "volatility, almost no autocorrelation. None of them is built into "
                 "this model. "
                 "<b>Does a market made only of simple rules reproduce them anyway?</b> "
                 "The criteria were fixed before the first run. That is exactly what "
                 "makes the answer hold up.")

    f += [p("What is unusual about it", "h2")]
    f += bullets([
        "<b>The order book is real.</b> A continuous double auction with price-time "
        "priority, partial fills, cancellation and expiry. A model with "
        "<font name='Courier' size='8'>price *= (1 + k · demand)</font> cannot explain a "
        "liquidity hole, because it has no liquidity that could run out.",
        "<b>News never moves the price.</b> It moves fair value and sentiment. Whether "
        "the price follows is up to the agents, and they read the same headline "
        "differently. The ETF does not read it at all.",
        "<b>The validation is code, not prose.</b> Six criteria as executable checks, "
        "measured across several seeds. A result that holds for only one random start "
        "does not count.",
        "<b>Failures are documented.</b> Four rounds of diagnosis, several of the "
        "project's own hypotheses refuted, two criteria still open. All of it is in the "
        "README and in this handbook.",
    ])
    f += rule()

    # -------------------------------------------------------------- 2 result
    f += [p("2 · Where it stands", "h1")]
    f += [p("Measured over 5 random starts × 5 instruments = 25 measurements, each "
            "90,000 steps (about 370 trading days).", "small")]
    rows = [["Criterion", "Requirement", "Measured", "Measurements", ""],
            ["Volatility clustering", "mean ACF of |returns| &gt; 0.05", "0.217 ± 0.109", "25/25", verdict(True)],
            ["Non-normality", "Jarque-Bera p &lt; 0.05", "0.0002", "25/25", verdict(True)],
            ["Fat tails", "excess kurtosis &gt; 1", "5.39 ± 5.93", "24/25", verdict(True)],
            ["Tail index", "Hill estimator between 2 and 6", "4.38 ± 1.37", "22/25", verdict(True)],
            ["No autocorrelation", "|ACF(1)| &lt; 0.1", "-0.223 ± 0.156", "8/25", verdict(False)],
            ["Volume-volatility", "correlation &gt; 0.1", "-0.072 ± 0.129", "3/25", verdict(False)]]
    f += [table(rows, [40 * mm, 52 * mm, 30 * mm, 22 * mm, 18 * mm],
                align_right=(2, 3), highlight=(5, 6)), Spacer(1, 8)]
    f += [p("In addition: annualised volatility 1.31, maximum drawdown -0.62, <b>sector "
            "correlation 0.398</b> (realistic: 0.4–0.6), 786 margin calls, trend-follower "
            "share varying with a standard deviation of 0.39.")]

    f += callout("Why the two open points are open",
                 "One trade-off runs through the whole model: <b>the anchor that keeps a "
                 "price honest is the same thing that makes its returns "
                 "predictable.</b> Tracking fair value more closely means more reversion "
                 "to the mean. Forced selling adds reversion and volatility. Every "
                 "mechanism that tightened the price's grip on its fundamental value "
                 "made the autocorrelation worse, every time in the same direction.", RED)
    f += rule()

    # ---------------------------------------------------------- 3 first steps
    f += [p("3 · The first ten minutes", "h1")]
    f += [code(["./start.sh", "", "# -> http://127.0.0.1:8000        the town",
                "# -> http://127.0.0.1:8000/sectors  the analysis page"])]
    f += [p("The first start creates the virtual environment and installs the "
            "dependencies. The server answers within a few seconds and then fast-forwards "
            "the market to 110 trading days in the background. The validation panel needs "
            "100 days before its figures mean anything, and the first few dozen days are "
            "the run settling down, not the model at work.")]

    trend_label = PARAM_SPEC["chartist_aggression"]["label"]
    f += [p("What to look at, in which order", "h2")]
    rows = [["Minute", "Do", "Watch for"],
            ["1–2", "Let the town on <font name='Courier' size='8'>/</font> run",
             "Five blue towers in the middle are the five exchanges. Tower height = book "
             "depth. Road width = order flow. One walking figure = ten agents with an "
             "order, carrying a green (buy) or red (sell) crate."],
            ["3–4", "Click a market in the market bar (TECH, ENRG …) or its tower",
             "Price, ticker and book line follow the selection, and the selected tower "
             "turns brighter. The simulation is not affected."],
            ["5–6", "Switch to <font name='Courier' size='8'>/sectors</font>",
             "Correlation heatmap: configured nowhere. It emerges from the common factor "
             "in the fundamental values and from portfolios spanning several sectors."],
            ["7–8", f"Push the control “{trend_label}” up",
             "Prices detach from fair value, kurtosis in the validation panel rises. "
             "Takes effect immediately, no restart."],
            ["9–10", "Set 16× and let it run",
             "The validation panel moves towards the calibrated values. Before that it "
             "shows a shorter sample and therefore different figures."]]
    f += [table(rows, [16 * mm, 52 * mm, 94 * mm]), Spacer(1, 8)]

    f += [p("The most important panel: “What is happening”", "h2")]
    f += [p("It sits in the town's left-hand panel and at the top of the analysis page, "
            "and it answers a fair question. A "
            "visualisation shows a <b>state</b>. Walking figures and growing blocks do "
            "not say what is happening right now and why it is worth noticing. Without "
            "this panel you would already have to know the model to read the town.")]
    f += [code([
        "The market is stretched     [mixed regime] [vol normal] [leverage 1.02x]",
        "",
        "  . TECH is trading +35% above fair value. Nobody decided that -",
        "    it is the result of more buying pressure than supply.",
        "  . The funds are at 1.02x leverage and have 97.3% headroom before a",
        "    margin call.",
        "",
        "  What to watch now",
        "  . The Issuer is selling new shares at this valuation. That is the",
        "    counterforce - watch whether the gap stops widening.",
    ])]
    f += [p("Two rules keep it from being decoration. Nothing is pre-written: a calm "
            "market is described as calm. And “high” or “unusual” is a <b>percentile "
            "against the run's own history</b>, because a volatility of 0.8 means nothing "
            "without knowing what this market normally does. Events carry their mechanism "
            "with them: not “margin call” but “A leveraged fund has fallen below its "
            "threshold and had to sell. It did not decide to.”", "small")]

    f += callout("A note that saves confusion",
                 "The live panel shows <b>different figures from this handbook</b>. It "
                 "computes on the days it has; the tables here use 370 days across five "
                 "seeds. Single runs scatter considerably. The same defaults gave 5.0 of 6 "
                 "on one seed over 60,000 steps, with an autocorrelation of -0.03. That is "
                 "exactly why the criteria are defined across several seeds and "
                 "<font name='Courier' size='8'>scripts/calibrate.py</font> is the figure "
                 "that counts. The panel shows <i>which control moves what</i>.")
    # A rule rather than a page break: the break left this callout stranded alone on
    # a page of its own.
    f += rule(space_before=2, space_after=10)

    # ------------------------------------------------------------- 4 agents
    f += [p("4 · The seven market participants", "h1")]
    f += [p("Each exists because the model was visibly wrong without it. The reasons "
            "given are what the calibration actually showed.", "small")]
    rows = [["Agent", "Rule", "Why it is in the model"],
            ["Value investor", "buys below its own estimate of value, sells above",
             "the only force pulling the price towards value"],
            ["Trend follower", "extrapolates the recent move, ignores valuation",
             "the feedback loop that produces bubbles"],
            ["Noise trader", "trades for reasons the model does not represent",
             "background liquidity"],
            ["ETF / savings plan", "receives money on a schedule, buys at any price",
             "price-insensitive demand"],
            ["Leveraged fund", "borrows to amplify a blended view",
             "forced selling, the cascade mechanism"],
            ["Market maker", "quotes both sides, leans against its inventory",
             "without it the book held ~600 shares against orders of several thousand: "
             "every order cleared every level and volatility was 129% a year. An "
             "artefact of the matching engine, not of behaviour"],
            ["Issuer", "sells new shares when expensive, buys back when cheap",
             "without it there is no supply: value investors sell out, market makers "
             "reach their inventory limit, and then the price rises to twice fair value "
             "and stays there"]]
    f += [table(rows, [26 * mm, 55 * mm, 81 * mm]), Spacer(1, 8)]
    f += [p("Value investors and trend followers are the <b>same</b> agent type. They "
            "switch between the two rules, and that switching is the source of the "
            "interesting behaviour. It is driven by relative success (Lux &amp; "
            "Marchesi 1999) and by herding (Kirman 1993). Herding makes the population "
            "<b>bistable</b>: it locks into a trend-following regime (volatile, "
            "bubble-prone) or a value regime (calm, mean-reverting) and stays there for a "
            "while. That persistence is what clusters volatility, and none of it is "
            "written into the price process.")]
    f += rule()

    # ---------------------------------------------------------- 5 experiments
    f += [p("5 · The guided experiments", "h1")]
    f += [p("They live in the application, not in this booklet. On "
            "<font name='Courier' size='8'>/sectors</font> each one sets up the market, "
            "says what to watch for, and afterwards checks by <b>measurement</b> whether it "
            "worked.", "lead")]

    f += callout("Why the check matters more than the instructions",
                 "A guided tour that always says “see, exactly as expected” teaches "
                 "nothing. It would say the same if the model were broken. These report "
                 "failure too, and several do so regularly. One is even designed for it: "
                 f"“{titles['predictable']}” checks the open autocorrelation criterion "
                 "and answers <b>not this time</b>, with the note that this is the "
                 "model's documented flaw and not an operating error.", TEAL)

    rows = [["Experiment", "Question", "What it shows"]]
    for key, title in titles.items():
        label, shows = LESSON_NOTES[key]
        rows.append([label, title, shows])
    f += [table(rows, [24 * mm, 55 * mm, 83 * mm]), Spacer(1, 8)]

    f += [p("A start that pays off", "h2")]
    f += bullets([
        "On <font name='Courier' size='8'>/sectors</font>, start the experiment "
        f"<b>“{titles['cascade']}”</b>.",
        "Switch to the town (link top right) and watch the Leverage Tower. When the "
        "cascade runs, its red beacon blinks fast, a red ring pulses on the ground and "
        "a MARGIN CALL tag appears.",
        "Back on the analysis page: the check says whether it worked this time, and with "
        "which figure.",
    ])
    # A rule rather than a page break: section 6 grew with the town's map table, and
    # starting it on a fresh page left its last lines alone on a page of their own.
    f += rule(space_before=2, space_after=10)

    # ------------------------------------------------------- 6 what it answers
    f += [p("6 · What the project can do", "h1")]

    f += [p("Watch it live", "h2")]
    f += bullets([
        "<b>The town</b> (<font name='Courier' size='8'>/</font>) is a bright 3D diorama "
        "(WebGL) that fills the whole window, with white glass panels floating over it. "
        "On the left: what is happening, the market panel, the districts, the Adaptive "
        "Quarter and this step. On the right: the selected unit with its values, its "
        "decision and the town log. Along the top: capital, sentiment, volume and price, "
        "day and step, the live lamp and the links to the other views. On the map: the "
        "market bar, the ticker, a command bar with Shock (Calm / Boom / Crash) and Speed "
        "(pause, step, 1× / 4× / 16×), a key and the camera buttons. Along the bottom: "
        "Scenario, Experiment, Headline, Controls, Replay and Restart, the next strategy "
        "review and the scale switch EURO / COMPARE.",
    ])
    rows = [["On the map", "Means"],
            ["Block height of a district",
             "the district's capital, on the euro ladder; the footer states the scale "
             "(“1 floor = €1M” and so on)"],
            ["Road width", "order flow this step"],
            ["Chevrons moving along a road", "the direction of that flow, towards the exchanges"],
            ["A walking figure", "ten agents carrying an order"],
            ["The crate it carries",
             "green (buy) or red (sell), in the proportion of that group's buy orders "
             "this step"],
            ["Golden figures between the two camps", "agents switching strategy"],
            ["Trucks", "the ETF Depot's scheduled purchases and the Issuer's new shares"],
            ["Smoke from the Issuer's chimneys", "it sold stock this step"],
            ["Five blue towers",
             "the five exchanges. Height = book depth; a band shows symbol and price; the "
             "selected market's tower is brighter"],
            ["Numbers rising over the selected tower", "its fills"],
            ["Hatched upper floors of the Leverage Tower", "borrowed capital"],
            ["Red beacon blinking fast, red ring pulsing on the ground, MARGIN CALL tag",
             "a margin call"],
            ["Blue pin", "the selected district"],
            ["Light and weather",
             "sentiment: warm sun when greedy, overcast when fearful, rain below about 30"],
            ["Trees, the faint town on the horizon", "nothing"]]
    f += [Spacer(1, 3), table(rows, [62 * mm, 100 * mm]), Spacer(1, 7)]
    f += bullets([
        "<b>Operating the town</b>: click a building or its label to select the "
        "district; a tower selects that market. Drag to turn the camera, scroll to zoom, "
        "right-drag (or shift-drag) to pan. <b>+ − 0</b> "
        "zoom and reset, and a button turns the town by 45°. Without WebGL the page says "
        "so, and the panels keep working.",
        "<b>Controllable from the town</b>: load a <b>scenario</b> (including the five "
        "historical episodes), start an <b>experiment</b> and read its measured check, "
        "inject a <b>headline</b> by hand, move any <b>control</b>, open a "
        "<b>recording</b>, restart the run. The <font name='Courier' size='8'>?</font> at "
        "the top left says what the town shows and what to try first. A click on a "
        "district explains it and puts a real member into the unit card.",
        "<b>Replay in the town</b>: a recorded run is recomputed from its seed, not read "
        "from curves. That is why the whole state is available at every position, and "
        "the slider moves the complete map including the order book.",
        "<b>Two scales</b>: after a hundred trading days one camp holds almost all the "
        "capital, the spread reaches 135×, and on the euro scale the other districts all "
        "sit at minimum height. <b>EURO</b> stays the honest default; <b>COMPARE</b> is "
        "logarithmic and says so in the same line.",
        "<b>Price, candles, order book</b>: the market panel on the left shows the same "
        "instrument on three levels: price against fair value, daily candles and the "
        "resting orders. The book is where a price is made in this model; almost all of "
        "the depth sits at the touch, where the market makers put it.",
        "<b>The analysis page</b> (<font name='Courier' size='8'>/sectors</font>): sector "
        "tiles with sparklines, an instrument panel with candles, order book and tape, "
        "correlation heatmap, Central Bank with duration per sector, validation panel "
        "with variance ratio, A/B comparison, replay slider.",
        "<b>The index board</b> (<font name='Courier' size='8'>/indices</font>): all "
        "indices live on one axis, normalised to the start of the window, and for each "
        "index its level, fair-value index, volatility, drawdown, breadth and the "
        "<i>measured</i> beta against the one set in the factor model. An index here is "
        "a measurement: weighted by the shares the ETF itself buys, and chain-linked.",
        "<b>The trader list</b> (<font name='Courier' size='8'>/traders</font>): all "
        "agents side by side instead of one after another: capital, cash, positions, "
        "leverage, result since the start of the run, forced sales. Sorted and filtered "
        "in the backend, with rollups per district and a jump back into the town to "
        "exactly this agent.",
        "<b>Every parameter</b> is declared once (<font name='Courier' size='8'>"
        "PARAM_SPEC</font>) and the control panel is generated from it. A new parameter "
        "appears without any change to the frontend.",
    ])

    # The heading travels with its table, so it is never left at the foot of a page.
    heading = p("Measure and compare", "h2")
    rows = [["Tool", "Answers"],
            ["<font name='Courier' size='8'>calibrate.py</font>",
             "Does the model meet the six criteria, per instrument, across several seeds?"],
            ["<font name='Courier' size='8'>sweep.py ablate</font>",
             "Which mechanism is responsible for which property? Switches each one off "
             "in turn."],
            ["<font name='Courier' size='8'>sweep.py param</font>",
             "How does a measure depend on a parameter, across a range of values?"],
            ["<font name='Courier' size='8'>/api/compare</font>",
             "What does this parameter do, from the same random start?"],
            ["<font name='Courier' size='8'>/api/compare/sweep</font>",
             "Is the difference larger than the scatter between seeds? Returns signal/noise."],
            ["<font name='Courier' size='8'>run.py</font>",
             "A run without the interface, exported as Parquet for analysis in a notebook."],
            ["<font name='Courier' size='8'>/api/replay</font>",
             "Scrub freely through a recorded run."],
            ["<font name='Courier' size='8'>/api/explain</font>",
             "What is happening, why, what to watch, as text."],
            ["<font name='Courier' size='8'>/api/lessons/{k}/check</font>",
             "Did the experiment show what it set out to show? Measured."]]
    f += [KeepTogether([heading, table(rows, [40 * mm, 122 * mm])]), Spacer(1, 8)]

    f += callout("Why the A/B comparison counts now, and did not before",
                 "Every agent draws from <b>its own</b> random stream, seeded from the "
                 "seed and the agent ID. With a shared stream, the number of random "
                 "draws consumed depended on what an agent decided. The first difference "
                 "in behaviour threw everyone out of step, and a channel worth 0.4% "
                 "became a 39% difference. Now the effect scales with its cause: a "
                 "borrowing spread of +5 basis points gives a 0.4% gap, trend following "
                 "from 55 to 140 gives 3.5%. And a parameter that <i>cannot</i> have an "
                 "effect (a leverage limit without leveraged funds) produces bit-identical "
                 "runs. This control test is in the suite.", TEAL)

    f += [p("Scenarios", "h2")]
    f += [p("A scenario never writes a price path. It sets conditions and supplies "
            "headlines. What the price then does is the model's answer.")]
    f += bullets([
        f"<b>Basic scenarios:</b> {_scenario_names(historical=False)}",
        f"<b>Historical episodes:</b> {_scenario_names(historical=True)}",
    ])
    f += [p("The historical episodes reproduce <b>mechanisms</b>, not price paths. "
            "Turning parameters until a chart matches history would prove nothing. The "
            "question is narrower and can be answered: does the mechanism credited with "
            "this episode produce that kind of behaviour in a model that was not built "
            "for it?", "small")]
    f += [PageBreak()]

    # --------------------------------------------------------- 7 method
    f += [p("7 · The method, and why it makes the difference", "h1")]
    f += [p("The most instructive part of this project is not the result but the way "
            "there. Almost every plausible explanation was wrong.", "lead")]

    f += [p("The test that explained everything", "h2")]
    f += [p("The <b>variance ratio</b>, Var(k-period return) / (k · Var(1-period)), "
            "separates permanent from transitory variance. A random walk gives 1 at "
            "every horizon.")]
    f += [code(["  20 steps     5.79     strongly trending",
                " 240 steps     0.72     one day, already reverting",
                "4800 steps     0.066    twenty days"])]
    f += [p("0.066 means the variance of 20-day returns was 6.6% of what a random walk "
            "would give. The price was nailed to fair value: 79% price volatility "
            "against 15% fundamental volatility, so around 90% of all price movement was "
            "transitory. And transitory movement <i>has to</i> be taken back. That is "
            "where the negative autocorrelation came from. No single agent type was to "
            "blame.")]

    f += [p("What was ruled out", "h2")]
    rows = [["Hypothesis", "Test", "Result"],
            ["Market makers shift prices with their inventory",
             "remove them completely", "ACF stays at -0.40"],
            ["Constant rebalancing (target = wealth ÷ price)",
             "tolerance band 5–30%", "no effect, other criteria worse"],
            ["Issuer overcorrects (bang-bang control)",
             "proportional issuance", "no effect"],
            ["Value investors correct too fast",
             "pull-back strength 0.08 instead of 0.005", "ACF gets <i>worse</i> (-0.22)"],
            ["Trading day too short",
             "10 / 30 / 120 / 360 steps per day", "ACF(1) around -0.4 throughout"],
            ["Measurement noise in the closing price",
             "averaging over the last 5% of the day", "-0.43 becomes -0.39"],
            ["Valuation is recognised too quickly",
             "delay of 0.5 / 12 / 30 days",
             "<b>worse</b>: the price trends instead of reverting, correlation falls from "
             "0.42 to 0.13, and the cascade stops firing"]]
    f += [table(rows, [56 * mm, 47 * mm, 59 * mm]), Spacer(1, 6)]
    f += [p("Two of these conclusions replaced earlier ones drawn from the same "
            "experiments <i>before</i> a fix to strategy switching. The dynamics underneath "
            "had changed, which is a good argument for re-running an ablation rather than "
            "trusting a note. That is what "
            "<font name='Courier' size='8'>scripts/sweep.py ablate</font> is for.", "small")]

    # Kept together: the last bullet used to spill onto a page of its own.
    worked = [p("What worked", "h2")]
    worked += bullets([
        "<b>Volatility clustering and mean reversion were the same mechanism.</b> The "
        "clustering came from regime switches, and the switch back to value <i>is</i> the "
        "reversion. Every parameter that improved the autocorrelation destroyed the "
        "clustering. The solution was a second, independent source of clustering: "
        "news arriving in bursts (the volatility of fair value is itself persistent).",
        "<b>Activity follows the news flow</b> (Clark 1973): volume and volatility are "
        "both consequences of the rate of information, not consequences of each other.",
        "<b>A market's capital has to scale with the number of markets.</b> With five "
        "sectors each market saw a fifth of the capital, while fair value diffused just "
        "as fast. Prices could not keep up, and the correlation from the factor model "
        "barely reached them: 0.07 instead of a realistic 0.4–0.6. After scaling: "
        "<b>0.40</b>.",
        "<b>Margin calls were dead code under the defaults.</b> The funds reach ~1.6× "
        "leverage; a threshold of 0.25 is never touched. It is now set against the "
        "leverage the model actually produces.",
    ])
    f += [KeepTogether(worked), PageBreak()]

    # ------------------------------------------------------ 8 where it is wrong
    f += [p("8 · Where the model is wrong", "h1")]
    f += [p("In full, because a simulation cannot be judged without this list.", "small")]
    rows = [["Finding", "How far from the target", "Diagnosis"],
            ["Returns are predictable", "ACF -0.22 instead of ±0.1",
             "The best value reached was -0.03 on one seed, in a configuration with a "
             "sector correlation of 0.19 and no margin calls. The trade-off is not solved."],
            ["Volume does not follow volatility", "-0.07 instead of &gt; 0.1",
             "Most volume is market-maker volume and does not rise with agitation. "
             "Countermeasures made four other measures worse."],
            ["Volatility too high", "1.31 a year against 0.15–0.25 in reality",
             "Partly a consequence of the active cascade: forced selling creates volatility."],
            ["One sector far from fair value", "Financials 89%, the others below 40%",
             "The Issuer only steps in above its threshold; in a long-running sector the "
             "flow is not enough to keep up."],
            ["Kurtosis unstable", "5.4 ± 5.9",
             "Driven by rare, very large single days in thin sectors, not by consistently "
             "heavy tails."]]
    f += [table(rows, [42 * mm, 40 * mm, 80 * mm]), Spacer(1, 8)]

    f += [p("Not built", "h2")]
    f += bullets([
        "<b>No dividends, no earnings.</b> Fair value is an exogenous process, not "
        "something a company earns. Buybacks are paid from a cash pile that never fills "
        "from the business.",
        "<b>The four views stay separate.</b> Town, analysis, indices and traders show the "
        "same simulation from four angles. Nothing was merged, because the town is "
        "readable precisely because it draws one market.",
        "<b>No reinforcement learning and no LLM agents.</b> Dropped on purpose: both cost "
        "reproducibility, and without a fixed seed no run is good enough as a result.",
    ])
    f += rule()

    # ----------------------------------------------------------- 9 reference
    f += [p("9 · Command reference", "h1")]
    tests_col = f"{tests} tests"
    f += [code([
        "./start.sh                                          start the interface",
        "",
        "python scripts/calibrate.py --runs 5 --steps 90000  validation, per instrument",
        "python scripts/sweep.py ablate --steps 80000        switch off each mechanism in turn",
        "python scripts/sweep.py param --name n_passive \\",
        "       --values 0,50,100,200                        sweep one parameter",
        "python scripts/run.py --steps 120000 --name baseline run without UI, Parquet export",
        "python scripts/run.py --scenario gfc2008 --name crisis",
        "",
        f"python -m pytest tests/ -q                          {tests_col}",
    ])]

    f += [p("Where things are in the code", "h2")]
    rows = [["File", "Contents"],
            ["<font name='Courier' size='8'>mes/orderbook.py</font>", "matching engine, price-time priority: the foundation"],
            ["<font name='Courier' size='8'>mes/agents.py</font>", "the seven decision rules"],
            ["<font name='Courier' size='8'>mes/simulation.py</font>", "the loop, settlement, margin, strategy switching"],
            ["<font name='Courier' size='8'>mes/market.py</font>", "one instrument: book, history, daily bars"],
            ["<font name='Courier' size='8'>mes/instruments.py</font>", "the five sectors and the factor model"],
            ["<font name='Courier' size='8'>mes/centralbank.py</font>", "Taylor rule, macro block, the three channels"],
            ["<font name='Courier' size='8'>mes/metrics.py</font>", "the stylized-facts checks and the variance ratio"],
            ["<font name='Courier' size='8'>mes/compare.py</font>", "A/B with a signal/noise assessment"],
            ["<font name='Courier' size='8'>mes/narrator.py</font>", "state becomes explanation: what, why, what to watch"],
            ["<font name='Courier' size='8'>mes/lessons.py</font>", "the seven experiments, each with a measured check"],
            ["<font name='Courier' size='8'>mes/config.py</font>", "every parameter, declared once"],
            ["<font name='Courier' size='8'>web/index.html</font>", "the town: panels, and the model it builds from /api/state (no build step)"],
            ["<font name='Courier' size='8'>web/town3d.js</font>", "the 3D renderer; draws only the model index.html builds"],
            ["<font name='Courier' size='8'>web/vendor/</font>", "three.js r159 (MIT), vendored as a classic script so the page works offline and from file://"],
            ["<font name='Courier' size='8'>web/sectors.html</font>", "the analysis page"],
            ["<font name='Courier' size='8'>web/indices.html</font>", "the index board: all indices live against each other"],
            ["<font name='Courier' size='8'>web/traders.html</font>", "the trader list: all agents, sortable and filterable"],
            ["<font name='Courier' size='8'>mes/indices.py</font>", "the index construction: chain-linked, ETF-weighted"],
            ["<font name='Courier' size='8'>mes/traders.py</font>", "population to table: the only translation point"]]
    f += [table(rows, [46 * mm, 116 * mm]), Spacer(1, 10)]

    f += [p("Literature", "h2")]
    f += [p("Cont (2001), <i>Empirical properties of asset returns</i> · Lux &amp; Marchesi "
            "(1999), <i>Scaling and criticality in a stochastic multi-agent model</i> · "
            "Kirman (1993), <i>Ants, rationality, and recruitment</i> · Brock &amp; Hommes "
            "(1997), <i>A rational route to randomness</i> · Chiarella &amp; Iori (2002), "
            "<i>A simulation analysis of the microstructure of double auction markets</i> · "
            "Clark (1973), <i>A subordinated stochastic process model …</i> · Lo &amp; "
            "MacKinlay (1988), <i>Stock market prices do not follow random walks</i> · "
            "Taylor (1993), <i>Discretion versus policy rules in practice</i> · LeBaron "
            "(2006), <i>Agent-based computational finance</i>", "small")]

    return f


if __name__ == "__main__":
    print("written:", build())
