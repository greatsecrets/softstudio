"""Softstudio gateway — FastAPI in front of ComfyUI.

Endpoints:
    POST /api/generate      kick off image or video job
    GET  /api/jobs/{id}     poll job status + output URLs
    GET  /api/jobs          list recent jobs
    POST /api/upload        upload image for image-to-video
    GET  /assets/{...}      serve generated outputs
    GET  /api/health        ComfyUI + GPU status

Runs on :8000. Talks to ComfyUI on :8188.
"""
from __future__ import annotations

import asyncio
import json
import re
import sqlite3
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

import httpx
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Paths and config
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
COMFY_ROOT = ROOT / "ComfyUI"
COMFY_OUTPUT = COMFY_ROOT / "output"
COMFY_INPUT = COMFY_ROOT / "input"
WORKFLOWS = ROOT / "workflows"
DB_PATH = ROOT / "softstudio.db"

COMFY_BASE = "http://127.0.0.1:8188"
CLIENT_ID = f"softstudio-{uuid.uuid4().hex[:8]}"

WORKFLOW_FILES = {
    "image": WORKFLOWS / "flux_schnell_t2i.json",
    "video": WORKFLOWS / "ltx_t2v.json",
    "i2v": WORKFLOWS / "ltx_i2v.json",
}

# Per-model overrides for image generation. The "image" mode picks one of
# these based on req.model. Each entry says which workflow file to render
# and a default negative prompt (Flux schnell ignores negatives, RealVisXL
# uses them).
IMAGE_MODELS: dict[str, dict] = {
    "flux-schnell": {
        "workflow": WORKFLOWS / "flux_schnell_t2i.json",
        "negative": "",
        "label": "Flux Schnell",
        "notes": "Fast, 4 steps, filtered training data",
    },
    "realvisxl": {
        "workflow": WORKFLOWS / "realvisxl_t2i.json",
        "negative": (
            "low quality, worst quality, blurry, jpeg artifacts, watermark, "
            "text, deformed, extra fingers, mutated hands, bad anatomy"
        ),
        "label": "RealVisXL V5.0",
        "notes": "Photorealistic, 28 steps, unfiltered",
    },
}
DEFAULT_IMAGE_MODEL = "flux-schnell"

# ---------------------------------------------------------------------------
# Database — minimal job ledger
# ---------------------------------------------------------------------------

