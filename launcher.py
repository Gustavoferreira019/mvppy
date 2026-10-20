import ctypes
import json
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path


BASE_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
CORE_EXE = BASE_DIR / "core" / "VigilAI-Core.exe"
CONFIG_EXE = BASE_DIR / "configurator" / "VigilAI-Config.exe"
PANEL_URL = "http://127.0.0.1:8765"
CORE_LOG = BASE_DIR / "core.log"
CONFIG_LOG = BASE_DIR / "configurator.log"


def wait_for_panel(config_process, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if config_process.poll() is not None:
            raise RuntimeError("O painel de configuração foi encerrado antes de ficar disponível.")
        try:
            with urllib.request.urlopen(PANEL_URL, timeout=1):
                return
        except (urllib.error.URLError, TimeoutError, OSError):
            time.sleep(0.5)
    raise RuntimeError("O painel não respondeu em http://127.0.0.1:8765.")


def show_error(error):
    message = f"Não foi possível iniciar o VIGIL.AI.\n\n{error}\n\nConsulte launcher_error.log."
    try:
        (BASE_DIR / "launcher_error.log").write_text(traceback.format_exc(), encoding="utf-8")
    except OSError:
        pass
    ctypes.windll.user32.MessageBoxW(None, message, "VIGIL.AI", 0x10)


def main():
    if not CORE_EXE.exists() or not CONFIG_EXE.exists():
        raise FileNotFoundError("Os componentes do VIGIL.AI não foram encontrados na pasta do programa.")

    core_log = CORE_LOG.open("a", encoding="utf-8", errors="replace")
    config_log = CONFIG_LOG.open("a", encoding="utf-8", errors="replace")
    app_process = None
    config_process = None
    try:
        app_process = subprocess.Popen(
            [str(CORE_EXE)], cwd=str(BASE_DIR), stdout=core_log, stderr=subprocess.STDOUT
        )
        config_process = subprocess.Popen(
            [str(CONFIG_EXE)], cwd=str(BASE_DIR), stdout=config_log, stderr=subprocess.STDOUT
        )
        wait_for_panel(config_process)
        webbrowser.open(PANEL_URL)

    finally:
        try:
            if app_process is not None:
                app_process.wait()
        finally:
            if config_process is not None and config_process.poll() is None:
                config_process.terminate()
                try:
                    config_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    config_process.kill()
            core_log.close()
            config_log.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        show_error(error)
