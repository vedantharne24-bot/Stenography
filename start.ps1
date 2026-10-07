# Start StegoLab (API on :8000, web app on :5173) in two terminal windows (Windows).
#   powershell -ExecutionPolicy Bypass -File start.ps1
$root = $PSScriptRoot
if (-not (Test-Path "$root\backend\.venv\Scripts\python.exe")) { throw 'Run setup.ps1 first.' }

Start-Process powershell -ArgumentList '-NoExit', '-Command', "Set-Location '$root\backend'; .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
Start-Process powershell -ArgumentList '-NoExit', '-Command', "Set-Location '$root\frontend'; npm run dev"

Write-Host "API      http://127.0.0.1:8000/api/health  (docs: /docs)"
Write-Host "Web app  http://localhost:5173"
Start-Sleep -Seconds 6
Start-Process 'http://localhost:5173'
