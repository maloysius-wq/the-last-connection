param([switch]$Cuda, [switch]$CudaBuildCheck)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
if ($CudaBuildCheck -and !$Cuda) { throw 'CudaBuildCheck requires -Cuda' }
$base = $PSScriptRoot
$root = Join-Path $base 'models\chatterbox-nano'
New-Item -ItemType Directory -Force -Path $root | Out-Null
$marker = Join-Path $root $(if ($Cuda) { 'ready-cuda.json' } else { 'ready.json' })
if (!$CudaBuildCheck) { Remove-Item $marker -Force -ErrorAction SilentlyContinue }
if ($Cuda -and !$CudaBuildCheck) {
    if (!(Test-Path (Join-Path $root 'ready.json'))) { throw 'Install the original CPU Nano first. CUDA setup reuses its existing checkpoint.' }
    foreach ($name in @('t3_nano_v1.safetensors','s3gen_meanflow.safetensors','ve.safetensors','conds.pt','vocab.json','merges.txt','added_tokens.json','special_tokens_map.json','tokenizer_config.json')) {
        if (!(Test-Path (Join-Path $root "checkpoint/$name"))) { throw "Existing checkpoint missing $name; repair CPU Nano first." }
    }
    $drive = Get-PSDrive -Name ([IO.Path]::GetPathRoot($root).Substring(0,1))
    if ($drive.Free -lt 10GB) { throw 'CUDA setup needs at least 10 GiB free on the game drive for packages and temporary files.' }
    $gpu = Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue
    if ($gpu) {
        & $gpu.Source --query-gpu=name,driver_version,memory.total,memory.free --format=csv
        if ($LASTEXITCODE -ne 0) { throw 'NVIDIA driver query failed. Existing CPU Nano is unchanged.' }
    }
    Write-Host 'Reusing original model checkpoint. CUDA dependencies are a large separate download; no model download.'
}
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
$venv = Join-Path $root $(if ($Cuda) { 'venv-cuda' } else { 'venv' })
$python = Join-Path $venv 'Scripts\python.exe'
if (Test-Path $python) {
    & $python --version
    if ($LASTEXITCODE -ne 0) { Remove-Item $venv -Recurse -Force }
}
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
$metadata = $metadata.Replace('git+https://github.com/resemble-ai/Perth.git@master', 'https://github.com/resemble-ai/Perth/archive/ff1c8ac55a976971245cdd53c18d6131ca00d993.zip')
Set-Content -Path $project -Value $metadata -Encoding ASCII
if ($Cuda) {
    & $uv pip install --python $python --index 'https://download.pytorch.org/whl/cu124' 'torch==2.6.0+cu124' 'torchaudio==2.6.0+cu124' $source
} else {
    & $uv pip install --python $python --index 'https://download.pytorch.org/whl/cpu' 'torch==2.6.0+cpu' 'torchaudio==2.6.0+cpu' $source
}
Check-Native
if ($CudaBuildCheck) {
    & $python (Join-Path $base 'nano_voice_worker.py') --root $root --check-cuda-build
    Check-Native
    return
}
if ($Cuda) {
    $env:HF_HUB_OFFLINE = '1'
    $env:TRANSFORMERS_OFFLINE = '1'
    $log = Join-Path $root 'setup-cuda.log'
    # Preserve previous diagnostic log and avoid PowerShell 5.1 treating
    # native stderr progress as a terminating error.
    if (Test-Path $log) { Copy-Item $log "$log.previous" -Force }
    $oldPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & $python -u (Join-Path $base 'nano_voice_worker.py') --root $root --setup --device cuda 2>&1 | Tee-Object -FilePath $log
        $exitCode = $LASTEXITCODE
    } finally { $ErrorActionPreference = $oldPreference }
    if ($exitCode -ne 0) { throw "CUDA synthesis failed (exit $exitCode). See $log. CPU Nano remains available." }
} else {
    & $python (Join-Path $base 'nano_voice_worker.py') --root $root --setup
    Check-Native
}
if (!(Test-Path $marker)) { throw 'Nano smoke test did not pass' }
Write-Host 'Nano is ready. Start TheLastConnection.exe normally. Piper remains a fallback.'
if ($Cuda) {
    Write-Host 'Select Chatterbox Nano CUDA GPU in Voice Studio. To disable CUDA, rename ready-cuda.json.'
} else {
    Write-Host 'To disable Nano, close the game and rename ready.json in models\chatterbox-nano.'
}
