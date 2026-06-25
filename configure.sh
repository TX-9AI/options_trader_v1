#!/usr/bin/env bash
# ============================================================
#  options_trader v1.0  —  Live Configuration Manager
#
#  Run this anytime to view or change bot settings.
#  Changes take effect on the NEXT bot start — the bot is
#  never restarted automatically to avoid mid-session surprises.
#
#  Usage:
#    ./configure.sh          — interactive menu
#    ./configure.sh --show   — print current config and exit
# ============================================================

SERVICE_NAME="optionsbot"
BOT_DIR="$HOME/options-trader"
UNIT_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

# ── Colours ──────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

print_banner() {
    echo ""
    echo -e "${BOLD}${CYAN}============================================================${RESET}"
    echo -e "${BOLD}${CYAN}  options_trader  —  Configuration Manager${RESET}"
    echo -e "${BOLD}${CYAN}============================================================${RESET}"
    echo ""
}

print_ok()   { echo -e "  ${GREEN}✓${RESET}   $1"; }
print_warn() { echo -e "  ${YELLOW}⚠${RESET}   $1"; }
print_info() { echo -e "  ${CYAN}→${RESET}  $1"; }
ask()        { read -p "    $1: " "$2"; }
ask_secret() { read -s -p "    $1: " "$2"; echo ""; }
ask_yn()     {
    while true; do
        read -p "    $1 [y/n]: " yn
        case "$yn" in [Yy]) return 0;; [Nn]) return 1;; esac
    done
}

# ── Read a single Environment= value from the unit file ──────
get_env() {
    # $1 = variable name (e.g. OT_INSTRUMENT)
    sudo grep -oP "(?<=Environment=${1}=).*" "$UNIT_FILE" 2>/dev/null | tail -1 || echo ""
}

# ── Update or add an Environment= line in the unit file ──────
set_env() {
    local key="$1" val="$2"
    if sudo grep -q "Environment=${key}=" "$UNIT_FILE" 2>/dev/null; then
        sudo sed -i "s|Environment=${key}=.*|Environment=${key}=${val}|" "$UNIT_FILE"
    else
        # Add before the ExecStartPre line
        sudo sed -i "/ExecStartPre=/i Environment=${key}=${val}" "$UNIT_FILE"
    fi
}

reload_daemon() {
    sudo systemctl daemon-reload
}

bot_is_running() {
    systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null
}

# ──────────────────────────────────────────────────────────────
# SHOW CURRENT CONFIG
# ──────────────────────────────────────────────────────────────
show_config() {
    local instrument risk paper account twilio_on

    if [[ ! -f "$UNIT_FILE" ]]; then
        echo -e "  ${RED}Service unit not found.${RESET}"
        echo -e "  Run setup_ec2.sh first to install the bot."
        return 1
    fi

    instrument=$(get_env "OT_INSTRUMENT")
    risk=$(get_env "OT_RISK_USD")
    paper=$(get_env "OT_PAPER_TRADING")
    account=$(get_env "TT_ACCOUNT_NUMBER")
    twilio_on=$(get_env "TWILIO_ACCOUNT_SID")

    local mode_label
    if [[ "$paper" == "False" ]]; then
        mode_label="${RED}${BOLD}🔴 LIVE — real money${RESET}"
    else
        mode_label="${GREEN}📄 PAPER — simulated fills${RESET}"
    fi

    local status_label
    if bot_is_running; then
        status_label="${GREEN}● running${RESET}"
    else
        status_label="${YELLOW}○ stopped${RESET}"
    fi

    echo -e "  ${BOLD}Current Configuration${RESET}"
    echo -e "  ─────────────────────────────────────────"
    echo -e "  Bot status:     $(echo -e $status_label)"
    echo -e "  Instrument:     ${BOLD}${instrument:-not set}${RESET}"
    echo -e "  Risk per trade: ${BOLD}\$${risk:-not set}${RESET}"
    echo -e "  Trading mode:   $(echo -e $mode_label)"
    echo -e "  TT Account:     ${BOLD}${account:-not set}${RESET}"
    echo -e "  SMS alerts:     ${BOLD}$([ -n "$twilio_on" ] && echo "✓ enabled" || echo "— disabled")${RESET}"
    echo -e "  ─────────────────────────────────────────"
    echo ""

    if bot_is_running; then
        print_warn "Bot is currently running. Changes take effect on next start."
    fi
}

# ──────────────────────────────────────────────────────────────
# MENU ACTIONS
# ──────────────────────────────────────────────────────────────

