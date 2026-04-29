"""Submit a job via Next.js rewrite (port 3000) end-to-end."""
import json, sys, time, urllib.request

BASE = "http://127.0.0.1:3000"

def post(path, body):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    return json.loads(urllib.request.urlopen(req, timeout=30).read())

def get(path):
    return json.loads(urllib.request.urlopen(BASE + path, timeout=30).read())

print("=== Submitting via :3000 rewrite ===")
res = post("/api/generate", {
    "prompt": "a cyberpunk fox in neon rain, photorealistic",
    "mode": "image", "width": 1024, "height": 1024,
})
print(res)
job_id = res["id"]
last = None
for _ in range(120):
    j = get(f"/api/jobs/{job_id}")
    if j["status"] != last:
        print(f"  -> {j['status']}")
        last = j["status"]
    if j["status"] == "done":
        print("outputs:", j["outputs"])
        # Verify asset is fetchable through :3000
        url = BASE + j["outputs"][0]["url"]
        with urllib.request.urlopen(url, timeout=10) as r:
            ct = r.headers.get("content-type")
            data = r.read()
            print(f"asset fetch: HTTP {r.status} {ct} bytes={len(data)}")
        sys.exit(0)
    if j["status"] == "error":
        print("ERROR:", j["error"])
        sys.exit(1)
    time.sleep(2)
print("timeout")
sys.exit(1)
