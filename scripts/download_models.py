"""Download Flux.1 schnell + LTX-Video weights into ComfyUI's models tree.

Idempotent: skips files that already exist with the right size.
Run with the softstudio venv python.
"""
from __future__ import annotations

import sys
from pathlib import Path

from huggingface_hub import hf_hub_download

ROOT = Path(__file__).resolve().parent.parent
COMFY = ROOT / "ComfyUI"
MODELS = COMFY / "models"

# (repo_id, filename, local_subdir)
DOWNLOADS = [
    # ---------- Flux.1 schnell (text-to-image, fast, filtered) ----------
    ("Comfy-Org/flux1-schnell", "flux1-schnell-fp8.safetensors", "checkpoints"),

    # ---------- RealVisXL V5.0 (text-to-image, photorealistic, unfiltered) ----------
    # SDXL-based, ~6.5 GB fp16. Handles explicit prompts.
    ("SG161222/RealVisXL_V5.0", "RealVisXL_V5.0_fp16.safetensors", "checkpoints"),

    # ---------- LTX-Video (text-to-video, image-to-video) ----------
    ("Lightricks/LTX-Video", "ltxv-13b-0.9.8-distilled-fp8.safetensors", "checkpoints"),
    ("Lightricks/LTX-Video", "ltx-video-2b-v0.9.5.safetensors", "checkpoints"),

    # T5 text encoder shared with LTX (Flux schnell-fp8 has its own packed in)
    ("comfyanonymous/flux_text_encoders", "t5xxl_fp8_e4m3fn.safetensors", "text_encoders"),
]


def main() -> int:
    for repo_id, filename, subdir in DOWNLOADS:
        target_dir = MODELS / subdir
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / filename
        if target.exists() and target.stat().st_size > 1_000_000:
            print(f"[skip] {subdir}/{filename} already present ({target.stat().st_size / 1e9:.2f} GB)")
            continue
        print(f"[get ] {repo_id}/{filename} -> {subdir}/")
        path = hf_hub_download(
            repo_id=repo_id,
            filename=filename,
            local_dir=str(target_dir),
        )
        size = Path(path).stat().st_size / 1e9
        print(f"[done] {subdir}/{filename} ({size:.2f} GB)")
    print("All models present.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
