# Troubleshooting

Every problem encountered while developing this procedure, with the fix that worked.

---

## 1. The feature key is silently not applied (no error, still default key)

**Symptom:** After `PUT /put_data/` returns success (or after pasting in the Web UI), `System → Feature Key` still shows the default registration key, and `show feature-key` on the CLI shows an expiration date (`Sep-…`) instead of `never`.

**Cause:** The Firebox reads `/etc/lickey.pem` **at boot time** and keeps it in memory. If you replace the key and immediately upload the license *without rebooting*, the running system still validates against the **old** key and rejects the new signature.

**Fix:** Replace `lickey.pem` → **reboot the Firebox** (wait for it to come back up) → *then* upload the feature key.

---

## 2. "Login failed. 'admin' is currently logged in from …"

**Symptom:** Web UI login or SSH CLI login (port `4118`) fails with this message.

**Cause:** The Firebox allows only **one** admin session at a time, shared between Web UI and CLI.

**Fix:** Close the other session properly:
- Web UI: `POST /auth/logout` with the session's page CSRF token, or simply wait for the idle timeout.
- If the session belongs to a script that already exited (cookie jar lost), the reliable option is to **reboot the appliance** — all sessions are cleared at boot.

---

## 3. GParted Live shuts down / blank screen after the boot menu

**Symptom:** The GParted VM powers off (or the screen goes black) shortly after the boot menu.

**Cause:** The syslinux menu has a **30-second timeout** and the default entry boots the **graphical** mode. Without a usable display (headless/VNC), X fails and the guest dies.

**Fix:** Intercept the menu and pick a text entry:
- **Other modes of GParted Live → Safe graphic settings (vga=normal)**, or
- **Other modes of GParted Live → Failsafe mode**.

`scripts/vnc/vnc_boot_menu.py` automates this.

---

## 4. `vmrun reset` powers the VM off and doesn't power it back on

**Symptom:** `vmrun reset` reports *"The virtual machine needs to be powered on"*; the VM ends up off.

**Cause:** On the Firebox V, `reset` performs a guest-initiated power cycle that fails without ACPI cooperation.

**Fix:** Use

```powershell
vmrun stop  <vmx> hard
vmrun start <vmx> gui
```

---

## 5. VNC keyboard: special characters are corrupted

**Symptom:** Typed commands contain `.` instead of `>`, `;` instead of `:`, lowercase instead of uppercase, etc.

**Cause:** The VMware VNC server does not apply shift state for many keysyms.

**Workarounds:**

| Need | Instead of | Use |
|---|---|---|
| Download a file | `wget http://10.0.1.2/key.pem` | `wget 10.0.1.2/key.pem` (wget adds `http://`) |
| Replace a string | `sed -i 's/utm/base/'` | `sed -i s/utm/base/` |
| Save in `vi` | `:wq` | `Esc` then `ZZ` |
| Check line endings | `cat -A file` (uppercase A) | `cat -e file` |
| Clear the screen | `clear` (needs `TERM`) | scroll with `Enter` ×40 |

See [headless-automation.md](headless-automation.md) for the full table.

---

## 6. `wget` can't resolve the host

**Symptom:** `unable to resolve host address 'http'`.

**Cause:** The `://` of the URL was corrupted by the keyboard, so `wget` received a bare word instead of a URL.

**Fix:** omit the scheme and the port:

```
wget 10.0.1.2/key.pem
```

`wget` prepends `http://` automatically; port 80 avoids the `:` of `:8000`.

---

## 7. `put_data` returns 403 Forbidden

**Symptom:** `POST /put_data/` → `403 Forbidden` ("Request forbidden -- authorization will not help").

**Cause:** The CSRF check failed. The endpoint requires the **page** CSRF token (`<input id="csrf_token">` from `GET /system/featurekey`) plus the `Origin` and `Referer` headers.

**Fix:** send all of:

```
X-CSRFToken: <page csrf token>
Origin:      https://<host>:<port>
Referer:     https://<host>:<port>/system/featurekey
```

Also make sure you post to the **root-relative** endpoint `/put_data/` — the page contains `<base href="/">`, so `put_data/` from the JavaScript resolves to `/put_data/`, **not** `/system/put_data/`.

---

## 8. Python `cryptography` can't load the key ("unsupported curve")

**Symptom:** `sign_feature_key.py` raises an error about the curve/OID.

**Cause:** `cryptography >= 48` removed `sect163k1` (OID `1.3.132.0.1`).

**Fix:** use the OpenSSL-based scripts (`sign_openssl.py`, `verify_openssl.py`) with OpenSSL 3.x, or pin an older `cryptography` release.

---

## 9. The mount point doesn't exist

**Symptom:** `mount /dev/sda2 /mnt/firebox` fails with *"mount point does not exist"*.

**Cause:** Fresh live-boot sessions do not pre-create `/mnt/firebox`.

**Fix:**

```bash
mkdir -p /mnt/firebox
mount /dev/sda2 /mnt/firebox
```

---

## 10. Long file transfers are unreliable (base64 / redirects / pipes)

**Symptom:** `echo <base64> | base64 -d > file` produces broken output or "extra operand" errors.

**Cause:** The keyboard corrupts `|`, `>` and `=` (see issue 5).

**Fix:** never type file content — transfer files over HTTP with `wget` and move them with `cp`/`mv` (all safe characters):

```bash
wget 10.0.1.2/key.pem
cp key.pem /mnt/firebox/etc/lickey.pem
```