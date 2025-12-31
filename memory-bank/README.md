# KGDreamInvest Memory Bank

This Memory Bank contains comprehensive documentation about the KGDreamInvest project, designed to preserve project knowledge across development sessions.

## Purpose

As outlined in the project's `.clinerules`, this Memory Bank serves as the single source of truth for understanding the project state, architecture, and current work focus. After each memory reset, this documentation enables quick project context recovery.

## File Structure

### Core Files (Required Reading)
1. **[projectbrief.md](./projectbrief.md)** - Foundation document
   - Core mission and requirements
   - Success criteria and constraints
   - Target users and use cases

2. **[productContext.md](./productContext.md)** - Why this exists
   - Problems being solved
   - Market gap and user benefits
   - Success metrics

3. **[activeContext.md](./activeContext.md)** - Current focus
   - Recent changes and current issues
   - Next steps and priorities
   - Session handoff notes

4. **[systemPatterns.md](./systemPatterns.md)** - Architecture
   - System design patterns
   - Critical implementation paths
   - Component relationships

5. **[techContext.md](./techContext.md)** - Technology stack
   - Development setup
   - Dependencies and tools
   - Configuration management

6. **[progress.md](./progress.md)** - Current status
   - What's working vs what needs work
   - Known issues and limitations
   - Evolution of key decisions

## Quick Context Recovery

### For New Sessions
1. Start with **projectbrief.md** for core mission
2. Check **activeContext.md** for current state and issues
3. Review **progress.md** for what's working/broken
4. Reference **systemPatterns.md** for architecture understanding

### For Specific Tasks
- **Bug fixes**: Check activeContext.md current issues
- **Feature work**: See progress.md for what's left to build
- **Architecture questions**: Reference systemPatterns.md
- **Setup issues**: Check techContext.md

## Key Project Context

### Current State (December 2025)
- **Status**: OpenRouter integration completed but has parse errors with kat-coder-pro model
- **Working**: Core 4-worker system, market data, knowledge graph, paper trading
- **Issues**: LLM response parsing, need to verify provider routing
- **Next**: Debug parse errors, improve error logging

### Architecture Summary
- **Pattern**: Three independent workers (Market, Dream, Think)
- **Database**: SQLite with event sourcing elements
- **LLM**: Dual provider (OpenRouter/Ollama) with unified interface
- **UI**: Flask + vis-network for interactive knowledge graph
- **Risk**: Multi-layered guard rails for safe paper trading

### Configuration
- **LLM Provider**: OpenRouter with kwaipilot/kat-coder-pro:free
- **Environment**: All config via .env with python-dotenv
- **Database**: Fresh database from recent reset
- **Portfolio**: $500 starting cash

### Recent Changes This Session
1. Added OpenRouter integration with langchain-openai
2. Fixed .env loading with python-dotenv + load_dotenv()
3. Created pyproject.toml for modern Python project
4. Updated requirements.txt and dependencies
5. Created complete Memory Bank documentation

## Memory Bank Maintenance

### When to Update
- After implementing significant features
- When user requests "update memory bank"
- After discovering new project patterns
- When debugging reveals new insights

### Update Priority
1. **activeContext.md**: Always update for session handoffs
2. **progress.md**: Update when status changes significantly  
3. **systemPatterns.md**: Update when architecture evolves
4. **techContext.md**: Update when dependencies or setup changes

### Quality Standards
- Focus on meaningful progress milestones
- Keep technical details accurate and current
- Ensure session handoff information is complete
- Document learnings and insights for future reference

## Navigation Tips

### By Role
- **Developer**: Start with techContext.md, then systemPatterns.md
- **Product**: Focus on productContext.md and progress.md  
- **Debugger**: Check activeContext.md current issues first
- **New Contributor**: Begin with projectbrief.md overview

### By Task Type
- **Feature Development**: progress.md → systemPatterns.md
- **Bug Investigation**: activeContext.md → techContext.md
- **Configuration**: techContext.md → activeContext.md  
- **Architecture Design**: systemPatterns.md → productContext.md

## Links to Key Files

### Project Files
- [Main Application](../kgdreaminvest.py) - Complete system in one file
- [Configuration](../.env) - Environment variables  
- [Dependencies](../requirements.txt) - Python packages
- [Project Config](../pyproject.toml) - Modern Python project setup

### Documentation
- [README](../README.md) - User-facing documentation with mermaid diagrams
- [Git Ignore](../.gitignore) - Version control exclusions
- [Options Trading Design](../docs/OPTIONS_TRADING_DESIGN.md) - Complete technical documentation for options integration

This Memory Bank ensures project continuity and enables effective collaboration across development sessions.
