# System Patterns & Architecture

## Core Architecture Pattern: Four-Worker System

### Worker Architecture
The system follows a **Producer-Consumer** pattern with four independent background workers:

```
Market Worker (Producer) → SQLite Database ← Dream Worker (Consumer/Producer)
                                ↓                        ↓
Options Worker (Consumer/Producer) ← Think Worker (Consumer) → Trading Decisions
```

### 1. Market Worker (Data Producer)
- **Frequency**: Every ~3 minutes via `MARKET_INTERVAL`
- **Responsibility**: Fetch live market data, compute indicators, generate signals
- **Pattern**: **ETL Pipeline**
  - **Extract**: Yahoo Finance API calls for all tickers
  - **Transform**: Technical indicators (RSI, momentum, volatility, z-scores)
  - **Load**: Store snapshots in database with mark-to-market updates

### 2. Dream Worker (Knowledge Graph Maintainer)
- **Frequency**: Every ~4 minutes via `DREAM_INTERVAL`
- **Responsibility**: Evolve knowledge graph relationships
- **Pattern**: **Probabilistic Graph Evolution**
  - Random pair selection (investible + bellwether)
  - Correlation analysis on return series
  - LLM-enhanced relationship labeling (30% of the time)
  - Edge weight updates using channel strengths

### 3. Think Worker (Decision Engine)
- **Frequency**: Every ~5 minutes via `THINK_INTERVAL`
- **Responsibility**: Generate trading decisions via multi-agent committee
- **Pattern**: **Committee Decision Making**
  - Read latest market snapshot
  - Multi-agent LLM prompt engineering
  - Critic scoring for insight quality
  - Optional auto-execution with guard rails

### 4. Options Worker (Derivatives Intelligence Layer)
- **Frequency**: Every ~6 minutes via `OPTIONS_INTERVAL`
- **Responsibility**: Monitor and analyze option chains for portfolio intelligence
- **Pattern**: **Selective LLM-Driven Monitoring**
  - Fetch option chains for active investibles
  - Filter by DTE (14-60 days) and liquidity (volume/OI)
  - LLM selects 3-5 best options per ticker
  - Updates monitored options database
  - Creates knowledge graph nodes/edges for options relationships
  - Stores pricing snapshots with Greeks over time

```mermaid
graph TB
    subgraph "Options Worker Cycle"
        O1[Select Random Tickers<br/>3-5 per cycle] --> O2[Fetch Option Chains<br/>yfinance API]
        O2 --> O3[Filter by Liquidity<br/>Volume & OI]
        O3 --> O4[Calculate Greeks<br/>Black-Scholes]
        O4 --> O5{LLM Budget?}
        O5 -->|Yes| O6[LLM Selection<br/>Top 3-5 options]
        O5 -->|No| O7[Skip this ticker]
        O6 --> O8[Update Monitored Options]
        O8 --> O9[Create Graph Nodes<br/>option_call/option_put]
        O9 --> O10[Store Snapshots<br/>Pricing + Greeks]
    end
    
    O10 -.-> ThinkWorker[Think Worker<br/>Uses options data]
    O10 -.-> KG[Knowledge Graph<br/>Options relationships]
```

**Why Separate Options Worker?**
- Different cadence (~6 min vs ~3 min for equities)
- Separate 10% allocation budget
- Different data model (Greeks, strikes, expirations)
- LLM selectivity (monitors 3-5 best vs bulk data)
- Independent budget prevents exhaustion

## Database Schema Patterns

### Event Sourcing Elements
- **Snapshots**: Complete market state at each point in time
- **Trades**: Immutable trading history with reasons
- **Dream Log**: Audit trail of all system actions
- **Insights**: Timestamped decision records with evidence

### Graph Storage Pattern
```sql
-- Nodes: Entities in the knowledge graph
nodes (node_id, kind, label, description, score, degree)

-- Edges: Relationships with normalized pairs
edges (edge_id, node_a, node_b, weight, top_channel) 

-- Edge Channels: Multi-channel relationship strengths
edge_channels (edge_id, channel, strength)
```

### Key Pattern: **Normalized Graph Storage**
- Node pairs always stored as `(min, max)` to avoid duplicates
- Edge weights computed from multiple channels
- Degree calculated dynamically for graph metrics

## Knowledge Graph Evolution Pattern

### Channel-Based Relationships
The system uses a **Multi-Channel Edge Model** where each relationship can have multiple aspects:

```python
CHANNEL_WEIGHTS = {
    "correlates": 1.0,
    "drives": 0.9, 
    "hedges": 0.8,
    "liquidity_coupled": 0.7,
    # ... more channels
}
```

### Evolution Algorithm
1. **Heuristic Baseline**: Correlation-based channel assignment
2. **LLM Enhancement**: Probabilistic relationship labeling
3. **Weight Aggregation**: Channel strengths → overall edge weight
4. **Graph Metrics**: Degree and score updates

