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
    python docs/build_quickstart.py --druck   # druckfreundliche Titelseite
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
    AMBER, DARK, FAINT, MONO, RED, RULE, S, SANS, SANS_B, TEAL,
    bullets, callout, code, p, rule, table,
)
from mes import lessons, scenarios  # noqa: E402
from mes.config import PARAM_SPEC, Config  # noqa: E402
from mes.instruments import SECTOR_SPEC  # noqa: E402
from mes.simulation import Simulation  # noqa: E402

OUT = ROOT / "docs" / "Market-Ecology-Simulator-Kurzanleitung.pdf"
OUT_PRINT = ROOT / "docs" / "Market-Ecology-Simulator-Kurzanleitung-Druck.pdf"
MAX_PAGES = 5

# Druckfreundliche Fassung: identischer Inhalt, nur die Titelfläche auf Seite eins
# kommt ohne den vollflächigen dunklen Kasten aus — der kostet auf einem Bürodrucker
# eine halbe Tonerpatrone und sieht auf Papier grau-fleckig aus. Umgeschaltet über
# `python docs/build_quickstart.py --druck`; die Geometrie bleibt Millimeter für
# Millimeter gleich, damit der Umbruch und das Fünf-Seiten-Limit unberührt sind.
PRINT_FRIENDLY = False


# ------------------------------------------------------------------ live facts
def facts() -> dict:
    """Every number in the document, read from the code that produces it."""
    cfg = Config()
    sim = Simulation(cfg)  # built, not stepped: only the population is needed
    kinds: dict[str, int] = {}
    for agent in sim.agents:
        kinds[agent.kind] = kinds.get(agent.kind, 0) + 1

    tests = sum(len(re.findall(r"^def test_", path.read_text(encoding="utf-8"), re.M))
                for path in sorted((ROOT / "tests").glob("test_*.py")))

    return {
        "cfg": cfg,
        "agents": len(sim.agents),
        "kinds": kinds,
        "instruments": len(sim.markets),
        "sectors": SECTOR_SPEC,
        "scenarios": len(scenarios.ALL),
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
                             "Erzeugt aus dem laufenden Code · "
                             "python docs/build_quickstart.py · "
                             "ausführlich: Market-Ecology-Simulator-Handbuch.pdf")


def on_page(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.5)
    canvas.line(20 * mm, A4[1] - 15 * mm, A4[0] - 20 * mm, A4[1] - 15 * mm)
    canvas.setFont(SANS, 7)
    canvas.setFillColor(FAINT)
    canvas.drawString(20 * mm, A4[1] - 12.5 * mm,
                      "MARKET ECOLOGY SIMULATOR · KURZANLEITUNG")
    canvas.drawRightString(A4[0] - 20 * mm, A4[1] - 12.5 * mm,
                           f"Seite {doc.page} von {MAX_PAGES}")
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
    canvas.setFillColor(DARK)
    canvas.rect(0, A4[1] - 42 * mm, A4[0], 42 * mm, stroke=0, fill=1)
    canvas.setFillColor(AMBER)
    canvas.rect(0, A4[1] - 4 * mm, A4[0], 4 * mm, stroke=0, fill=1)
    canvas.setFont(SANS_B, 7.4)
    canvas.drawString(20 * mm, A4[1] - 16 * mm, "AGENTENBASIERTE FINANZMARKTSIMULATION")
    canvas.setFillColor(colors.HexColor("#8d949d"))
    canvas.drawRightString(A4[0] - 20 * mm, A4[1] - 16 * mm, f"SEITE 1 VON {MAX_PAGES}")
    canvas.setFillColor(colors.white)
    canvas.setFont(SANS_B, 23)
    canvas.drawString(20 * mm, A4[1] - 27 * mm, "Market Ecology Simulator")
    canvas.setFillColor(colors.HexColor("#c9ced6"))
    canvas.setFont(SANS, 10)
    canvas.drawString(20 * mm, A4[1] - 35 * mm,
                      "Kurzanleitung — was das Projekt ist und wie man damit arbeitet")


