"""Submit a video generation through the tunnel and wait for it."""
import json, sys, time, urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
PROMPT = sys.argv[2] if len(sys.argv) > 2 else "a sleek black panther stalking through a neon-lit jungle, slow-motion, cinematic"
LENGTH = int(sys.argv[3]) if len(sys.argv) > 3 else 97  # ~4 sec at 25fps

def post(path, body):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    return json.loads(urllib.request.urlopen(req, timeout=30).read())

def get(path):
    return json.loads(urllib.request.urlopen(BASE + path, timeout=30).read())

print(f"BASE   = {BASE}")
print(f"PROMPT = {PROMPT}")
print(f"LENGTH = {LENGTH} frames")

res = post("/api/generate", {
    "prompt": PROMPT, "mode": "video",
    "width": 1024, "height": 576, "length": LENGTH,
})
job_id = res["id"]
print(f"job: {job_id}")

start = time.time()
last = None
while time.time() - start < 900:
    j = get(f"/api/jobs/{job_id}")
    if j["status"] != last:
        elapsed = int(time.time() - start)
        print(f"  [{elapsed:>3}s] {j['status']}")
        last = j["status"]
    if j["status"] == "done":
        url = j["outputs"][0]["url"]
        print(f"\nDONE — open {BASE}{url}")
        sys.exit(0)
    if j["status"] == "error":
        print("\nERROR:", j["error"])
        sys.exit(1)
    time.sleep(3)
print("timeout")
sys.exit(1)
