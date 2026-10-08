# Market Ecology Simulator (MES)

> **This is the original draft, not a description of what was built.**
> It was originally written in German and is kept here in English translation.
> It stays in the repository because it records what the project started from, and
> because the distance to the result is itself a finding. What was actually built is
> described in the [`README.md`](README.md). The differences are intentional:
> no database (a run can be reproduced from its seed, so it does not need one), no
> React (the view is an HTML file without a build step), no reinforcement learning
> (the agents switch between two rules after Brock & Hommes; a learning method would
> have hidden where the behaviour comes from).

## Project overview

The **Market Ecology Simulator (MES)** is an agent-based financial market
simulation whose goal is **not to forecast share prices** but to understand the
mechanisms behind financial markets.

The simulation models a simplified but as realistic as possible economy. Thousands
of independent actors (agents) make their own decisions based on their
information, goals and strategies. From these individual decisions emerge complex
market movements such as bubbles, crashes, momentum, liquidity squeezes or panic
selling.

## Goal

-   Investigate how market mechanisms emerge
-   Make emergent behaviour visible
-   A research and showcase project for AI, simulation and software
    architecture

## Core modules

-   Agents
-   Companies
-   Exchange
-   Macroeconomics
-   News system
-   Learning system
-   Analytics & dashboard

## Technologies

**Backend** - Python - FastAPI - PostgreSQL - Redis

**Frontend** - React - TypeScript - Plotly

**AI** - Ollama - OpenAI API (optional) - Reinforcement learning

## Long-term vision

The Market Ecology Simulator is not meant to become a game but a research and
analysis tool for studying complex financial markets.