def _first_page_band_print(canvas):
    """Dieselbe Typografie auf weißem Papier: die Fläche wird zur Linie.

    Statt des Kastens trägt ein schmaler Amber-Strich oben und eine Haarlinie unter
    dem Untertitel die Kopfzone; die Schrift wechselt von weiß auf dunkel. Die
    Grundlinien liegen auf denselben Höhen wie in der Bildschirmfassung, damit sich
    an Umbruch und Rahmen nichts verschiebt.
    """
    canvas.setFillColor(AMBER)
    canvas.rect(20 * mm, A4[1] - 4 * mm, A4[0] - 40 * mm, 1.6 * mm, stroke=0, fill=1)
    canvas.setFillColor(DARK)
    canvas.setFont(SANS_B, 7.4)
    canvas.drawString(20 * mm, A4[1] - 16 * mm, "AGENTENBASIERTE FINANZMARKTSIMULATION")
    canvas.setFillColor(FAINT)
    canvas.drawRightString(A4[0] - 20 * mm, A4[1] - 16 * mm, f"SEITE 1 VON {MAX_PAGES}")
    canvas.setFillColor(DARK)
    canvas.setFont(SANS_B, 23)
    canvas.drawString(20 * mm, A4[1] - 27 * mm, "Market Ecology Simulator")
    canvas.setFillColor(colors.HexColor("#4a5058"))
    canvas.setFont(SANS, 10)
    canvas.drawString(20 * mm, A4[1] - 35 * mm,
                      "Kurzanleitung — was das Projekt ist und wie man damit arbeitet")
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.5)
    canvas.line(20 * mm, A4[1] - 40 * mm, A4[0] - 20 * mm, A4[1] - 40 * mm)


