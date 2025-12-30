# Active Context

## Current Focus (December 2025)

### Primary Objective
**RESOLVED**: Fixed critical LLM truncation bug causing agents to output zero-allocation "risk-off" plans. Agents now generate real trading decisions with proper capital allocation.

### Critical Bug Fix (December 29, 2025)

#### Agent Zero-Allocation Bug (RESOLVED)
**Problem:** All agent plans showed identical "risk-off posture" with 0% allocation across all tickers, despite varying market conditions.

**Root Cause Discovered:**
- LLM responses were being **truncated at ~750-850 tokens** (3066 characters)
- `max_tokens=1000` parameter was too small for complete JSON response
- Response cut off mid-JSON, missing:
  - Closing `]` for decisions array
  - `"explanation"` field
  - `"confidence"` field
  - Closing `}` for entire response
- JSON extraction code used regex fallback that extracted wrong object (`agents` instead of root)
- Result: System used default 0.5 confidence and missed all BUY decisions

**Example Truncated Response:**
```json
{
  "agents": {...},
  "decisions": [
    {"ticker": "MSFT", "action": "BUY", "allocation_pct": 10.0, ...},
    {"ticker": "NVDA", "action": "BUY", "allocation_pct": 10.0, ...},
    {"ticker": "WOLF", "action": "HOLD", "allocation_pct": 0, "note": "Declining, avoid"},
    // TRUNCATED HERE - missing closing ], explanation, confidence, }
```

**Solution Implemented:**
1. **Increased `max_tokens` from 1000 to 4000** in `src/llm/providers.py`
2. **Made it configurable** via `LLM_MAX_TOKENS` environment variable
3. **Improved JSON extraction** to try `json.loads()` first before regex fallback
4. **Added diagnostic logging** to capture full raw responses

**Files Modified:**
- `src/config.py` - Added `LLM_MAX_TOKENS` configuration
- `src/llm/providers.py` - Changed to use `Config.LLM_MAX_TOKENS`
- `src/utils.py` - Improved `extract_json()` to try direct parsing first
- `.env.example` - Added `LLM_MAX_TOKENS=4000`
- `README.md` - Documented new configuration option

**Results - BEFORE vs AFTER:**

**BEFORE** (truncated at 1000 tokens):
- ❌ All HOLD with 0% allocation
- ❌ Confidence: 0.50 (default fallback)
- ❌ Critic score: 0.66
- ❌ Generic auto-generated explanations (193 chars)
- ❌ Parsed wrong JSON object (agents dict instead of root)

**AFTER** (with 4000 tokens):
- ✅ Real BUY decisions: MSFT 10%, NVDA 10%, AMZN 8%, GOOGL 8%, LUNR 6%
- ✅ Confidence: 0.72 (from LLM)
- ✅ Critic score: 0.77 (higher quality)
- ✅ Detailed explanations (520 chars)
- ✅ Correct JSON parsing with all fields present

**Configuration:**
```env
LLM_MAX_TOKENS=4000  # Default, can be increased for larger responses
```

### Previous Completed Feature (December 29, 2025)

#### LLM-Powered Portfolio Expansion (COMPLETED)

### Latest Major Feature (December 29, 2025)

#### LLM-Powered Portfolio Expansion (COMPLETED)
A complete system for dynamically expanding the trading portfolio using AI-driven stock discovery:

**What Was Built:**
1. **Separate LLM Budget**: ExpansionBudget class for independent LLM call tracking
2. **Database Schema**: investibles table with parent_ticker, expansion_level, sector tracking
3. **Full CRUD API**: 8 RESTful endpoints for investibles management
4. **Three LLM Functions**:
   - `llm_detect_sector()` - Auto-detects GICS sectors
   - `llm_find_similar()` - Finds industry peers
   - `llm_find_dependents()` - Finds suppliers/customers/influencers
