import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from desktop import core, disk_worker, wsl


SAMPLE = """Serial Number: FVE00000000000
License ID: FVE00000000000
Name: lab
Model: FireboxV-XLG
Version: 2
Feature: APT@Sep-13-2026;+TOKEN
Feature: SPAMBLOCKER@Sep-13-2026;SUFFIX
Feature: SESSION#15000000
Feature: FIREWARE_XTM
Expiration: Sep-13-2026
Signature: 0000
"""


class FeatureKeyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.private, self.public = core.create_keys(self.root)

    def test_roundtrip_tamper_and_wrong_key(self):
        signed = core.sign_license(SAMPLE, self.private, self.public)
        core.verify_license(signed, self.public)
        with self.assertRaisesRegex(ValueError, "Firma inválida"):
            core.verify_license(signed.replace("Name: lab", "Name: altered"), self.public)
        other_private, other_public = core.create_keys(self.root / "other")
        with self.assertRaisesRegex(ValueError, "no corresponde"):
            core.sign_license(SAMPLE, self.private, other_public)

    def test_key_and_output_protection(self):
        original = self.private.read_bytes()
        with self.assertRaises(FileExistsError):
            core.create_keys(self.root)
        self.assertEqual(self.private.read_bytes(), original)
        target = self.root / "fk.txt"
        core.write_new(target, b"first")
        with self.assertRaises(FileExistsError):
            core.write_new(target, b"second")
        self.assertEqual(target.read_bytes(), b"first")

    def test_export_import_dates_and_suffixes(self):
        exported = "FBV1\nYour Serial Number\nProduct: WatchGuard\nSerial Number: FVE-OTHER\nFK:\n" + SAMPLE
        cleaned = core.import_license(exported)
        self.assertEqual(cleaned, SAMPLE)
        updated = core.set_expiration(cleaned, "2032-01-01")
        self.assertIn("Feature: APT@Jan-01-2032;+TOKEN", updated)
        self.assertIn("Feature: SPAMBLOCKER@Jan-01-2032;SUFFIX", updated)
        self.assertIn("Feature: SESSION#15000000", updated)
        self.assertIn("Expiration: Jan-01-2032", updated)
        with self.assertRaises(ValueError):
            core.set_expiration(cleaned, "2032-02-30")

    def test_invalid_import(self):
        for text in (SAMPLE + "Name: extra\n", SAMPLE.replace("Signature:", "Unknown:"),
                     SAMPLE.replace("License ID:", "Name:"), SAMPLE + "\x00"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                core.import_license(text)

    @unittest.skipUnless(shutil.which("openssl"), "OpenSSL is required for interoperability")
    def test_openssl_interoperability(self):
        signed = core.sign_license(SAMPLE, self.private, self.public)
        source = self.root / "feature.txt"
        source.write_text(signed)
        normalized = self.root / "normalized.bin"
        normalized.write_bytes(core.normalized(signed))
        signature = self.root / "signature.bin"
        signature.write_bytes(bytes.fromhex(signed.split("Signature:")[1].strip().replace("-", "")))
        subprocess.run(["openssl", "dgst", "-sha1", "-verify", str(self.public),
                        "-signature", str(signature), str(normalized)], check=True, capture_output=True)
        result = subprocess.run(["openssl", "dgst", "-sha1", "-sign", str(self.private), str(normalized)],
                                check=True, capture_output=True)
        core.verify_license(SAMPLE.split("Signature:")[0] + "Signature: " + result.stdout.hex(), self.public)


class DiskGuardTests(unittest.TestCase):
    def test_same_disk_and_existing_output_rejected_before_tools(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.vmdk"
            key = Path(folder) / "key.pem"
            source.write_bytes(b"original")
            key.write_bytes(b"public")
            with mock.patch.object(disk_worker, "run") as run:
                with self.assertRaises(ValueError):
                    disk_worker.modify(source, source, key)
                run.assert_not_called()

    def test_lock_and_snapshot_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.vmdk"
            source.touch()
            lock = Path(folder) / "machine.vmx.lck"
            lock.mkdir()
            with self.assertRaisesRegex(ValueError, "bloqueos"):
                disk_worker.image_info(source)
            lock.rmdir()
            with mock.patch.object(disk_worker, "run", return_value='{"format":"vmdk","backing-filename":"parent.vmdk"}'):
                with self.assertRaisesRegex(ValueError, "snapshots"):
                    disk_worker.image_info(source)

    def test_guestfish_quote_and_failed_worker(self):
        with self.assertRaises(ValueError):
            disk_worker.quote("filename\nrun")
        self.assertEqual(disk_worker.quote('path with "quotes"'), '"path with \\"quotes\\""')
        result = subprocess.CompletedProcess([], 1, '{"ok":false,"error":"broken"}', "")
        with self.assertRaisesRegex(RuntimeError, "broken"):
            wsl._decode(result)

    def test_export_preserves_existing_ova_and_checks_locks(self):
        with tempfile.TemporaryDirectory() as folder:
            vmx, ova = Path(folder) / "vm.vmx", Path(folder) / "vm.ova"
            vmx.touch()
            ova.write_bytes(b"existing")
            with self.assertRaises(FileExistsError):
                core.export_ova("missing-ovftool", vmx, ova)
            ova.unlink()
            (Path(folder) / "vm.vmx.lck").mkdir()
            with self.assertRaisesRegex(ValueError, "bloqueos"):
                core.export_ova("missing-ovftool", vmx, ova)


@unittest.skipUnless(os.environ.get("FIREBOX_DISK_INTEGRATION") == "1", "Set FIREBOX_DISK_INTEGRATION=1 with libguestfs/qemu installed")
class DiskIntegrationTests(unittest.TestCase):
    def test_real_vmdk_copy_original_unchanged_and_output_verified(self):
        for tool in ("qemu-img", "guestfish", "openssl"):
            self.assertIsNotNone(shutil.which(tool), tool)
        with tempfile.TemporaryDirectory(prefix="firebox-integration-") as folder:
            root = Path(folder)
            raw, source, output = [root / name for name in ("disk.raw", "source.vmdk", "prepared.vmdk")]
            private, public = core.create_keys(root / "keys")
            info = root / "info.txt"
            info.write_text("Product = utm\nPlatform = liberty\nVersion = synthetic-test\n")
            disk_worker.run(["qemu-img", "create", "-f", "raw", str(raw), "96M"])
            disk_worker.run(["guestfish", "--rw", "--format=raw", "-a", str(raw)],
                            "run\npart-disk /dev/sda mbr\nmkfs ext2 /dev/sda1\nmount /dev/sda1 /\nmkdir /etc\n"
                            + f"upload {disk_worker.quote(public)} /etc/lickey.pem\nupload {disk_worker.quote(info)} /info.txt\nsync\numount-all\n")
            disk_worker.run(["qemu-img", "convert", "-f", "raw", "-O", "vmdk", str(raw), str(source)])
            before = hashlib.sha256(source.read_bytes()).hexdigest()
            details = disk_worker.inspect(source)
            self.assertEqual(details["partition"], "/dev/sda1")
            result = disk_worker.modify(source, output, public)
            self.assertTrue(output.is_file())
            self.assertIn("Product = base", result["info"])
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)
            self.assertIn("Product = utm", disk_worker.inspect(source)["info"])
            self.assertIn("Product = base", disk_worker.inspect(output)["info"])
            original = root / "original-info.txt"
            disk_worker.fish(output, f"mount-ro /dev/sda1 /\ndownload /info.txt.bak {disk_worker.quote(original)}\numount-all")
            self.assertEqual(original.read_text(), info.read_text())


if __name__ == "__main__":
    unittest.main()
