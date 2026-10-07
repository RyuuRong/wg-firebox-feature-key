import hashlib
import datetime as dt
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

    def test_expired_export_requires_renewal_before_signing(self):
        today = dt.date(2026, 10, 7)
        exported = "Your Serial Number\nProduct: WatchGuard\nSerial Number: FVE-OTHER\nFK:\n" + SAMPLE
        with self.assertRaisesRegex(ValueError, "Firmar no cambia las fechas"):
            core.prepare_for_signing(exported, today=today)
        renewed = core.set_expiration(exported, "2032-01-01")
        cleaned, review = core.prepare_for_signing(renewed, "FVE-00000000000", today=today)
        self.assertTrue(cleaned.startswith("Serial Number: FVE00000000000\n"))
        self.assertNotIn("Your Serial Number", cleaned)
        self.assertNotIn("Product:", cleaned)
        self.assertNotIn("FK:", cleaned)
        self.assertEqual(review["expiration"], "Jan-01-2032")
        self.assertEqual(review["expired"], [])
        self.assertIn(";+TOKEN", cleaned)
        self.assertIn(";SUFFIX", cleaned)
        self.assertIn("Feature: SESSION#15000000", cleaned)
        signed = core.sign_license(cleaned, self.private, self.public)
        core.verify_license(signed, self.public)

    def test_signing_alone_does_not_renew_expiration(self):
        signed = core.sign_license(SAMPLE, self.private, self.public)
        core.verify_license(signed, self.public)
        review = core.license_review(signed, today=dt.date(2026, 10, 7))
        self.assertEqual(review["expiration"], "Sep-13-2026")
        self.assertEqual(len(review["expired"]), 3)
        with self.assertRaisesRegex(ValueError, "fechas vencidas"):
            core.prepare_for_signing(signed, today=dt.date(2026, 10, 7))

    def test_review_rejects_wrong_serial_and_expired_features(self):
        renewed = core.set_expiration(SAMPLE, "2032-01-01")
        with self.assertRaisesRegex(ValueError, "serial del FK no corresponde"):
            core.prepare_for_signing(renewed, "FVE99999999999", today=dt.date(2026, 10, 7))
        expired_feature = renewed.replace("APT@Jan-01-2032", "APT@Sep-13-2026")
        with self.assertRaisesRegex(ValueError, "APT: Sep-13-2026"):
            core.prepare_for_signing(expired_feature, today=dt.date(2026, 10, 7))
        never_expiring = SAMPLE.replace("Expiration: Sep-13-2026", "Expiration: never")
        self.assertEqual(len(core.license_review(never_expiring, today=dt.date(2026, 10, 7))["expired"]), 2)

    def test_date_change_invalidates_existing_signature(self):
        signed = core.sign_license(SAMPLE, self.private, self.public)
        changed = core.set_expiration(signed, "2032-01-01")
        self.assertTrue(changed.endswith("Signature: 0000\n"))
        with self.assertRaises(ValueError):
            core.verify_license(changed, self.public)
        with self.assertRaises(ValueError):
            core.license_review(SAMPLE.replace("Sep-13-2026", "Feb-30-2026"))

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
    def test_prepared_ovf_manifest_and_ide_binding(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            ovf, disk, manifest = root / "vm.ovf", root / "disk.vmdk", root / "vm.mf"
            ovf.write_text('''<Envelope xmlns="http://schemas.dmtf.org/ovf/envelope/1" xmlns:o="http://schemas.dmtf.org/ovf/envelope/1" xmlns:r="http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/CIM_ResourceAllocationSettingData"><References><File o:href="disk.vmdk"/></References><VirtualSystem><VirtualHardwareSection><Item><r:ResourceType>5</r:ResourceType><r:InstanceID>5</r:InstanceID></Item><Item><r:ResourceType>17</r:ResourceType><r:Parent>5</r:Parent><r:AddressOnParent>0</r:AddressOnParent></Item></VirtualHardwareSection></VirtualSystem></Envelope>''')
            disk.write_bytes(b"synthetic content")
            manifest.write_text("\n".join(f"SHA256({path.name})= {hashlib.sha256(path.read_bytes()).hexdigest()}" for path in (ovf, disk)))
            result = core.inspect_ovf(ovf)
            self.assertEqual(result["disks"], [{"controller": "IDE", "position": "0"}])
            disk.write_bytes(b"altered")
            with self.assertRaisesRegex(ValueError, "hash no coincide"):
                core.inspect_ovf(ovf)

    def test_vmx_reports_controllers_and_multiple_disks(self):
        with tempfile.TemporaryDirectory() as folder:
            vmx = Path(folder) / "vm.vmx"
            vmx.write_text('ide0:0.present = "TRUE"\nide0:0.fileName = "original.vmdk"\nscsi0.virtualDev = "lsilogic"\nscsi0:0.fileName = "prepared.vmdk"\nfirmware = "efi"\n')
            result = core.inspect_vmx(vmx)
            self.assertEqual(result["firmware"], "efi")
            self.assertEqual(result["disks"][0]["position"], "ide0:0")
            self.assertEqual(result["disks"][1]["controller"], "lsilogic")
            self.assertTrue(result["warning"])

    def test_descriptor_adapter_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "disk.vmdk"
            path.write_bytes(b'# Disk DescriptorFile\nddb.adapterType = "lsilogic"\n')
            self.assertEqual(disk_worker.adapter_type(path), "lsilogic")
            path.write_bytes(b'# Disk DescriptorFile\nddb.adapterType = "unknown"\n')
            with self.assertRaises(ValueError):
                disk_worker.adapter_type(path)

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
