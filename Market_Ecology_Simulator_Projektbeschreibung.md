# Market Ecology Simulator (MES)

> **Das hier ist der ursprüngliche Entwurf, nicht die Beschreibung des Gebauten.**
> Er steht im Repository, weil er festhält, womit das Projekt angefangen hat — und
> weil der Abstand zum Ergebnis selbst eine Erkenntnis ist. Was tatsächlich gebaut
> wurde, steht im [`README.md`](README.md). Die Unterschiede sind absichtlich:
> keine Datenbank (ein Lauf ist aus seinem Seed reproduzierbar, also braucht er
> keine), kein React (die Ansicht ist eine HTML-Datei ohne Build-Schritt), kein
> Reinforcement Learning (die Agenten wechseln nach Brock & Hommes zwischen zwei
> Regeln — ein Lernverfahren hätte verdeckt, woher das Verhalten kommt).

## Projektübersicht

Der **Market Ecology Simulator (MES)** ist eine agentenbasierte
Finanzmarktsimulation, deren Ziel **nicht die Vorhersage von
Aktienkursen**, sondern das Verständnis der Mechanismen hinter
Finanzmärkten ist.

Die Simulation bildet eine vereinfachte, aber möglichst realistische
Wirtschaft nach. Tausende unabhängige Akteure (Agenten) treffen auf
Basis ihrer Informationen, Ziele und Strategien eigenständig
Entscheidungen. Aus diesen individuellen Entscheidungen entstehen
komplexe Marktbewegungen wie Blasen, Crashs, Momentum,
Liquiditätsengpässe oder Panikverkäufe.

## Ziel

-   Entstehung von Marktmechanismen untersuchen
-   Emergent Behavior sichtbar machen
-   Forschungs- und Showcase-Projekt für KI, Simulation und
    Softwarearchitektur

## Kernmodule

-   Agenten
-   Unternehmen
-   Börse
-   Makroökonomie
-   Nachrichtensystem
-   Lernsystem
-   Analytics & Dashboard

## Technologien

**Backend** - Python - FastAPI - PostgreSQL - Redis

**Frontend** - React - TypeScript - Plotly

**KI** - Ollama - OpenAI API (optional) - Reinforcement Learning

## Langfristige Vision

Der Market Ecology Simulator soll kein Spiel werden, sondern ein
Forschungs- und Analysewerkzeug zur Untersuchung komplexer Finanzmärkte.
