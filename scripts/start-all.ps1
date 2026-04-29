# Start all three softstudio services in separate windows.
# Usage: .\scripts\start-all.ps1

$root = Resolve-Path "$PSScriptRoot\.."
$py = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $py)) {
    Write-Error "venv not found at $py — run .\scripts\setup.ps1 first."
    exit 1
}

Write-Host ">> Starting ComfyUI on :8188" -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit","-Command","Set-Location '$root\ComfyUI'; & '$py' main.py --listen 127.0.0.1 --port 8188 --disable-auto-launch"

Start-Sleep -Seconds 3

Write-Host ">> Starting FastAPI gateway on :8000" -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit","-Command","Set-Location '$root'; & '$py' -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload"

Start-Sleep -Seconds 2

Write-Host ">> Starting Next.js frontend on :3000" -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit","-Command","Set-Location '$root\frontend'; npm run dev"

Start-Sleep -Seconds 4

Write-Host ""
Write-Host "Softstudio launching... open http://localhost:3000" -ForegroundColor Green
Write-Host "  ComfyUI : http://127.0.0.1:8188"
Write-Host "  Gateway : http://127.0.0.1:8000/api/health"
Write-Host "  Web UI  : http://localhost:3000"
