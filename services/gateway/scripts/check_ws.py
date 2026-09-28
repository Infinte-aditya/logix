"""Manual check: connect to the running gateway and print received alerts.

Usage (from repo root, with gateway + redis + mock publisher running):
    services/gateway/.venv/Scripts/python services/gateway/scripts/check_ws.py
    ... --count 2   # exit after N alerts instead of streaming until Ctrl+C
"""

import argparse
import asyncio
import sys

import websockets


async def main() -> int:
    parser = argparse.ArgumentParser(description="print alerts from the gateway")
    parser.add_argument(
        "--count",
        type=int,
        default=0,
        help="exit after N alerts (0 = stream until Ctrl+C)",
    )
    args = parser.parse_args()
    async with websockets.connect("ws://localhost:8000/ws") as ws:
        print("connected; waiting for alerts (Ctrl+C to stop)...", flush=True)
        seen = 0
        while True:
            print(await ws.recv(), flush=True)
            seen += 1
            if args.count and seen >= args.count:
                return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        sys.exit(0)
