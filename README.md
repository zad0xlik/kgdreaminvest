# KGDreamInvest (Paper) — Multi-Agent Allocator + Investing Knowledge Graph + GUI

A continuously “thinking” paper-trading sandbox:
- pulls daily market data (Yahoo Finance chart endpoint)
- maintains a small investing knowledge graph in SQLite
- runs background loops to **observe → dream (KG) → think (plans)**
- shows everything in a “pretty” web dashboard (vis-network)

> **Educational / experimental. Not financial advice. Paper trading only.**
> This project does **not** place real trades and does **not** connect to any broker.

---

## Screenshot

![KGDreamInvest UI](kgdreaminvest.png)

Prerequisites
1) Python
Python 3.10+ recommended

2) Ollama + a local model (required for “thinking/dreaming”)
This app calls a local LLM via Ollama over HTTP (OLLAMA_HOST/api/chat).
You must have:
Ollama installed and running
At least one model pulled (example: gpt-oss:20b)
Environment variables set:
OLLAMA_HOST (default: http://localhost:11434)
DREAM_MODEL (example: gpt-oss:20b)
Works best on a Mac with Apple Silicon (Metal) or any GPU-capable machine.
CPU-only machines can run, but “dream/think” cycles will be slower. If needed, reduce loop speeds.
Note: If the LLM call fails, the app falls back to a rule-based allocator.
But the “multi-agent committee” output and KG labeling are best with Ollama available.

Install
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

mkdir -p data

DATA_DIR=./data \
KGINVEST_DB=./data/kginvest_live.db \
OLLAMA_HOST=http://localhost:11434 \
DREAM_MODEL=gpt-oss:20b \
PORT=5062 \
AUTO_TRADE=0 \
python3 kgdreaminvest.py
Open:

http://127.0.0.1:5062
