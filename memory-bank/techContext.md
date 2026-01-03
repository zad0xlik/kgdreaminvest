# Technical Context

## Technology Stack

### Core Technologies
- **Python 3.10+**: Main application language
- **Flask 2.3+**: Web framework for dashboard UI
- **SQLite**: Embedded database for persistence
- **NumPy**: Numerical computations (indicators, correlations)
- **Requests**: HTTP client for Yahoo Finance API

### LLM Integration Stack
- **OpenRouter API**: Primary LLM provider (cloud-based)
- **langchain-openai**: OpenRouter integration library
- **Ollama**: Alternative local LLM provider
- **python-dotenv**: Environment variable management

### Frontend Technologies
- **Vis-Network 9.1.2**: Interactive knowledge graph visualization
- **Vanilla JavaScript**: Frontend logic (no frameworks)
- **CSS3**: Modern styling with gradients, transitions
- **HTML5**: Semantic markup structure

### Development Tools
- **uv**: Modern Python package manager
- **pyproject.toml**: Project metadata and dependencies
- **Black**: Code formatting
- **Ruff**: Fast Python linting
- **MyPy**: Type checking

## Development Environment Setup

### Prerequisites
1. **Python 3.10+** installed
2. **uv** package manager installed
3. **OpenRouter API key** or local **Ollama** setup

### Quick Start
```bash
# Clone repository
git clone https://github.com/DormantOne/kgdreaminvest.git
cd kgdreaminvest

# Install dependencies
uv sync

# Configure environment
cp .env.example .env
# Edit .env with your OpenRouter API key

# Run application
uv run python kgdreaminvest.py
```

### Development Commands
```bash
# Install development dependencies
uv sync --group dev

# Format code
uv run black kgdreaminvest.py

# Lint code
uv run ruff check kgdreaminvest.py

# Type check
uv run mypy kgdreaminvest.py

# Run tests (when added)
uv run pytest
```

## LLM Provider Configuration

### OpenRouter (Recommended)
```env
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=sk-or-v1-your-key-here
DREAM_MODEL=kwaipilot/kat-coder-pro:free
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
```

**Benefits:**
- Free tier available with kat-coder-pro model
- No local GPU requirements
- Cloud-based reliability
- Multiple model options

### Ollama (Local Alternative)
```env
LLM_PROVIDER=ollama
OLLAMA_HOST=http://localhost:11434
DREAM_MODEL=gemma3:4b
```

**Setup:**
```bash
# Install Ollama
curl -fsSL https://ollama.com/install.sh | sh

# Pull model
ollama pull gemma3:4b

# Start service
ollama serve
```

## Database Architecture

### SQLite Design Decisions
- **Single File**: Simplifies deployment and backup
- **WAL Mode**: Better concurrency for multiple workers
- **Thread Safety**: RLock protection for concurrent access
- **Transactions**: Atomic operations for consistency

### Schema Evolution
- **Bootstrap Function**: Initializes empty database
- **Migration Strategy**: Version-based schema updates
- **Backup Strategy**: File-based copies for safety

### Performance Considerations
```python
# Connection optimization
conn.execute("PRAGMA journal_mode=WAL;")
conn.execute("PRAGMA synchronous=NORMAL;")
conn.execute("PRAGMA busy_timeout=8000;")
```

## API Integration Patterns

### Yahoo Finance API
- **Endpoint**: `https://query2.finance.yahoo.com/v8/finance/chart/{symbol}`
- **Rate Limiting**: Conservative defaults to avoid blocking
- **Caching**: 90-second price cache to reduce API calls
- **Error Handling**: Graceful fallback for failed requests

### Request Strategy
```python
# Concurrent requests with thread pool
with ThreadPoolExecutor(max_workers=10) as executor:
    futures = {executor.submit(fetch_single_ticker, symbol): symbol 
               for symbol in symbols}
```

## Concurrency & Threading

