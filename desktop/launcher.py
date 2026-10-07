"""PyInstaller entry point with an offline packaged-dependency readiness check."""
import json
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch


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
        expired = text.replace("Expiration: never", "Expiration: Jan-01-2000")
        try:
            core.prepare_for_signing(expired)
        except ValueError:
            pass
        else:
            raise RuntimeError("The renewal workflow accepted an expired FK")
        import datetime as dt
        date = (dt.date.today() + dt.timedelta(days=365)).isoformat()
        renewed, review = core.prepare_for_signing(core.set_expiration(expired, date), "TEST")
        core.verify_license(core.sign_license(renewed, private, public), public)
        try:
            core.verify_license(signed.replace("Name: test", "Name: altered"), public)
        except ValueError:
            pass
        else:
            raise RuntimeError("Tampered text was accepted")
    with tempfile.TemporaryDirectory(prefix="firebox-gui-selftest-") as directory:
        private, public = core.create_keys(directory)
        output = Path(directory) / "renewed.txt"
        app = Assistant()
        app.withdraw()
        app.update()
        if len(app.tabs.tabs()) != 5:
            raise RuntimeError("The application did not create its five workflow tabs")
        app.private.set(str(private))
        app.public.set(str(public))
        app.expected_serial.set("TEST")
        exported = "Your Serial Number\nProduct: WatchGuard\nSerial Number: WRONG\nFK:\n" + expired
        app.replace_text(core.import_license(exported))
        with patch("desktop.app.messagebox.showerror") as error, patch("desktop.app.filedialog.asksaveasfilename", return_value=str(output)) as save, patch("desktop.app.messagebox.askyesno", return_value=True):
            app.sign()
            if not error.called or save.called or output.exists():
                raise RuntimeError("The GUI did not block signing an expired FK")
            app.expiry_preset.set("Dentro de 10 años")
            app.select_expiry_preset()
            app.change_expiration()
            app.sign()
            deadline = time.monotonic() + 10
            while app.busy and time.monotonic() < deadline:
                app.update()
                time.sleep(0.01)
            if app.busy or not output.is_file():
                raise RuntimeError("The GUI renewal workflow did not complete")
            saved = output.read_text()
            core.verify_license(saved, public)
            if not saved.startswith("Serial Number: TEST\n") or "Jan-01-2000" in saved:
                raise RuntimeError("The saved FK retained export headers or expired dates")
        app.close()
    core.write_new(report, json.dumps({"keys": "passed", "signature": "passed", "tamper": "passed", "renewal": "passed", "gui": "passed", "worker": "present"}).encode())

if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--self-test":
        self_test(sys.argv[2])
    else:
        from desktop.app import Assistant
        Assistant().mainloop()
