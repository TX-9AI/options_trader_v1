@echo off
:: =============================================================================
:: install.bat — Windows launcher for options-trader EC2 setup
:: Place in C:\options_trader\ alongside your .pem key and bot files.
:: Double-click to run.
:: =============================================================================

setlocal EnableDelayedExpansion

echo.
echo ============================================================
echo   options_trader v1.1  --  EC2 Deployment
echo ============================================================
echo.
echo   You can deploy to multiple EC2 instances in sequence.
echo   Each instance gets its own instrument (QQQ / SPY / SPX).
echo.

:DEPLOY_LOOP

echo ------------------------------------------------------------
echo   New Deployment
echo ------------------------------------------------------------
echo.

:: ─── PEM key ──────────────────────────────────────────────────────────────────
set /p PEM_FILE="  PEM key path (e.g. C:\options_trader\tx-9.pem): "
if not exist "!PEM_FILE!" (
    echo   ERROR: PEM file not found: !PEM_FILE!
    goto DEPLOY_LOOP
)

:: ─── EC2 IP ───────────────────────────────────────────────────────────────────
set /p EC2_IP="  EC2 Public IP: "
if "!EC2_IP!"=="" (
    echo   ERROR: EC2 IP cannot be empty.
    goto DEPLOY_LOOP
)

:: ─── Instrument ───────────────────────────────────────────────────────────────
echo.
echo   Instrument:
echo     1. QQQ  (Nasdaq ETF,     $1 strike increments)
echo     2. SPY  (S^&P 500 ETF,   $1 strike increments)
echo     3. SPX  (S^&P 500 Index,  $5 strike increments)
echo.
set /p INST_CHOICE="  Select [1/2/3, default=1]: "
if "!INST_CHOICE!"=="2" (set INSTRUMENT=SPY) else if "!INST_CHOICE!"=="3" (set INSTRUMENT=SPX) else (set INSTRUMENT=QQQ)
echo   Instrument: !INSTRUMENT!

:: ─── Risk per trade ───────────────────────────────────────────────────────────
echo.
set /p RISK_INPUT="  Risk per trade in $ [default=200]: "
if "!RISK_INPUT!"=="" (set RISK_USD=200) else (set RISK_USD=!RISK_INPUT!)
echo   Risk per trade: $!RISK_USD!

:: ─── Paper vs live ────────────────────────────────────────────────────────────
echo.
echo   Trading mode:
echo     P = Paper  (safe default, no real orders)
echo     L = Live   (real money)
echo.
set /p MODE_INPUT="  Mode [P/L, default=P]: "
if /i "!MODE_INPUT!"=="L" (
    echo.
    echo   WARNING: LIVE TRADING -- real money will be at risk.
    set /p LIVE_CONFIRM="  Type YES to confirm live trading: "
    if "!LIVE_CONFIRM!"=="YES" (
        set PAPER=False
        set PAPER_LABEL=LIVE
        echo   LIVE MODE confirmed.
    ) else (
        set PAPER=True
        set PAPER_LABEL=PAPER
        echo   Defaulting to PAPER mode.
    )
) else (
    set PAPER=True
    set PAPER_LABEL=PAPER
    echo   PAPER mode ^(safe default^).
)

:: ─── EC2 username ─────────────────────────────────────────────────────────────
echo.
set /p EC2_USER_INPUT="  EC2 username [default=ubuntu]: "
if "!EC2_USER_INPUT!"=="" (set EC2_USER=ubuntu) else (set EC2_USER=!EC2_USER_INPUT!)

:: ─── Confirm ──────────────────────────────────────────────────────────────────
echo.
echo   ============================================================
echo   Deployment Summary
echo   ============================================================
echo   EC2 IP:        !EC2_IP!
echo   PEM:           !PEM_FILE!
echo   Instrument:    !INSTRUMENT!
echo   Risk/trade:    $!RISK_USD!
echo   Mode:          !PAPER_LABEL!
echo   ============================================================
echo.
set /p GO="  Deploy now? [Y/n, default=Y]: "
if /i "!GO!"=="n" (
    echo   Skipping this deployment.
    goto ANOTHER
)

