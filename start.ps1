$venvPath = ".\.venv"

if (-not (Test-Path $venvPath)) {
    Write-Host "Virtual environment not found. Creating .venv..." -ForegroundColor Yellow
    python -m venv $venvPath
    & "$venvPath\Scripts\python.exe" -m pip install --upgrade pip
    & "$venvPath\Scripts\pip.exe" install -r requirements.txt
    Write-Host "Dependencies installed." -ForegroundColor Green
}

Write-Host "Starting uvicorn on http://0.0.0.0:8000 ..." -ForegroundColor Cyan
& "$venvPath\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