### Worker Thread Architecture
```python
class WorkerPattern:
    def __init__(self):
        self.running = False
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._loop, daemon=True)
    
    def _loop(self):
        while self.running and not self.stop.is_set():
            # Work cycle
            jitter_sleep(INTERVAL, self.stop)
```

### Thread Safety Measures
- **Database Lock**: `threading.RLock()` for SQLite
- **Price Cache Lock**: Thread-safe cache access
- **Event-Based Shutdown**: Clean worker termination
- **Daemon Threads**: Automatic cleanup on exit

## Configuration Management

### Environment Variables
All configuration through environment variables with sensible defaults:

```python
# Pattern: Environment with fallback
MARKET_SPEED = float(os.environ.get("MARKET_SPEED", "0.35"))
LLM_CALLS_PER_MIN = int(os.environ.get("LLM_CALLS_PER_MIN", "8"))
```

### Configuration Categories
- **LLM Provider**: Model selection and API credentials
- **Worker Speeds**: Timing intervals for each worker
- **Risk Parameters**: Guard rail percentages
- **System Settings**: Logging, database paths, ports

## Deployment Considerations

### Single-File Application
- **kgdreaminvest.py**: Complete application in one file
- **Benefits**: Easy deployment, no import complexity
- **Trade-offs**: Large file, but excellent for educational use

### Resource Requirements
- **Memory**: ~50MB base + model inference
- **CPU**: Light load (mostly I/O bound)
- **Network**: Yahoo Finance API calls + LLM inference
- **Storage**: SQLite database grows slowly over time

### Production Readiness
Current state is **educational prototype**:
- Single-threaded Flask (development server)
- No authentication or authorization
- Limited error recovery
- Basic logging and monitoring

## Technical Constraints

### Design Constraints
- **Educational Focus**: Code clarity over optimization
- **Single File**: No module splitting for simplicity
- **Paper Trading**: No real broker integration
- **SQLite Only**: No distributed database support

### Performance Constraints
- **LLM Budget**: Rate limiting to prevent API overuse
- **Yahoo API**: Rate limiting to respect usage terms
- **SQLite Concurrency**: Limited to WAL mode capabilities
- **Memory Usage**: Knowledge graph size bounded by SQLite

## Dependencies & Versions

### Core Dependencies
```toml
dependencies = [
    "flask>=2.3",           # Web framework
    "requests>=2.31",       # HTTP client
    "numpy>=1.24",          # Numerical computing
    "pytz>=2023.3",         # Timezone handling
    "langchain-openai>=0.1.0",  # LLM integration
    "python-dotenv>=1.0.0",     # Environment management
    "alpaca-py>=0.23.0",        # Alpaca broker integration (NEW - Jan 3, 2026)
]
```

**Alpaca Integration** (NEW - Jan 3, 2026):
- `alpaca-py v0.43.2` - Official Alpaca SDK for Python
- Provides both market data and trading capabilities
- Supports paper and live trading modes
- REST API client with built-in authentication

### Development Dependencies
```toml
[project.optional-dependencies]
dev = [
    "pytest>=7.0.0",       # Testing framework
    "black>=23.0.0",       # Code formatting
    "ruff>=0.1.0",         # Fast linting
    "mypy>=1.5.0",         # Type checking
]
```

## Error Handling Strategy

### Graceful Degradation
1. **LLM Failures**: Fall back to rule-based decisions
2. **Network Issues**: Use cached data when possible
3. **Database Errors**: Retry with exponential backoff
4. **Parse Failures**: Continue with safe defaults

### Monitoring & Observability
- **Structured Logging**: JSON-formatted logs for analysis
- **LLM Budget Tracking**: API usage monitoring
- **Worker Health**: Thread status and error rates
- **Database Metrics**: Query performance and storage growth

## Security Considerations

### API Key Management
- **Environment Variables**: Never hardcode credentials
- **.gitignore**: Exclude .env files from version control
- **Minimal Permissions**: Use least-privilege API keys

### Network Security
- **HTTPS Only**: All external API calls use TLS
- **No Inbound Connections**: System only makes outbound requests
- **Local Only**: Web UI binds to localhost by default