:: ─── Fix PEM permissions ──────────────────────────────────────────────────────
echo.
echo [1/4] Fixing PEM permissions...
icacls "!PEM_FILE!" /inheritance:r >nul 2>&1
icacls "!PEM_FILE!" /grant:r "%USERNAME%:(R)" >nul 2>&1
icacls "!PEM_FILE!" /remove "BUILTIN\Users" >nul 2>&1
icacls "!PEM_FILE!" /remove "Everyone" >nul 2>&1
icacls "!PEM_FILE!" /remove "NT AUTHORITY\Authenticated Users" >nul 2>&1
icacls "!PEM_FILE!" /remove "NT AUTHORITY\NETWORK" >nul 2>&1
echo   PEM permissions set.

:: ─── Create remote staging directory ─────────────────────────────────────────
echo.
echo [2/4] Connecting to EC2...
ssh -i "!PEM_FILE!" -o StrictHostKeyChecking=no !EC2_USER!@!EC2_IP! "mkdir -p ~/options-trader-deploy"
if !ERRORLEVEL! neq 0 (
    echo   ERROR: Could not connect to EC2. Check IP, PEM, and security group ^(port 22^).
    pause
    goto ANOTHER
)
echo   Connected to !EC2_IP!

:: ─── Copy files to EC2 with visible progress ─────────────────────────────────
echo.
echo [3/4] Copying project files to EC2...
echo.

:: Copy subdirectories one at a time so each shows on screen
for /d %%D in ("%~dp0*") do (
    if /i not "%%~nxD"==".git" (
        if /i not "%%~nxD"=="venv" (
            if /i not "%%~nxD"=="__pycache__" (
                if /i not "%%~nxD"=="options-trader-deploy" (
                    echo   Uploading %%~nxD\...
                    scp -r -i "!PEM_FILE!" -o StrictHostKeyChecking=no "%%D" !EC2_USER!@!EC2_IP!:~/options-trader-deploy/
                )
            )
        )
    )
)

:: Copy root-level files individually so each filename is visible
for %%F in ("%~dp0*") do (
    if /i not "%%~xF"==".pem" (
        if /i not "%%~xF"==".bat" (
            if /i not "%%~xF"==".gz" (
                if exist "%%F" if not "%%~aF"=="d" (
                    echo   Uploading %%~nxF...
                    scp -i "!PEM_FILE!" -o StrictHostKeyChecking=no "%%F" !EC2_USER!@!EC2_IP!:~/options-trader-deploy/
                )
            )
        )
    )
)

echo.
echo   All files uploaded.

:: ─── SSH: run setup_ec2.sh ────────────────────────────────────────────────────
echo.
echo [4/4] Running setup on EC2...
echo   ^(You will be prompted for TastyTrade credentials and optional Twilio^)
echo   ^(Paste values with right-click or Ctrl+V^)
echo.

ssh -t -i "!PEM_FILE!" -o StrictHostKeyChecking=no !EC2_USER!@!EC2_IP! ^
    "chmod +x ~/options-trader-deploy/setup_ec2.sh && OT_INSTRUMENT=!INSTRUMENT! OT_RISK_USD=!RISK_USD! OT_PAPER_TRADING=!PAPER! ~/options-trader-deploy/setup_ec2.sh"

echo.
echo   ============================================================
echo   Deployed: !INSTRUMENT! to !EC2_IP!
echo.
echo   SSH in anytime:
echo     ssh -i "!PEM_FILE!" !EC2_USER!@!EC2_IP!
echo.
echo   Then run:
echo     sudo systemctl start optionsbot
echo     python status.py
echo     python query.py
echo   ============================================================
echo.

:ANOTHER
echo.
set /p ANOTHER_INPUT="  Deploy to another EC2 instance? [Y/n, default=n]: "
if /i "!ANOTHER_INPUT!"=="Y" goto DEPLOY_LOOP

echo.
echo   All deployments complete.
echo.
pause
