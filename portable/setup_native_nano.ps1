$ErrorActionPreference = 'Stop'
$base = $PSScriptRoot
$root = Join-Path $base 'models\chatterbox-nano-native'
New-Item -ItemType Directory -Force -Path $root | Out-Null
$marker = Join-Path $root 'ready.json'
Remove-Item $marker -Force -ErrorAction SilentlyContinue
function Get-Verified($url, $dest, $hash) {
    if (!(Test-Path $dest) -or (Get-FileHash $dest -Algorithm SHA256).Hash.ToLowerInvariant() -ne $hash) {
        $partial = "$dest.partial"
        Invoke-WebRequest $url -OutFile $partial
        if ((Get-FileHash $partial -Algorithm SHA256).Hash.ToLowerInvariant() -ne $hash) {
            Remove-Item $partial -Force
            throw "Checksum mismatch: $dest"
        }
        Move-Item $partial $dest -Force
    }
}
$runtime = Join-Path $root 'runtime'
$zip = Join-Path $root 'runtime.zip'
Get-Verified 'https://github.com/delebash/audio.cpp/releases/download/v0.9.4-jv.7/audio-v0.9.4-jv.7-bin-windows-x64-cpu-portable.zip' $zip '55b484bdfa1cce9bf535e567f3d03459c337d843bd5eed4866ac722d431a002d'
if (Test-Path $runtime) { Remove-Item $runtime -Recurse -Force }
Expand-Archive $zip -DestinationPath $runtime -Force
$model = Join-Path $root 'chatterbox-nano-q8_0.gguf'
Get-Verified 'https://huggingface.co/delebash/chatterbox-nano-GGUF/resolve/main/chatterbox-nano-q8_0.gguf' $model 'cb320915e43cf318a052392ed742504169886a3bcbf2b4871c0679aca73aee31'
$exe = @(Get-ChildItem -Path $runtime -Filter audiocpp_server.exe -Recurse)
if ($exe.Count -ne 1) { throw 'Native audio server executable not found or ambiguous' }
# Test exactly the persistent API configuration used by the game, without Python.
$listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
$listener.Start()
$port = $listener.LocalEndpoint.Port
$listener.Stop()
$threads = [int][Math]::Max(1, [Math]::Min(8, [Math]::Floor([Environment]::ProcessorCount / 2)))
$config = Join-Path $root 'setup-server.json'
@{host='127.0.0.1';port=$port;backend='cpu';threads=$threads;lazy_load=$false;max_loaded_models=1;log_request_body=$false;models=@(@{id='eli';family='chatterbox_turbo';path=$model;task='tts';mode='offline'})} | ConvertTo-Json -Depth 5 | Set-Content -Encoding ascii $config
$output = Join-Path $root 'sample.wav'
$second = Join-Path $root 'sample-warm.wav'
Remove-Item $output,$second -Force -ErrorAction SilentlyContinue
$stdout = Join-Path $root 'setup-server.log'
$stderr = Join-Path $root 'setup-server-error.log'
$timer = [Diagnostics.Stopwatch]::StartNew()
$p = Start-Process -FilePath $exe[0].FullName -WorkingDirectory $exe[0].DirectoryName -ArgumentList @('--config', ('"' + $config + '"'), '--no-ui') -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru -WindowStyle Hidden
try {
    $url = "http://127.0.0.1:$port"
    $ready = $false
    for ($i=0; $i -lt 100; $i++) {
        if ($p.HasExited) { throw 'Native server exited. See setup-server-error.log' }
        try { $health = Invoke-WebRequest "$url/health" -UseBasicParsing -TimeoutSec 1; if ($health.StatusCode -eq 200) { $ready=$true; break } } catch {}
        Start-Sleep -Milliseconds 200
    }
    if (!$ready) { throw 'Native server did not start' }
    $startup = $timer.Elapsed.TotalSeconds
    $timings = @()
    foreach ($line in @(@{text='[fear] Is someone there? I can hear you.';path=$output}, @{text='[angry] Who are you?';path=$second})) {
        $timer.Restart()
        $body = @{model='eli';input=$line.text;response_format='wav'} | ConvertTo-Json -Compress
        Invoke-WebRequest "$url/v1/audio/speech" -Method Post -ContentType 'application/json' -Body $body -OutFile $line.path -UseBasicParsing -TimeoutSec 90
        $timings += [Math]::Round($timer.Elapsed.TotalSeconds,3)
        $bytes = [IO.File]::ReadAllBytes($line.path)
        if ($bytes.Length -lt 4096 -or [Text.Encoding]::ASCII.GetString($bytes, 0, 4) -ne 'RIFF' -or [Text.Encoding]::ASCII.GetString($bytes, 8, 4) -ne 'WAVE') {
            throw 'Native audio is not a playable WAV'
        }
    }
} finally {
    if (!$p.HasExited) { Stop-Process -Id $p.Id -Force }
    $p.WaitForExit()
}
@{engine='audio.cpp v0.9.4-jv.7';model='chatterbox-nano-q8_0';startup_seconds=[Math]::Round($startup,3);first_seconds=$timings[0];warm_seconds=$timings[1];threads=$threads} | ConvertTo-Json | Set-Content -Encoding utf8 $marker
Get-Content $marker
Write-Host "Native Nano ready. Restart the game and select Native Nano Q8 in Voice Studio."
