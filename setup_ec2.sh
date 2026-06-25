#!/bin/bash
# =============================================================================
# setup_ec2.sh — options-trader EC2 setup script
# Mirrors the proven crypto_trader methodology:
#   - Files SCP'd to ~/options-trader-deploy/ by install.bat
#   - rsync copies them to ~/options-trader/ (the live install dir)
#   - All prompts run here on the server
#   - instrument/risk/mode pre-supplied as env vars from bat file
# =============================================================================

set -e
export DEBIAN_FRONTEND=noninteractive
export TERM=xterm-256color

INSTALL_DIR="$HOME/options-trader"
DEPLOY_DIR="$HOME/options-trader-deploy"
SERVICE_NAME="optionsbot"
VENV="$INSTALL_DIR/venv"
VERSION="1.0"

# Redirect stdin from terminal so prompts work when called via SSH
exec < /dev/tty

# ── Colours ───────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'
BOLD='\033[1m'; RESET='\033[0m'

print_step() { echo -e "\n${BOLD}${GREEN}[ $1 ]${RESET} $2"; }
print_ok()   { echo -e "  ${GREEN}✓${RESET}  $1"; }
print_info() { echo -e "  ${CYAN}→${RESET}  $1"; }
print_warn() { echo -e "  ${YELLOW}⚠${RESET}  $1"; }
ask()        { read -rp "    $1: " "$2"; }
ask_secret() { read -rp "    $1 (paste, then ENTER): " "$2"; }
ask_yn()     {
    while true; do
        read -rp "    $1 [y/n]: " yn
        case "$yn" in [Yy]) return 0;; [Nn]) return 1;; esac
    done
}

echo ""
echo -e "${BOLD}${CYAN}╔══════════════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}${CYAN}║     options_trader v${VERSION}  —  EC2 Setup            ║${RESET}"
echo -e "${BOLD}${CYAN}╚══════════════════════════════════════════════════════╝${RESET}"
echo ""

# ── PRE-SUPPLIED VALUES from install.bat ────────────────────────────────────
PRESUPPLIED=false
if [[ -n "${OT_INSTRUMENT:-}" && -n "${OT_RISK_USD:-}" && -n "${OT_PAPER_TRADING:-}" ]]; then
    PRESUPPLIED=true
    INSTRUMENT="$OT_INSTRUMENT"
    RISK_USD="$OT_RISK_USD"
    PAPER_TRADING="$OT_PAPER_TRADING"
    echo -e "  ${CYAN}Settings received from install.bat:${RESET}"
    echo -e "    Instrument:  ${BOLD}${INSTRUMENT}${RESET}"
    echo -e "    Risk/trade:  ${BOLD}\$${RISK_USD}${RESET}"
    MODE_LABEL=$([ "$PAPER_TRADING" = "True" ] && echo "📄 PAPER" || echo "🔴 LIVE")
    echo -e "    Mode:        ${BOLD}${MODE_LABEL}${RESET}"
    echo ""
fi

# ─── STEP 1: INSTRUMENT ───────────────────────────────────────────────────────
print_step "1/8" "Instrument"
if [[ "$PRESUPPLIED" == "true" ]]; then
    print_ok "Instrument: ${INSTRUMENT}  (from install.bat)"
else
    echo ""
    echo -e "  ${BOLD}1. QQQ${RESET}  —  Nasdaq-100 ETF   (\$1 strike increments)"
    echo -e "  ${BOLD}2. SPY${RESET}  —  S&P 500 ETF      (\$1 strike increments)"
    echo -e "  ${BOLD}3. SPX${RESET}  —  S&P 500 Index    (\$5 strike increments)"
    echo ""
    while true; do
        read -rp "    Select [1/2/3, default=1]: " INST_CHOICE
        case "${INST_CHOICE:-1}" in
            1) INSTRUMENT="QQQ"; break ;;
            2) INSTRUMENT="SPY"; break ;;
            3) INSTRUMENT="SPX"; break ;;
            *) print_warn "Please enter 1, 2, or 3." ;;
        esac
    done
    print_ok "Instrument: ${INSTRUMENT}"
