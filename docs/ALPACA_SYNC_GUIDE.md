# Alpaca Trade Sync - Quick Guide

## Problem Fixed

**Root Cause**: Think Worker was hardcoded to call `execute_paper_trades()` instead of the `execute_trades()` router, bypassing your `BROKER_PROVIDER=alpaca` configuration.

**Result**: Trades were only saved locally in the database but never sent to Alpaca API.

## Fixes Applied

### 1. ✅ Think Worker Fixed
- Changed `from src.portfolio import execute_paper_trades` → `from src.portfolio import execute_trades`
- Changed function call from `execute_paper_trades()` → `execute_trades()`
- Now respects `BROKER_PROVIDER` setting and routes to Alpaca when configured

### 2. ✅ Startup Sync Added
- `main.py` now syncs with Alpaca on startup
- Pulls account balance and positions from Alpaca → local database
- Ensures consistent state when service starts

### 3. ✅ Reconciliation Script Created
- `sync_alpaca_trades.py` - Syncs existing local trades to Alpaca
- Compares local database positions vs Alpaca positions
- Submits delta orders to bring Alpaca in sync

## How to Sync Your Existing Trades

### Step 1: Dry Run (Recommended First)
See what orders would be placed without actually executing them:

```bash
python sync_alpaca_trades.py --dry-run
```

This shows:
- Local database positions
- Current Alpaca positions  
- Delta orders needed to sync
- **No orders are submitted**

### Step 2: Sync Today's Trades
Execute the sync to submit catch-up orders to Alpaca:

```bash
python sync_alpaca_trades.py
```

This will:
1. Sync current Alpaca account state
2. Query local trades from today
3. Calculate position differences
4. Submit market orders to Alpaca for the delta
5. Show execution summary

### Step 3: Restart Service
After syncing, restart the service to use the fixed code:

```bash
python main.py
```

Now:
- ✅ Startup will sync with Alpaca automatically
- ✅ Future trades will route to Alpaca via `execute_trades()`
- ✅ UI will show accurate positions from Alpaca

## Additional Options

### Sync trades from a specific date:
```bash
python sync_alpaca_trades.py --since 2026-01-05
```

### Get help:
```bash
python sync_alpaca_trades.py --help
```

## Safety Features

The reconciliation script:
- ✅ Syncs Alpaca state first (accurate starting point)
- ✅ Only submits delta orders (not duplicate trades)
- ✅ Uses market orders (immediate execution)
- ✅ Logs all actions (full audit trail)
- ✅ Shows clear summary (success/failure counts)
- ✅ Respects `ALPACA_PAPER_MODE` setting

## Verification

After syncing, verify in:
1. **Alpaca Dashboard**: Check positions match expected
2. **UI Transactions Tab**: Check portfolio value is correct
3. **Alpaca Orders**: Verify orders were filled

## Troubleshooting

### "BROKER_PROVIDER is set to 'paper', not 'alpaca'"
- Your `.env` has `BROKER_PROVIDER=paper`
- Change to `BROKER_PROVIDER=alpaca` and try again

### "Failed to sync Alpaca account. Check your API keys"
- Verify `ALPACA_API_KEY` and `ALPACA_SECRET_KEY` in `.env`
- Check your Alpaca account is active
- Verify API keys have trading permissions

### Orders Failed
- Check Alpaca buying power sufficient
- Verify symbols are tradeable on Alpaca
- Check market is open (or use extended hours)
- Review error messages in output

## What's Different Now

**Before (Broken)**:
```
Think Worker → execute_paper_trades() → Local DB only
                                      ↓
                              No Alpaca orders!
```

**After (Fixed)**:
```
Think Worker → execute_trades() → Check BROKER_PROVIDER
                                ↓
                        BROKER_PROVIDER=alpaca
                                ↓
                     execute_alpaca_trades() → Alpaca API ✓
                                             ↓
                                    Local DB updated ✓
```

## Future Trades

All future trades will automatically:
1. Check `Config.BROKER_PROVIDER`
2. Route to Alpaca when `BROKER_PROVIDER=alpaca`
3. Submit orders to Alpaca API
4. Update local database
5. Show in UI with accurate positions

No more manual syncing needed! 🎉