5. **Expansion Algorithm**: Background thread implementing 1→3→9→27 pattern
6. **Beautiful UI**: Complete tree view with color-coded levels and real-time progress

**How It Works:**
- User adds stock (e.g., AAPL) with "Auto-expand" checkbox
- LLM detects sector (Technology)
- LLM finds 3 similar stocks (MSFT, GOOGL, META) - Level 1
- For each Level 1 stock, LLM finds 3 dependents - Level 2
- Continues until EXPANSION_MAX_STOCKS reached (default: 27)
- All happens in background with real-time progress display

**Technical Implementation:**
- Separate expansion budget (10 calls/min) independent from worker budget
- JSON serialization bug fixed (None key → "null" string)
- Market worker now uses `get_active_investibles()` from database
- Tree structure with parent-child relationships
- Enable/disable stocks without deleting

**Configuration:**
```env
INVESTIBLES=XLE,XLF,XLV,XME,IYT,AAPL,MSFT,JPM,UNH,CAT,NVDA,AMD,AMZN,GOOGL,META,...
EXPANSION_ENABLED=true
EXPANSION_MAX_STOCKS=27
EXPANSION_LLM_CALLS_PER_MIN=10
```

### Recent Major Changes

#### 1. OpenRouter Integration (COMPLETED)
- **Added Support**: Implemented dual LLM provider system (Ollama + OpenRouter)
- **New Dependencies**: Added `langchain-openai>=0.1.0` for OpenRouter API calls
- **Configuration**: Added environment variables for provider selection
- **Code Changes**: 
  - Created `openrouter_chat_json()` function
  - Added unified `llm_chat_json()` interface
  - Updated ThinkWorker to use new LLM interface

#### 2. Environment Loading Fix (COMPLETED)
- **Problem**: `.env` file variables not being loaded by application
- **Root Cause**: Missing `python-dotenv` dependency and `load_dotenv()` call
- **Solution**: Added `from dotenv import load_dotenv` and `load_dotenv()` at top of application
- **Result**: Application now properly reads `.env` configuration

#### 3. Project Modernization (COMPLETED)
- **pyproject.toml**: Added modern Python project configuration
- **Development Tools**: Configured Black, Ruff, MyPy for code quality
- **Build System**: Set up hatchling for package building
- **Scripts**: Added entry point for cleaner execution

### Current Issues Under Investigation

#### 1. Portfolio Display Issue (RESOLVED STATUS: PARTIALLY FIXED)
**Problem:** UI shows $10,000 start cash instead of configured $500
- **Root Cause**: Existing database contains cached $10,000 from previous runs
- **Status**: User successfully deleted database (`rm kginvest_live.*`) and restarted
- **Next Steps**: Verify new database initialized with $500 from `.env` 

#### 2. LLM Parse Errors (INVESTIGATING)
**Problem:** "parse_fail" errors when kat-coder-pro model responds
- **Symptoms**: LLM Budget shows "parse_fail" as last error
- **Potential Causes**:
  - Model response format differs from expected JSON structure
  - JSON extraction logic may not handle kat model's output format
  - Response might contain extra text outside JSON blocks
- **Investigation Needed**: Capture raw LLM responses to analyze format differences

#### 3. Configuration Loading Verification (MONITORING)
**Problem:** Need to verify OpenRouter configuration is properly loaded
- **Status**: Log shows `model=kwaipilot/kat-coder-pro:free` which is correct
- **Still Checking**: Whether `LLM_PROVIDER=openrouter` is actually routing to OpenRouter vs Ollama
- **Evidence Needed**: LLM API call logs to confirm which endpoint is being used

## Latest Work Session Insights

### What's Working Well
1. **Database Reset**: Clearing database and cache resolved portfolio display issue
2. **Environment Loading**: `.env` variables now being read properly
3. **Model Configuration**: Log shows correct model name being used
4. **System Stability**: All three workers running without crashes