## Multi-Agent LLM Pattern

### Agent Specialization
The system implements **Role-Based Agent Architecture**:

```python
agents = {
    "macro": {"regime": "risk-on/off", "bullets": [...]},
    "technical": {"top": [...], "bottom": [...], "bullets": [...]},
    "risk": {"cash_buffer_pct": N, "trim": [...], "bullets": [...]},
    "allocator": {"bullets": [...]}
}
```

### Decision Synthesis Pattern
1. **Single LLM Call**: All agents respond in one structured JSON
2. **Structured Output**: Enforced schema for decisions
3. **Fallback Logic**: Rule-based decisions if LLM fails
4. **Critic Scoring**: Quality assessment for insight starring

## Risk Management Patterns

### Guard Rails System
Multiple layers of protection using **Defense in Depth**:

```python
# Portfolio level
MAX_BUY_EQUITY_PCT_PER_CYCLE = 18%
MIN_CASH_BUFFER_PCT = 12%

# Position level  
MAX_SYMBOL_WEIGHT_PCT = 14%
MIN_TRADE_NOTIONAL = $25

# Time-based
TRADE_ANYTIME = False  # Respects market hours
```

### Pattern: **Graduated Constraints**
- **Cycle-level**: Limits per decision cycle
- **Position-level**: Limits per holding
- **Portfolio-level**: Overall exposure limits
- **Time-based**: Trading window restrictions

## Web UI Patterns

### Real-Time Dashboard Pattern
- **Server Push**: WebSocket-like updates via periodic AJAX
- **Component Architecture**: Modular panels (KPIs, graph, controls, insights)
- **Interactive Graph**: vis-network for knowledge graph visualization

### API Design Pattern
```
GET /api/state          # Current system state
GET /graph-data         # Knowledge graph for visualization  
GET /node/<id>          # Node details with connections
GET /edge/<id>          # Edge details with channels
POST /api/worker/action # Worker control endpoints
```

## Error Handling Patterns

### Graceful Degradation
1. **LLM Failures**: Fall back to rule-based decisions
2. **Data Failures**: Continue with cached data
3. **Network Issues**: Retry with exponential backoff
4. **Parse Errors**: Log and continue with defaults

### Budget Control Pattern
```python
class LLMBudget:
    def acquire(self) -> bool:  # Rate limiting
    def stats(self) -> dict:    # Monitoring
```

## Configuration Patterns

### Environment-Driven Configuration
- **Provider Abstraction**: Ollama vs OpenRouter via `LLM_PROVIDER`
- **Speed Controls**: Configurable worker intervals
- **Risk Parameters**: Adjustable guard rail percentages
- **Debug Modes**: Verbose logging and testing hooks

### Pattern: **Strategy Pattern for LLM Providers**
```python
def llm_chat_json(system: str, user: str):
    if LLM_PROVIDER == "openrouter":
        return openrouter_chat_json(system, user)
    else:
        return ollama_chat_json(system, user)
```

## Critical Implementation Paths

### Market Data Flow
```
Yahoo API → fetch_single_ticker() → last_close_many() 
→ compute_indicators() → compute_signals_from_bells() 
→ SQLite snapshots → mark-to-market positions
```

### Decision Flow  
```
Latest snapshot → _llm_committee() → sanitize_decisions()
→ critic_score() → starred insights → execute_paper_trades()
```

### Knowledge Graph Update Flow
```
Random pair selection → corr() analysis → LLM labeling (30%)
→ channel strength updates → edge weight computation → degree updates
```

## Concurrency Patterns

### Thread Safety
- **DB Lock**: `threading.RLock()` for SQLite access
- **Worker Isolation**: Each worker runs independently
- **Cache Protection**: Thread-safe price caching
- **Atomic Operations**: Database transactions for consistency

### Pattern: **Independent Worker Threads**
- No shared state between workers
- Database as single source of truth
- Event-driven communication via database

## Options Integration & Trading Strategy Intelligence

### How Options Enhance Trading Decisions

Options provide a **multi-dimensional intelligence layer** that complements equity positions:

```mermaid
graph TB
    subgraph "Options Intelligence Signals"
        IV[Implied Volatility<br/>Market Fear Gauge]
        Greeks[Greeks Analysis<br/>Δ Γ Θ V]
        OI[Open Interest<br/>Positioning Data]
        Skew[Volatility Skew<br/>Risk Premium]
    end
    
    subgraph "Knowledge Graph Integration"
        Nodes[Option Nodes<br/>option_call/put]
        Edges[Option Edges<br/>options_hedges<br/>options_leverages]
        Underlying[Equity Nodes]
    end
    
    subgraph "Strategy Signals"
        S1[Hedge Detection<br/>Put OI Spikes]
        S2[Leverage Opportunity<br/>Cheap Calls]
        S3[Sentiment Gauge<br/>Put/Call Ratio]
        S4[Mispricing<br/>IV Anomalies]
    end
    
    IV --> S3
    IV --> S4
    Greeks --> S2
    OI --> S1
    Skew --> S4
    
    Nodes --> Edges
    Edges --> Underlying
    
    S1 --> ThinkWorker[Think Worker<br/>Strategy Formation]
    S2 --> ThinkWorker
    S3 --> ThinkWorker
    S4 --> ThinkWorker
```

