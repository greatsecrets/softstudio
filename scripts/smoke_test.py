"""End-to-end smoke test: submit a Flux image job and a short LTX video job
through the gateway, poll until done, print the asset URLs.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request

GATEWAY = "http://127.0.0.1:8000"


def post(path: str, body: dict) -> dict:
    req = urllib.request.Request(
        GATEWAY + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def get(path: str) -> dict:
    with urllib.request.urlopen(GATEWAY + path, timeout=30) as r:
        return json.loads(r.read())


def wait(job_id: str, label: str, max_seconds: int = 600) -> dict:
    print(f"[{label}] waiting on {job_id}...")
    start = time.time()
    last_status = None
    while time.time() - start < max_seconds:
        job = get(f"/api/jobs/{job_id}")
        if job["status"] != last_status:
            print(f"[{label}] status -> {job['status']}")
            last_status = job["status"]
        if job["status"] == "done":
            return job
        if job["status"] == "error":
            raise RuntimeError(f"{label} failed: {job['error']}")
        time.sleep(2)
    raise TimeoutError(f"{label} did not finish in {max_seconds}s")


def main() -> int:
    print("=== T2I (Flux schnell) ===")
    res = post(
        "/api/generate",
        {
            "prompt": "a cinematic photo of a violet neon mountain at dusk, ultra detailed",
            "mode": "image",
            "width": 1024,
            "height": 1024,
        },
    )
    print(res)
    job = wait(res["id"], "T2I")
    print("[T2I] outputs:", job["outputs"])

    print()
    print("=== T2V (LTX 0.9.5, ~3s) ===")
    res = post(
        "/api/generate",
        {
            "prompt": "a slow-motion shot of golden silk falling through dark water",
            "mode": "video",
            "width": 768,
            "height": 512,
            "length": 73,
        },
    )
    print(res)
    job = wait(res["id"], "T2V", max_seconds=900)
    print("[T2V] outputs:", job["outputs"])

    print("\nAll smoke tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
