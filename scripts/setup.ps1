# One-time setup for softstudio.
# Installs Python 3.12, creates venv, installs deps, clones ComfyUI, downloads models.
# Usage: .\scripts\setup.ps1

$ErrorActionPreference = "Stop"
$root = Resolve-Path "$PSScriptRoot\.."

# 1. Python 3.12
$py312 = "py -3.12 --version"
try { Invoke-Expression $py312 | Out-Null } catch {
    Write-Host ">> Installing Python 3.12 via py launcher..." -ForegroundColor Cyan
    py install 3.12
}

# 2. venv
if (-not (Test-Path "$root\.venv\Scripts\python.exe")) {
    Write-Host ">> Creating venv..." -ForegroundColor Cyan
    py -3.12 -m venv "$root\.venv"
}
$pyvenv = "$root\.venv\Scripts\python.exe"
$pip = "$root\.venv\Scripts\pip.exe"

# 3. Pip deps
Write-Host ">> Installing PyTorch (CUDA 12.8)..." -ForegroundColor Cyan
& $pyvenv -m pip install --upgrade pip | Out-Null
& $pip install --index-url https://download.pytorch.org/whl/cu128 torch torchvision torchaudio

# 4. ComfyUI
if (-not (Test-Path "$root\ComfyUI")) {
    Write-Host ">> Cloning ComfyUI..." -ForegroundColor Cyan
    git clone --depth 1 https://github.com/comfyanonymous/ComfyUI.git "$root\ComfyUI"
}
& $pip install -r "$root\ComfyUI\requirements.txt"

# 5. Backend deps
Write-Host ">> Installing backend deps..." -ForegroundColor Cyan
& $pip install fastapi "uvicorn[standard]" "websockets>=12" python-multipart

# 6. Frontend deps
Write-Host ">> Installing frontend deps..." -ForegroundColor Cyan
Push-Location "$root\frontend"
npm install --silent
Pop-Location

# 7. Models
Write-Host ">> Downloading models (this takes a while, ~31 GB)..." -ForegroundColor Cyan
& $pyvenv "$root\scripts\download_models.py"

Write-Host ""
Write-Host "Setup complete. Run .\scripts\start-all.ps1 to launch." -ForegroundColor Green
