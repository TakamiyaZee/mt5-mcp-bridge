#!/usr/bin/env python3
"""Quick test: verify server.py connects to bridge and account info works."""
import sys, os, subprocess, time, json
from pathlib import Path

server = str(Path(__file__).parent / "server.py")

# Start server
proc = subprocess.Popen(
    [sys.executable, server],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
)

# Wait for lifespan to connect to bridge
time.sleep(3)

# Send tools/list via JSON-RPC
req = json.dumps({"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}})
proc.stdin.write((req + "\n").encode())
proc.stdin.flush()
time.sleep(2)

# Try to read response
import select
fl = select.poll()
fl.register(proc.stdout, select.POLLIN)
if fl.poll(5000):
    out = proc.stdout.read1(5000).decode()
    print("TOOLS:", out[:2000])
else:
    print("No response from server - checking stderr...")
    _, stderr = proc.communicate(timeout=5)
    print("STDERR:", stderr.decode()[:2000])

proc.terminate()
