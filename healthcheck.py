import time

_start = time.time()


def run_healthcheck() -> dict:
    return {"status": "healthy", "uptime_seconds": round(time.time() - _start, 2)}