def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                prompt_id TEXT,
                mode TEXT NOT NULL,
                prompt TEXT NOT NULL,
                params TEXT NOT NULL,
                status TEXT NOT NULL,
                outputs TEXT,
                error TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at DESC);
            """
        )


# ---------------------------------------------------------------------------
# Workflow rendering
# ---------------------------------------------------------------------------

def _json_escape(value: str) -> str:
    """Escape a value for safe substitution into a JSON string literal."""
    return json.dumps(value)[1:-1]


def render_workflow(template_path: Path, **fields: Any) -> dict:
    template = template_path.read_text(encoding="utf-8")

    def replace(match: re.Match) -> str:
        key = match.group(1)
        if key not in fields:
            raise KeyError(f"workflow placeholder {{{{ {key} }}}} has no value")
        value = fields[key]
        # Numeric placeholders are NOT wrapped in quotes in the template,
        # so substitute the raw repr. String placeholders ARE wrapped, so
        # we substitute the escaped string contents.
        if isinstance(value, str):
            return _json_escape(value)
        return json.dumps(value)

    rendered = re.sub(r"\{\{\s*(\w+)\s*\}\}", replace, template)
    return json.loads(rendered)


# ---------------------------------------------------------------------------
# ComfyUI client
# ---------------------------------------------------------------------------

class ComfyClient:
    def __init__(self, base: str = COMFY_BASE) -> None:
        self._client = httpx.AsyncClient(base_url=base, timeout=httpx.Timeout(60.0))

    async def close(self) -> None:
        await self._client.aclose()

    async def submit(self, workflow: dict) -> str:
        r = await self._client.post(
            "/prompt",
            json={"prompt": workflow, "client_id": CLIENT_ID},
        )
        if r.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"ComfyUI rejected workflow: {r.text}")
        return r.json()["prompt_id"]

    async def history(self, prompt_id: str) -> dict | None:
        r = await self._client.get(f"/history/{prompt_id}")
        r.raise_for_status()
        data = r.json()
        return data.get(prompt_id)

    async def queue(self) -> dict:
        r = await self._client.get("/queue")
        r.raise_for_status()
        return r.json()

    async def system_stats(self) -> dict:
        r = await self._client.get("/system_stats")
        r.raise_for_status()
        return r.json()

    async def upload_image(self, name: str, data: bytes, content_type: str) -> str:
        files = {"image": (name, data, content_type)}
        r = await self._client.post("/upload/image", files=files, data={"overwrite": "true"})
        if r.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"ComfyUI upload failed: {r.text}")
        return r.json().get("name", name)


comfy = ComfyClient()


# ---------------------------------------------------------------------------
# Job polling (single background loop)
# ---------------------------------------------------------------------------

async def _poll_loop() -> None:
    while True:
        try:
            with db() as conn:
                rows = conn.execute(
                    "SELECT id, prompt_id FROM jobs WHERE status IN ('queued','running') AND prompt_id IS NOT NULL"
                ).fetchall()
            for row in rows:
                history = await comfy.history(row["prompt_id"])
                if not history:
                    continue
                outputs = _collect_outputs(history)
                status = history.get("status", {})
                if status.get("status_str") == "error" or status.get("completed") is False and status.get("messages"):
                    err_msgs = [m for m in status.get("messages", []) if m and m[0] == "execution_error"]
                    if err_msgs:
                        err = json.dumps(err_msgs[0][1])
                        with db() as conn:
                            conn.execute(
                                "UPDATE jobs SET status='error', error=?, updated_at=? WHERE id=?",
                                (err, time.time(), row["id"]),
                            )
                        continue
                if outputs:
                    with db() as conn:
                        conn.execute(
                            "UPDATE jobs SET status='done', outputs=?, updated_at=? WHERE id=?",
                            (json.dumps(outputs), time.time(), row["id"]),
                        )
        except Exception as exc:  # noqa: BLE001 — loop must survive
            print(f"[poll] error: {exc}")
        await asyncio.sleep(1.0)


def _collect_outputs(history: dict) -> list[dict]:
    out: list[dict] = []
    for node_outputs in (history.get("outputs") or {}).values():
        for kind in ("images", "gifs"):
            for entry in node_outputs.get(kind, []) or []:
                filename = entry.get("filename")
                if not filename:
                    continue
                subfolder = entry.get("subfolder", "")
                rel = f"{subfolder}/{filename}" if subfolder else filename
                out.append(
                    {
                        "filename": filename,
                        "subfolder": subfolder,
                        "type": entry.get("type", "output"),
                        "url": f"/assets/{rel}",
                    }
                )
    return out


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    task = asyncio.create_task(_poll_loop())
    try:
        yield
    finally:
        task.cancel()
        await comfy.close()


app = FastAPI(title="Softstudio", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

Mode = Literal["image", "video", "i2v"]


class GenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)
    mode: Mode = "image"
    model: str | None = None  # for image mode; defaults to DEFAULT_IMAGE_MODEL
    width: int = 1024
    height: int = 1024
    seed: int | None = None
    enhance: bool = True
    # Video-only
    length: int = 97  # frames; LTX wants 8n+1
    image_name: str | None = None  # required for i2v


# ---------------------------------------------------------------------------
# Prompt enhancement — short prompts get a cinematic wrapper. Critical for
# LTX-Video, which was trained on long film-style captions and hallucinates
# anatomy when given terse prompts like "a woman drinking coffee".
# ---------------------------------------------------------------------------

VIDEO_NEGATIVE = (
    "low quality, worst quality, blurry, jittery, deformed, distorted, "
    "extra limbs, extra fingers, mutated hands, missing fingers, "
    "fused fingers, bad anatomy, malformed face, watermark, text, logo, "
    "static frame, frozen, unstable motion"
)

IMAGE_NEGATIVE = ""  # Flux schnell uses zeroed-out negative; we ignore this


def _strip_article(s: str) -> str:
    s = s.strip()
    for art in ("a ", "an ", "the "):
        if s.lower().startswith(art):
            return s[len(art):]
    return s


def enhance_prompt(raw: str, mode: str) -> str:
    """Expand short prompts. LTX-Video and Flux both reward literal scene
    description over style-stacked tag soup. The wrapper here adds *what the
    subject is doing*, not what the lens looks like.
    """
    raw = raw.strip()
    word_count = len(raw.split())
    if word_count >= 18:
        return raw

    subject = _strip_article(raw)

    if mode == "image":
        # Flux schnell handles short prompts well — only nudge a little.
        return f"{raw}, sharp focus, natural lighting, photorealistic, highly detailed"

    # Video — describe the scene as if writing a screenplay shot. Avoid
    # heavy bokeh/DOF terms which over-blur LTX outputs.
    return (
        f"{raw.capitalize()}. The scene shows {subject} captured in clear, "
        f"steady motion with natural realistic movement. Even, well-balanced "
        f"lighting reveals the subject in full clarity. The camera holds steady. "
        f"High detail, sharp focus, photorealistic, anatomically correct."
    )


class JobOut(BaseModel):
    id: str
    prompt_id: str | None
    mode: str
    prompt: str
    params: dict
    status: str
    outputs: list[dict]
    error: str | None
    created_at: float
    updated_at: float


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/models")
async def list_models():
    return {
        "image": [
            {"id": k, "label": v["label"], "notes": v["notes"]}
            for k, v in IMAGE_MODELS.items()
        ],
        "default_image": DEFAULT_IMAGE_MODEL,
    }


@app.get("/api/health")
async def health():
    try:
        stats = await comfy.system_stats()
        return {"ok": True, "comfy": stats}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


@app.post("/api/generate")
async def generate(req: GenerateRequest):
    if req.mode == "i2v" and not req.image_name:
        raise HTTPException(status_code=400, detail="image_name is required for i2v")

    job_id = uuid.uuid4().hex[:12]
    seed = req.seed if req.seed is not None else int(time.time() * 1000) & 0xFFFFFFFF
    final_prompt = enhance_prompt(req.prompt, req.mode) if req.enhance else req.prompt
    selected_model: str | None = None

    if req.mode == "image":
        selected_model = req.model or DEFAULT_IMAGE_MODEL
        if selected_model not in IMAGE_MODELS:
            raise HTTPException(
                status_code=400,
                detail=f"unknown model {selected_model!r}; choices: {list(IMAGE_MODELS)}",
            )
        cfg = IMAGE_MODELS[selected_model]
        wf = render_workflow(
            cfg["workflow"],
            prompt=final_prompt,
            negative=cfg["negative"],
            width=req.width,
            height=req.height,
            seed=seed,
            job_id=job_id,
        )
    elif req.mode == "video":
        wf = render_workflow(
            WORKFLOW_FILES["video"],
            prompt=final_prompt,
            negative=VIDEO_NEGATIVE,
            width=req.width,
            height=req.height,
            length=req.length,
            seed=seed,
            job_id=job_id,
        )
    else:  # i2v
        wf = render_workflow(
            WORKFLOW_FILES["i2v"],
            prompt=final_prompt,
            negative=VIDEO_NEGATIVE,
            width=req.width,
            height=req.height,
            length=req.length,
            seed=seed,
            job_id=job_id,
            image_name=req.image_name,
        )

    prompt_id = await comfy.submit(wf)
    now = time.time()
    params = req.model_dump(exclude={"prompt"})
    params["seed"] = seed
    if selected_model:
        params["model"] = selected_model
    if final_prompt != req.prompt:
        params["enhanced_prompt"] = final_prompt
    with db() as conn:
        conn.execute(
            "INSERT INTO jobs(id, prompt_id, mode, prompt, params, status, outputs, error, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                job_id,
                prompt_id,
                req.mode,
                req.prompt,
                json.dumps(params),
                "queued",
                None,
                None,
                now,
                now,
            ),
        )
    return {"id": job_id, "prompt_id": prompt_id, "status": "queued"}


@app.get("/api/jobs/{job_id}", response_model=JobOut)
async def get_job(job_id: str):
    with db() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="job not found")
    return JobOut(
        id=row["id"],
        prompt_id=row["prompt_id"],
        mode=row["mode"],
        prompt=row["prompt"],
        params=json.loads(row["params"]),
        status=row["status"],
        outputs=json.loads(row["outputs"]) if row["outputs"] else [],
        error=row["error"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


@app.get("/api/jobs")
async def list_jobs(limit: int = 50):
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [
        {
            "id": r["id"],
            "mode": r["mode"],
            "prompt": r["prompt"],
            "status": r["status"],
            "outputs": json.loads(r["outputs"]) if r["outputs"] else [],
            "error": r["error"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]


@app.get("/api/jobs/{job_id}/stream")
async def stream_job(job_id: str):
    async def gen():
        last: str | None = None
        for _ in range(600):  # cap at ~10 min
            with db() as conn:
                row = conn.execute(
                    "SELECT status, outputs, error FROM jobs WHERE id=?", (job_id,)
                ).fetchone()
            if not row:
                yield f"event: error\ndata: {json.dumps({'error': 'not found'})}\n\n"
                return
            payload = {
                "status": row["status"],
                "outputs": json.loads(row["outputs"]) if row["outputs"] else [],
                "error": row["error"],
            }
            blob = json.dumps(payload)
            if blob != last:
                yield f"data: {blob}\n\n"
                last = blob
            if row["status"] in ("done", "error"):
                return
            await asyncio.sleep(1.0)
    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    data = await file.read()
    name = f"softstudio_{uuid.uuid4().hex[:8]}_{file.filename or 'upload.png'}"
    saved = await comfy.upload_image(name, data, file.content_type or "image/png")
    return {"name": saved}


_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
}


# Serve ComfyUI outputs as /assets/...
@app.get("/assets/{rest:path}")
async def asset(rest: str):
    candidate = (COMFY_OUTPUT / rest).resolve()
    if not str(candidate).startswith(str(COMFY_OUTPUT.resolve())):
        raise HTTPException(status_code=400, detail="bad path")
    if not candidate.exists():
        raise HTTPException(status_code=404, detail="not found")
    media_type = _MIME.get(candidate.suffix.lower(), "application/octet-stream")
    return FileResponse(candidate, media_type=media_type)
