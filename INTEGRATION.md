# Integrationsnotiz Simulationskern → Ansicht

Stand: Kalibrierung des Kerns. Diese Datei beschreibt, was sich in `mes/` geändert
hat und was die Ansicht davon braucht. Sie ersetzt keine Absprache, sie hält nur
den Vertrag fest.

## Zwei neue Ansichten und zwei neue Lesepunkte

`Simulation.indices` (aus [`mes/indices.py`](mes/indices.py)) wird bei jedem Reset
neu gebaut und in jedem Schritt fortgeschrieben. Sie zieht **keine Zufallszahlen**
und ändert keinen Zustand — derselbe Seed ergibt mit und ohne sie bitgenau denselben
Lauf, und `tests/test_indices.py` prüft das über den RNG-Zustand.

`mes/traders.py` ist zu `/traders` das, was `mes/city.py` zur Stadt ist: der einzige
Punkt, an dem Simulationszustand zu Anzeigezahlen wird. Sortierung, Filter und
Blättern liegen dort, nicht im Browser.

Für die Ansicht wichtig:

- **`Agent.start_equity`** ist neu: das Eigenkapital beim Spawn.
  `Agent.last_wealth` ist die Basislinie des Strategie-Reviews und wandert bei jedem
  Review, taugt also nicht als Vergleich für „wie hat dieser Trader abgeschnitten".
- **`Market.step_orders`** zählt Orders je Buch. `Simulation.step_orders` zählt sie
  über alle Märkte; die Stadtzeile mischte beide.
- **`Simulation.script_source`** hält die Szenario-Zeitleiste unverbraucht, damit
  eine Aufzeichnung sie mitschreiben und ein Replay sie zurücklegen kann.
- **`Simulation.cfg_start`** ist die Konfiguration, mit der der Lauf *begonnen* hat.
  `Config.update_live` verändert das Objekt in place, das Aufzeichnungsformat braucht
  aber den Anfangszustand.

## Zwei neue Agentengruppen

`Simulation.group_of()` gibt jetzt sieben Gruppen zurück statt fünf:

| Gruppe | Klasse | Rolle | Warum sie existiert |
|---|---|---|---|
| `momentum` | `AdaptiveTrader` | Trendfolge | wie bisher |
| `value` | `AdaptiveTrader` | Bewertung | wie bisher |
| `noise` | `NoiseTrader` | Rauschen | wie bisher |
| `passive` | `PassiveInvestor` | ETF / Sparplan | wie bisher |
| `leveraged` | `LeveragedFund` | Hebel, Margin Calls | wie bisher |
| **`maker`** | `MarketMaker` | **neu** — beidseitige Quotes | ohne ihn hatte das Buch ~600 Stück Tiefe gegen Orders von mehreren Tausend; jede Order räumte das Buch ab, die Volatilität lag bei 129 % p. a. |
| **`company`** | `Company` | **neu** — Emittent | ohne ihn gab es kein Aktienangebot: Value-Investoren verkauften ihre Bestände leer, Market Maker liefen ins Bestandslimit, danach stieg der Kurs ungebremst auf das Doppelte des Fundamentalwerts |

Beide handeln in **jedem** Schritt (`Simulation.always_active`), nicht nach
`activation_rate` — sonst verschwindet ihre Wirkung zwischen den Zügen.

Besonderheiten für die Darstellung:

- **Market Maker** dürfen negative Bestände haben (bis `mm_inventory_limit`).
  Ein negativer Bestand ist eine Short-Position.
- **Der Emittent** hat systematisch negative Bestände. Das ist kein Fehler:
  `-shares` **ist** der ausgegebene Streubesitz. Sein Kapital liegt in der Kasse.
- `Simulation.strategy_performance()` leitet die Gruppen jetzt aus der Population
  ab statt aus einer festen Liste — neue Typen fallen nicht mehr stillschweigend
  aus dem Vergleich.

**Erledigt:** `city.py` kennt die beiden Viertel `mkr` und `cmp` inzwischen, in
`_ROADS`, `capital` und `rooms`. Die Summenprüfung im Test schneidet pro Agent bei
0 ab, wie `_equity_by_group` es tut — gehebelte Fonds können negatives
Eigenkapital haben.