change_instrument() {
    local current
    current=$(get_env "OT_INSTRUMENT")
    echo ""
    echo -e "  Current instrument: ${BOLD}${current}${RESET}"
    echo ""
    echo -e "  ${BOLD}1. QQQ${RESET}  —  Nasdaq-100 ETF   (\$1 strikes)"
    echo -e "  ${BOLD}2. SPY${RESET}  —  S&P 500 ETF      (\$1 strikes)"
    echo -e "  ${BOLD}3. SPX${RESET}  —  S&P 500 Index    (\$5 strikes)"
    echo ""
    while true; do
        read -p "    Select [1/2/3, or ENTER to keep ${current}]: " choice
        case "${choice:-0}" in
            0) print_info "Unchanged: ${current}"; return ;;
            1) NEW_INST="QQQ"; break ;;
            2) NEW_INST="SPY"; break ;;
            3) NEW_INST="SPX"; break ;;
            *) print_warn "Please enter 1, 2, or 3." ;;
        esac
    done
    set_env "OT_INSTRUMENT"  "$NEW_INST"
    set_env "OT_BOT_NAME"    "OptionsTrader-${NEW_INST}"
    reload_daemon
    print_ok "Instrument updated to ${BOLD}${NEW_INST}${RESET}."
}

change_risk() {
    local current
    current=$(get_env "OT_RISK_USD")
    echo ""
    echo -e "  Current risk per trade: ${BOLD}\$${current}${RESET}"
    echo ""
    while true; do
        read -p "    New risk per trade in \$ [ENTER to keep \$${current}]: " input
        if [[ -z "$input" ]]; then
            print_info "Unchanged: \$${current}"
            return
        fi
        if [[ "$input" =~ ^[0-9]+(\.[0-9]+)?$ ]] && (( $(echo "$input > 0" | bc -l) )); then
            set_env "OT_RISK_USD" "$input"
            reload_daemon
            print_ok "Risk per trade updated to ${BOLD}\$$input${RESET}."
            return
        fi
        print_warn "Please enter a positive number (e.g. 200 or 150.50)."
    done
}

change_mode() {
    local current
    current=$(get_env "OT_PAPER_TRADING")
    echo ""
    if [[ "$current" == "False" ]]; then
        echo -e "  Current mode: ${RED}${BOLD}🔴 LIVE${RESET}"
        echo ""
        if ask_yn "Switch to PAPER mode?"; then
            set_env "OT_PAPER_TRADING" "True"
            reload_daemon
            print_ok "Switched to ${BOLD}📄 PAPER mode${RESET}."
        else
            print_info "Unchanged: LIVE."
        fi
    else
        echo -e "  Current mode: ${GREEN}📄 PAPER${RESET}"
        echo ""
        print_warn "You are about to enable LIVE TRADING."
        print_warn "Real orders will be placed with real money."
        echo ""
        read -p "    Type  LIVE  to confirm: " confirm
        if [[ "$confirm" == "LIVE" ]]; then
            set_env "OT_PAPER_TRADING" "False"
            reload_daemon
            print_ok "Switched to ${RED}${BOLD}🔴 LIVE mode${RESET}."
        else
            print_info "Confirmation not received — mode unchanged."
        fi
    fi
}

change_tt_credentials() {
    echo ""
    echo -e "  Update your TastyTrade OAuth credentials."
    echo -e "  ${CYAN}Leave blank and press ENTER to keep the current value.${RESET}"
    echo ""

    local current_secret current_token current_account
    current_secret=$(get_env "TT_CLIENT_SECRET")
    current_token=$(get_env "TT_REFRESH_TOKEN")
    current_account=$(get_env "TT_ACCOUNT_NUMBER")

    read -s -p "    New Client Secret  [ENTER to keep current]: " new_secret; echo ""
    read -s -p "    New Refresh Token  [ENTER to keep current]: " new_token;  echo ""
    read -p    "    Account Number     [ENTER to keep ${current_account}]: " new_account

    local changed=false
    if [[ -n "$new_secret" ]]; then
        set_env "TT_CLIENT_SECRET"  "$new_secret";  changed=true; fi
    if [[ -n "$new_token" ]]; then
        set_env "TT_REFRESH_TOKEN"  "$new_token";   changed=true; fi
    if [[ -n "$new_account" ]]; then
        set_env "TT_ACCOUNT_NUMBER" "$new_account"; changed=true; fi

    if [[ "$changed" == "true" ]]; then
        reload_daemon
        print_ok "TastyTrade credentials updated."
    else
        print_info "No credentials changed."
    fi
}

