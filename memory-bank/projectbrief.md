# KGDreamInvest Project Brief

## Core Mission
Create a continuously thinking multi-agent paper trading system that combines investing knowledge graphs, LLM-driven decision making, and real-time market analysis in an educational sandbox environment.

## What We're Building
A sophisticated paper trading system that:
- Fetches real market data from Yahoo Finance
- Maintains a living knowledge graph of market relationships
- Uses multi-agent LLM committees for trading decisions
- Provides real-time web dashboard visualization
- Operates autonomously with configurable guard rails

## Key Requirements

### Functional Requirements
1. **Real-time Market Data**: Continuous price feeds from Yahoo Finance API
2. **Knowledge Graph**: Dynamic relationship mapping between investibles and bellwethers
3. **Multi-Agent Decision Making**: LLM committee system for trading insights
4. **Paper Trading**: Safe trading simulation with risk management
5. **Web Dashboard**: Interactive visualization using vis-network
6. **Autonomous Operation**: Self-running background workers

### Non-Functional Requirements
1. **Educational Focus**: Paper trading only, no real money
2. **Transparency**: All decisions must be explainable
3. **Safety**: Multiple guard rails and risk controls
4. **Modularity**: Swappable LLM providers (Ollama, OpenRouter)
5. **Persistence**: SQLite for reliable data storage

## Success Criteria
- System runs continuously without intervention
- Generates reasonable trading insights with explanations
- Maintains stable knowledge graph relationships
- Provides clear visualization of decision-making process
- Operates safely within defined risk parameters

## Constraints
- Paper trading only (no real broker integration)
- Single-file Python application for simplicity
- SQLite database for lightweight persistence
- Web-based UI only (no mobile app)
- Educational/experimental use case only

## Target Users
- Developers learning about algorithmic trading
- Researchers studying multi-agent systems
- Students exploring knowledge graph applications
- Hobbyists interested in market analysis automation
