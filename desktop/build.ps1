$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
python -m pip install -r desktop/requirements.txt pyinstaller==6.20.0
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
python -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
python -m PyInstaller --noconfirm --clean --onefile --windowed --name FireboxAssistant --paths . --add-data 'desktop/disk_worker.py;.' desktop/launcher.py
if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
Write-Host 'Executable: dist\FireboxAssistant.exe'