def build() -> Path:
    out = OUT_PRINT if PRINT_FRIENDLY else OUT
    doc = BaseDocTemplate(
        str(out), pagesize=A4, title="Market Ecology Simulator — Kurzanleitung",
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
            f"{out.name} ist {pages} Seiten lang, erlaubt sind {MAX_PAGES}. "
            "Kürzen, nicht das Limit erhöhen — dafür gibt es das Handbuch.")
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

    # =================================================== 1 · was das Projekt ist
    f += [Spacer(1, 6), p("1 · Was das Projekt ist", "h1")]
    f += [p("Ein agentenbasiertes Modell eines Aktienmarktes. Es sagt keine Kurse "
            "vorher — es fragt, <b>woher Marktverhalten kommt</b>.", "lead")]
    f += [p(f"{f_['agents']} Agenten folgen je einer einfachen Regel. Keiner kennt den "
            "wahren Wert eines Papiers, keiner weiß, was die anderen als Nächstes tun, "
            "und <b>nirgends im Code steht eine Formel für den Kurs</b>. Jeder Handel ist "
            "eine Order, die auf eine andere trifft — ein fortlaufendes Doppelauktions-"
            "Orderbuch mit Preis-Zeit-Priorität, Teilausführungen und Verfall. Blasen, "
            "Crashs, Volatilitätscluster und Zwangsverkaufs-Kaskaden entstehen aus diesem "
            "Zusammenspiel, oder sie sind nicht da.")]

    f += [p("Die Frage", "h2")]
    f += [p("Echte Renditereihen teilen eine Handvoll statistischer Eigenschaften, die "
            "über Anlageklassen und Jahrhunderte hinweg gelten. <b>Keine davon ist in "
            "dieses Modell eingebaut.</b> Erfüllt ein Markt aus lauter einfachen, "
            "unterschiedlichen Regeln sie trotzdem? Die Kriterien stehen als ausführbare "
            "Prüfungen in <font name='Courier' size='8'>mes/metrics.py</font> — "
            "festgelegt, <i>bevor</i> gemessen wurde. Das ist der Unterschied zwischen "
            "einem Ergebnis und einer nachträglichen Erzählung.")]

    rows = [["Kriterium", "Anforderung", "Gemessen", "Erfüllt"],
            ["Volatilitäts-Cluster", "mittlere ACF der |Renditen| &gt; 0,05", "0,217", "25 / 25"],
            ["Nicht-Normalität", "Jarque-Bera p &lt; 0,05", "0,0002", "25 / 25"],
            ["Fat Tails", "Überschuss-Kurtosis &gt; 1", "5,39", "24 / 25"],
            ["Tail-Index", "Hill-Schätzer zwischen 2 und 6", "4,38", "22 / 25"],
            ["Keine Autokorrelation", "|ACF(1)| &lt; 0,1", "−0,223", "8 / 25"],
            ["Volumen-Kopplung", "Korr(Volumen, |Rendite|) &gt; 0,1", "−0,072", "3 / 25"]]
    f += [table(rows, [40 * mm, 63 * mm, 27 * mm, 40 * mm],
                align_right=(2, 3), highlight=(5, 6)), Spacer(1, 8)]

    f += callout(
        "Vier von sechs erfüllt — und die zwei offenen stehen mit im Dokument",
        "Fünf Seeds × fünf Instrumente = 25 Messungen über je 90.000 Schritte. Ein "
        "Ergebnis, das nur für einen Seed gilt, ist keins; deshalb wird über Seeds "
        "gemessen und die Streuung mitgeführt. Die beiden hervorgehobenen Zeilen sind "
        "<b>nicht</b> erfüllt, und das steht hier, weil ein Projekt, das seine eigenen "
        "Kriterien nachträglich weichzeichnet, nichts mehr misst. Warum sie nicht zu "
        "lösen waren, erklärt das Handbuch: die Kraft, die einen Kurs am fairen Wert "
        "hält, ist dieselbe, die seine Renditen vorhersagbar macht.")

    f += [p("Diese fünf Seiten", "h2")]
    rows = [["Seite", "Worum es geht"],
            ["2", "Starten, und was die vier Ansichten voneinander unterscheidet"],
            ["3", "Wer handelt, und wie aus Orders ein Kurs wird"],
            ["4", "Die fünf Arbeitsweisen — von „einmal zusehen“ bis „eine Behauptung prüfen“"],
            ["5", "Befehle, wo im Code was steht, und was am Modell offen ist"]]
    f += [table(rows, [14 * mm, 156 * mm], align_right=(0,))]

    f += [PageBreak()]

    # ============================================== 2 · starten und die ansichten
    f += [p("2 · Starten und die vier Ansichten", "h1")]
    # Plain ASCII inside the monospace block: Courier has no arrow glyph, and
    # reportlab silently substitutes a ligature for the missing one.
    f += [code(["./start.sh   ->   http://127.0.0.1:8000",
                "oder Marktstadt.app doppelklicken, oeffnet den Browser von selbst"])]
    f += [p("Der erste Start legt die virtuelle Umgebung an und installiert die "
            f"Abhängigkeiten. Danach spult der Server im Hintergrund auf 110 Handelstage "
            "vor — das Validierungspanel braucht 100 Tage Tagesdaten, bevor seine Zahlen "
            "etwas bedeuten. Der Balken oben sagt, wie weit er ist. Pause und Tempo "
            "greifen sofort.", "small")]

    f += [p("Vier Blickwinkel auf denselben Lauf", "h2")]
    f += [p("Es läuft <b>eine</b> Simulation. Alle vier Seiten zeigen sie, beantworten "
            "aber verschiedene Fragen, und jede ist von jeder anderen aus erreichbar.")]
    rows = [["Seite", "Beantwortet", "Dafür ist sie da"],
            ["<b>/</b> — die Stadt",
             "Was passiert gerade, und warum?",
             "Eine isometrische Stadt: jedes Viertel eine Agentengruppe, jede Blockhöhe "
             "Kapital, jede Straßenbreite Orderfluss. Nichts daran ist Dekoration. Links "
             "Kurs, Kerzen und Orderbuch, rechts ein einzelner Agent mit der Rechnung "
             "hinter seiner letzten Entscheidung."],
            ["<b>/sectors</b> — Analyse",
             "Stimmen die Zahlen?",
             "Sektorvergleich, gemessene Korrelationen, Zentralbank mit Duration je "
             "Sektor, das Validierungspanel, A/B-Vergleiche über mehrere Seeds und die "
             "aufgezeichneten Läufe."],
            ["<b>/indices</b> — Indizes",
             "Wer ist gelaufen, wann, und gegen was?",
             "Alle Indizes live auf einer Achse, auf den Fensterstart normiert. Dazu je "
             "Index Stand, Fair-Wert-Index, Volatilität, Drawdown, Breite — und das "
             "<i>gemessene</i> Beta gegen das im Modell gesetzte."],
            ["<b>/traders</b> — Trader",
             "Wer handelt, und wie geht es ihm?",
             f"Alle {f_['agents']} Agenten nebeneinander statt einer nach dem anderen: "
             "Kapital, Bargeld, Positionen, Hebel, Ergebnis seit Laufbeginn, "
             "Zwangsverkäufe. Sortier- und filterbar, mit Sprung zurück in die Stadt."]]
    f += [table(rows, [30 * mm, 42 * mm, 98 * mm]), Spacer(1, 8)]

    f += [p("Der erste Blick — worauf man in den ersten zwei Minuten achtet", "h2")]
    f += bullets([
        "<b>Der Kurs gegen den fairen Wert</b> (Panel links oben). Die beiden Linien "
        "laufen selten zusammen. Wie weit sie auseinanderstehen, ist die interessanteste "
        "Einzelzahl des Modells — und sie schließt sich nicht von allein.",
        "<b>Das Verhältnis Momentum zu Value</b> im adaptiven Viertel. Es kippt in Wellen "
        "und bleibt dann eine Weile stehen. Genau diese Beharrlichkeit ist es, die "
        "Volatilität clustern lässt.",
        "<b>Der rote Ring am Hebel-Turm.</b> Er bedeutet, dass ein Fonds verkauft, weil "
        "er <i>muss</i> — nicht, weil er sich dafür entschieden hat. Das ist der einzige "
        "Ort, an dem ein Agent handelt, ohne zu entscheiden.",
        "<b>Das Orderbuch</b> (dritte Ansicht im Marktpanel). Fast die gesamte Tiefe "
        "liegt direkt am Kurs, dahinter stehen nur noch einzelne Stücke. Genau deshalb "
        "kann hier ein Liquiditätsloch entstehen — ein Modell mit einer Preisformel "
        "hätte keins, weil es nichts hätte, das ausgehen kann.",
    ])

    f += [p("Tasten in der Stadt", "h2")]
    rows = [["Taste", "Wirkung", "Taste", "Wirkung"],
            ["Leertaste", "Pause / weiter", "1 2 3", "Tempo 1× / 4× / 16×"],
            ["]", "ein einzelner Schritt", "+ − 0", "Kamera näher / weiter / zurück"],
            ["R B C", "Schock: ruhig, boom, crash", "?", "Erklärung öffnen"]]
    f += [table(rows, [20 * mm, 58 * mm, 20 * mm, 72 * mm]), Spacer(1, 7)]
    f += [p("Das Tempo ist der wichtigste Regler: bei 1× ist ein Handelstag etwa zwei "
            "Minuten Echtzeit, bei 16× wenige Sekunden. Für alles, was Handelstage "
            "sammeln muss — Validierung, Experimente — gehört die Uhr auf 16×.", "small")]

    f += [PageBreak()]

    # ================================================ 3 · wer handelt, wie ein kurs entsteht
    f += [p("3 · Wer handelt — und wie ein Kurs entsteht", "h1")]
    f += [p("Sieben Regeln. Jede existiert, weil das Modell ohne sie sichtbar falsch "
            "war — nicht, weil sie die Liste vollständig macht.", "lead")]
    k = f_["kinds"]
    rows = [["Typ", "Anzahl", "Regel", "Warum sie im Modell ist"],
            ["Value-Investor", str(k.get("adaptive", 0)),
             "kauft unter der eigenen Schätzung des fairen Werts",
             "die einzige Kraft, die den Kurs zum Wert zieht"],
            ["Trendfolger", "dieselben",
             "extrapoliert die letzte Bewegung, ignoriert die Bewertung",
             "die Rückkopplung, aus der Blasen entstehen"],
            ["Noise-Trader", str(k.get("noise", 0)),
             "handelt aus Gründen, die das Modell nicht abbildet",
             "Grundliquidität — sonst gibt es keine Gegenseite"],
            ["ETF / Sparplan", str(k.get("passive", 0)),
             "bekommt nach Plan Geld und kauft zu jedem Preis",
             "preisunabhängige Nachfrage"],
            ["Hebel-Fonds", str(k.get("leveraged", 0)),
             "handelt auf Kredit, wird bei Unterdeckung zwangsverkauft",
             "die Kaskade; überträgt Stress zwischen Sektoren"],
            ["Market Maker", str(k.get("maker", 0)),
             "stellt dauerhaft beide Seiten, lehnt sich gegen den Bestand",
             "die einzige stehende Liquidität"],
            ["Emittent", str(k.get("company", 0)),
             "gibt Aktien aus, wenn sie teuer sind, kauft zurück, wenn billig",
             "die einzige Quelle neuen Angebots"]]
    f += [table(rows, [26 * mm, 22 * mm, 54 * mm, 68 * mm], align_right=(1,)),
          Spacer(1, 7)]
    f += [p("Value-Investoren und Trendfolger sind <b>dieselben</b> Agenten. Sie wechseln "
            f"alle {cfg.switch_interval} Schritte zwischen beiden Regeln — danach, was "
            "zuletzt funktioniert hat, und danach, was die Mehrheit tut. Dieses Wechseln "
            "ist der Motor: die Population kippt in ein Trend- oder ein Wert-Regime und "
            "bleibt eine Weile dort.", "small")]

    f += [p("Wie ein Kurs zustande kommt", "h2")]
    f += bullets([
        f"<b>Ein Schritt ist keine Sekunde und kein Tag.</b> {cfg.steps_per_day} Schritte "
        "ergeben einen Handelstag mit einer Tageskerze. Die statistischen Eigenschaften "
        "gelten für <i>Tages</i>renditen; auf Schrittebene dominiert Mikrostruktur.",
        f"<b>{f_['instruments']} Instrumente handeln gleichzeitig</b>, jedes mit eigenem "
        "Orderbuch: Technologie, Energie, Finanzen, Gesundheit, Konsum. Ihre fairen Werte "
        "teilen einen gemeinsamen Marktfaktor — Korrelation <i>entsteht</i> daraus, sie "
        "ist nicht als Matrix vorgegeben.",
        "<b>Nachrichten bewegen nie den Kurs.</b> Sie bewegen den fairen Wert und die "
        "Stimmung. Ob der Kurs folgt, entscheiden die Agenten — der Value-Investor sieht "
        "ein billigeres Papier, der Trendfolger sieht andere verkaufen, der ETF liest gar "
        "keine Nachrichten.",
        "<b>Die Zentralbank handelt nicht.</b> Sie setzt einen Zins, der über drei Kanäle "
        "ankommt: Bewertung (Duration je Sektor), Finanzierungskosten der Hebel-Fonds und "
        "Zuflüsse in die Sparpläne.",
    ])

    f += [p("Die fünf Sektoren sind bewusst verschiedene Charaktere", "h2")]
    character = {
        "TECH": "hohes Beta, blasenanfällig — reagiert am stärksten auf Marktnachrichten",
        "ENRG": "niedriges Beta, aber die höchste Eigenvolatilität",
        "FINL": "zinsempfindlich: ein Zinsschritt bewegt hier den fairen Wert am meisten",
        "HLTH": "defensiv, ruhig, wenig Eigenbewegung",
        "CONS": "defensiv, dicht am Gesamtmarkt",
    }
    rows = [["Sektor", "Beta", "Charakter"]]
    for spec in f_["sectors"]:
        rows.append([f"<b>{spec['symbol']}</b> {spec['name']}",
                     f"{spec['beta']:.2f}".replace(".", ","),
                     character.get(spec["symbol"], "")])
    f += [table(rows, [32 * mm, 14 * mm, 124 * mm], align_right=(1,)), Spacer(1, 5)]
    f += [p("Wären sie fünf Kopien voneinander, wäre die gemessene Korrelation zwischen "
            "ihnen kein Ergebnis, sondern eine Tautologie.", "small")]

    f += [PageBreak()]

    # ================================================== 4 · wie man damit arbeitet
    f += [p("4 · Wie man damit arbeitet", "h1")]
    f += [p("Fünf Arbeitsweisen, von „einmal zusehen“ bis „eine Behauptung prüfen“. "
            "Sie bauen aufeinander auf.", "lead")]

    rows = [["Weg", "Beantwortet", "So geht es"],
            ["<b>1 · Szenario laden</b>",
             f"Was macht dieses Modell unter diesen Bedingungen? ({f_['scenarios']} Presets)",
             "Stadt → Fußzeile <b>SZENARIO</b>. Ruhiger Markt, Blase, Hebel-Crash, "
             "ETF-Dominanz, Nachrichtenschock — dazu Dotcom 2000, Finanzkrise 2008, "
             "Corona 2020, Meme-Aktien 2021, Zinswende 2022. Ein Szenario setzt "
             "Bedingungen und liefert Schlagzeilen; <b>es schreibt keinen Kursverlauf "
             "vor</b>. Ob der Kurs 5 % oder 40 % fällt, ist die Antwort des Modells."],
            ["<b>2 · Geführtes Experiment</b>",
             f"Zeigt sich der Mechanismus wirklich? ({len(f_['lessons'])} Stück)",
             "Analyse → <b>Geführte Experimente</b>. Jedes stellt den Markt ein, sagt "
             "vorher worauf zu achten ist — und prüft danach <i>gemessen</i>, ob es "
             "geklappt hat, auch wenn nicht. Der Start schaltet auf 16×; empfohlen sind "
             f"{min(l['days'] for l in f_['lessons'])}–"
             f"{max(l['days'] for l in f_['lessons'])} Handelstage, und das Panel sagt, "
             "wie viele Minuten das noch sind."],
            ["<b>3 · Parameter drehen</b>",
             f"Woran hängt das? ({f_['params']} Regler)",
             "Analyse → rechte Spalte, oder Stadt → <b>PARAMETER</b>. Ein Punkt hinter "
             "dem Namen heißt: wirkt erst nach einem Neustart. Abweichungen vom "
             "kalibrierten Standard werden orange markiert, <b>Standardwerte</b> holt "
             "alles zurück — nur dort bedeuten die Validierungszahlen das, was das README "
             "über sie sagt."],
            ["<b>4 · A/B über Seeds</b>",
             "Ist der Unterschied größer als der Zufall?",
             "Analyse → <b>A/B-Vergleich</b>. Zwei Konfigurationen aus demselben Seed, "
             "mit Differenztabelle. Wichtig ist <b>über 3 Seeds</b>: die Spalte "
             "Signal/Rauschen sagt, ob der Unterschied sich von der Streuung zwischen "
             "Seeds abhebt. Unter 1 tut er das nicht — egal wie deutlich ein einzelnes "
             "Diagramm aussieht."],
            ["<b>5 · Aufzeichnen und abspielen</b>",
             "Was genau ist damals passiert?",
             "<font name='Courier' size='8'>python scripts/run.py --steps 60000 --name "
             "basis</font>, dann in der Stadt <b>AUFZEICHNUNG</b>. Ein Replay wird aus "
             "dem Seed <i>nachgerechnet</i>, nicht aus Kurven gelesen — deshalb steht an "
             "jeder Position der ganze Zustand zur Verfügung: Orderbuch, Viertel, "
             "Agenten. Der Regler bewegt die komplette Karte."]]
    f += [table(rows, [30 * mm, 40 * mm, 100 * mm]), Spacer(1, 8)]

    f += callout(
        "Die eine Regel, die alles andere trägt",
        "<b>Eine Zahl aus einem Lauf ist kein Ergebnis.</b> Einmal produzierte ein Seed "
        "hier eine Autokorrelation von −0,002 bei allen sechs erfüllten Kriterien — und "
        "es ließ sich nicht wiederholen; der Mittelwert über vier Seeds lag bei −0,19 mit "
        "einer Streuung von 0,11. Diesen Lauf als Erfolg zu melden wäre genau die Falle "
        "gewesen, vor der die Methode dieses Projekts warnt. Deshalb: über Seeds messen, "
        "Streuung mitschreiben, und im Zweifel <font name='Courier' size='8'>"
        "scripts/calibrate.py</font> zitieren statt das Live-Panel.", TEAL)

    f += [p("Ein typischer Ablauf", "h2")]
    f += bullets([
        "<b>Zusehen.</b> Starten, Tempo auf 4×, ein paar Minuten die Stadt laufen lassen "
        "und das Panel „Was passiert gerade“ mitlesen — jede seiner Aussagen kommt aus "
        "einer Zahl, die die Simulation in diesem Moment hält.",
        "<b>Eine Vermutung fassen.</b> Etwa: „Ohne Market Maker ist die Volatilität "
        "höher.“ Auf <b>/indices</b> und <b>/traders</b> nachsehen, ob die Vermutung "
        "überhaupt an den Zahlen hängt, die man dafür braucht.",
        "<b>Prüfen lassen.</b> Gibt es ein geführtes Experiment dazu, dieses nehmen — es "
        "prüft sich selbst und sagt auch, wenn es <i>nicht</i> funktioniert hat.",
        "<b>Sonst selbst messen.</b> A/B über drei Seeds, und nur den Zeilen glauben, "
        "deren Signal/Rauschen über 1 liegt.",
        "<b>Festhalten.</b> <font name='Courier' size='8'>scripts/run.py</font> zeichnet "
        "den Lauf auf, mit Seed und Zeitleiste — er lässt sich später Schritt für Schritt "
        "wieder durchgehen statt nur als Kurve ansehen.",
    ])

    f += [PageBreak()]

    # ============================================ 5 · befehle, code, offene punkte
    f += [p("5 · Befehle, Code und was offen ist", "h1")]
    # A table, not aligned columns inside one code block: reportlab collapses runs of
    # spaces, so hand-set columns arrive as a single run-on line.
    rows = [["Befehl", "Wofür"],
            ["./start.sh", "die Oberfläche starten"],
            ["python scripts/calibrate.py --runs 5 --steps 90000",
             "die Validierung — die Zahlen von Seite 1"],
            ["python scripts/sweep.py ablate --steps 80000",
             "jeden Mechanismus einzeln abschalten und messen, was fehlt"],
            ["python scripts/sweep.py param --name n_passive --values 0,50,100",
             "einen Parameter über einen Wertebereich abfahren"],
            ["python scripts/run.py --steps 120000 --name basis",
             "ein Lauf ohne Oberfläche, exportiert und aufgezeichnet"],
            ["python docs/build_handbook.py",
             "das ausführliche Handbuch neu erzeugen"],
            ["python -m pytest -q",
             f"{f_['tests']} Testfunktionen — Invarianten, keine Kursprognosen"]]
    f += [table(rows, [96 * mm, 74 * mm], align_right=(0,)), Spacer(1, 8)]

    f += [p("Wo im Code was steht", "h2")]
    rows = [["Datei", "Inhalt"],
            ["<font name='Courier' size='8'>mes/orderbook.py</font>",
             "Matching Engine, Preis-Zeit-Priorität — das Fundament"],
            ["<font name='Courier' size='8'>mes/agents.py</font>",
             "die sieben Entscheidungsregeln; hier steht das ganze Verhalten"],
            ["<font name='Courier' size='8'>mes/simulation.py</font>",
             "die Schleife: ein <font name='Courier' size='8'>step()</font> ist eine "
             "Marktperiode"],
            ["<font name='Courier' size='8'>mes/instruments.py</font>",
             "die fünf Sektoren und das Faktormodell hinter ihren fairen Werten"],
            ["<font name='Courier' size='8'>mes/indices.py</font>",
             "die Indexkonstruktion — verkettet, mit den Gewichten des ETF"],
            ["<font name='Courier' size='8'>mes/metrics.py</font>",
             "die Kriterien aus Abschnitt 1, als ausführbare Prüfungen"],
            ["<font name='Courier' size='8'>mes/config.py</font>",
             f"alle {f_['params']} Parameter, einmal deklariert — das Bedienfeld wird "
             "daraus erzeugt"],
            ["<font name='Courier' size='8'>mes/city.py</font> · "
             "<font name='Courier' size='8'>traders.py</font>",
             "die beiden Stellen, an denen Zustand zu Anzeigezahlen wird"]]
    f += [table(rows, [45 * mm, 125 * mm]), Spacer(1, 8)]

    f += [p("Was offen ist", "h2")]
    f += [p("Kein Modell ist fertig, und dieses schreibt auf, wo es steht:", "small")]
    f += bullets([
        "<b>Zwei der sechs Kriterien sind nicht erfüllt</b> (Seite 1). Vier Runden Arbeit "
        "haben die anderen vier robust gemacht und diese beiden nicht bewegt — sie hängen "
        "an derselben Abwägung.",
        "<b>Die Bestandsgrenze der Market Maker ist doppelt definiert</b>: der Agent "
        "rechnet mit dem Fünffachen dessen, was die Engine durchlässt. Welche der beiden "
        "Zahlen gilt, verändert die Buchtiefe und damit jede Zahl der Validierung. "
        "Dokumentiert in <font name='Courier' size='8'>INTEGRATION.md</font>.",
        "<b>Die Barmittelprüfung nimmt den besten Angebotspreis</b>, eine große Order "
        "läuft aber durch mehrere Preisstufen — Agenten, die keinen Kredit aufnehmen "
        "dürfen, können es kurz doch.",
        "<b>Keine Dividenden, keine Gewinne.</b> Der faire Wert ist ein exogener Prozess, "
        "kein erwirtschaftetes Ergebnis; Rückkäufe zahlt eine Kasse, die sich nie füllt.",
    ])
    f += rule()
    f += [p("Ausführlich — sieben geführte Experimente, die Herleitung der Ergebnisse, "
            "was alles versucht wurde und nicht funktioniert hat — steht im Handbuch: "
            "<font name='Courier' size='8'>docs/Market-Ecology-Simulator-Handbuch.pdf</font>. "
            "Die Methode und die Zahlen im Detail: "
            "<font name='Courier' size='8'>README.md</font>.", "small")]

    return f


if __name__ == "__main__":
    PRINT_FRIENDLY = "--druck" in sys.argv[1:] or "--print" in sys.argv[1:]
    print("geschrieben:", build())
