param(
    [ValidateRange(1,32)][int]$Threads = 2,
    [ValidateSet('cpu','vulkan')][string]$Backend = 'cpu',
    [switch]$ProbeOnly
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$curl = (Get-Command curl.exe -ErrorAction Stop).Source
$base = $PSScriptRoot
$root = Join-Path $base 'models\chatterbox-nano-native'
New-Item -ItemType Directory -Force -Path $root | Out-Null
$isVulkan = $Backend -eq 'vulkan'
$suffix = if ($isVulkan) { '-vulkan' } else { '' }
$marker = Join-Path $root "ready$suffix.json"
if (!$ProbeOnly) { Remove-Item $marker -Force -ErrorAction SilentlyContinue }
function Get-Verified($url, $dest, $hash) {
    if (!(Test-Path $dest) -or (Get-FileHash $dest -Algorithm SHA256).Hash.ToLowerInvariant() -ne $hash) {
        $partial = "$dest.partial"
        Write-Host "Downloading $dest"
        Invoke-WebRequest $url -OutFile $partial -UseBasicParsing
        if ((Get-FileHash $partial -Algorithm SHA256).Hash.ToLowerInvariant() -ne $hash) {
            Remove-Item $partial -Force
            throw "Checksum mismatch: $dest"
        }
        Move-Item $partial $dest -Force
    } else {
        Write-Host "Reusing verified download: $dest"
    }
}
$runtime = Join-Path $root "runtime$suffix"
$zip = Join-Path $root "runtime$suffix.zip"
if ($isVulkan) {
    Get-Verified 'https://github.com/delebash/audio.cpp/releases/download/v0.9.4-jv.7/audio-v0.9.4-jv.7-bin-windows-x64-vulkan-portable.zip' $zip '8a1d823d9de612536eb49e00114a729fa7444df8179acec7466cdc26dbc3fe78'
} else {
    Get-Verified 'https://github.com/delebash/audio.cpp/releases/download/v0.9.4-jv.7/audio-v0.9.4-jv.7-bin-windows-x64-cpu-portable.zip' $zip '55b484bdfa1cce9bf535e567f3d03459c337d843bd5eed4866ac722d431a002d'
}
if (Test-Path $runtime) { Remove-Item $runtime -Recurse -Force }
Expand-Archive $zip -DestinationPath $runtime -Force
$exe = @(Get-ChildItem -Path $runtime -Filter audiocpp_server.exe -Recurse)
if ($exe.Count -ne 1) { throw 'Native audio server executable not found or ambiguous' }
$device = $null
$deviceInfo = $null
function Read-Devices {
    $probeOut = Join-Path $root "devices$suffix.json"
    $probeErr = Join-Path $root "devices$suffix-error.log"
    $probe = Start-Process -FilePath $exe[0].FullName -WorkingDirectory $exe[0].DirectoryName -ArgumentList @('--list-devices','--json') -RedirectStandardOutput $probeOut -RedirectStandardError $probeErr -PassThru -WindowStyle Hidden
    if (!$probe.WaitForExit(30000)) { Stop-Process -Id $probe.Id -Force; throw 'Native device probe timed out' }
    if ($probe.ExitCode -ne 0) {
        Get-Content $probeErr -Tail 80 -ErrorAction SilentlyContinue
        throw "Native device probe failed (exit $($probe.ExitCode))"
    }
    $report = Get-Content $probeOut -Raw | ConvertFrom-Json
    if ($null -eq $report.devices) { throw 'Native device probe returned invalid JSON' }
    return $report
}
if ($isVulkan -or $ProbeOnly) {
    $report = Read-Devices
    Write-Host ($report | ConvertTo-Json -Depth 8)
    if ($ProbeOnly) {
        # CI exercises the actual executable on a runner that may have no GPU.
        # This mode does not download the model or write an activation marker.
        Write-Host 'Runtime probe completed; no synthesis was attempted.'
        return
    }
    $eligible = @($report.devices | Where-Object {
        $_.backend -eq 'vulkan' -and $_.type -eq 'gpu' -and
        $null -ne $_.memory -and $_.memory.free_bytes -ge 2147483648 -and
        $_.memory.free_bytes -le $_.memory.total_bytes
    } | Sort-Object -Property @{Expression={$_.memory.free_bytes};Descending=$true})
    if ($eligible.Count -eq 0) { throw 'No discrete Vulkan GPU reports at least 2 GiB free. Close other GPU applications and retry; existing voices remain available.' }
    $deviceInfo = $eligible[0]
    $device = [int]$deviceInfo.index
    Write-Host "Selected Vulkan GPU: $($deviceInfo.description); reported free bytes: $($deviceInfo.memory.free_bytes)"
}
$model = Join-Path $root 'chatterbox-nano-q8_0.gguf'
Get-Verified 'https://huggingface.co/delebash/chatterbox-nano-GGUF/resolve/main/chatterbox-nano-q8_0.gguf' $model 'cb320915e43cf318a052392ed742504169886a3bcbf2b4871c0679aca73aee31'
# Test exactly the persistent API configuration used by the game, without Python.
$listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
$listener.Start()
$port = $listener.LocalEndpoint.Port
$listener.Stop()
$threads = [int][Math]::Min($Threads, [Environment]::ProcessorCount)
$config = Join-Path $root "setup-server$suffix.json"
$settings = @{host='127.0.0.1';port=$port;backend=$Backend;threads=$threads;lazy_load=$false;max_loaded_models=1;log_request_body=$false;models=@(@{id='eli';family='chatterbox_turbo';path=$model;task='tts';mode='offline'})}
if ($isVulkan) { $settings.device = $device }
[IO.File]::WriteAllText($config, ($settings | ConvertTo-Json -Depth 5), [Text.UTF8Encoding]::new($false))
$output = Join-Path $root "sample$suffix.wav"
$second = Join-Path $root "sample$suffix-warm.wav"
Remove-Item $output,$second -Force -ErrorAction SilentlyContinue
$stdout = Join-Path $root "setup-server$suffix.log"
$stderr = Join-Path $root "setup-server$suffix-error.log"
# Keep the previous crash evidence before replacing redirected logs.
foreach ($logPath in @($stdout,$stderr)) {
    if (Test-Path $logPath) { Copy-Item $logPath "$logPath.previous" -Force }
}
$timer = [Diagnostics.Stopwatch]::StartNew()
Write-Host "Starting native $Backend server ($threads CPU threads)..."
$p = Start-Process -FilePath $exe[0].FullName -WorkingDirectory $exe[0].DirectoryName -ArgumentList @('--config', ('"' + $config + '"'), '--no-ui') -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru -WindowStyle Hidden
try {
    $url = "http://127.0.0.1:$port"
    $ready = $false
    for ($i=0; $i -lt 100; $i++) {
        if ($p.HasExited) { throw 'Native server exited. See setup-server-error.log' }
        & $curl --noproxy "*" --silent --fail --connect-timeout 1 --max-time 1 "$url/health" -o NUL
        if ($LASTEXITCODE -eq 0) { $ready=$true; break }
        Start-Sleep -Milliseconds 200
    }
    if (!$ready) { throw 'Native server did not start' }
    $startup = $timer.Elapsed.TotalSeconds
    $timings = @()
    foreach ($line in @(@{text='[fear] Is someone there?';path=$output}, @{text='[angry] Who are you?';path=$second})) {
        $timer.Restart()
        $body = @{model='eli';input=$line.text;response_format='wav'} | ConvertTo-Json -Compress
        $requestFile = Join-Path $root "setup-request$suffix.json"
        [IO.File]::WriteAllText($requestFile, $body, [Text.UTF8Encoding]::new($false))
        Write-Host "Testing local $Backend speech: $($line.text)"
        & $curl --noproxy "*" --http1.1 --fail --silent --show-error --connect-timeout 5 --max-time 180 -H "Content-Type: application/json" --data-binary "@$requestFile" -o $line.path "$url/v1/audio/speech"
        $curlExit = $LASTEXITCODE
        if ($curlExit -ne 0) { throw "Local speech request failed (curl exit $curlExit)" }
        $timings += [Math]::Round($timer.Elapsed.TotalSeconds,3)
        Write-Host "Speech generated in $($timings[-1]) seconds."
        $bytes = [IO.File]::ReadAllBytes($line.path)
        if ($bytes.Length -lt 4096 -or [Text.Encoding]::ASCII.GetString($bytes, 0, 4) -ne 'RIFF' -or [Text.Encoding]::ASCII.GetString($bytes, 8, 4) -ne 'WAVE') {
            throw 'Native audio is not a playable WAV'
        }
    }
} catch {
    $p.Refresh()
    Write-Host "Native setup failure: $($_.Exception.Message)"
    if ($p.HasExited) {
        Write-Host ("Native server exited with code {0} (0x{0:X8})" -f $p.ExitCode)
    } else {
        Write-Host "Native server is still running; the request failed or timed out."
    }
    foreach ($logPath in @($stdout,$stderr)) {
        Write-Host "--- $logPath ---"
        Get-Content $logPath -Tail 80 -ErrorAction SilentlyContinue
    }
    throw
} finally {
    if (!$p.HasExited) { Stop-Process -Id $p.Id -Force }
    $p.WaitForExit()
}
$summary = @{engine='audio.cpp v0.9.4-jv.7';backend=$Backend;model='chatterbox-nano-q8_0';startup_seconds=[Math]::Round($startup,3);first_seconds=$timings[0];warm_seconds=$timings[1];threads=$threads}
if ($isVulkan) { $summary.device=$device; $summary.device_info=$deviceInfo }
$summary | ConvertTo-Json -Depth 8 | Set-Content -Encoding utf8 $marker
Get-Content $marker
Write-Host "Native Nano $Backend ready. Restart the game and select the corresponding engine in Voice Studio."
