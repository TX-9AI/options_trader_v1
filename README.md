# options_trader v1.0 — Vertigo Capital
**QQQ 0DTE | TastyTrade | Regime-Aware | GEX-Informed | Auto-Sized**

Institutional-grade 0DTE options trading bot. Classifies intraday market regime every 15 seconds and deploys the appropriate strategy. GEX (Gamma Exposure) is computed in real time from the live options chain — no external API required. Position sizing is automatic. Supports paper and live trading via TastyTrade SDK.

---

## Architecture

### Regime Classification
The bot classifies intraday market structure on every tick using ATR, ADX, Bollinger Band width, VWAP, VIX, and GEX environment. Regime drives strategy selection and entry conviction.

| Regime | Strategy |
|--------|----------|
| COMPRESSION | ButterflyStrategy (GEX pin-centered) |
| SWEEP_REVERSAL | SweepReversal (OTM gamma play) |
| TRENDING_BULL / TRENDING_BEAR | ORB debit spread |
| RANGING | No new entries |

### Strategies

**ORB (Opening Range Breakout)**
- 5-minute opening range locked at 9:30 ET
- Entry on confirmed 1-minute close outside range + retest
- Debit call/put spread targeting 100% premium gain
- Valid until noon ET | Entries cut off at 2:00 PM ET

**Sweep Reversal**
- Detects liquidity sweeps at key levels
- OTM options targeting delta ~0.08 (pure gamma play)
- BOS (Break of Structure) exit on 1-minute chart
- Entries cut off at 2:00 PM ET

**Debit Butterfly (Compression + GEX Pinning)**
- Fires only in COMPRESSION regime (Bollinger squeeze + low ADX)
- Center strike anchored to GEX pin zone when within $5 of price
- Grade A = PINNING environment + center within $2 of GEX pin
- Grade B = COMPRESSION regime, GEX neutral or moderate
- Blocked entirely when GEX environment = TRENDING
- Entries valid until 3:00 PM ET (late-day pinning window)
- 25% of max profit target | 25% loss stop | 2.5hr max hold

### GEX Integration
Computed live from the TastyTrade options chain every 15 seconds. No external scraping required.

```
call_gex = gamma × open_interest × 100 × spot_price
put_gex  = gamma × open_interest × 100 × spot_price × -1
net_gex  = call_gex + put_gex (summed across all strikes)
```

Derived levels: call wall, put wall, pin strike, flip strike, GEX environment

GEX informs all three strategies:
- **Butterfly** — centers on pin strike, blocked in TRENDING GEX
- **Sweep Reversal** — confluence boost when sweep hits call/put wall
- **ORB** — `DAMPENING` (×0.75 conviction) or `AMPLIFYING` (×1.15 conviction)

### BOS Exit (Directional Trades)
Break of Structure on the 1-minute chart. Candle closes only — no wicks.

- **Long:** tracks highest close from entry. Protected HL = low of candle that made the new high. Close below protected HL = BOS → exit
- **Short:** mirror image — tracks lowest close, protected LH = high of candle making new low
- Hard stop (25% premium loss) still fires first regardless of structure

### Position Sizing (Auto)
Risk per trade: `$200` (configurable in config.py)

- Grade A = 1.5× base risk | Grade B = 1.0× base risk
- Below minimum score threshold → rejected, no trade (no Grade C)
- Butterfly sizing halved when VIX in 15–20 zone

### Session Rules
| Rule | Value |
|------|-------|
| RTH only | 9:30 AM – 4:00 PM ET |
| Hard close | 3:45 PM ET (all positions) |
| Directional entry cutoff | 2:00 PM ET |
| Butterfly entry cutoff | 3:00 PM ET |
| ORB validity | Until noon ET |
| VIX > 20 | Butterflies blocked |
| Fed day | All entries blocked |

---

## Deployment

### Option 1 — Web install (mobile / Terminus / any SSH client)
SSH into a fresh EC2 and run:
```bash
curl -fsSL https://raw.githubusercontent.com/TX-9AI/options_trader_v1/main/install.sh -o install.sh && bash install.sh
```
Have ready: TastyTrade username & password, Telegram bot token & chat ID.

### Option 2 — Local install (Windows desktop)
1. Unpack to `C:\options_trader_v1\`
2. Place `tx-9.pem` in `C:\options_trader\`
3. Double-click `install.bat`
4. Follow `setup_ec2.sh` prompts — enter TastyTrade credentials and Telegram token

### EC2 Reference
| Bot | EC2 IP | Key location |
|-----|--------|-------------|
| options_trader v1.0 | 3.142.95.131 | C:\options_trader\tx-9.pem |

---

## Key Commands

### Service control
```bash
sudo systemctl start optionsbot
sudo systemctl stop optionsbot
sudo systemctl restart optionsbot
sudo systemctl status optionsbot
```

### Clean restart (wipe trades and log)
```bash
sudo systemctl stop optionsbot
rm -f ~/options-trader/trades.db ~/options-trader/bot.log
sudo systemctl start optionsbot
```

### Monitoring
```bash
# Live status dashboard
python status.py