### What Needs Attention
1. **LLM Response Parsing**: kat-coder-pro model may return different JSON format
2. **Error Logging Verbosity**: Need better error messages for parse failures
3. **Provider Verification**: Confirm actually using OpenRouter vs Ollama

### Key Configuration Values (Current)
```env
LLM_PROVIDER=openrouter
DREAM_MODEL=kwaipilot/kat-coder-pro:free
OPENROUTER_API_KEY=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
START_CASH=500.0
LLM_CALLS_PER_MIN=10
```

## Next Steps & Priorities

### Immediate (Next Session)
1. **Debug Parse Errors**: 
   - Add debug logging to capture raw LLM responses
   - Compare kat model output format vs expected JSON structure
   - Improve JSON extraction robustness if needed

2. **Verify Provider Routing**:
   - Add logging to confirm which LLM provider is being called
   - Check if requests are going to OpenRouter or Ollama endpoints

3. **Monitor Portfolio Initialization**:
   - Confirm new database starts with $500 cash
   - Verify all configuration values are properly applied

### Short-term Enhancements
1. **Error Handling**: Improve LLM response parsing robustness
2. **Debugging Tools**: Add better logging for LLM interactions
3. **Configuration Validation**: Add startup checks for required settings
4. **Documentation**: Update README with latest OpenRouter setup steps

### Medium-term Considerations
1. **Testing Framework**: Add unit tests for LLM integration
2. **Multiple Models**: Test different OpenRouter models for comparison  
3. **Fallback Improvements**: Better graceful degradation when LLM fails
4. **Performance Monitoring**: Track LLM response times and success rates

## Development Patterns Established

### Environment Management
- All configuration via `.env` file with sensible defaults
- `python-dotenv` for reliable environment loading
- Provider abstraction allows easy switching between Ollama/OpenRouter

### LLM Integration Architecture
```python
# Unified interface pattern
def llm_chat_json(system: str, user: str) -> Tuple[Optional[Dict], Optional[str]]:
    if LLM_PROVIDER == "openrouter":
        return openrouter_chat_json(system, user)
    else:
        return ollama_chat_json(system, user)
```

### Error Recovery Strategy
- LLM failures → Rule-based fallback decisions
- Parse errors → Continue with defaults + logging
- Network issues → Cached data when available
- Database errors → Retry with backoff

## Memory Bank Creation Status
- [x] **projectbrief.md**: Core mission and requirements
- [x] **productContext.md**: Why the project exists, user benefits
- [x] **systemPatterns.md**: Architecture patterns and implementation paths  
- [x] **techContext.md**: Technology stack and development setup
- [x] **activeContext.md**: Current focus and issues (this document)
- [ ] **progress.md**: What's working, what's left to build

## Session Handoff Notes

### For Future Cline Sessions
1. **Current State**: System is running but has parse errors with kat model
2. **Critical Files**: `.env` contains working OpenRouter configuration
3. **Database**: Fresh database initialized (user deleted old one)
4. **Next Debug**: Focus on LLM response parsing for kat-coder-pro model
5. **Memory Bank**: Document system knowledge for future sessions

### Key Files Modified This Session
- `requirements.txt`: Added python-dotenv
- `kgdreaminvest.py`: Added dotenv loading, OpenRouter support  
- `pyproject.toml`: Created modern project configuration
- `.env`: Updated with OpenRouter settings
- `memory-bank/`: Created complete documentation structure

## Learning & Insights

### Technical Learnings
- `uv run` doesn't automatically load `.env` - needs explicit `load_dotenv()`
- Database state persistence can cause configuration conflicts
- OpenRouter integration requires proper header configuration
- Different LLM models may return varied JSON response formats

### Process Learnings  
- Memory bank structure is crucial for session continuity
- Database reset often needed when changing fundamental configuration
- Environment variable debugging requires checking multiple layers
- LLM provider abstraction enables easier experimentation