fi

# ─── STEP 2: RISK PER TRADE ───────────────────────────────────────────────────
print_step "2/8" "Risk Per Trade"
if [[ "$PRESUPPLIED" == "true" ]]; then
    print_ok "Risk per trade: \$${RISK_USD}  (from install.bat)"
else
    echo ""
    while true; do
        read -rp "    Risk per trade in \$ [default=200]: " RISK_INPUT
        RISK_USD="${RISK_INPUT:-200}"
        if [[ "$RISK_USD" =~ ^[0-9]+(\.[0-9]+)?$ ]]; then break; fi
        print_warn "Please enter a positive number."
    done
    print_ok "Risk per trade: \$${RISK_USD}"
fi

# ─── STEP 3: PAPER vs LIVE ────────────────────────────────────────────────────
print_step "3/8" "Trading Mode"
if [[ "$PRESUPPLIED" == "true" ]]; then
    print_ok "Mode: $([ "$PAPER_TRADING" = "True" ] && echo "📄 PAPER" || echo "🔴 LIVE")  (from install.bat)"
else
    PAPER_TRADING="True"
    echo ""
    if ask_yn "Enable LIVE trading? (paper is the safe default)"; then
        read -rp "    Type  LIVE  to confirm: " LIVE_CONFIRM
        if [[ "$LIVE_CONFIRM" == "LIVE" ]]; then
            PAPER_TRADING="False"
            print_ok "LIVE trading enabled."
        else
            print_info "Defaulting to paper mode."
        fi
    else
        print_ok "Paper mode."
    fi
fi

# ─── STEP 4: TASTYTRADE CREDENTIALS ──────────────────────────────────────────
print_step "4/8" "TastyTrade API Credentials"
echo ""
echo -e "  ${BOLD}How to get your credentials (2 minutes):${RESET}"
echo ""
echo -e "  1. Go to: ${CYAN}my.tastytrade.com → Manage → API → OAuth Applications${RESET}"
echo -e "  2. Click ${BOLD}New OAuth Application${RESET} — check all scopes — click Create"
echo -e "     ${BOLD}Save the Client Secret — shown once only${RESET}"
echo -e "  3. Inside the app → ${BOLD}Manage → New Personal OAuth Grant${RESET}"
echo -e "     Check all scopes — ${BOLD}Save the Refresh Token — shown once only${RESET}"
echo -e "  4. Your Account Number is on the main account page (e.g. 5WT12345)"
echo ""
read -rp "    Press ENTER when ready..."
echo ""

while true; do
    ask_secret "Client Secret" TT_CLIENT_SECRET
    [[ -n "$TT_CLIENT_SECRET" ]] && break
    print_warn "Cannot be empty."
done
while true; do
    ask_secret "Refresh Token" TT_REFRESH_TOKEN
    [[ -n "$TT_REFRESH_TOKEN" ]] && break
    print_warn "Cannot be empty."
done
while true; do
    ask "Account Number (e.g. 5WT12345)" TT_ACCOUNT_NUMBER
    [[ -n "$TT_ACCOUNT_NUMBER" ]] && break
    print_warn "Cannot be empty."
done
print_ok "TastyTrade credentials accepted."

