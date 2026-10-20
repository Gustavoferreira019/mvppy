$ErrorActionPreference = 'Stop'

$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $root 'venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $python)) {
    throw "Ambiente virtual não encontrado em $python. Execute a instalação descrita no README.md."
}

$processes = @()
try {
    $processes += Start-Process -FilePath $python -ArgumentList 'app.py' -WorkingDirectory $root -PassThru
    $processes += Start-Process -FilePath $python -ArgumentList 'setup_server.py' -WorkingDirectory $root -PassThru
    $ready = $false
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        try {
            Invoke-WebRequest -Uri 'http://127.0.0.1:8765' -UseBasicParsing -TimeoutSec 1 | Out-Null
            $ready = $true
            break
        }
        catch {
            Start-Sleep -Milliseconds 500
        }
    }
    if (-not $ready) { throw 'O painel não respondeu em http://127.0.0.1:8765.' }
    Start-Process 'http://127.0.0.1:8765' | Out-Null
    Write-Host 'VIGIL.AI em modo desenvolvimento: http://127.0.0.1:8765'
    Write-Host 'Pressione Ctrl+C nesta janela para encerrar os dois processos.'
    while ($processes | Where-Object { -not $_.HasExited }) { Start-Sleep -Milliseconds 500 }
}
finally {
    foreach ($process in $processes) {
        if ($process -and -not $process.HasExited) {
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        }
    }
}