### Options in the Knowledge Graph

Options are **first-class graph entities** with specialized edge types:

```mermaid
graph LR
    AAPL[AAPL<br/>Equity Node<br/>Score: 0.85] 
    
    CALL1[AAPL_C180_0315<br/>Call Option<br/>Δ: 0.60] 
    CALL2[AAPL_C190_0315<br/>Call Option<br/>Δ: 0.35]
    
    PUT1[AAPL_P175_0315<br/>Put Option<br/>Δ: -0.40]
    PUT2[AAPL_P170_0315<br/>Put Option<br/>Δ: -0.25]
    
    AAPL -->|options_leverages<br/>strength: 0.80| CALL1
    AAPL -->|options_leverages<br/>strength: 0.55| CALL2
    AAPL -->|options_hedges<br/>strength: 0.85| PUT1
    AAPL -->|options_hedges<br/>strength: 0.65| PUT2
    
    style CALL1 fill:#c8e6c9
    style CALL2 fill:#c8e6c9
    style PUT1 fill:#ffcdd2
    style PUT2 fill:#ffcdd2
    style AAPL fill:#e3f2fd
```

**Edge Channels:**
- `options_leverages` (0.80) - Calls provide upside exposure with defined risk
- `options_hedges` (0.85) - Puts protect against downside moves
- `greek_exposure` (0.70) - Correlated delta/vega movements
- `options_strategy` (0.75) - Part of spread or combo strategy

**Node Score Calculation:**
- Option nodes scored by absolute delta (directional conviction)
- Higher open interest → higher score (more market consensus)
- Integrated into overall graph degree calculations

### Trading Strategy Thought Process

The system uses options data to make **context-aware decisions**:

```mermaid
flowchart TD
    Start[Market Snapshot] --> Analysis{Analyze Options Data}
    
    Analysis --> Vol[IV Analysis]
    Analysis --> Position[Positioning Analysis]
    Analysis --> Price[Pricing Analysis]
    Analysis --> Corr[Correlation Analysis]
    
    Vol --> V1{IV Spike?}
    V1 -->|Yes| Fear[Market Fear<br/>Reduce Risk]
    V1 -->|No| Calm[Normal Vol<br/>Maintain Exposure]
    
    Position --> P1{Put OI Surge?}
    P1 -->|Yes| Hedge[Institutions Hedging<br/>Caution Signal]
    P1 -->|No| Bullish[Low Hedge Demand<br/>Risk-On Signal]
    
    Price --> PR1{Call IV < Put IV?}
    PR1 -->|Yes| Skew[Protective Skew<br/>Market Worried]
    PR1 -->|No| Flat[Balanced Sentiment]
    
    Corr --> C1[Options Greeks vs<br/>Equity Movement]
    C1 --> C2{Delta Alignment?}
    C2 -->|Yes| Confirm[Confirms Equity Trend]
    C2 -->|No| Diverge[Potential Reversal]
    
    Fear --> Decision[Strategic Decision]
    Calm --> Decision
    Hedge --> Decision
    Bullish --> Decision
    Skew --> Decision
    Flat --> Decision
    Confirm --> Decision
    Diverge --> Decision
    
    Decision --> Execute[Multi-Agent Committee<br/>Incorporates Options Intel]
```

### Detecting Market Conditions via Options

#### 1. **Volatility Regime Detection**

```python
# High IV = Market Fear
if option.iv > historical_avg * 1.5:
    signal = "Risk-Off"  # Think worker reduces exposure
    
# Low IV = Complacency  
if option.iv < historical_avg * 0.7:
    signal = "Risk-On"  # Opportunities for leverage
```

**Graph Impact:** Options with high IV get higher edge weights to underlying → stronger signal in correlation analysis

#### 2. **Institutional Positioning**

```python
# Put OI surge = Hedging activity
put_call_oi_ratio = sum(put.open_interest) / sum(call.open_interest)

if put_call_oi_ratio > 1.5:
    signal = "Institutions Hedging"  # Reduce bullish exposure
elif put_call_oi_ratio < 0.7:
    signal = "Bullish Positioning"  # Market confident
```

**Graph Impact:** High put OI creates stronger `options_hedges` edges → Dream worker identifies defensive correlations