# ─── STEP 5: TWILIO (OPTIONAL) ────────────────────────────────────────────────
print_step "5/8" "SMS Alerts via Twilio (Optional)"
echo ""
TWILIO_SID="" TWILIO_TOKEN="" TWILIO_FROM="" ALERT_TO=""
if ask_yn "Configure SMS alerts now?"; then
    echo ""
    while true; do
        ask "Twilio Account SID (starts with AC)" TWILIO_SID
        [[ "$TWILIO_SID" == AC* ]] && break
        print_warn "SID should start with AC."
    done
    while true; do
        ask_secret "Twilio Auth Token" TWILIO_TOKEN
        [[ -n "$TWILIO_TOKEN" ]] && break
        print_warn "Cannot be empty."
    done
    while true; do
        ask "Twilio From number (e.g. +15005550006)" TWILIO_FROM
        [[ "$TWILIO_FROM" == +* ]] && break
        print_warn "Must start with + and country code."
    done
    while true; do
        ask "Your mobile number (e.g. +18135550000)" ALERT_TO
        [[ "$ALERT_TO" == +* ]] && break
        print_warn "Must start with + and country code."
    done
    print_ok "SMS alerts configured."
else
    print_info "SMS skipped. Run configure.sh to add later."
fi

# ─── STEP 6: SYSTEM PACKAGES ─────────────────────────────────────────────────
print_step "6/8" "Installing system packages..."
sudo apt-get update -qq
sudo apt-get install -y -qq python3 python3-pip python3-venv git rsync bc
print_ok "System packages ready."

# ─── Install bot files via rsync from deploy dir ─────────────────────────────
mkdir -p "$INSTALL_DIR"
rsync -a \
    --exclude='.git' \
    --exclude='*.pem' \
    --exclude='*.bat' \
    --exclude='venv' \
    --exclude='trades.db' \
    --exclude='bot.log' \
    --exclude='__pycache__' \
    "$DEPLOY_DIR/" "$INSTALL_DIR/"
chmod +x "$INSTALL_DIR/setup_ec2.sh" "$INSTALL_DIR/configure.sh" 2>/dev/null || true
print_ok "Bot files installed to ${INSTALL_DIR}."

# Verify critical files
for f in main.py config.py requirements.txt; do
    [ -f "$INSTALL_DIR/$f" ] || { echo "ERROR: $f missing. Aborting."; exit 1; }
done
print_ok "File verification passed."

# ─── STEP 7: PYTHON ENVIRONMENT ──────────────────────────────────────────────
print_step "7/8" "Python virtual environment..."
python3 -m venv "$VENV"
source "$VENV/bin/activate"
pip install --upgrade pip -q
pip install -r "$INSTALL_DIR/requirements.txt" -q
print_ok "Dependencies installed."

grep -q "options-trader/venv" ~/.bashrc || echo "source $VENV/bin/activate" >> ~/.bashrc
grep -q "cd ~/options-trader"  ~/.bashrc || echo "cd $INSTALL_DIR"           >> ~/.bashrc

# ─── STEP 8: SYSTEMD SERVICE ─────────────────────────────────────────────────
print_step "8/8" "Configuring systemd service..."

ENV_BLOCK="Environment=OT_INSTRUMENT=${INSTRUMENT}
Environment=OT_RISK_USD=${RISK_USD}
Environment=OT_PAPER_TRADING=${PAPER_TRADING}
Environment=OT_BOT_NAME=OptionsTrader-${INSTRUMENT}
Environment=TT_CLIENT_SECRET=${TT_CLIENT_SECRET}
Environment=TT_REFRESH_TOKEN=${TT_REFRESH_TOKEN}
Environment=TT_ACCOUNT_NUMBER=${TT_ACCOUNT_NUMBER}"

if [[ -n "$TWILIO_SID" ]]; then
    ENV_BLOCK="${ENV_BLOCK}
Environment=TWILIO_ACCOUNT_SID=${TWILIO_SID}
Environment=TWILIO_AUTH_TOKEN=${TWILIO_TOKEN}
Environment=TWILIO_FROM_NUMBER=${TWILIO_FROM}
Environment=ALERT_TO_PHONE=${ALERT_TO}"
fi

sudo tee /etc/systemd/system/${SERVICE_NAME}.service > /dev/null << SVCEOF
[Unit]
Description=options_trader v${VERSION} — ${INSTRUMENT} 0DTE bot
After=network.target