## Preis, Kurse und Bars

- `sim.price` ist der **Mid des Orderbuchs**, nicht der letzte Handelspreis.
  Auf den letzten Trade zu markieren erzeugte eine Autokorrelation von −0,29 in
  den Renditen, die reine Mikrostruktur war.
- `sim.last_trade` ist der letzte tatsächliche Ausführungspreis — der richtige
  Wert für Tape und Orderbuchanzeige.
- **Neu: `sim.bars`** — Tages-OHLC (`t, step, o, h, l, c, v`). Ein Tag sind
  `cfg.steps_per_day` Schritte (Standard 240). Der Schluss ist über die letzten
  5 % des Tages gemittelt, wie eine Schlussauktion.
- **Neu: `sim.daily_returns`** — die Reihe, auf der die Validierung rechnet.
  Die Stylized Facts sind Eigenschaften von *Tages*renditen; auf Schrittebene
  kommt jede Kennzahl falsch heraus.
- **Neu: `sim.fitness`** — `{"momentum": float, "value": float}`, wie gut jede
  Regel zuletzt gewesen wäre. Treibt den Strategiewechsel und ist als
  Anzeige interessant: man sieht, welches Lager gerade Recht hat.

## Kalibrierte Standardwerte

Die Defaults in `config.py` sind jetzt kalibriert und **nicht** frei wählbar,
ohne die Validierung neu zu prüfen. Insbesondere:

```
steps_per_day        240        ein Tag muss einen vollen Anpassungszyklus fassen
fundamental_drift    7 %/Jahr   geteilt durch 252*steps_per_day
fundamental_vol      15 %/Jahr  geteilt durch sqrt(252*steps_per_day)
chartist_aggression  100        darunter verschwindet das Volatilitätscluster
mm_skew              0.9        Bestandsneigung über Ordergrößen, nicht über Preise
passive_inflow       30         ca. 5 % der Marktkapitalisierung pro Jahr
```

Bei `steps_per_day=240` entsteht ein Tagesbar alle 240 Schritte. Die Ansicht
sollte für das Validierungspanel darauf vorbereitet sein, dass zu Beginn
weniger als 50 Tage vorliegen — `metrics.analyse` gibt dann
`{"insufficient": True}` zurück.

## Stand der Validierung

Die Rendite-Autokorrelation, die hier als offener Punkt stand (−0,4), ist mit den
fünf Sektoren behoben. Offen ist jetzt der Tail-Index. Beides samt Herleitung im
`README.md`.

Die Standardwerte oben sind teilweise überholt: `chartist_aggression` steht auf 55,
`fundamental_vol` auf 60 %/Jahr. Verbindlich ist immer `mes/config.py`; die Werte
dort sind die, gegen die `scripts/calibrate.py` gelaufen ist.


---

# Nachtrag: fünf Sektoren

Der Kern handelt jetzt **fünf Instrumente** gleichzeitig. Für die Ansicht ändert
sich nichts, was sie schon nutzt — alle Einzelmarkt-Zugriffe funktionieren weiter
und zeigen das erste Instrument (`TECH`).

## Was gleich geblieben ist

`sim.price`, `sim.prices`, `sim.book`, `sim.bars`, `sim.daily_returns`,
`sim.volumes`, `sim.returns`, `sim.recent_trades`, `sim.step_volume`,
`sim.step_trades`, `sim.step_fills`, `sim.trend`, `sim.realized_vol` — alle
vorhanden, alle auf `sim.primary` bezogen. `agent.equity(sim.price)` funktioniert
weiter: der Float wird bewusst ignoriert und die Portfoliobewertung der letzten
Bewertungsmarken verwendet, weil eine einzelne Zahl die Frage bei einem Portfolio
nicht beantworten kann.

## Was neu ist

