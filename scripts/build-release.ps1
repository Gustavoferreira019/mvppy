$ErrorActionPreference = 'Stop'

$name = $null
if ($args.Count -eq 2 -and ($args[0] -eq '--name' -or $args[0] -eq '-Name')) {
    $name = $args[1]
}
else {
    throw 'O parâmetro --name é obrigatório. Uso: .\scripts\build-release.ps1 --name alpha-0.1.0'
}

$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $root 'venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw "Ambiente virtual não encontrado em $python." }

& $python (Join-Path $PSScriptRoot 'build_release.py') --name $name
if ($LASTEXITCODE -ne 0) { throw "A criação da build falhou (código $LASTEXITCODE)." }
