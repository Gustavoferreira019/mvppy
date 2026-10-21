from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
WORK = ROOT / ".release-work"
PYINSTALLER = Path(sys.executable).with_name("pyinstaller.exe")
NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def render_progress(percent: float, label: str) -> None:
    """Render one compact progress line for terminals and CI logs."""
    percent = max(0.0, min(100.0, percent))
    width = 32
    filled = round(width * percent / 100)
    bar = "#" * filled + "." * (width - filled)
    print(f"\r[{bar}] {percent:5.1f}% {label:<48}", end="", flush=True)


def finish_progress() -> None:
    print()


def validate_name(value: str) -> str:
    value = value.strip()
    if not value or not NAME_PATTERN.fullmatch(value):
        raise argparse.ArgumentTypeError(
            "use somente letras, números, ponto, hífen ou sublinhado no nome da build"
        )
    return value


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Gera um pacote portátil do VIGIL.AI com PyInstaller."
    )
    result.add_argument(
        "--name",
        type=validate_name,
        required=True,
        help="identificador obrigatório da versão",
    )
    return result


def build(
    name: str,
    entrypoint: str,
    start_percent: float,
    end_percent: float,
    *extra: str,
) -> Path:
    output = WORK / "pyinstaller-dist"
    command = [
        str(PYINSTALLER),
        "--noconfirm",
        "--clean",
        "--onefile",
        "--noconsole",
        "--name",
        name,
        "--distpath",
        str(output),
        "--workpath",
        str(WORK / f"pyinstaller-build-{name}"),
        "--specpath",
        str(WORK),
        *extra,
        entrypoint,
    ]
    print(f"\nGerando {name}.exe...")
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    last_lines: list[str] = []
    marker_percent = {
        "Analyzing": 0.20,
        "Building PYZ": 0.48,
        "Building PKG": 0.72,
        "Building EXE": 0.90,
        "Build complete": 1.00,
    }
    current = start_percent
    if process.stdout is not None:
        for raw_line in process.stdout:
            line = raw_line.strip()
            if line:
                last_lines.append(line)
                del last_lines[:-8]
            for marker, fraction in marker_percent.items():
                if marker in line:
                    current = max(current, start_percent + (end_percent - start_percent) * fraction)
                    render_progress(current, f"{name}: {marker}")
                    break
    return_code = process.wait()
    if return_code != 0:
        finish_progress()
        details = "\n".join(last_lines[-5:])
        raise RuntimeError(f"PyInstaller falhou para {name}.exe (código {return_code}).\n{details}")
    render_progress(end_percent, f"{name}: concluído")
    finish_progress()
    result = output / f"{name}.exe"
    if not result.exists():
        raise FileNotFoundError(result)
    return result


def copy_manual(package: Path, archive_name: str, launcher_name: str) -> None:
    manual = (ROOT / "LEIA-ME.txt").read_text(encoding="utf-8")
    version = re.search(r"alpha-\d+\.\d+\.\d+", archive_name, re.IGNORECASE)
    if version:
        manual = re.sub(
            r"Versão Alpha \d+\.\d+\.\d+",
            f"Versão {version.group(0).replace('-', ' ').title()}",
            manual,
            count=1,
        )
    manual = re.sub(
        r"VigilAI-(?:Alpha|alpha)-\d+\.\d+\.\d+(?:-single)?\.zip",
        archive_name,
        manual,
    )
    manual = re.sub(
        r"VigilAI-(?:Alpha|alpha)-\d+\.\d+\.\d+\.exe",
        launcher_name,
        manual,
    )
    (package / "LEIA-ME.txt").write_text(manual, encoding="utf-8")


def create_archive(package: Path, archive: Path, start_percent: float = 85.0) -> None:
    files = [file for file in package.rglob("*") if file.is_file()]
    total = max(1, len(files))
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as output:
        for index, file in enumerate(files, start=1):
            output.write(file, file.relative_to(WORK).as_posix())
            percent = start_percent + (100.0 - start_percent) * index / total
            render_progress(percent, f"Compactando pacote ({index}/{total})")
    finish_progress()


def main() -> None:
    args = parser().parse_args()
    if not PYINSTALLER.exists():
        raise SystemExit(
            f"PyInstaller não encontrado em {PYINSTALLER}. "
            "Execute usando venv\\Scripts\\python.exe."
        )
    for required in (
        ROOT / "yolov8n.pt",
        ROOT / "config" / "config.yaml",
        ROOT / "LEIA-ME.txt",
    ):
        if not required.exists():
            raise FileNotFoundError(required)

    package_stem = f"VigilAI-{args.name}"
    launcher_name = f"{package_stem}.exe"
    archive_name = f"{package_stem}.zip"
    archive = DIST / archive_name
    package = WORK / f"{package_stem}-package"
    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir()
    DIST.mkdir(exist_ok=True)
    try:
        launcher = build(launcher_name.removesuffix(".exe"), "launcher.py", 0, 30)
        configurator = build("VigilAI-Config", "setup_server.py", 30, 55)
        core = build("VigilAI-Core", "app.py", 55, 85, "--collect-all", "torchvision")

        (package / "configurator").mkdir(parents=True)
        (package / "core" / "config").mkdir(parents=True)
        shutil.copy2(launcher, package / launcher.name)
        shutil.copy2(configurator, package / "configurator" / configurator.name)
        shutil.copy2(core, package / "core" / core.name)
        shutil.copy2(ROOT / "config" / "config.yaml", package / "core" / "config" / "config.yaml")
        shutil.copy2(ROOT / "yolov8n.pt", package / "core" / "yolov8n.pt")
        copy_manual(package, archive_name, launcher_name)

        for previous_archive in (
            archive,
            DIST / f"{package_stem}-single.zip",
        ):
            if previous_archive.exists():
                previous_archive.unlink()
        create_archive(package, archive)
        render_progress(100, f"Build concluída: {archive_name}")
        finish_progress()
        print(f"Arquivo gerado: {archive}")
    finally:
        shutil.rmtree(WORK, ignore_errors=True)


if __name__ == "__main__":
    main()
