# Options Deep Integration with Dream Worker

## Overview

This document describes the deep integration of options chains into the Knowledge Graph via Dream Worker enhancements. Options are now treated as first-class nodes in the graph with sophisticated correlation analysis and LLM-powered relationship labeling.

## Architecture

### New Node Types
- `option_call`: Call option nodes
- `option_put`: Put option nodes

### New Edge Channels

#### Options-Underlying Channels
- `options_hedges` (0.85): Put provides downside hedge for equity
- `options_leverages` (0.80): Call provides leveraged upside exposure
- `greek_exposure` (0.70): Delta/Vega correlation to underlying

#### Options Cross-Correlation Channels
- `iv_correlates` (0.75): Implied volatilities move together (volatility clustering)
- `iv_inverse` (0.75): Implied volatilities move inversely
- `delta_flow` (0.70): Directional alignment via delta
- `vega_exposure` (0.70): Shared volatility sensitivity
- `cross_underlying_hedge` (0.80): Options hedge across different underlyings
- `spread_strategy` (0.75): Part of vertical/horizontal/diagonal spread
- `collar_strategy` (0.85): Put+Call collar relationship
- `vol_regime_coupled` (0.75): Move together in volatility regime changes

## Dream Worker Enhancements

### Assessment Mode Distribution
The Dream Worker now cycles through three assessment types:

1. **60% - Investible ↔ Bellwether** (original behavior)
   - Correlates stock returns with market indices
   - Uses price history from snapshots

2. **20% - Option ↔ Bellwether** (NEW)
   - Analyzes how options respond to market regime changes
   - Special handling for VIX (volatility), SPY/QQQ (market)
   - Example: AAPL puts correlate with VIX spikes

3. **20% - Option ↔ Option** (NEW)
   - Cross-option correlation analysis
   - Detects spread strategies (vertical, horizontal, diagonal, collar)
   - Analyzes IV correlation, delta alignment, vega similarity
   - Example: AAPL $180 call correlated with NVDA $900 call (tech rotation)

### LLM Usage Frequency
- Stock-Bellwether: 30% (original)
- Option-Bellwether: 40% (higher - more complex)
- Option-Option: 50% (highest - most nuanced)

## Correlation Utilities

New functions in `src/knowledge_graph/correlation.py`:

### `iv_corr(iv_a, iv_b) -> float`
Correlates implied volatility time series (30 periods).
Captures volatility regime clustering across options.

### `delta_alignment(delta_a, delta_b) -> float`
Measures directional alignment based on option deltas.
- High (0.7-1.0): Both bullish or both bearish
- Low (0.0-0.3): Opposite directions (hedge)

### `vega_similarity(vega_a, vega_b) -> float`
Compares volatility sensitivity between options.
High values indicate both options react similarly to IV changes.

### `spread_score(opt_type_a, opt_type_b, strike_a, strike_b, exp_a, exp_b) -> (str, float)`
Detects and scores potential option strategies:
- **Vertical Spread**: Same type, same exp, different strikes (0.70-0.90)
- **Horizontal Spread**: Same type, same strike, different exp (0.80)
- **Diagonal Spread**: Same type, different strike and exp (0.60-0.75)
- **Collar**: Call + Put, same exp (0.65-0.85)

## Example Knowledge Graph Relationships

### Option ↔ Bellwether
```
AAPL_P180_0321 --[options_hedges: 0.80]-->  ^VIX
               --[vol_regime_coupled: 0.75]--> ^VIX

TSLA_C250_0415 --[inverse_correlates: 0.70]--> ^VIX
               --[correlates: 0.65]-----------> QQQ
```

### Option ↔ Option (Same Underlying)
```
AAPL_C180_0321 --[spread_strategy: 0.90]---> AAPL_C200_0321
               (vertical call spread, bullish)

NVDA_P850_0228 --[collar_strategy: 0.85]---> NVDA_C950_0228
               (protective collar)
```

### Option ↔ Option (Cross-Underlying)
```
AAPL_C180_0321 --[iv_correlates: 0.82]-------> NVDA_C900_0321
               --[delta_flow: 0.75]-----------> NVDA_C900_0321
               --[vol_regime_coupled: 0.70]---> NVDA_C900_0321
               (Tech sector rotation play)

AAPL_P180_0321 --[cross_underlying_hedge: 0.78]-> GOOGL_C170_0321
               (Diversified hedge strategy)
```

