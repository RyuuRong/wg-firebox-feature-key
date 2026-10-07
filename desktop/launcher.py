"""PyInstaller entry point with an offline packaged-dependency readiness check."""
import json
from pathlib import Path
import sys
import tempfile


def self_test(report):
    from desktop import core
    from desktop.app import Assistant
    worker = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "disk_worker.py"
    if not worker.is_file():
        raise RuntimeError("The Linux worker is missing from the application bundle")
    with tempfile.TemporaryDirectory(prefix="firebox-selftest-") as directory:
        private, public = core.create_keys(directory)
        text = "Serial Number: TEST\nLicense ID: TEST\nName: test\nModel: FireboxV-XLG\nVersion: 2\nFeature: FIREWARE_XTM\nExpiration: never\nSignature: 00\n"
        signed = core.sign_license(text, private, public)
        core.verify_license(signed, public)
        try:
            core.verify_license(signed.replace("Name: test", "Name: altered"), public)
        except ValueError:
            pass
        else:
            raise RuntimeError("Tampered text was accepted")
    app = Assistant()
    app.update()
    if len(app.tabs.tabs()) != 5:
        raise RuntimeError("The application did not create its five workflow tabs")
    app.close()
    core.write_new(report, json.dumps({"keys": "passed", "signature": "passed", "tamper": "passed", "gui": "passed", "worker": "present"}).encode())

if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--self-test":
        self_test(sys.argv[2])
    else:
        from desktop.app import Assistant
        Assistant().mainloop()