#### 3. **Mispricing Detection**

Options can reveal **disconnect between derivatives and equity**:

```python
# Expected move from options
expected_move = spot_price * iv * sqrt(dte / 365)

# Actual equity volatility
realized_vol = std(returns[-30:])

if iv > realized_vol * 1.3:
    signal = "IV Overpriced"  # Options expensive vs reality
    strategy = "Consider equity over options"
    
if iv < realized_vol * 0.8:
    signal = "IV Cheap"  # Options underpriced
    strategy = "Leverage opportunities via calls/puts"
```

**Graph Impact:** Mispricing creates `greek_exposure` edges with lower correlation → signals opportunity

#### 4. **Sentiment and Momentum**

```python
# Delta-weighted positioning
portfolio_delta = sum(option.delta * option.open_interest)

if portfolio_delta > 0:
    signal = "Net Bullish Options Positioning"
else:
    signal = "Net Bearish Options Positioning"
    
# Compare to equity momentum
if portfolio_delta > 0 and equity_momentum < 0:
    signal = "Divergence - Options Bullish, Stock Weak"
    strategy = "Potential reversal setup"
```

**Graph Impact:** Delta divergence weakens `options_leverages` edges → flags mismatch to Think worker

### Options Data Flow to Trading Decisions

```mermaid
sequenceDiagram
    participant OW as Options Worker
    participant DB as Database
    participant KG as Knowledge Graph
    participant TW as Think Worker
    participant LLM as Multi-Agent LLM
    
    OW->>DB: Store Options Snapshot<br/>(Greeks, IV, OI, Volume)
    OW->>KG: Create Option Nodes<br/>(option_call/put)
    OW->>KG: Create Edges to Underlying<br/>(options_leverages/hedges)
    KG->>DB: Update Edge Weights<br/>(based on delta)
    
    Note over TW: ~5 min later
    TW->>DB: Fetch Latest Snapshot
    TW->>DB: Read Options Data
    TW->>KG: Query Option Relationships
    
    TW->>LLM: Multi-Agent Prompt<br/>+ Options Context
    Note over LLM: "Macro Agent: High put OI suggests hedging"<br/>"Technical Agent: IV spike = fear"<br/>"Risk Agent: Reduce exposure 5%"<br/>"Allocator: Trim AAPL to 8%"
    
    LLM->>TW: Trading Decisions<br/>Informed by Options
    TW->>DB: Execute Trades<br/>Log Reasoning
```

### Correlation Analysis with Options

Options provide **leading indicators** for equity movements:

**Example Correlation Scenarios:**

1. **Hedging Correlation:**
   ```
   Stock declining → Put OI increasing → options_hedges edge strengthens
   Graph signals: "Protective demand rising"
   ```

2. **Leverage Correlation:**
   ```
   Stock rallying → Call OI increasing → options_leverages edge strengthens  
   Graph signals: "Conviction in upside"
   ```

3. **Volatility Correlation:**
   ```
   Stock choppy → IV elevated → greek_exposure edge weakens
   Graph signals: "Uncertainty, reduce position sizes"
   ```

4. **Divergence (Mispricing):**
   ```
   Stock flat → Put IV spiking → Abnormal fear premium
   Graph signals: "Hedges expensive, potential overreaction"
   ```

### Strategic Decision Integration

The Think Worker receives options intelligence via:

1. **Portfolio Greeks Summary:**
   - Net Delta: Overall directional exposure
   - Net Gamma: Sensitivity to moves
   - Net Theta: Time decay drag
   - Net Vega: Volatility exposure

2. **Sentiment Gauges:**
   - Put/Call OI ratio by ticker
   - IV percentile rank (historical context)
   - Volatility skew (risk premium)

3. **Graph Relationships:**
   - Options with strong edges to trending stocks
   - Hedge patterns (multiple stocks showing put activity)
   - Leverage patterns (call accumulation)

4. **LLM receives formatted summary:**
   ```json
   {
     "options_intel": {
       "portfolio_greeks": {"delta": 2.5, "theta": -12.5, "vega": 45.2},
       "by_ticker": {
         "AAPL": {
           "put_call_oi": 1.8,
           "iv_percentile": 85,
           "signal": "High hedging demand, caution"
         }
       }
     }
   }
   ```

### Future Strategy Enhancements

Options data enables sophisticated strategies (not yet implemented):

- **Spread Construction:** Use graph to identify natural hedge pairs
- **Volatility Arbitrage:** Options vs realized vol mispricing
- **Event Detection:** IV spikes before earnings/news
- **Risk Reversal Signals:** Skew changes as sentiment indicators
- **Cross-Asset Hedging:** Options on sector ETFs vs individual stocks

The foundation is built - options are monitored, graphed, and available to the decision engine. Future iterations can leverage this intelligence for explicit options trading.