## LLM Prompt

New prompt: `option_edge_relationship` in `dream_prompts.json`

Provides context to LLM:
- Node types (option vs underlying vs bellwether)
- Price correlation
- IV correlation
- Delta alignment, Vega similarity
- Strategy fit (spread/collar/hedge)
- Greeks (Delta, Gamma, Theta, Vega)

LLM selects 1-3 appropriate channels with strengths 0.10-1.0.

## Data Flow

```
Options Worker (every 10 min)
   ↓
Creates option nodes + stores snapshots
   ↓
Dream Worker (every 2 min)
   ↓
Randomly picks assessment type
   ↓
   ├─→ [60%] Stock-Bellwether correlation
   ├─→ [20%] Option-Bellwether correlation
   └─→ [20%] Option-Option correlation
        ↓
   Computes: IV corr, delta align, vega sim, spread score
        ↓
   Heuristic channels (always) + LLM labels (probabilistic)
        ↓
   Updates edges, weights, node degrees
        ↓
   Knowledge Graph continuously enriched
```

## Use Cases

### 1. Volatility Hedging Discovery
When VIX spikes, the KG reveals which put options have historically provided best hedges for your portfolio holdings.

### 2. Spread Strategy Detection
The system automatically identifies when monitored options could form profitable spreads (vertical, calendar, etc.) based on strike/expiration relationships.

### 3. Cross-Asset Correlation
Discover that tech stock options move together during sector rotations, enabling smarter diversification or concentration decisions.

### 4. Regime-Based Insights
See which options are coupled to volatility regimes, helping anticipate option price movements during market stress.

### 5. LLM-Enhanced Understanding
The LLM provides human-readable explanations for why certain option relationships exist, going beyond pure numerical correlation.

## Configuration

No additional configuration needed. The feature is automatically enabled when:
```python
OPTIONS_ENABLED = True  # in .env or Config
```

## Performance Considerations

- **Database Queries**: Option assessment queries are optimized with RANDOM() sampling to avoid full table scans
- **History Requirements**: 
  - Option-Bellwether: 10+ snapshots minimum
  - Option-Option: 10+ snapshots per option minimum
- **LLM Budget**: Uses existing DREAM_BUDGET, frequency tuned per assessment type
- **Skipping Logic**: Option-Option pairs skip recently assessed edges (1 hour cooldown) to avoid over-computation

## Monitoring

Check Dream Worker stats:
```python
DREAM.stats
# {
#   "steps": 1547,
#   "edges_updated": 1204,
#   "last_ts": "2026-01-07T13:22:00Z",
#   "last_action": "assess_option_option"
# }
```

View logs:
```sql
SELECT * FROM dream_log 
WHERE action IN ('assess_option_bw', 'assess_option_option')
ORDER BY ts DESC LIMIT 20;
```

## Future Enhancements

1. **Greeks Time Series**: Store delta/vega/theta history for even deeper correlation analysis
2. **Multi-Leg Strategy Detection**: Identify iron condors, butterflies, straddles
3. **Regime Classification**: Cluster options by behavior during risk-on vs risk-off regimes
4. **Portfolio Optimization**: Use graph relationships to suggest optimal options for current holdings
5. **Alert System**: Notify when strong new option correlations emerge

## Implementation Summary

**Files Modified:**
- `src/database/schema.py`: Added 8 new option channels
- `src/prompts/dream_prompts.json`: Added `option_edge_relationship` prompt
- `src/knowledge_graph/correlation.py`: Added `iv_corr`, `delta_alignment`, `vega_similarity`, `spread_score`
- `src/workers/dream_worker.py`: Added `_assess_option_bellwether_pair()` and `_assess_option_option_pair()` methods

**Lines of Code:** ~400 new lines of sophisticated correlation analysis and graph maintenance logic

**Dependencies:** No new external dependencies required - uses existing numpy, SQLite, LLM infrastructure

---

*Document created: 2026-01-07*
*Author: Cline AI Assistant*
