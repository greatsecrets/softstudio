import json, urllib.request, time

req = urllib.request.Request(
    "http://127.0.0.1:8000/api/generate",
    data=json.dumps({
        "prompt": "portrait of a woman with red hair, sharp focus, natural light",
        "mode": "image",
        "model": "realvisxl",
        "width": 1024,
        "height": 1024,
    }).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)
res = json.loads(urllib.request.urlopen(req).read())
print("submitted:", res)

start = time.time()
while time.time() - start < 180:
    j = json.loads(urllib.request.urlopen(f"http://127.0.0.1:8000/api/jobs/{res['id']}").read())
    print(f"  [{int(time.time()-start):>3}s] {j['status']}")
    if j["status"] == "done":
        print("output:", j["outputs"][0]["url"])
        print("filename:", j["outputs"][0]["filename"])
        break
    if j["status"] == "error":
        print("ERROR:", j["error"])
        break
    time.sleep(2)
