"""Build the project handbook as a PDF.

Kept as a script rather than a one-off so the document can be regenerated when the
figures change — a handbook quoting stale calibration numbers is worse than none.
Every number in here comes from `scripts/calibrate.py` and is labelled with the
sample it was measured on.

    python docs/build_handbook.py
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (BaseDocTemplate, Frame, KeepTogether, NextPageTemplate,
                                PageBreak, PageTemplate, Paragraph, Spacer, Table,
                                TableStyle)

OUT = Path(__file__).resolve().parent / "Market-Ecology-Simulator-Handbuch.pdf"

INK = colors.HexColor("#1d2126")
DIM = colors.HexColor("#5f6873")
FAINT = colors.HexColor("#8d949d")
RULE = colors.HexColor("#d8dce1")
BAND = colors.HexColor("#f2f4f6")
AMBER = colors.HexColor("#b96219")
TEAL = colors.HexColor("#1d7a68")
RED = colors.HexColor("#b1372c")
DARK = colors.HexColor("#171a1f")

MONO = "Courier"
SANS = "Helvetica"
SANS_B = "Helvetica-Bold"


# --------------------------------------------------------------------- styles
def styles() -> dict:
    base = getSampleStyleSheet()
    s = {}
    s["title"] = ParagraphStyle("title", parent=base["Normal"], fontName=SANS_B,
                                fontSize=27, leading=31, textColor=colors.white)
    s["subtitle"] = ParagraphStyle("subtitle", parent=base["Normal"], fontName=SANS,
                                   fontSize=12.5, leading=18,
                                   textColor=colors.HexColor("#c9ced6"))
    s["kicker"] = ParagraphStyle("kicker", parent=base["Normal"], fontName=SANS_B,
                                 fontSize=8, leading=12, textColor=AMBER)
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

    t = Table(data, colWidths=widths, hAlign="LEFT")
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
    mark, colour = ("erfüllt", TEAL) if ok else ("offen", RED)
    return Paragraph(mark, ParagraphStyle("v", parent=S["cellb"], textColor=colour,
                                          fontSize=8))


# ------------------------------------------------------------------- document
def on_cover(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(DARK)
    canvas.rect(0, 0, A4[0], A4[1], stroke=0, fill=1)
    canvas.setFillColor(AMBER)
    canvas.rect(0, A4[1] - 6 * mm, A4[0], 6 * mm, stroke=0, fill=1)
    # A skyline, because the interface is a town.
    canvas.setFillColor(colors.HexColor("#22262c"))
    heights = [16, 34, 24, 46, 28, 58, 38, 20, 44, 30, 52, 26, 36, 22, 40]
    x = 0
    for i, h in enumerate(heights):
        w = A4[0] / len(heights)
        canvas.rect(x, 0, w - 1.5, h * mm * 0.5, stroke=0, fill=1)
        x += w
    canvas.setFillColor(colors.HexColor("#2b3037"))
    for i, h in enumerate(heights):
        if i % 3:
            continue
        canvas.rect(i * (A4[0] / len(heights)) + 4, 0, 10, h * mm * 0.34, stroke=0, fill=1)
    canvas.restoreState()


def on_page(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.5)
    canvas.line(22 * mm, A4[1] - 16 * mm, A4[0] - 22 * mm, A4[1] - 16 * mm)
    canvas.setFont(SANS, 7.2)
    canvas.setFillColor(FAINT)
    canvas.drawString(22 * mm, A4[1] - 13.5 * mm, "MARKET ECOLOGY SIMULATOR · HANDBUCH")
    canvas.drawRightString(A4[0] - 22 * mm, A4[1] - 13.5 * mm, f"Seite {doc.page - 1}")
    canvas.line(22 * mm, 15 * mm, A4[0] - 22 * mm, 15 * mm)
    canvas.setFont(SANS, 7)
    canvas.drawCentredString(A4[0] / 2, 11 * mm,
                             "Alle Zahlen aus scripts/calibrate.py · 5 Seeds × 5 Instrumente × 90.000 Schritte")
    canvas.restoreState()


def build():
    doc = BaseDocTemplate(str(OUT), pagesize=A4, title="Market Ecology Simulator — Handbuch",
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
def story():
    f = []

    # ---------------------------------------------------------------- cover
    f += [Spacer(1, 52 * mm),
          p("AGENTENBASIERTE FINANZMARKTSIMULATION", "kicker"),
          Spacer(1, 5),
          p("Market Ecology<br/>Simulator", "title"),
          Spacer(1, 12),
          p("Ein Handbuch zum Arbeiten, Lernen und Verstehen — was das Projekt "
            "kann, wie man es bedient, welche Fragen es beantwortet und wo es "
            "nachweislich falsch liegt.", "subtitle"),
          Spacer(1, 30),
          p("315 Tests · 7 Agententypen · 5 Sektoren · 7 geführte Experimente",
            ParagraphStyle("cm", parent=S["subtitle"], fontName=MONO, fontSize=9,
                           textColor=AMBER)),
          NextPageTemplate("body"), PageBreak()]

    # ------------------------------------------------------------ 1 was es ist
    f += [p("1 · Was das Projekt ist", "h1")]
    f += [p("Eine agentenbasierte Simulation eines Aktienmarktes. Sie sagt keine Kurse "
            "vorher — sie fragt, <b>woher Marktverhalten kommt</b>.", "lead")]
    f += [p("Rund 600 Agenten folgen je einer einfachen Regel. Keiner kennt den wahren "
            "Wert eines Papiers, keiner weiß, was die anderen als Nächstes tun, und "
            "nirgends im Code steht eine Formel für den Kurs. Jeder Handel ist eine Order, "
            "die auf eine andere trifft. Blasen, Crashs, Volatilitätscluster und "
            "Zwangsverkaufs-Kaskaden entstehen aus diesem Zusammenspiel — oder sie sind "
            "nicht da.")]

    f += callout("Die eigentliche Fragestellung",
                 "Echte Renditereihen teilen eine Handvoll statistischer Eigenschaften, "
                 "die über Anlageklassen und Jahrhunderte hinweg gelten: dicke "
                 "Verteilungsränder, geklumpte Volatilität, nahezu keine "
                 "Autokorrelation. Keine davon ist in dieses Modell eingebaut. "
                 "<b>Reproduziert ein Markt aus lauter einfachen Regeln sie trotzdem?</b> "
                 "Die Kriterien standen vor dem ersten Lauf fest — genau das macht die "
                 "Antwort belastbar.")

    f += [p("Was daran ungewöhnlich ist", "h2")]
    f += bullets([
        "<b>Das Orderbuch ist echt.</b> Continuous Double Auction mit Preis-Zeit-"
        "Priorität, Teilausführungen, Storno und Verfall. Ein Modell mit "
        "<font name='Courier' size='8'>preis *= (1 + k · nachfrage)</font> kann ein "
        "Liquiditätsloch nicht erklären, weil es keine Liquidität hat, die ausgehen kann.",
        "<b>Nachrichten bewegen nie den Kurs.</b> Sie bewegen den fairen Wert und die "
        "Stimmung. Ob der Kurs folgt, entscheiden die Agenten — und sie lesen dieselbe "
        "Nachricht verschieden. Der ETF liest sie gar nicht.",
        "<b>Die Validierung ist Code, nicht Prosa.</b> Sechs Kriterien als ausführbare "
        "Prüfungen, gemessen über mehrere Seeds. Ein Ergebnis, das nur bei einem "
        "Zufallsstart gilt, zählt nicht.",
        "<b>Fehlschläge sind dokumentiert.</b> Vier Runden Diagnose, mehrere widerlegte "
        "eigene Hypothesen, zwei Kriterien bis heute offen. Das steht alles im README "
        "und in diesem Handbuch.",
    ])
    f += rule()

    # -------------------------------------------------------------- 2 ergebnis
    f += [p("2 · Der Stand", "h1")]
    f += [p("Gemessen über 5 Zufallsstarts × 5 Instrumente = 25 Messungen, je 90.000 "
            "Schritte (etwa 370 Handelstage).", "small")]
    rows = [["Kriterium", "Anforderung", "Gemessen", "Messungen", ""],
            ["Volatilitätscluster", "mittlere ACF der |Renditen| &gt; 0,05", "0,217 ± 0,109", "25/25", verdict(True)],
            ["Nicht-Normalität", "Jarque-Bera p &lt; 0,05", "0,0002", "25/25", verdict(True)],
            ["Dicke Ränder", "Überschuss-Kurtosis &gt; 1", "5,39 ± 5,93", "24/25", verdict(True)],
            ["Tail-Index", "Hill-Schätzer zwischen 2 und 6", "4,38 ± 1,37", "22/25", verdict(True)],
            ["Keine Autokorrelation", "|ACF(1)| &lt; 0,1", "-0,223 ± 0,156", "8/25", verdict(False)],
            ["Volumen-Volatilität", "Korrelation &gt; 0,1", "-0,072 ± 0,129", "3/25", verdict(False)]]
    f += [table(rows, [40 * mm, 52 * mm, 30 * mm, 22 * mm, 18 * mm],
                align_right=(2, 3), highlight=(5, 6)), Spacer(1, 8)]
    f += [p("Dazu: Volatilität 1,31 p. a., maximaler Drawdown -0,62, <b>Sektor-Korrelation "
            "0,398</b> (realistisch: 0,4–0,6), 786 Margin Calls, Schwankung des "
            "Trendfolger-Anteils Standardabweichung 0,39.")]

    f += callout("Warum die zwei offenen Punkte offen sind",
                 "Ein Zielkonflikt zieht sich durch das ganze Modell: <b>der Anker, der "
                 "einen Kurs ehrlich hält, ist dasselbe, was seine Renditen "
                 "prognostizierbar macht.</b> Besseres Nachvollziehen des fairen Wertes "
                 "bedeutet mehr Rückkehr zum Mittel. Zwangsverkäufe fügen Rückkehr und "
                 "Volatilität hinzu. Jeder Mechanismus, der den Griff des Kurses auf "
                 "seinen Fundamentalwert verbesserte, verschlechterte die "
                 "Autokorrelation — jedes Mal in dieselbe Richtung.", RED)
    f += rule()

    # ---------------------------------------------------------- 3 erste schritte
    f += [p("3 · Die ersten zehn Minuten", "h1")]
    f += [code(["./start.sh", "", "# -> http://127.0.0.1:8000        die Stadt",
                "# -> http://127.0.0.1:8000/sectors  die Analyse"])]
    f += [p("Der erste Start legt die virtuelle Umgebung an und installiert die "
            "Abhängigkeiten. Der Server antwortet nach wenigen Sekunden und spult den "
            "Markt danach im Hintergrund auf 110 Handelstage vor — das Validierungspanel "
            "braucht 100 Tage, bevor seine Zahlen etwas bedeuten, und die ersten Dutzend "
            "Tage sind der Lauf beim Einschwingen, nicht das Modell beim Arbeiten.")]

    f += [p("Was in welcher Reihenfolge anzuschauen ist", "h2")]
    rows = [["Minute", "Tun", "Worauf achten"],
            ["1–2", "Die Stadt auf <font name='Courier' size='8'>/</font> laufen lassen",
             "Fünf Börsengebäude in der Mitte. Höhe = Buchtiefe. Straßenbreite = Orderfluss. "
             "Eine laufende Figur = zehn Agenten mit einer Order."],
            ["3–4", "Auf einen Markt-Chip klicken (TECH, ENRG …)",
             "Kurs, Ticker und Buchzeile folgen der Auswahl, das hervorgehobene Gebäude wechselt. "
             "Die Simulation bleibt unberührt."],
            ["5–6", "Zu <font name='Courier' size='8'>/sectors</font> wechseln",
             "Korrelations-Heatmap: nirgends konfiguriert, sie entsteht aus dem gemeinsamen "
             "Faktor in den Fundamentalwerten und aus Portfolios über mehrere Sektoren."],
            ["7–8", "Regler „Trendfolge-Stärke“ hochziehen",
             "Kurse lösen sich vom fairen Wert, Kurtosis im Validierungspanel steigt. "
             "Sofort wirksam, kein Neustart."],
            ["9–10", "Auf 16× stellen und laufen lassen",
             "Das Validierungspanel läuft auf die kalibrierten Werte zu. Vorher zeigt es "
             "eine kürzere Stichprobe und damit andere Zahlen."]]
    f += [table(rows, [16 * mm, 52 * mm, 94 * mm]), Spacer(1, 8)]

    f += [p("Der wichtigste Bereich: „Was passiert gerade“", "h2")]
    f += [p("Er steht oben auf beiden Seiten und ist die Antwort auf eine berechtigte "
            "Frage. Eine Visualisierung zeigt einen <b>Zustand</b> — laufende Figuren "
            "und wachsende Häuser sagen nicht, was gerade passiert und warum es "
            "bemerkenswert ist. Ohne diesen Bereich muss man das Modell schon kennen, "
            "um die Stadt zu lesen.")]
    f += [code([
        "Der Markt ist ueberdehnt     [gemischtes Regime] [Vola normal] [Hebel 1,02x]",
        "",
        "  . TECH steht +35 % ueber dem fairen Wert. Niemand hat das beschlossen -",
        "    es ist das Ergebnis von mehr Kaufdruck als Angebot.",
        "  . Die Fonds stehen bei 1,02x Hebel und haben 97,3 % Luft bis zum",
        "    Margin Call.",
        "",
        "  Worauf jetzt achten",
        "  . Der Emittent gibt bei dieser Bewertung neue Aktien aus. Das ist die",
        "    Gegenkraft - beobachten Sie, ob der Abstand aufhoert zu wachsen.",
    ])]
    f += [p("Zwei Regeln halten das von Deko frei. Nichts ist vorformuliert — ein "
            "ruhiger Markt wird als ruhig beschrieben. Und „hoch“ oder „ungewöhnlich“ "
            "ist ein <b>Perzentil gegen die eigene Historie des Laufs</b>, denn eine "
            "Volatilität von 0,8 bedeutet nichts, ohne zu wissen, was dieser Markt "
            "normalerweise macht. Ereignisse tragen ihren Mechanismus mit: nicht "
            "„Margin Call“, sondern „Ein gehebelter Fonds ist unter seine Schwelle "
            "gefallen und musste verkaufen. Er hat es nicht entschieden.“", "small")]

    f += callout("Ein Hinweis, der Verwirrung erspart",
                 "Das Live-Panel zeigt <b>andere Zahlen als dieses Handbuch</b>. Es "
                 "rechnet auf den Tagen, die es hat; die Tabellen hier auf 370 Tagen über "
                 "fünf Seeds. Einzelläufe streuen erheblich — dieselben Standardwerte "
                 "ergaben auf einem Seed über 60.000 Schritte 5,0 von 6 mit einer "
                 "Autokorrelation von -0,03. Genau deshalb sind die Kriterien über mehrere "
                 "Seeds definiert und <font name='Courier' size='8'>scripts/calibrate.py</font> "
                 "ist die Zahl, die zählt. Das Panel zeigt, <i>welcher Regler was bewegt</i>.")
    # A rule rather than a page break: the break left this callout stranded alone on
    # a page of its own.
    f += rule(space_before=2, space_after=10)

    # ------------------------------------------------------------- 4 agenten
    f += [p("4 · Die sieben Marktteilnehmer", "h1")]
    f += [p("Jeder existiert, weil das Modell ohne ihn sichtbar falsch war. Die "
            "Begründungen sind das, was die Kalibrierung tatsächlich gezeigt hat.", "small")]
    rows = [["Agent", "Regel", "Warum er im Modell ist"],
            ["Value-Investor", "kauft unter der eigenen Wertschätzung, verkauft darüber",
             "die einzige Kraft, die den Kurs zum Wert zieht"],
            ["Trendfolger", "extrapoliert die letzte Bewegung, ignoriert Bewertung",
             "die Rückkopplung, aus der Blasen entstehen"],
            ["Rausch-Händler", "handelt aus Gründen, die das Modell nicht abbildet",
             "Grundliquidität"],
            ["ETF / Sparplan", "bekommt Geld im Takt, kauft zu jedem Preis",
             "preisunempfindliche Nachfrage"],
            ["Hebel-Fonds", "leiht, um eine gemischte Sicht zu verstärken",
             "Zwangsverkäufe — der Kaskaden-Mechanismus"],
            ["Market Maker", "quotiert beidseitig, lehnt sich gegen seinen Bestand",
             "ohne ihn hielt das Buch ~600 Stück gegen Orders von mehreren Tausend: jede "
             "Order räumte alle Ebenen ab, die Volatilität lag bei 129 % p. a. — ein Artefakt "
             "der Matching-Engine, nicht des Verhaltens"],
            ["Emittent", "gibt teure Aktien aus, kauft billige zurück",
             "ohne ihn gibt es kein Angebot: Value-Investoren verkaufen leer, Market Maker "
             "erreichen ihr Bestandslimit, danach steigt der Kurs auf das Doppelte des "
             "fairen Werts und bleibt dort"]]
    f += [table(rows, [26 * mm, 55 * mm, 81 * mm]), Spacer(1, 8)]
    f += [p("Value-Investoren und Trendfolger sind <b>derselbe</b> Agententyp. Sie "
            "wechseln zwischen den beiden Regeln, und dieser Wechsel ist die Quelle des "
            "interessanten Verhaltens: er wird von relativem Erfolg getrieben (Lux &amp; "
            "Marchesi 1999) und vom Herdentrieb (Kirman 1993). Der Herdentrieb macht die "
            "Population <b>bistabil</b> — sie rastet in ein Trendfolge-Regime ein "
            "(volatil, blasenanfällig) oder in ein Value-Regime (ruhig, mittelkehrend) "
            "und bleibt dort eine Weile. Diese Beharrlichkeit ist es, was die Volatilität "
            "klumpen lässt, und nichts davon steht im Preisprozess.")]
    f += rule()

    # ---------------------------------------------------------- 5 experimente
    f += [p("5 · Die geführten Experimente", "h1")]
    f += [p("Sie stehen in der Anwendung, nicht in diesem Heft. Auf "
            "<font name='Courier' size='8'>/sectors</font> stellt jedes den Markt ein, "
            "sagt worauf zu achten ist — und prüft danach <b>gemessen</b>, ob es "
            "funktioniert hat.", "lead")]

    f += callout("Warum die Prüfung wichtiger ist als die Anleitung",
                 "Eine geführte Tour, die immer „sehen Sie, genau wie erwartet“ sagt, "
                 "lehrt nichts — sie würde dasselbe sagen, wenn das Modell kaputt wäre. "
                 "Diese melden auch Misserfolg, und mehrere tun das regelmäßig. Eines ist "
                 "sogar darauf angelegt: „Ist dieser Markt prognostizierbar?“ prüft das "
                 "offene Autokorrelations-Kriterium und antwortet <b>diesmal nicht</b> — "
                 "mit dem Hinweis, dass das der dokumentierte Fehler des Modells ist und "
                 "kein Bedienfehler.", TEAL)

    rows = [["Experiment", "Frage", "Was es zeigt"],
            ["Blase", "Entsteht eine Blase von selbst?",
             "Trendfolge ist eine Rückkopplung. Niemand empfiehlt etwas, niemand "
             "koordiniert — die Blase folgt aus den Regeln."],
            ["Kaskade", "Braucht ein Crash schlechte Nachrichten?",
             "Nein. Ein Auslöser genügt; ein Fonds unter seiner Margin-Schwelle "
             "verkauft, weil er muss, und drückt den nächsten darunter."],
            ["ETF", "Machen ETFs den Markt instabiler?",
             "Ein Sparplan prüft nicht, was etwas wert ist. Genug davon, und der Kurs "
             "verliert den Bezug — nicht weil jemand irrt, sondern weil niemand prüft."],
            ["Korrelation", "Woher kommt die Korrelation der Sektoren?",
             "Aus einem gemeinsamen Marktfaktor und aus gemeinsamen Bilanzen: ein Fonds "
             "in Not verkauft alle Positionen, nicht nur die problematische."],
            ["Zinswende", "Wie wirkt eine Zinserhöhung?",
             "Über drei Kanäle, unterschiedlich schnell — und die Zentralbank "
             "überschießt, weil die Wirkung verzögert eintritt."],
            ["Regime", "Welche Strategie gewinnt langfristig?",
             "Keine dauerhaft. Wer gewinnt, zieht Nachahmer an und macht sich damit "
             "selbst unrentabel."],
            ["Prognose", "Ist dieser Markt prognostizierbar?",
             "Leider ja — und dieses Experiment zeigt den Fehler absichtlich, statt ihn "
             "zu verstecken."]]
    f += [table(rows, [24 * mm, 55 * mm, 83 * mm]), Spacer(1, 8)]

    f += [p("Ein Einstieg, der sich lohnt", "h2")]
    f += bullets([
        "Auf <font name='Courier' size='8'>/sectors</font> das Experiment "
        "<b>„Braucht ein Crash schlechte Nachrichten?“</b> starten.",
        "In die Stadt wechseln (Link oben rechts) und den Hebel-Turm beobachten — der "
        "Alarm feuert, wenn die Kaskade läuft.",
        "Zurück auf die Analyseseite: die Prüfung sagt, ob es diesmal geklappt hat, und "
        "mit welcher Zahl.",
    ])
    f += [PageBreak()]

    # ------------------------------------------------------- 6 was es beantwortet
    f += [p("6 · Was das Projekt kann", "h1")]

    f += [p("Live beobachten", "h2")]
    f += bullets([
        "<b>Die Stadt</b> (<font name='Courier' size='8'>/</font>): Viertelhöhe = Kapital "
        "der Gruppe, Straßenbreite = Orderfluss, laufende Figuren = Agenten mit Orders, "
        "goldene Figuren = Strategiewechsel, fünf Börsengebäude = fünf Märkte mit ihrer "
        "Buchtiefe, Alarm am Turm = Margin Calls.",
        "<b>Aus der Stadt heraus</b> steuerbar: ein <b>Szenario</b> laden (auch die fünf "
        "historischen Episoden), ein <b>Experiment</b> starten und seine gemessene Prüfung "
        "lesen, eine <b>Nachricht</b> von Hand einspeisen, jeden <b>Regler</b> bewegen, eine "
        "<b>Aufzeichnung</b> öffnen, den Lauf zurücksetzen. Das <font name='Courier' "
        "size='8'>?</font> oben links sagt, was die Stadt zeigt und was zuerst zu probieren "
        "ist; ein Klick auf ein Viertel erklärt es und stellt ein echtes Mitglied in die "
        "Einheiten-Karte.",
        "<b>Replay in der Stadt</b>: ein aufgezeichneter Lauf wird aus seinem Seed "
        "nachgerechnet, nicht aus Kurven gelesen — deshalb steht an jeder Position der "
        "ganze Zustand bereit und der Regler bewegt die komplette Karte samt Orderbuch.",
        "<b>Zwei Maßstäbe</b>: nach hundert Handelstagen hält ein Lager fast das gesamte "
        "Kapital, die Spreizung erreicht 135× und auf der Euro-Leiter stehen die übrigen "
        "Viertel alle auf Minimalhöhe. <b>EURO</b> bleibt der ehrliche Standard, "
        "<b>VERGLEICH</b> ist logarithmisch und sagt das in derselben Zeile.",
        "<b>Kurs, Kerzen, Orderbuch</b>: das Markt-Panel links zeigt dasselbe Instrument "
        "auf drei Ebenen — Kurs gegen fairen Wert, Tageskerzen und die ruhenden Orders. "
        "Das Buch ist die Stelle, an der ein Kurs in diesem Modell entsteht; fast die "
        "gesamte Tiefe liegt am Touch, wo die Market Maker sie hinstellen.",
        "<b>Die Analyseseite</b> (<font name='Courier' size='8'>/sectors</font>): Sektor-"
        "Kacheln mit Sparklines, ein Instrument-Panel mit Kerzen, Orderbuch und Tape, "
        "Korrelations-Heatmap, Zentralbank mit Duration je Sektor, Validierungspanel mit "
        "Varianz-Ratio, A/B-Vergleich, Replay-Regler.",
        "<b>Die Indextafel</b> (<font name='Courier' size='8'>/indices</font>): alle "
        "Indizes live auf einer Achse, auf den Fensterstart normiert, dazu je Index "
        "Stand, Fair-Wert-Index, Volatilität, Drawdown, Breite und das <i>gemessene</i> "
        "Beta gegen das im Faktormodell gesetzte. Ein Index ist hier eine Messung: "
        "gewichtet mit den Anteilen, die der ETF selbst kauft, und verkettet.",
        "<b>Die Traderliste</b> (<font name='Courier' size='8'>/traders</font>): alle "
        "Agenten nebeneinander statt einer nach dem anderen — Kapital, Bargeld, "
        "Positionen, Hebel, Ergebnis seit Laufbeginn, Zwangsverkäufe. Sortier- und "
        "filterbar im Backend, mit Rollups je Viertel und einem Sprung zurück in die "
        "Stadt zu genau diesem Agenten.",
        "<b>Jeder Parameter</b> ist einmal deklariert (<font name='Courier' size='8'>"
        "PARAM_SPEC</font>) und das Bedienfeld wird daraus erzeugt — ein neuer Parameter "
        "erscheint ohne Änderung am Frontend.",
    ])

    f += [p("Messen und vergleichen", "h2")]
    rows = [["Werkzeug", "Antwortet auf"],
            ["<font name='Courier' size='8'>calibrate.py</font>",
             "Erfüllt das Modell die sechs Kriterien — pro Instrument, über mehrere Seeds?"],
            ["<font name='Courier' size='8'>sweep.py ablate</font>",
             "Welcher Mechanismus ist für welche Eigenschaft verantwortlich? Schaltet jeden "
             "einzeln ab."],
            ["<font name='Courier' size='8'>sweep.py param</font>",
             "Wie hängt eine Kennzahl von einem Parameter ab, über einen Wertebereich?"],
            ["<font name='Courier' size='8'>/api/compare</font>",
             "Was macht dieser Parameter, bei gleichem Zufallsstart?"],
            ["<font name='Courier' size='8'>/api/compare/sweep</font>",
             "Ist der Unterschied größer als die Streuung zwischen Seeds? Liefert Signal/Rauschen."],
            ["<font name='Courier' size='8'>run.py</font>",
             "Ein Lauf ohne Oberfläche, als Parquet exportiert für die Auswertung im Notebook."],
            ["<font name='Courier' size='8'>/api/replay</font>",
             "Einen aufgezeichneten Lauf beliebig durchscrubben."],
            ["<font name='Courier' size='8'>/api/explain</font>",
             "Was passiert gerade, warum, worauf achten — als Text."],
            ["<font name='Courier' size='8'>/api/lessons/{k}/check</font>",
             "Hat das Experiment gezeigt, was es zeigen wollte? Gemessen."]]
    f += [table(rows, [40 * mm, 122 * mm]), Spacer(1, 8)]

    f += callout("Warum der A/B-Vergleich jetzt zählt — und vorher nicht",
                 "Jeder Agent zieht aus <b>seinem eigenen</b> Zufallsstrom, gesetzt aus "
                 "Seed und Agenten-ID. Mit einem gemeinsamen Strom hing die Zahl "
                 "verbrauchter Zufallszahlen davon ab, was ein Agent entschied — der erste "
                 "Verhaltensunterschied warf alle aus dem Tritt, und aus einem Kanal im "
                 "Wert von 0,4 % wurden 39 % Unterschied. Jetzt skaliert die Wirkung mit "
                 "ihrer Ursache: Kreditaufschlag +5 Basispunkte ergibt 0,4 % Abstand, "
                 "Trendfolge 55 auf 140 ergibt 3,5 %. Und ein Parameter, der nichts bewirken "
                 "<i>kann</i> — Hebelgrenze ohne Hebel-Fonds — erzeugt bitidentische "
                 "Läufe. Dieser Kontrolltest steht in der Suite.", TEAL)

    f += [p("Szenarien", "h2")]
    f += [p("Ein Szenario schreibt nie einen Kursverlauf. Es setzt Bedingungen und liefert "
            "Schlagzeilen — was der Kurs dann macht, ist die Antwort des Modells.")]
    f += bullets([
        "<b>Grundszenarien:</b> Ruhiger Markt · Blasenbildung · Hebel-Crash · "
        "ETF-Dominanz · Nachrichtenschock",
        "<b>Historische Episoden:</b> Dotcom 1998–2000 · Finanzkrise 2008 · "
        "COVID-Crash 2020 · Meme-Aktie 2021 · Zinswende 2022",
    ])
    f += [p("Die historischen Episoden bilden <b>Mechanismen</b> nach, keine Kursverläufe. "
            "Parameter zu drehen, bis ein Chart zur Geschichte passt, würde nichts "
            "beweisen. Die Frage ist enger und beantwortbar: Erzeugt der Mechanismus, dem "
            "man diese Episode zuschreibt, in einem Modell, das nicht dafür gebaut wurde, "
            "diese Art von Verhalten?", "small")]
    f += [PageBreak()]

    # --------------------------------------------------------- 7 methode
    f += [p("7 · Die Methode — und warum sie den Unterschied macht", "h1")]
    f += [p("Der lehrreichste Teil dieses Projekts ist nicht das Ergebnis, sondern der Weg "
            "dorthin. Fast jede plausible Erklärung war falsch.", "lead")]

    f += [p("Der Test, der alles erklärte", "h2")]
    f += [p("Das <b>Varianz-Ratio</b> — Var(k-Perioden-Rendite) / (k · Var(1-Periode)) — "
            "trennt dauerhafte von vorübergehender Varianz. Ein Random Walk ergibt 1 auf "
            "jedem Horizont.")]
    f += [code(["  20 Schritte   5,79     stark trendend",
                " 240 Schritte   0,72     ein Tag, schon rückkehrend",
                "4800 Schritte   0,066    zwanzig Tage"])]
    f += [p("0,066 heißt: die Varianz der 20-Tage-Renditen betrug 6,6 % dessen, was ein "
            "Random Walk ergäbe. Der Kurs war am fairen Wert festgenagelt — 79 % "
            "Kursvolatilität gegen 15 % Fundamentalvolatilität, also waren rund 90 % "
            "aller Kursbewegung vorübergehend. Und vorübergehende Bewegung <i>muss</i> "
            "zurückgenommen werden. Daher kam die negative Autokorrelation. Kein "
            "einzelner Agententyp war schuld.")]

    f += [p("Was ausgeschlossen wurde", "h2")]
    rows = [["Hypothese", "Test", "Ergebnis"],
            ["Market Maker verschieben mit ihrem Bestand die Preise",
             "vollständig entfernen", "ACF bleibt bei -0,40"],
            ["Ständiges Rebalancing (Ziel = Vermögen ÷ Kurs)",
             "Toleranzschwelle 5–30 %", "kein Effekt, andere Kriterien schlechter"],
            ["Emittent übersteuert (Bang-Bang-Regelung)",
             "proportionale Emission", "kein Effekt"],
            ["Value-Investoren korrigieren zu schnell",
             "Rückholkraft 0,08 statt 0,005", "ACF wird <i>schlechter</i> (-0,22)"],
            ["Handelstag zu kurz",
             "10 / 30 / 120 / 360 Schritte/Tag", "ACF(1) rund -0,4 durchgehend"],
            ["Messrauschen im Schlusskurs",
             "Mittelung über die letzten 5 % des Tages", "-0,43 wird -0,39"],
            ["Bewertung wird zu schnell erkannt",
             "Verzögerung 0,5 / 12 / 30 Tage",
             "<b>schlechter</b>: Kurs trendet statt zurückzukehren, Korrelation fällt "
             "0,42 auf 0,13, und die Kaskade feuert nicht mehr"]]
    f += [table(rows, [56 * mm, 47 * mm, 59 * mm]), Spacer(1, 6)]
    f += [p("Zwei dieser Schlüsse ersetzten frühere, die aus denselben Experimenten "
            "<i>vor</i> einer Korrektur am Strategiewechsel gezogen worden waren. Die "
            "Dynamik hatte sich darunter verändert — ein gutes Argument dafür, eine "
            "Ablation neu zu rechnen statt einer Notiz zu vertrauen. Dafür gibt es "
            "<font name='Courier' size='8'>scripts/sweep.py ablate</font>.", "small")]

    # Kept together: the last bullet used to spill onto a page of its own.
    worked = [p("Was gewirkt hat", "h2")]
    worked += bullets([
        "<b>Volatilitätscluster und Mean Reversion waren derselbe Mechanismus.</b> Das "
        "Cluster kam aus Regimewechseln — und der Wechsel zurück zu Value <i>ist</i> die "
        "Rückkehr. Jeder Parameter, der die Autokorrelation verbesserte, zerstörte das "
        "Cluster. Die Lösung war eine zweite, unabhängige Cluster-Quelle: geschubte "
        "Nachrichten (die Volatilität des fairen Werts ist selbst persistent).",
        "<b>Aktivität folgt der Nachrichtenlage</b> (Clark 1973): Volumen und Volatilität "
        "sind beide Folgen der Informationsrate, nicht Folgen voneinander.",
        "<b>Das Kapital eines Marktes muss mit der Zahl der Märkte skalieren.</b> Bei fünf "
        "Sektoren sah jeder Markt ein Fünftel des Kapitals, während der faire Wert genauso "
        "schnell diffundierte. Die Kurse kamen nicht mit, und die Korrelation aus dem "
        "Faktormodell erreichte sie kaum: 0,07 statt realistischer 0,4–0,6. Nach der "
        "Skalierung: <b>0,40</b>.",
        "<b>Margin Calls waren im Standard toter Code.</b> Die Fonds erreichen ~1,6× Hebel, "
        "eine Schwelle von 0,25 wird nie berührt. Sie ist jetzt gegen den Hebel gesetzt, "
        "den das Modell tatsächlich erzeugt.",
    ])
    f += [KeepTogether(worked), PageBreak()]

    # ------------------------------------------------------ 8 wo es falsch ist
    f += [p("8 · Wo das Modell falsch liegt", "h1")]
    f += [p("Vollständig, weil eine Simulation ohne diese Liste nicht beurteilbar ist.", "small")]
    rows = [["Befund", "Wie weit vom Ziel", "Diagnose"],
            ["Renditen sind prognostizierbar", "ACF -0,22 statt ±0,1",
             "Der beste erreichte Wert war -0,03 auf einem Seed — in einer Konfiguration mit "
             "Sektor-Korrelation 0,19 und ohne Margin Calls. Der Zielkonflikt ist nicht gelöst."],
            ["Volumen folgt der Volatilität nicht", "-0,07 statt &gt; 0,1",
             "Das meiste Volumen ist Market-Maker-Volumen und steigt nicht mit der Hektik. "
             "Gegenmaßnahmen verschlechterten vier andere Kennzahlen."],
            ["Volatilität zu hoch", "1,31 p. a. gegen real 0,15–0,25",
             "Teilweise Folge der aktiven Kaskade: Zwangsverkäufe erzeugen Volatilität."],
            ["Ein Sektor weit vom fairen Wert", "Finanzen 89 %, die übrigen unter 40 %",
             "Der Emittent greift erst über seiner Schwelle; in einem langlaufenden Sektor "
             "reicht der Fluss nicht, um mitzuhalten."],
            ["Kurtosis instabil", "5,4 ± 5,9",
             "Getrieben von seltenen, sehr großen Einzeltagen in dünnen Sektoren, nicht von "
             "durchgehend schweren Rändern."]]
    f += [table(rows, [42 * mm, 40 * mm, 80 * mm]), Spacer(1, 8)]

    f += [p("Nicht gebaut", "h2")]
    f += bullets([
        "<b>Keine Dividenden, keine Gewinne.</b> Der faire Wert ist ein exogener Prozess, "
        "nicht etwas, das ein Unternehmen erwirtschaftet — Rückkäufe werden aus einer "
        "Kasse bezahlt, die sich nie aus dem Geschäft füllt.",
        "<b>Die vier Ansichten bleiben getrennt.</b> Stadt, Analyse, Indizes und Trader "
        "zeigen dieselbe Simulation aus vier Blickwinkeln; zusammengelegt wurde nichts, "
        "weil die Stadt genau deshalb lesbar ist, dass sie einen Markt zeichnet.",
        "<b>Kein Reinforcement Learning und keine LLM-Agenten.</b> Bewusst gestrichen: "
        "beides kostet Reproduzierbarkeit, und ohne festen Seed taugt kein Lauf als Ergebnis.",
    ])
    f += rule()

    # ----------------------------------------------------------- 9 referenz
    f += [p("9 · Befehlsreferenz", "h1")]
    f += [code([
        "./start.sh                                          Oberfläche starten",
        "",
        "python scripts/calibrate.py --runs 5 --steps 90000  Validierung, pro Instrument",
        "python scripts/sweep.py ablate --steps 80000        jeden Mechanismus einzeln abschalten",
        "python scripts/sweep.py param --name n_passive \\",
        "       --values 0,50,100,200                        einen Parameter abfahren",
        "python scripts/run.py --steps 120000 --name basis   Lauf ohne UI, Parquet-Export",
        "python scripts/run.py --scenario gfc2008 --name krise",
        "",
        "python -m pytest tests/ -q                          315 Tests",
    ])]

    f += [p("Wo im Code was steht", "h2")]
    rows = [["Datei", "Inhalt"],
            ["<font name='Courier' size='8'>mes/orderbook.py</font>", "Matching Engine, Preis-Zeit-Priorität — das Fundament"],
            ["<font name='Courier' size='8'>mes/agents.py</font>", "die sieben Entscheidungsregeln"],
            ["<font name='Courier' size='8'>mes/simulation.py</font>", "die Schleife, Settlement, Margin, Strategiewechsel"],
            ["<font name='Courier' size='8'>mes/market.py</font>", "ein Instrument: Buch, Historie, Tagesbars"],
            ["<font name='Courier' size='8'>mes/instruments.py</font>", "die fünf Sektoren und das Faktormodell"],
            ["<font name='Courier' size='8'>mes/centralbank.py</font>", "Taylor-Regel, Makroblock, die drei Kanäle"],
            ["<font name='Courier' size='8'>mes/metrics.py</font>", "die Stylized-Facts-Prüfungen und das Varianz-Ratio"],
            ["<font name='Courier' size='8'>mes/compare.py</font>", "A/B mit Signal/Rausch-Bewertung"],
            ["<font name='Courier' size='8'>mes/narrator.py</font>", "Zustand wird Erklärung: was, warum, worauf achten"],
            ["<font name='Courier' size='8'>mes/lessons.py</font>", "die sieben Experimente, jedes mit gemessener Prüfung"],
            ["<font name='Courier' size='8'>mes/config.py</font>", "jeder Parameter, einmal deklariert"],
            ["<font name='Courier' size='8'>web/index.html</font>", "die Stadt (2.5D, ohne Buildstep)"],
            ["<font name='Courier' size='8'>web/sectors.html</font>", "die Analyseseite"],
            ["<font name='Courier' size='8'>web/indices.html</font>", "die Indextafel: alle Indizes live gegeneinander"],
            ["<font name='Courier' size='8'>web/traders.html</font>", "die Traderliste: alle Agenten, sortier- und filterbar"],
            ["<font name='Courier' size='8'>mes/indices.py</font>", "die Indexkonstruktion — verkettet, ETF-gewichtet"],
            ["<font name='Courier' size='8'>mes/traders.py</font>", "Population zu Tabelle: der einzige Übersetzungspunkt"]]
    f += [table(rows, [46 * mm, 116 * mm]), Spacer(1, 10)]

    f += [p("Literatur", "h2")]
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
    print("geschrieben:", build())
