# Softstudio

Self-hosted Grok Imagine clone. Text-to-image, text-to-video, and image-to-video — all running locally on your GPU.

## Stack

```
Next.js (frontend) ──► FastAPI (gateway) ──► ComfyUI (inference) ──► RTX 5070 Ti
                              │
                              └── SQLite (jobs/users) + local disk (assets)
```

## Hardware target

- NVIDIA Blackwell (RTX 50-series) or newer, **16 GB VRAM minimum**
- 32 GB system RAM
- ~150 GB free disk for models

## Models

| Job | Model | VRAM | Speed |
|---|---|---|---|
| Text-to-image (fast) | Flux.1 schnell FP8 | ~11 GB | ~2 s / 1024² |
| Text-to-video (fast) | LTX-Video 0.9.5 | ~10 GB | ~4 s / 5-sec clip |
| Image-to-video | LTX-Video I2V | ~10 GB | ~4 s / 5-sec clip |

## Run

```powershell
# One-time install
.\scripts\setup.ps1

# Start everything (3 terminals or use launcher)
.\scripts\start-all.ps1
```

Then open <http://localhost:3000>.

## Layout

```
softstudio/
├─ ComfyUI/        # cloned upstream, headless inference engine
├─ backend/        # FastAPI gateway
├─ frontend/       # Next.js app
├─ workflows/      # ComfyUI graph templates we POST to /prompt
├─ models/         # downloaded weights (git-ignored)
├─ outputs/        # generated assets (git-ignored)
└─ scripts/        # setup/run helpers
```
