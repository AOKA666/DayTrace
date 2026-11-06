"""Crash test with a sleeping synthetic child; no desktop access."""
import os
from pathlib import Path
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))


def sleeper(connection,request):
    time.sleep(30)


if __name__=='__main__':
    from daytrace.content.coordinator import Worker
    worker=Worker({'source':'uia'},target=sleeper)
    print(worker.process.pid,flush=True)
    time.sleep(.3)
    os._exit(0)