| Zugriff | Inhalt |
|---|---|
| `sim.markets` | `dict[symbol, Market]` — Buch, Kursreihe, Bars je Instrument |
| `sim.symbols` | `['TECH','ENRG','FINL','HLTH','CONS']` |
| `sim.primary` | Symbol des Instruments, auf das die Einzelmarkt-Zugriffe zeigen |
| `sim.fair` | Fundamentalwert des primären Instruments (**ersetzt `sim.world.fundamental`**) |
| `sim.sector_returns()` | Tagesrenditen je Instrument, Eingabe für die Heatmap |
| `agent.positions` | `dict[symbol, int]` — `agent.shares` ist jetzt die read-only Summe |
| `agent.symbol` | gesetzt bei Market Makern und Emittenten, sonst `None` |
| `GET /api/sectors` | alle Instrumente plus gemessene Korrelationsmatrix |
| `GET /api/sectors/{symbol}` | ein Instrument: Historie, Buch, Tape, eigene Validierung |

**Achtung, eine Umbenennung:** `sim.world.fundamental` existiert nicht mehr. Die
Fundamentalwerte gehören den Instrumenten; zwei Quellen der Wahrheit waren ein
echter Fehler (eine Nachricht bewegte die eine und nicht die andere). `city.py` ist
bereits angepasst.

## Aufwärmen läuft jetzt im Hintergrund

Der Server antwortet nach wenigen Sekunden und spult den Markt danach im
Hintergrund auf 110 Handelstage vor. Der Snapshot hat zwei neue Felder:
`warming` (bool) und `warmProgress` (0…1). Ein Fortschrittsbalken wäre dort
sinnvoll.

## Was für die Ansicht offen ist

Die Stadt zeichnet weiterhin nur das primäre Instrument. Sinnvoll wären fünf
Sektor-Kacheln mit Sparkline, eine Korrelations-Heatmap und ein Umschalter, welcher
Sektor die Detailansicht füllt. Die Daten dafür liegen alle in `/api/sectors`.


---

# Nachtrag: Zentralbank

Neu: `mes/centralbank.py`. Sie handelt nicht, sie setzt **eine Zahl** — den
Leitzins — und dieser erreicht den Markt über drei Kanäle.

## Zugriff

| Zugriff | Inhalt |
|---|---|
| `sim.bank` | die `CentralBank` |
| `sim.bank.rate` | Leitzins, annualisiert (0,02 = 2 %). **Abgeleitet**, nicht gespeichert — im Handmodus liest er direkt die Konfiguration |
| `sim.bank.inflation`, `.output_gap`, `.real_rate`, `.stance` | Makrozustand |
| `sim.bank.to_dict()` | anzeigefertig, alles in **Prozent**, mit `history` für das Chart |
| `GET /api/centralbank` | Zins, Makro, plus Duration je Sektor und die drei Kanäle |
| `POST /api/centralbank` | `{"rate": 0.045}` setzt von Hand, `{"manual": false}` gibt an die Regel zurück |

`to_dict()` gibt Prozentwerte (4.5 für 4,5 %), die internen Felder sind Dezimalzahlen
(0.045). Für ein Zins-Chart eignet sich `history`: Liste aus
`{step, rate, inflation, output_gap}`, alle fünf Handelstage ein Punkt.

## Die drei Kanäle

1. **Bewertung** — eine Zinsbewegung bewertet die Fundamentalwerte neu, mit der
   Duration des Sektors. FINL hat Duration 8,8, ENRG 1,6 — dieselbe Entscheidung
   trifft die Sektoren also unterschiedlich hart. Getrieben von der *Änderung* des
   Zinses, nicht vom Niveau: eine Senkung gibt zurück, was eine Erhöhung nahm.
2. **Finanzierungskosten** — gehebelte Fonds zahlen `Zins + borrow_spread` auf
   geliehenes Geld. Ihr Eigenkapital erodiert, Margin Calls kommen früher.
   Einseitig: Sparer bekommen keine Zinsen, weil das Geld in den Markt injizieren
   und die Kalibrierung für einen Effekt zweiter Ordnung verschieben würde.
3. **Zuflüsse** — `bank.flow_multiplier()` skaliert die Sparplan-Zuflüsse. Bei 10 %
   Zins fließt etwa halb so viel in Aktien.

## Was sich für die Ansicht anbietet

