"""An explicit absolute cutoff for an authorized test window."""
from datetime import datetime
import time
import math

class DeadlineReached(Exception):
    pass

def parse_deadline(value):
    stamp=datetime.fromisoformat(value)
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError('--until requires an ISO timestamp with a timezone offset')
    return stamp.timestamp()

def ensure_time(until):
    if until is not None and time.time()>=until:
        raise DeadlineReached('Authorized test window ended')


def positive_minutes(value):
    minutes=float(value)
    if not math.isfinite(minutes) or minutes<=0:
        raise ValueError("--minutes must be a finite positive number")
    return minutes