change_twilio() {
    local current_sid
    current_sid=$(get_env "TWILIO_ACCOUNT_SID")
    echo ""

    if [[ -n "$current_sid" ]]; then
        echo -e "  SMS alerts are currently ${GREEN}enabled${RESET}."
        echo ""
        echo -e "  ${BOLD}1.${RESET} Update SMS settings"
        echo -e "  ${BOLD}2.${RESET} Disable SMS alerts"
        echo -e "  ${BOLD}3.${RESET} Cancel"
        echo ""
        read -p "    Select [1/2/3]: " sms_choice
        case "$sms_choice" in
            2)
                # Remove Twilio lines from unit
                sudo sed -i '/Environment=TWILIO_/d' "$UNIT_FILE"
                sudo sed -i '/Environment=ALERT_TO_PHONE=/d' "$UNIT_FILE"
                reload_daemon
                print_ok "SMS alerts disabled."
                return ;;
            3) print_info "Cancelled."; return ;;
        esac
    else
        echo -e "  SMS alerts are currently ${YELLOW}disabled${RESET}."
        echo ""
        if ! ask_yn "Enable SMS alerts?"; then
            print_info "No change."
            return
        fi
    fi

    echo ""
    echo -e "  ${CYAN}Find these values at console.twilio.com → Account Info${RESET}"
    echo ""

    local sid token from_num to_num
    while true; do
        ask "Twilio Account SID (starts with AC)" sid
        [[ "$sid" == AC* ]] && break
        print_warn "SID should start with AC."
    done
    while true; do
        ask_secret "Twilio Auth Token" token
        [[ -n "$token" ]] && break
        print_warn "Cannot be empty."
    done
    while true; do
        ask "Twilio 'From' number  (e.g. +15005550006)" from_num
        [[ "$from_num" == +* ]] && break
        print_warn "Must start with + and country code."
    done
    while true; do
        ask "Your mobile number    (e.g. +18135550000)" to_num
        [[ "$to_num" == +* ]] && break
        print_warn "Must start with + and country code."
    done

    # Remove any existing Twilio lines first, then add fresh
    sudo sed -i '/Environment=TWILIO_/d' "$UNIT_FILE"
    sudo sed -i '/Environment=ALERT_TO_PHONE=/d' "$UNIT_FILE"

    set_env "TWILIO_ACCOUNT_SID"  "$sid"
    set_env "TWILIO_AUTH_TOKEN"   "$token"
    set_env "TWILIO_FROM_NUMBER"  "$from_num"
    set_env "ALERT_TO_PHONE"      "$to_num"
    reload_daemon
    print_ok "SMS alerts configured."
}

restart_prompt() {
    echo ""
    if bot_is_running; then
        print_warn "The bot is currently running with the OLD settings."
        echo ""
        if ask_yn "Restart now to apply changes?"; then
            sudo systemctl restart "$SERVICE_NAME"
            sleep 1
            if bot_is_running; then
                print_ok "Bot restarted successfully with new settings."
            else
                print_warn "Bot may not have started — check: journalctl -u ${SERVICE_NAME} -f"
            fi
        else
            print_info "Changes will apply on the next manual start."
        fi
    else
        print_info "Start the bot when ready:  sudo systemctl start ${SERVICE_NAME}"
    fi
}

# ──────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────

# --show flag: print config and exit
if [[ "${1:-}" == "--show" ]]; then
    print_banner
    show_config
    exit 0
fi

# Check unit file exists
if [[ ! -f "$UNIT_FILE" ]]; then
    print_banner
    echo -e "  ${RED}No service unit found at ${UNIT_FILE}${RESET}"
    echo -e "  Run setup_ec2.sh first to install and configure the bot."
    echo ""
    exit 1
fi

print_banner
show_config

CHANGED=false
while true; do
    echo -e "  ${BOLD}What would you like to change?${RESET}"
    echo ""
    echo -e "  ${BOLD}1.${RESET}  Instrument          (currently: $(get_env OT_INSTRUMENT))"
    echo -e "  ${BOLD}2.${RESET}  Risk per trade      (currently: \$$(get_env OT_RISK_USD))"
    echo -e "  ${BOLD}3.${RESET}  Paper / Live mode   (currently: $([ "$(get_env OT_PAPER_TRADING)" = "False" ] && echo "🔴 LIVE" || echo "📄 PAPER"))"
    echo -e "  ${BOLD}4.${RESET}  TastyTrade credentials"
    echo -e "  ${BOLD}5.${RESET}  SMS alert settings"
    echo -e "  ${BOLD}6.${RESET}  Done"
    echo ""
    read -p "    Select [1-6]: " menu_choice

    case "$menu_choice" in
        1) change_instrument; CHANGED=true ;;
        2) change_risk;       CHANGED=true ;;
        3) change_mode;       CHANGED=true ;;
        4) change_tt_credentials; CHANGED=true ;;
        5) change_twilio;    CHANGED=true ;;
        6) break ;;
        *) print_warn "Please enter a number between 1 and 6." ;;
    esac
    echo ""
done

if [[ "$CHANGED" == "true" ]]; then
    echo ""
    show_config
    restart_prompt
fi

echo ""
