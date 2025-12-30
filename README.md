# KGDreamInvest (Paper) — Multi-Agent Allocator + Investing Knowledge Graph + GUI

> **Forked from**: [DormantOne/kgdreaminvest](https://github.com/DormantOne/kgdreaminvest)  
> This repository contains refactored and enhanced version with modular architecture.

A continuously “thinking” paper-trading sandbox:
- pulls daily market data (Yahoo Finance chart endpoint)
- maintains a small investing knowledge graph in SQLite
- runs background loops to **observe → dream (KG) → think (plans)**
- shows everything in a “pretty” web dashboard (vis-network)

> **Educational / experimental. Not financial advice. Paper trading only.**
> This project does **not** place real trades and does **not** connect to any broker.

---

## System Architecture

```mermaid
graph TB
    subgraph "Web Interface"
        UI[Web Dashboard<br/>Flask + vis-network]
        UI --> API[REST API Endpoints]
        API --> UI
    end

    subgraph "Background Workers"
        MarketWorker[Market Worker<br/>Data Collection]
        DreamWorker[Dream Worker<br/>KG Maintenance]
        ThinkWorker[Think Worker<br/>Multi-Agent Decisions]
        
        MarketWorker -->|Price Data| DB[(SQLite Database)]
        DreamWorker -->|KG Updates| DB
        ThinkWorker -->|Insights/Trades| DB
    end

    subgraph "Data Processing"
        YahooAPI[Yahoo Finance API]
        Indicators[Technical Indicators]
        Signals[Market Signals]
        Correlation[Correlation Analysis]
        LLM[LLM Committee<br/>Ollama API]
    end

    subgraph "Knowledge Graph"
        Nodes[Nodes<br/>Investibles/Bellwethers]
        Edges[Edges<br/>Relationships]
        Channels[Edge Channels<br/>correlates, drives, etc.]
    end

    subgraph "Portfolio Management"
        Portfolio[Paper Portfolio]
        Trades[Trade Execution]
        Guardrails[Guard Rails<br/>Risk Management]
    end

    MarketWorker --> YahooAPI
    YahooAPI --> Indicators
    Indicators --> Signals
    Signals --> DB
    
    DreamWorker --> Correlation
    Correlation --> LLM
    LLM --> Edges
    Edges --> Nodes
    
    ThinkWorker --> LLM
    LLM --> Trades
    Trades --> Portfolio
    Portfolio --> Guardrails
    
    DB --> UI
    Nodes --> UI
    Edges --> UI
    Portfolio --> UI
```

## Process Flow

```mermaid
sequenceDiagram
    participant M as Market Worker
    participant D as Dream Worker
    participant T as Think Worker
    participant DB as SQLite Database
    participant LLM as Ollama LLM
    participant UI as Web Interface

    loop Continuous Operation
        M->>YahooAPI: Fetch Prices (every 3 min)
        YahooAPI->>M: Price Data
        M->>DB: Store Snapshot
        M->>DB: Update Positions
        
        D->>DB: Read Latest Snapshot
        D->>Correlation: Analyze Random Pair
        D->>LLM: Label Relationships (30% chance)
        LLM->>D: JSON Channels
        D->>DB: Update Edge Weights
        
        T->>DB: Read Snapshot + Portfolio
        T->>LLM: Multi-Agent Committee
        LLM->>T: Decisions + Explanation
        T->>DB: Store Insight
        alt Auto Trade Enabled
            T->>DB: Execute Paper Trades
            DB->>T: Trade Results
        end
        
        UI->>DB: Fetch State
        DB->>UI: Nodes, Edges, Portfolio
    end
```

## Three-Worker Architecture

```mermaid
flowchart LR
    subgraph Market_Cycle["Market Worker Cycle (Every 3 min)"]
        A1[Fetch Yahoo Prices] --> A2[Compute Indicators]
        A2 --> A3[Generate Signals]
        A3 --> A4[Store Snapshot]
        A4 --> A5[Mark-to-Market]
    end

    subgraph Dream_Cycle["Dream Worker Cycle (Every 4 min)"]
        B1[Select Random Pair] --> B2[Calculate Correlation]
        B2 --> B3{LLM Labeling?}
        B3 -->|Yes| B4[Call Ollama API]
        B3 -->|No| B5[Heuristic Channels]
        B4 --> B6[Update Edge Channels]
        B5 --> B6
        B6 --> B7[Update Node Scores]
    end

    subgraph Think_Cycle["Think Worker Cycle (Every 5 min)"]
        C1[Read Latest Snapshot] --> C2[Build Market Context]
        C2 --> C3[Multi-Agent LLM Call]
        C3 --> C4[Parse Decisions]
        C4 --> C5[Critic Scoring]
        C5 --> C6{Starred?}
        C6 -->|Yes| C7[Execute Trades]
        C6 -->|No| C8[Store Insight]
        C7 --> C8
    end

    A4 -.-> B1
    A4 -.-> C1
```

## Screenshot

![KGDreamInvest UI](kgdreaminvest.png)

## Prerequisites

1) **Python**
   - Python 3.10+ recommended

