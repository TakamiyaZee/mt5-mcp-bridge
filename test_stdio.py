#!/usr/bin/env python3
import subprocess, json, sys, time, os

server = os.path.expanduser("~/.hermes/mcp-servers/mt5-mcp-server/server.py")

proc = subprocess.Popen(
    [sys.executable, server],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
)

init_req = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": 1,
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0.1"}
    }
}

proc.stdin.write((json.dumps(init_req) + "\n").encode())
proc.stdin.flush()
time.sleep(2)

proc.stdin.close()
stdout, stderr = proc.communicate(timeout=15)
print("=== STDOUT ===")
print(stdout.decode()[:3000])
if stderr:
    sys.stderr.write("=== STDERR ===\n")
    sys.stderr.write(stderr.decode()[:1000])
