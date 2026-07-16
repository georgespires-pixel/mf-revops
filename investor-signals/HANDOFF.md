# Handoff — Investor Signals MVP

A small internal tool that turns (synthetic, for now) investor calls & emails into
a queryable sales dashboard + a deck-fit report. **Runs fully offline** — no
HubSpot and no API keys needed to demo it.

This note is for whoever runs it. Full details are in `README.md`.

## 0. Prerequisite: Python 3.9+

The error "command not found: python" just means Python isn't installed (or isn't
on PATH). Install it:

- **macOS:** `brew install python@3.12` (or download from https://python.org/downloads).
  Note: macOS also ships a system `python3` (3.9) — that works too (the project
  supports 3.9), but a newer Python is recommended.
- **Windows:** install from https://python.org/downloads and tick
  "Add python.exe to PATH" during setup
- **Linux:** `sudo apt install python3 python3-venv python3-pip`

Verify (on macOS the command is almost always `python3`, not `python`):

```bash
python3 --version
```

Use whichever name works (`python3` or `python`) in the commands below.
Python **3.10+ recommended**; **3.9 is supported** (an extra dependency,
`eval_type_backport`, installs automatically from `requirements.txt` on 3.9).

## 1. Install

```bash
cd investor-signals
python3 -m venv .venv

# activate the virtual environment:
source .venv/bin/activate        # macOS / Linux
# .venv\Scripts\activate         # Windows PowerShell

pip install -r requirements.txt
cp config.example.yaml config.yaml     # copy config.example.yaml config.yaml   (Windows)
```

## 2. Run the MVP (offline, synthetic data)

```bash
python -m investor_signals seed        # generate synthetic calls + emails
python -m investor_signals serve       # then open http://127.0.0.1:8000
```

- **Sales dashboard** — filter contacts by fund / industry / sentiment / rep.
- **Deck fit** — upload a PDF or PPTX, get a Low/Medium/High fit with named
  investor evidence (offline heuristic in MVP mode).

`Ctrl+C` stops the server. Re-run `seed` any time to regenerate data
(`python -m investor_signals seed --contacts 40` for a bigger set).

## 3. Sanity-check tests

```bash
python tests/test_core.py     # should print: ALL TESTS PASSED
```

## What's real vs. stubbed for the MVP

- **Real:** the full pipeline shape — fund-name normalization, per-contact signal
  aggregation, SQLite store, incremental-sync logic, FastAPI app + frontend.
- **Synthetic (MVP):** the calls/emails come from `synthetic.py`, not HubSpot.
- **Ready but off:** connecting live HubSpot (`sync` command, needs a read-only
  token) and model-based extraction / deck-fit (needs an Anthropic API key). Both
  activate automatically once those credentials are set — see `README.md`.

The tool is **read-only against HubSpot by design** — it never writes to the CRM.