Ein Panel mit dem Leitzins groß, darunter Inflation und Output-Gap als Linien, und
ein Umschalter „Regel / von Hand" mit einem Zins-Slider. Der interessante Moment ist
sichtbar: die Bank strafft weiter, während die Inflation schon fällt, weil die
Wirkung verzögert eintritt. Im Szenario **Zinswende 2022** läuft das durch —
Zinsgipfel 8,6 %, danach Rezession und Unterschießen bis unter null Inflation.
Der Zinspfad ist **nicht** geskriptet, nur der Inflationsschock.

## Zwei Fallen, die hier steckten

- **Eigener Zufallsstrom.** Die Bank zieht aus ihrem eigenen Generator
  (`cfg.seed + 7919`). Ein optionales Modul, das aus dem gemeinsamen Strom zieht,
  verschiebt jede spätere Zahl — dann ist „Bank aus" nicht dieselbe Welt ohne Bank,
  sondern eine andere Welt. Dieser Fehler hat hier zweimal zu falschen Schlüssen
  geführt, bevor er behoben war.
- **`macro_shock` ist mächtiger als es aussieht.** Bei 0,02 wanderte der Zins so
  stark, dass die Neubewertung mit Duration alles andere im Modell dominierte und
  die Validierung von fünf auf drei Kriterien fiel. Standard ist jetzt 0,006;
  Szenarien drehen ihn hoch, wenn es um den Zins geht.


---

# Nachtrag: Einzelaktien

`stocks_per_sector` (Standard **0**) schaltet zwischen zwei Welten. Bei 0 handeln die
fünf Sektoren selbst — das ist die kalibrierte Konfiguration und bleibt Standard.
Über 0 handeln Einzelaktien (`TECH-1`, `TECH-2`, …) und der Sektor ist kein
Instrument mehr, sondern ein gemeinsamer Schock mit Index.

## Zugriff

| Zugriff | Inhalt |
|---|---|
| `sim.sectors` | `dict[sector, [symbols]]` — bei Sektor-Instrumenten `{"TECH": ["TECH"], …}` |
| `sim.sector_of` | `dict[symbol, sector]` |
| `sim.sector_index(sector)` | gleichgewichteter Kursindex der Mitglieder |
| `sim.sector_fair(sector)` | dasselbe für die Fundamentalwerte |
| `sim.inject_news(text, mag, symbol=…)` | `symbol` darf ein Instrument (`TECH-1`), ein **Sektor** (`TECH`, trifft alle Mitglieder) oder `None` sein (marktweit, mit Beta skaliert) |

## `/api/sectors` ist jetzt gruppiert

Die flache Liste ist weg. Neue Form:

```json
{
  "groups": [
    {"sector": "TECH", "tradable": false, "index": 101.82, "fair": 227.75,
     "members": [{"symbol": "TECH-1", "price": 102.44, "beta": 1.46,
                  "duration": 7.5, "stretch": 7.9, "spark": [...], ...}]}
  ],
  "stocks_per_sector": 2,
  "correlation":   {"symbols": [...], "matrix": [[...]], "average": 0.036},
  "within_across": {"within": 0.098, "across": 0.028, ...}
}
```

`tradable` sagt, ob der Sektor selbst ein Instrument ist — die Ansicht muss also
nicht raten. Bei `tradable=false` hat die Gruppe einen Index, aber keinen eigenen
Kurs; die Einzelnamen darunter haben beides.

`within_across` ist die interessante Zahl bei Einzelaktien: Korrelation innerhalb
eines Sektors gegen sektorübergreifend. Nichts davon ist konfiguriert.

## Was für die Ansicht offen ist

Bei Einzelaktien wären zwei Ebenen sinnvoll: Sektor-Kacheln mit Index und
darunter aufklappbar die Einzelnamen. `groups` ist genau dafür geformt.

Laufzeit: der Orderfluss skaliert pro Instrument, zehn Instrumente laufen mit
~225 Schritten/s gegen ~440 bei fünf. Ein Umschalter in der UI sollte also einen
Neustart auslösen (`stocks_per_sector` ist bewusst **nicht** live).


---

# Nachtrag: was die letzte Runde geändert hat

