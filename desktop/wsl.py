"""Invoke the bundled Linux worker through WSL without interpolated shell commands."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def execute(request, distro="Ubuntu"):
    worker = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "disk_worker.py"
    if os.name != "nt":
        with tempfile.TemporaryDirectory(prefix="firebox-request-") as directory:
            manifest = Path(directory) / "request.json"
            manifest.write_text(json.dumps(request), encoding="utf-8")
            return _decode(subprocess.run([sys.executable, str(worker), str(manifest)],
                                         capture_output=True, text=True))
    prefix = ["wsl.exe", "--distribution", distro, "--exec"]

    def linux_path(path):
        result = subprocess.run(prefix + ["wslpath", "-a", "-u", str(Path(path).resolve())],
                                capture_output=True, text=True, encoding="utf-8")
        if result.returncode:
            raise RuntimeError("No se pudo acceder a WSL. Instala o inicia la distribución indicada.\n" + result.stderr)
        return result.stdout.strip()

    converted = dict(request)
    for field in ("source", "output", "key"):
        if field in converted:
            converted[field] = linux_path(converted[field])
    with tempfile.TemporaryDirectory(prefix="firebox-request-") as directory:
        manifest = Path(directory) / "request.json"
        manifest.write_text(json.dumps(converted), encoding="utf-8")
        result = subprocess.run(prefix + ["python3", linux_path(worker), linux_path(manifest)],
                                capture_output=True, text=True, encoding="utf-8")
        return _decode(result)


def _decode(result):
    try:
        response = json.loads(result.stdout)
    except (ValueError, TypeError) as exc:
        raise RuntimeError("WSL no devolvió un resultado válido.\n" + result.stderr[-2000:]) from exc
    if result.returncode or not response.get("ok"):
        raise RuntimeError(response.get("error", result.stderr[-2000:]))
    return response["result"]