[Service]
Type=simple
User=${USER}
WorkingDirectory=${INSTALL_DIR}
${ENV_BLOCK}
Environment=OPTIONSBOT_SERVICE=${SERVICE_NAME}
ExecStartPre=/bin/bash -c 'touch ${INSTALL_DIR}/bot.log ${INSTALL_DIR}/trades.db && chown ${USER}:${USER} ${INSTALL_DIR}/bot.log ${INSTALL_DIR}/trades.db'
ExecStart=${VENV}/bin/python main.py --service
Restart=always
RestartSec=30
StandardOutput=journal
StandardError=journal
SyslogIdentifier=${SERVICE_NAME}

[Install]
WantedBy=multi-user.target
SVCEOF

sudo chmod 600 /etc/systemd/system/${SERVICE_NAME}.service
sudo systemctl daemon-reload
sudo systemctl enable ${SERVICE_NAME}
print_ok "Service configured and enabled."

# ─── PREPARE AND START ────────────────────────────────────────────────────────
touch "$INSTALL_DIR/bot.log" "$INSTALL_DIR/trades.db"
chown "${USER}:${USER}" "$INSTALL_DIR/bot.log" "$INSTALL_DIR/trades.db"

print_info "Starting bot service..."
sudo systemctl start ${SERVICE_NAME}
sleep 5

# Verify it started
SVC_STATUS=$(systemctl is-active ${SERVICE_NAME})
if [ "$SVC_STATUS" = "active" ]; then
    echo ""
    echo -e "${BOLD}${CYAN}╔══════════════════════════════════════════════════════╗${RESET}"
    echo -e "${BOLD}${GREEN}║          ✅  Setup Complete — Bot Running!          ║${RESET}"
    echo -e "${BOLD}${CYAN}╚══════════════════════════════════════════════════════╝${RESET}"
    echo ""
    echo -e "  Instrument:   ${BOLD}${INSTRUMENT}${RESET}"
    echo -e "  Risk/trade:   ${BOLD}\$${RISK_USD}${RESET}"
    echo -e "  Mode:         ${BOLD}$([ "$PAPER_TRADING" = "True" ] && echo "📄 PAPER" || echo "🔴 LIVE")${RESET}"
    echo -e "  TT Account:   ${BOLD}${TT_ACCOUNT_NUMBER}${RESET}"
    echo -e "  SMS:          ${BOLD}$([ -n "$TWILIO_SID" ] && echo "✓ enabled" || echo "— disabled")${RESET}"
    echo -e "  Service:      ${GREEN}● ACTIVE${RESET}"
    echo ""
    echo -e "  ${BOLD}Commands:${RESET}"
    echo -e "    ${CYAN}python status.py${RESET}                  — live status"
    echo -e "    ${CYAN}python query.py${RESET}                   — session dashboard"
    echo -e "    ${CYAN}journalctl -u ${SERVICE_NAME} -f${RESET}        — live logs"
    echo -e "    ${CYAN}sudo systemctl stop ${SERVICE_NAME}${RESET}    — stop bot"
    echo -e "    ${CYAN}./configure.sh${RESET}                    — change settings"
    echo ""
    # Show live status immediately
    source "${VENV}/bin/activate"
    python status.py
else
    echo ""
    echo -e "${BOLD}${CYAN}╔══════════════════════════════════════════════════════╗${RESET}"
    echo -e "${BOLD}${YELLOW}║          ⚠️   Setup Complete — Start Failed         ║${RESET}"
    echo -e "${BOLD}${CYAN}╚══════════════════════════════════════════════════════╝${RESET}"
    echo ""
    echo -e "  ${RED}Service did not start. Check the error:${RESET}"
    echo -e "    ${CYAN}journalctl -u ${SERVICE_NAME} -n 30 --no-pager${RESET}"
    echo ""
    journalctl -u ${SERVICE_NAME} -n 20 --no-pager
fi