2) **LLM Provider** (required for "thinking/dreaming")
   
   Choose one of the following:
   
   **Option A: OpenRouter** (Recommended - No setup required)
   - Cloud-based LLM inference
   - Get a free API key from [openrouter.ai](https://openrouter.ai/keys)
   - Use free models like `kwaipilot/kat-coder-pro:free`
   - No local installation needed
   - Works on any machine with internet connection
   
   **Option B: Ollama** (Local - Privacy-focused)
   - Local LLM inference via Ollama over HTTP
   - You must have:
     - Ollama installed and running ([ollama.com](https://ollama.com/download))
     - At least one model pulled (example: `gemma3:4b`, `llama3.2:latest`)
     - Environment variables set:
       - OLLAMA_HOST (default: http://localhost:11434)
       - DREAM_MODEL (example: gemma3:4b)
   - Works best on Mac with Apple Silicon (Metal) or GPU-capable machine
   - CPU-only machines can run but will be slower
   
   **Fallback**: If LLM calls fail, the app falls back to a rule-based allocator, but the "multi-agent committee" output and KG labeling work best with LLM available.

3) **Model Recommendations**
   - **OpenRouter (Cloud)**: `kwaipilot/kat-coder-pro:free` (recommended for getting started)
   - **Ollama (Local)**: `gemma3:4b`, `llama3.2:latest`, or `qwen2:latest`

## Install

```bash
# Install dependencies
pip install -r requirements.txt

# Or using uv (recommended)
uv sync
```

## Running the Application

### Quick Start

```bash
# Using uv (recommended)
uv run python main.py

# Or with standard Python
python main.py
```

### Command-Line Options

The `main.py` script supports the following command-line arguments:

```bash
uv run python main.py [OPTIONS]
```

**Options:**

- `--host HOST` - Host to bind the server to (default: 127.0.0.1)
- `--port PORT` - Port to run the server on (default: 5062)
- `--debug` - Enable debug mode for verbose logging

**Examples:**

```bash
# Run on default settings (localhost:5062)
uv run python main.py

# Run on custom port
uv run python main.py --port 8080

# Run accessible from other machines
uv run python main.py --host 0.0.0.0 --port 5062

# Run with debug logging
uv run python main.py --debug
```

## Configuration

All configuration is done via the `.env` file. Copy `.env.example` to `.env` and customize:

```bash
cp .env.example .env
```

### LLM Provider Configuration

KGDreamInvest supports both **Ollama** (local) and **OpenRouter** (cloud) for LLM inference.

#### Option 1: OpenRouter (Recommended)
For cloud-based LLM inference with free models:

**Edit `.env`:**
```env
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=your-api-key-here
DREAM_MODEL=kwaipilot/kat-coder-pro:free
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
```

Get your API key from: https://openrouter.ai/keys

**Run:**
```bash
uv run python main.py
```

#### Option 2: Ollama (Local)
For local LLM inference:

```bash
# Install Ollama: https://ollama.com/download
# Pull a model (example):
ollama pull gemma3:4b
```

**Edit `.env`:**
```env
LLM_PROVIDER=ollama
OLLAMA_HOST=http://localhost:11434
DREAM_MODEL=gemma3:4b
```

**Run:**
```bash
uv run python main.py
```

### Environment Variables Reference

| Variable | Description | Default |
|----------|-------------|---------|
| **LLM Configuration** | | |
| `LLM_PROVIDER` | LLM provider: "ollama" or "openrouter" | `ollama` |
| `OLLAMA_HOST` | Ollama server URL | `http://localhost:11434` |
| `OPENROUTER_API_KEY` | OpenRouter API key | - |
| `OPENROUTER_BASE_URL` | OpenRouter API base URL | `https://openrouter.ai/api/v1` |
| `DREAM_MODEL` | LLM model name | `gemma3:4b` |
| `LLM_CALLS_PER_MIN` | Max LLM calls per minute | `20` |
| `LLM_TIMEOUT` | LLM request timeout (seconds) | `45` |
| `LLM_TEMP` | LLM temperature | `0.25` |
| `LLM_MAX_REASK` | Max retry attempts for LLM | `1` |
| `LLM_MAX_TOKENS` | Max tokens per LLM response | `4000` |
| **Database & Storage** | | |
| `DATA_DIR` | Data directory path | `./data` |
| `KGINVEST_DB` | SQLite database path | `data/kginvest_live.db` |
| **Web UI** | | |
| `HOST` | Server host | `127.0.0.1` |
| `PORT` | Server port | `5062` |
| **Trading Configuration** | | |
| `START_CASH` | Initial paper trading cash | `500.0` |
| `MIN_TRADE_NOTIONAL` | Minimum trade size | `25.0` |
| `MAX_BUY_EQUITY_PCT_PER_CYCLE` | Max buy % per cycle | `18.0` |
| `MAX_SELL_HOLDING_PCT_PER_CYCLE` | Max sell % per cycle | `35.0` |
| `MAX_SYMBOL_WEIGHT_PCT` | Max position weight % | `14.0` |
| `MIN_CASH_BUFFER_PCT` | Min cash buffer % | `12.0` |
| `TRADE_ANYTIME` | Trade outside market hours | `0` (disabled) |
| **Market Configuration** | | |
| `MARKET_SPEED` | Market worker speed (ticks/min) | `0.35` |
| `DREAM_SPEED` | Dream worker speed (ticks/min) | `0.25` |
| `THINK_SPEED` | Think worker speed (ticks/min) | `0.20` |
| `BELLWETHERS` | Comma-separated bellwether tickers | `^VIX,SPY,QQQ,TLT,UUP,^TNX,CL=F,TSM,VTI` |
| `INVESTIBLES` | Comma-separated tradeable stock tickers | `XLE,XLF,XLV,XME,IYT,AAPL,MSFT,JPM,UNH,CAT,NVDA,AMD,AMZN,GOOGL,META,...` |
| **Portfolio Expansion** | | |
| `EXPANSION_ENABLED` | Enable LLM-powered portfolio expansion | `true` |
| `EXPANSION_MAX_STOCKS` | Maximum stocks after expansion | `27` |
| `EXPANSION_LLM_CALLS_PER_MIN` | LLM budget for expansion | `10` |
| **Yahoo Finance** | | |
| `YAHOO_TIMEOUT` | API timeout (seconds) | `12` |
| `YAHOO_RANGE_DAYS` | Historical data range | `90` |
| `YAHOO_CACHE_SECONDS` | Price cache duration | `90` |
| **Autonomy Toggles** | | |
| `AUTO_MARKET` | Auto-start market worker | `1` (enabled) |
| `AUTO_DREAM` | Auto-start dream worker | `1` (enabled) |
| `AUTO_THINK` | Auto-start think worker | `1` (enabled) |
| `AUTO_TRADE` | Auto-execute trades | `1` (enabled) |
| **Advanced** | | |
| `STAR_THRESHOLD` | Insight starring threshold | `0.55` |
| `EXPLANATION_MIN_LENGTH` | Min explanation length | `180` |
| `KGINVEST_DEBUG` | Enable debug logging | `true` |

### Bellwether Configuration

Bellwethers are market indicators used to generate regime signals. You can configure them in two ways:

**1. Via `.env` file:**
```env
BELLWETHERS=^VIX,SPY,QQQ,TLT,UUP,^TNX,CL=F,TSM,VTI
```

**2. Via Web UI:**
- Open the web interface
- Expand "📡 Bellwethers Config" section in the right panel
- Add, remove, or toggle bellwethers dynamically
- Changes persist in the database

### Investibles Configuration with LLM-Powered Expansion

**NEW FEATURE**: Investibles are the tradeable stock tickers in your portfolio. The system includes **LLM-powered automatic portfolio expansion** using a 1→3→9→27 pattern.

#### How It Works

When you add a stock with auto-expansion enabled, the LLM:
1. **Detects the sector** (using GICS classification)
2. **Finds 3 similar stocks** in the same industry (Level 1)
3. **For each similar stock**, finds 3 suppliers/customers/influencers (Level 2)
4. Continues until reaching `EXPANSION_MAX_STOCKS` (default: 27)

**Example Expansion Tree:**
```
AAPL (USER) → Technology
  ├─ MSFT (SIMILAR) → Technology
  │  ├─ CRM (DEPENDENT) → Software (customer)
  │  ├─ AVGO (DEPENDENT) → Hardware (supplier)
  │  └─ SAP (DEPENDENT) → Software (customer)
  ├─ GOOGL (SIMILAR) → Technology  
  │  ├─ TSM (DEPENDENT) → Semiconductors (supplier)
  │  └─ QCOM (DEPENDENT) → Hardware (supplier)
  └─ META (SIMILAR) → Communication Services
```

#### Configuration Options

**1. Via `.env` file (Initial Setup):**
```env
# Base investibles list
INVESTIBLES=XLE,XLF,XLV,XME,IYT,AAPL,MSFT,JPM,UNH,CAT,NVDA,AMD,AMZN,GOOGL,META

# Expansion settings
EXPANSION_ENABLED=true
EXPANSION_MAX_STOCKS=27
EXPANSION_LLM_CALLS_PER_MIN=10
```

**2. Via Web UI (Dynamic Management):**
- Open the web interface  
- Expand "🎯 Investibles Config" section in the right panel
- **Add stocks** with optional auto-expansion
- **View tree structure** with parent-child relationships
- **Toggle stocks** on/off without deleting
- **Color-coded levels**:
  - 🟢 Green = USER (manually added)
  - 🔵 Blue = SIMILAR (LLM-found peers)
  - 🟣 Purple = DEPENDENT (LLM-found suppliers/customers)
- **Monitor real-time expansion progress**
- Changes persist in the database

#### Expansion Timeline

- **Instant**: Stock added to database
- **~5-10 seconds**: Sector detection completes
- **~2-5 minutes**: Full expansion to 27 stocks (depends on LLM speed)

The expansion runs in a **background thread** and uses a **separate LLM budget** (`EXPANSION_LLM_CALLS_PER_MIN`) independent from the main worker budget.

#### Disabling Expansion

To add stocks **without** auto-expansion:
- Uncheck "Auto-expand portfolio" in the UI before adding
- Or set `EXPANSION_ENABLED=false` in `.env`

## Accessing the Web UI

Once running, open your browser to:

**http://127.0.0.1:5062**

(Or use the host/port you specified with `--host` and `--port`)
