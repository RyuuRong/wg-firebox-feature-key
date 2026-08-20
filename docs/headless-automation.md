# Headless automation

The whole procedure can be driven from a script, with **no manual interaction**, by connecting to the VMware console over **VNC**. This is how the procedure was originally developed and tested. Use this variant when you need repeatability (e.g. you expect to run the process again on another appliance).

> If you have console access to VMware Workstation, the manual flow in the main README is simpler and recommended.

---

## 1. Enable the VMware VNC server

Add these lines to the **GParted Live VM** `.vmx` file:

```
vnc.enabled = "TRUE"
vnc.password = "your-vnc-password"
vnc.port = "5900"
```

(VNC applies to the VM console — the GParted guest. VMware VNC has no encryption and no TLS; keep it on host-only interfaces.)

Restart the VM. The VNC endpoint is `127.0.0.1:5900` (or the VM host IP).

---

## 2. Install the VNC client library

```bash
pip install vncdotool
```

Helper scripts live in [`scripts/vnc/`](../scripts/vnc/):

| Script | Purpose |
|---|---|
| `vnc_key.py` | Press a key (optionally N times): `enter`, `tab`, `down`, `up`, `2`, … |
| `vnc_cmd.py` | Type a full command line followed by Enter |
| `vnc_shot.py` | Capture the console to a PNG file (for OCR-based verification) |
| `vnc_boot_menu.py` | Navigate the GParted boot menu and dialogs to reach the root shell |

All of them accept `--host`, `--port` and `--password` (defaults: `127.0.0.1:5900`, password `vncpass123` — change them).

---

## 3. Boot the GParted guest to a root shell

The GParted Live ISO boots into a **syslinux graphical menu** with a **30-second timeout** that defaults to the graphical entry. In a headless VNC session there is no usable video for X, so you must force **text mode**:

1. Power on the VM (via `vmrun start` or the Workstation UI).
2. Wait ~15–20 s for the menu to appear.
3. Navigate:

   ```
   down ×4  → "Other modes of GParted Live"
   Enter
   down ×3  → "Safe graphic settings (vga=normal)"
   Enter
   ```

4. Boot dialogs (debconf):

   | Dialog | Action |
   |---|---|
   | *Policy for handling keymaps* | `Enter` (accept default) |
   | *Which language do you prefer?* | `Enter` (default: US English) |
   | *Which mode do you prefer?* | `Tab`, `2`, `Enter` → **Enter command line prompt** |

You now have a **root bash shell**. The `bash: no job control in this shell` message is expected.

`vnc_boot_menu.py` automates steps 3–4 and prints progress; afterwards you control the shell with `vnc_cmd.py`/`vnc_key.py`.

---

## 4. VNC keyboard limitations (important!)

The VMware VNC server maps keysyms to scancodes **without shift state** for most characters. In practice:

| Character | Works? | Note |
|---|---|---|
| Letters (lowercase), digits, space | ✅ | |
| `-`, `/`, `.`, `;` | ✅ | |
| Enter, Tab, arrow keys | ✅ | |
| Uppercase letters | ❌ | typed as lowercase |
| `>`, `:`, `=`, `|`, `_`, `@` | ❌ | corrupted or dropped |

Workarounds used throughout the procedure:

- **Downloading files** — use `wget 10.0.1.2/key.pem` *without* a scheme; `wget` prepends `http://` automatically, so the broken `:` never has to be typed.
- **Editing `info.txt`** — `sed -i 's/utm/base/' /mnt/firebox/info.txt`… but `'`/`=` can be fragile. The safe variant we used avoids quotes and `=` entirely:

  ```
  sed -i s/utm/base/ /mnt/firebox/info.txt
  ```

- **Replacing `lickey.pem`** — never type the key content; `cp key.pem /mnt/firebox/etc/lickey.pem` (all safe characters).
- **Saving files in `vi`** — `Esc` then `ZZ` (save & quit) avoids the `:` of `:wq`.
- **Verification** — keep outputs short and re-check with `cat -e` (lowercase, no shift) or capture + OCR.

---

## 5. Serving the key file from the host

On the host, in the directory containing your key:

```powershell
Copy-Item public_key.pem key.pem        # short name, safe characters only
python -m http.server 80
```

In the guest (host-only network, host = `10.0.1.2`):

```
wget 10.0.1.2/key.pem
```

Verify with `cat key.pem` — the output must match `public_key.pem`.

---

## 6. Web UI session protocol (used by `apply_license.py`)

The Firebox Web UI is a **Python XML-RPC + REST** application. The script in [`scripts/apply_license.py`](../scripts/apply_license.py) implements the full flow:

1. **XML-RPC login**

   ```
   POST /agent/login          Content-Type: text/xml
   methodName: login
   params: [{password, user, domain: "Firebox-DB", uitype: "2"}]
   ```

   → returns `sid` + `csrf_token` (agent token).

2. **Establish the session** (form POST, creates the `session_id` cookie)

   ```
   POST /auth/login
   username, password, domain, sid, csrf_token, privilege, from_page
   ```

   → `303` to the dashboard.

3. **Read the page CSRF token**

   ```
   GET /system/featurekey
   → <input id="csrf_token" value="...">
   ```

4. **Submit the feature key** (note: the page has `<base href="/">`, so the endpoint is root-relative)

   ```
   POST /put_data/
   Content-Type: application/json
   X-CSRFToken: <page csrf token>
   Origin: https://<host>:<port>
   Referer: https://<host>:<port>/system/featurekey

   {
     "__module__": "modules.scripts.page.system.PageSystemFeatureKeyObj",
     "__class__": "PageSystemFeatureKeyPutObj",
     "action": "update_feature_key",
     "feature_key": "<full license text>",
     "new_feature_key_auto_sync": 0,
     "fk_expired_alarm_obj": {
       "__module__": "modules.scripts.vo.AlarmActionObj",
       "__class__": "AlarmActionObj",
       "name": "", "property": 0, "enable": 1, "severity": 7, "protocol": 7,
       "trap_enable": 0, "block_ip_enable": 0, "remote_enable": 0,
       "action_type": 1, "launch_interval": 900, "repeat_count": 10
     }
   }
   ```

   → success response:

   ```json
   {"status": true, "message": ["The changes were saved successfully"]}
   ```

5. **Verify** — `GET /system/featurekey` again; the `feature_list_all` JavaScript array is now populated with your features.

> **One session only.** The Firebox allows a **single admin session**. If a Web UI or CLI session is already active, new logins fail with *"admin is currently logged in from …"*. Log out properly (`POST /auth/logout` with a valid page token) or reboot the appliance.

---

## 7. Cleanup between runs

- `umount /mnt/firebox && sync && poweroff` in the guest, then remove the GParted VM (or detach the disk).
- Prefer `vmrun stop hard` + `vmrun start` over `vmrun reset` (reset is unreliable on the Firebox V: it powers off but may fail to power back on).
- Reboot the Firebox once after injecting the key and before applying the license (see main README, Step 5).