Vier Korrekturen, die für die Ansicht relevant sind.

## Kapital skaliert mit der Zahl der Märkte

`initial_cash` und `initial_shares` gelten jetzt **pro Instrument**, nicht verteilt
über alle. Ein Agent mit fünf Märkten startet also mit fünffachem Kapital. Grund: mit
einem Fünftel des Kapitals pro Markt konnten die Kurse den Fundamentalwerten nicht
folgen, und die Korrelation aus dem Faktormodell erreichte die Kurse nicht (0,07
statt realistischer 0,4–0,6). Jetzt **0,42**.

Für die Ansicht heißt das nur: die absoluten Kapitalzahlen in den Vierteln sind
fünfmal größer als vorher. Der Maßstab passt sich automatisch an (`chooseScale`).

## Market Maker skalieren mit

Sie sind an ein Instrument gebunden, ihr Kapital wuchs also nicht mit — das Buch war
um genau den Instrumentenfaktor zu dünn und die Volatilität verdoppelte sich. Neu ist
`Agent.scale`: bei marktgebundenen Agenten die Zahl der Märkte, sonst 1. Sie
multipliziert `mm_quote_size` und die Normierung des Bestands-Skews.

**Achtung, die beiden Seiten der Bestandsgrenze sind nicht dieselbe Zahl.**
`MarketMaker.act` normiert seinen Skew gegen `mm_inventory_limit * agent.scale`
([`mes/agents.py`](mes/agents.py)), die harte Verkaufsgrenze in
`Simulation._submit` ist aber `-mm_inventory_limit` **ohne** `scale`. Im Standard mit
fünf Instrumenten heißt das: der Maker quotiert die fünffache Größe, hält seine Grenze
für 30 000 Stück und wird bei 6 000 abgeschnitten — sein Skew erreicht an der Kappung
kaum 0,2 und kann seine Aufgabe nie erfüllen. Im Ein-Instrument-Fall ist `scale = 1`
und die beiden Definitionen fallen zusammen, weshalb der ursprünglich kalibrierte
Markt das nie gezeigt hat.

Das ist **eine offene Frage, keine Erledigung.** Welche der beiden Definitionen gilt,
verändert die Buchtiefe und damit jede Zahl in der Validierungstabelle des README, und
`tests/test_simulation.py::test_market_makers_respect_their_inventory_limit` prüft
derzeit die unskalierte Form — sie schlägt fehl, sobald die andere gewählt wird. Diese
Zeile beschreibt daher, was der Code tut, nicht was er tun sollte.

## Margin Calls sind im Standard aktiv

`maintenance_margin` steht jetzt auf **0,38** statt 0,25. Die Fonds erreichen ~1,6×
Hebel, ihr Verhältnis Eigenkapital zu Engagement liegt also bei ~0,62 — eine Schwelle
von 0,25 wurde nie berührt, die Kaskade war toter Code. Bei 0,38 kommen Calls
gelegentlich (654 über 90.000 Schritte), bei 0,44 in jedem zweiten Schritt.

Der Alarm auf dem Hebel-Turm (`alarm`, `mcFg`) feuert damit im Normalbetrieb.

## Ein Zufallsstrom pro Agent

`agent.rng`, gesetzt aus `[seed, aid]`. Für die Ansicht unsichtbar, aber es macht den
A/B-Vergleich belastbar: ein Parameter ohne Wirkung erzeugt jetzt bitidentische Läufe.
Der Warnhinweis im Vergleichs-Panel ist entsprechend umformuliert — er warnt nicht
mehr vor Pfaddivergenz, sondern nur noch davor, aus einem Seed-Paar zu viel zu lesen.

## Fehlerbehandlung im Frontend

`pull()` in `index.html` unterschied nicht zwischen „Abruf fehlgeschlagen" und
„Zeichnen fehlgeschlagen" und meldete beides als „kein Backend". Das kostete mich
eine Fehlersuche an der falschen Stelle. Jetzt getrennt: ein Zeichenfehler meldet
„Verbunden · Zeichnen fehlgeschlagen: …" und landet zusätzlich in der Konsole.
