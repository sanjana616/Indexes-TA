"""
scheduler.py — Run src.main every minute during Indian market hours (Mon-Fri 09:15-15:30 IST).
Usage: python scheduler.py
"""
import time
import subprocess
import sys
from datetime import datetime
import pytz

IST = pytz.timezone("Asia/Kolkata")

def is_market_open():
    now = datetime.now(IST)
    if now.weekday() >= 5:
        return False
    hm = now.hour * 100 + now.minute
    return 915 <= hm <= 1530

def run_pipeline():

    start = time.time()

    print(
        f"[{datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S IST')}] Running pipeline..."
    )

    result = subprocess.run(
        [sys.executable, "-m", "src.main"],
        capture_output=False
    )

    duration = round(time.time() - start, 2)

    print(f"Exit code: {result.returncode}")
    print(f"Duration: {duration} seconds")

print("Scheduler started. Waiting for market hours (Mon-Fri 09:15-15:30 IST)...")

while True:
    now = datetime.now(IST)
    if is_market_open():
        run_pipeline()
        # sleep until next minute boundary
        seconds_to_next = 60 - now.second
        time.sleep(seconds_to_next)
    else:
        hm = now.hour * 100 + now.minute
        if hm < 915:
            print(f"[{now.strftime('%H:%M IST')}] Market not open yet. Waiting...")
        elif hm > 1530:
            print(f"[{now.strftime('%H:%M IST')}] Market closed for today.")
        time.sleep(60)