# Performance dashboard
python query.py

# Live logs filtered
journalctl -u optionsbot -f --no-pager | grep -v "tastytrade\|FEED_DATA\|received"

# Last 30 lines
journalctl -u optionsbot -n 30 --no-pager | grep -v "tastytrade\|FEED_DATA\|received"

# Errors only
journalctl -u optionsbot -n 50 --no-pager | grep -i error
```

### Debugging
```bash
# Check DB schema
sqlite3 ~/options-trader/trades.db ".schema"

# Add missing column (if needed after update)
sqlite3 ~/options-trader/trades.db "ALTER TABLE trades ADD COLUMN current_premium REAL DEFAULT 0.0;"

# Check open trades
sqlite3 ~/options-trader/trades.db "SELECT trade_id, strategy, status, entry_premium, current_premium FROM trades WHERE status='open';"

# Check today's closed trades
sqlite3 ~/options-trader/trades.db "SELECT trade_id, strategy, entry_premium, exit_premium, pnl_usd, exit_reason FROM trades WHERE status='closed' ORDER BY exit_time DESC LIMIT 10;"

# Clear pycache
find ~/options-trader -name "*.pyc" -delete
find ~/options-trader -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null
```

### Config variables (config.py)
```bash
# Risk per trade
grep "RISK_PER_TRADE" ~/options-trader/config.py

# Butterfly TP target (default 25% of max profit)
grep "BUTTERFLY_TP_PCT" ~/options-trader/config.py

# Entry cutoffs
grep "ENTRY_CUTOFF\|BUTTERFLY_ENTRY" ~/options-trader/config.py

# Delta targets for sweep reversal
grep "SWEEP_TARGET_DELTA\|SWEEP_DELTA_TOLERANCE" ~/options-trader/config.py

# VIX thresholds
grep "VIX_BUTTERFLY" ~/options-trader/config.py
```

### Deploy single file update
```bash
# From Windows PowerShell (run separately)
scp -i "C:\options_trader\tx-9.pem" "C:\options_trader_v1\main.py" ubuntu@3.142.95.131:~/options-trader/main.py

# Then restart on EC2
sudo systemctl restart optionsbot
```

---

## Telegram Alerts
- Startup, entry, exit, regime change
- Configure token and chat ID via `setup_ec2.sh` during deployment
- Token stored as systemd environment variable — never in source code

---

## GitHub
```
https://github.com/TX-9AI/options_trader_v1
```

### First push
```bash
git init
git remote add origin https://github.com/TX-9AI/options_trader_v1.git
git add .
git commit -m "options_trader v1.0 — initial release"
git branch -M main
git push -u origin main
```

### Subsequent pushes
```bash
git add .
git commit -m "describe your change"
git push origin main
```

---

## File Structure
```
options_trader_v1/
├── main.py                    # Main loop, regime dispatch, GEX compute, entry/exit
├── config.py                  # All tunable parameters
├── credentials.py.template    # Copy to credentials.py, fill in keys
├── setup_ec2.sh               # EC2 first-time setup script
├── install.bat                # Windows launcher
├── status.py                  # Live status dashboard
├── query.py                   # Performance dashboard
├── requirements.txt           # Python dependencies
├── analysis/                  # Regime classifier, ORB engine, volatility, structure, liquidity
├── data/                      # TastyTrade client, options chain, GEX calculator, macro
├── database/                  # Trade logger (SQLite)
├── execution/                 # Entry engine, exit engine (BOS), position manager
├── notifications/             # Telegram alerts
├── risk/                      # Risk manager, session guard, setup scorer
├── strategy/                  # ORB, SweepReversal, Butterfly
└── utils/                     # Math, time utilities
```

---

## Dependencies
```
tastytrade
yfinance
pandas
numpy
requests
tzdata
```

Install: `pip install -r requirements.txt`

---

## Session Notes — June 25, 2026
- v1.0 initial deployment on EC2 3.142.95.131
- QQQ 0DTE paper trading via TastyTrade SDK
- GEX computed from live chain — no external API
- BOS exit replacing premium-based trailing stop on directional trades
- Butterfly restricted to COMPRESSION regime only (RANGING removed)
- Grade C eliminated — below minimum score = no trade
- Butterfly entry cutoff extended to 3:00 PM ET for late-day pinning
- Live P&L display in status.py and query.py (current_premium updated every tick)
