# GATES Workshop: OneLab Laboratory Assistant

A hands-on workshop and primer on building a real, tool-using AI agent — from
individual tools, to a **Model Context Protocol (MCP) server**, to an agent served
over the **Agent2Agent (A2A) protocol** — all for one assistant over DOST-ITDI's
OneLab laboratory network. Run by the GATES Data Lakehouse Component.

## What's in this repository

- `Exercise-1.ipynb` — build the txt2sql, RAG, waypoints, nearest-labs, and hotspot-analysis workflows, plus the security guardrails that protect them.
- `Exercise-2.ipynb` — wrap those workflows as MCP tools with FastMCP and run the server over stdio.
- `Exercise-3/` — refactor the chatbot into a single-turn `answer_query()` method, then wrap it as an Agent2Agent server (`onelab_agent.py`). Includes a proposed solution.
- `onelab_server/` — the finished MCP server exposing OneLab's lab-network tools (SQL, RAG, geocoding).
- `onelab_chatbot/` — the finished MCP client/chatbot that calls `onelab_server`.
- `workflows.py`, `utils.py`, `instructions_and_templates.py` — shared helpers the root-level exercise notebooks import directly.
- `OneLab.db`, `population.db`, `unique_values/`, `files/` — the data the exercises run against.
- `analytics/` — example analysis outputs (tables, charts, and maps) referenced in Exercise 1.
- `TESTQUERIES.md` — sample queries to test each workflow (text-to-SQL, RAG, waypoints, threat filter).
- `requirements.txt` — Python package list for all notebooks and servers.

## Setup

See the [Setup Guide](setup_guide.html) for full instructions (VS Code, Miniconda, Node.js, Windows/macOS). Short version:

```bash
git clone https://github.com/gates-dost-asti/OneLab-Workshop.git
cd OneLab-Workshop
conda create -n gates_workshop_env python=3.12 -y
conda activate gates_workshop_env
pip install -r requirements.txt
```

Then open the repo in VS Code, select the `gates_workshop_env` kernel, and start with `Exercise-1.ipynb`.

## Building the site

This repo includes a Quarto website (`index.qmd`). To preview it locally:

```bash
quarto render
open _site/index.html
```
