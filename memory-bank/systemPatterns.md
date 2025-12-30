# System Patterns & Architecture

## Core Architecture Pattern: Three-Worker System

### Worker Architecture
The system follows a **Producer-Consumer** pattern with three independent background workers:

```
Market Worker (Producer) → SQLite Database ← Dream Worker (Consumer/Producer)
                                ↓
                         Think Worker (Consumer) → Trading Decisions
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
