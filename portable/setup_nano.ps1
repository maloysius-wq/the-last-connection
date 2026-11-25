$ErrorActionPreference = 'Stop'
$base = $PSScriptRoot
$root = Join-Path $base 'models\chatterbox-nano'
New-Item -ItemType Directory -Force -Path $root | Out-Null
$marker = Join-Path $root 'ready.json'
Remove-Item $marker -Force -ErrorAction SilentlyContinue
$env:UV_CACHE_DIR = Join-Path $root 'uv-cache'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $root 'python'
$env:UV_PYTHON_BIN_DIR = Join-Path $root 'bin'
$env:UV_PYTHON_NO_REGISTRY = '1'
$env:HF_HOME = Join-Path $root 'hf-cache'
$env:HF_HUB_DISABLE_XET = '1'
$env:TEMP = Join-Path $root 'temp'
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Force -Path $env:TEMP | Out-Null
$env:HF_HUB_OFFLINE = '0'
$env:TRANSFORMERS_OFFLINE = '0'

function Check-Native { if ($LASTEXITCODE -ne 0) { throw "Setup command failed: exit $LASTEXITCODE" } }
$uv = Join-Path $root 'uv.exe'
if (!(Test-Path $uv)) {
    $zip = Join-Path $root 'uv.zip'
    Invoke-WebRequest 'https://github.com/astral-sh/uv/releases/download/0.13.6/uv-x86_64-pc-windows-msvc.zip' -OutFile $zip
    if ((Get-FileHash $zip -Algorithm SHA256).Hash.ToLowerInvariant() -ne 'a2a8820d5eea32f08ef467ef3b7f66883a9b076d5737a2fc2fbb5f458d1bb50f') {
        throw 'uv archive checksum mismatch'
    }
    Expand-Archive $zip -DestinationPath $root -Force
    if (!(Test-Path $uv)) {
        $candidate = Get-ChildItem -Path $root -Filter uv.exe -Recurse | Select-Object -First 1
        if (!$candidate) { throw 'uv executable missing' }
        Copy-Item $candidate.FullName $uv
    }
    Remove-Item $zip -Force
}
& $uv python install 3.11 --no-bin
Check-Native
$venv = Join-Path $root 'venv'
$python = Join-Path $venv 'Scripts\python.exe'
if (!(Test-Path $python)) {
    & $uv venv --managed-python --python 3.11 $venv
    Check-Native
}
# Official source at a fixed revision; replace its moving Git dependency
# with the same upstream Perth package from a fixed source archive.
$srcRevision = 'ab55923c27757c90cfcc407baa57dc25a7d25217'
$srcZip = Join-Path $root 'chatterbox-source.zip'
$source = Join-Path $root "chatterbox-$srcRevision"
if (!(Test-Path (Join-Path $source 'pyproject.toml'))) {
    Invoke-WebRequest "https://codeload.github.com/resemble-ai/chatterbox/zip/$srcRevision" -OutFile $srcZip
    Expand-Archive $srcZip -DestinationPath $root -Force
    Remove-Item $srcZip -Force
}
$project = Join-Path $source 'pyproject.toml'
$metadata = Get-Content $project -Raw
$metadata = $metadata.Replace('git+https://github.com/resemble-ai/Perth.git@master', 'https://codeload.github.com/resemble-ai/Perth/zip/ff1c8ac55a976971245cdd53c18d6131ca00d993')
Set-Content -Path $project -Value $metadata -Encoding ASCII
& $uv pip install --python $python --index 'https://download.pytorch.org/whl/cpu' 'torch==2.6.0+cpu' 'torchaudio==2.6.0+cpu' $source
Check-Native
& $python (Join-Path $base 'nano_voice_worker.py') --root $root --setup
Check-Native
if (!(Test-Path $marker)) { throw 'Nano smoke test did not pass' }
Write-Host 'Nano is ready. Start TheLastConnection.exe normally. Piper remains a fallback.'
Write-Host 'To disable Nano, close the game and rename ready.json in models\chatterbox-nano.'
