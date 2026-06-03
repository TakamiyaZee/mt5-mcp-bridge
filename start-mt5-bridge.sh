#!/bin/bash
# Start MT5 bridge (Wine Python + RPyC) - single xvfb session
# Prerequisites: Wine Python 3.11, MetaTrader 5 installed under Wine
set -e

export WINEPREFIX="$HOME/.mt5"
MT5_BRIDGE_PORT="${MT5_BRIDGE_PORT:-8001}"

# Kill stale RPyC bridge only (NOT terminal)
pkill -f "ThreadedServer.*${MT5_BRIDGE_PORT}" 2>/dev/null || true
sleep 1

# Create inner wrapper script
WRAPPER="/tmp/mt5_bridge_wrapper.sh"
cat > "$WRAPPER" << 'INNER'
#!/bin/bash
export WINEPREFIX="$HOME/.mt5"

# Start MT5 terminal
MT5_EXE="$HOME/.mt5/drive_c/Program Files/MetaTrader 5/terminal64.exe"
if [ -f "$MT5_EXE" ]; then
  wine "$MT5_EXE" &
  TERM_PID=$!
  echo "Terminal started PID=$TERM_PID"
  sleep 12
fi

# Start Python bridge (connects to running terminal)
wine "C:\\Python311\\python.exe" -u -c "
import MetaTrader5 as mt5
import rpyc
from rpyc.utils.server import ThreadedServer
from rpyc.core import SlaveService
import sys, os

print('Initializing MT5...')
if not mt5.initialize():
    print('init failed:', mt5.last_error())
    sys.exit(1)

# Read credentials from environment (set these before running)
LOGIN = int(os.environ.get('MT5_LOGIN', '0'))
PASSWORD = os.environ.get('MT5_PASSWORD', '')
SERVER = os.environ.get('MT5_SERVER', '')

if LOGIN == 0:
    print('ERROR: Set MT5_LOGIN, MT5_PASSWORD, MT5_SERVER env vars')
    sys.exit(1)

print('Logging in...')
if not mt5.login(LOGIN, password=PASSWORD, server=SERVER):
    print('login failed:', mt5.last_error())
    sys.exit(1)

acc = mt5.account_info()
print('Logged in:', acc.login, 'balance:', acc.balance)

from rpyc.lib import setup_logger
setup_logger(0, None)
port = int(os.environ.get('MT5_BRIDGE_PORT', '8001'))
server = ThreadedServer(SlaveService, hostname='0.0.0.0', port=port)
print(f'Bridge ready on :{port}')
server.start()
"
INNER
chmod +x "$WRAPPER"

# Run everything in a single xvfb session
echo "Starting single xvfb session on port ${MT5_BRIDGE_PORT}..."
xvfb-run -a bash "$WRAPPER"
