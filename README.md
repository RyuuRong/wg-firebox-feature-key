# WatchGuard Firebox V — Feature Key Replacement

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> **Disclaimer:** This project is provided for **educational and research purposes only**, to be used exclusively on hardware that you own or are authorized to administer. Replacing the signing key and installing a custom feature key may violate your license agreement with WatchGuard Technologies. The authors assume no responsibility for any use of this material. Use at your own risk.

---

## Table of Contents

- [What is this?](#what-is-this)
- [How it works](#how-it-works)
- [Requirements](#requirements)
- [Procedure](#procedure)
  - [Step 0 — Environment preparation](#step-0--environment-preparation)
  - [Step 1 — Generate your key pair](#step-1--generate-your-key-pair)
  - [Step 2 — Create and sign your feature key](#step-2--create-and-sign-your-feature-key)
  - [Step 3 — Verify the signature locally](#step-3--verify-the-signature-locally)
  - [Step 4 — Modify the Firebox system partition](#step-4--modify-the-firebox-system-partition)
  - [Step 5 — Apply the feature key](#step-5--apply-the-feature-key)
  - [Step 6 — Verify the result](#step-6--verify-the-result)
- [Repository layout](#repository-layout)
- [Headless automation](#headless-automation)
- [Troubleshooting](#troubleshooting)
- [Legal](#legal)

---

## What is this?

WatchGuard **Firebox V** (the virtual firewall appliance) validates the *feature key* (license) that you upload through the Web UI using a cryptographic **public key** stored on the appliance at:

```
/etc/lickey.pem
```

Only a feature key whose signature validates against that public key is accepted. By replacing that key with one from a key pair that **you** control, you can generate, sign, and install your own feature keys that unlock every feature of the device.

This repository documents a complete, step-by-step, reproducible procedure to do exactly that, including:

- Generating the EC key pair (curve `sect163k1`).
- Creating a feature key file from a template.
- Signing and verifying it.
- Injecting your public key into the Firebox disk image using **GParted Live**.
- Installing the feature key through the Web UI (interactively or fully scripted).

---

## How it works

```
┌─────────────────┐      ┌──────────────────────┐      ┌──────────────────────┐
│ 1. Key pair     │      │ 2. Feature key       │      │ 3. Firebox disk      │
│                 │      │                      │      │                      │
│ private_key.pem │─────▶│ feature_key.txt      │─────▶│ /etc/lickey.pem =    │
│ public_key.pem  │ sign │ Signature: <hex>     │      │   public_key.pem     │
└─────────────────┘      └──────────────────────┘      │ /info.txt:           │
                                                       │   Product = base     │
                                                       └──────────┬───────────┘
                                                                  │ boot
                                                        ┌─────────▼───────────┐
                                                        │ 4. Web UI           │
                                                        │    System → Feature │
                                                        │    Key → paste → OK │
                                                        └─────────────────────┘
```

The device verifies the signature of the feature key with `/etc/lickey.pem` (read **at boot time**), so both the key replacement and the license upload must be followed by a reboot of the appliance.

---

## Requirements

| Item | Notes |
|---|---|
| Windows host (this guide was written on Windows 10/11) | Adjustments possible on Linux/macOS |
| VMware Workstation (Pro or Player) | Used for both the Firebox V and the GParted Live VM |
| GParted Live ISO (`gparted-live-1.8.x`) | [Download](https://gparted.org/download.php) |
| Python 3.10+ | For the signing/automation scripts |
| OpenSSL 3.x | Bundled with *Git for Windows* (`C:\Program Files\Git\usr\bin\openssl.exe`) or any distro package |
| A WatchGuard Firebox V appliance (VM) you own | Fireware 12.6.x tested |

> **Note on `cryptography`:** Python `cryptography >= 48` **removed** support for the `sect163k1` curve (OID `1.3.132.0.1`) required here. Use the bundled OpenSSL scripts (`sign_openssl.py` / `verify_openssl.py`) or an older `cryptography` release.

---

## Procedure

### Step 0 — Environment preparation

1. **Locate your Firebox V virtual disk.** In our setup:
   - VM: `FireboxV_12_6_2_U2.vmx`
   - Disk: `FireboxV_12_6_2_U2-disk1.vmdk` (~550 MB, dynamically grown)

2. **Create a second VM** (`GPartedLinux.vmx`) that:
   - Attaches the **Firebox VMDK** as an IDE disk (`ide0:0`).
   - Attaches the **GParted Live ISO** as a CD-ROM (`ide1:0`).
   - Uses a **host-only network** (e.g. `VMnet1`) so the guest can reach the host over HTTP (used to transfer the key file). Host side of `VMnet1` is typically `10.0.1.2`.

3. **Prepare an HTTP server on the host** to serve your `public_key.pem`:

   ```powershell
   # copy it under a name with only "safe" characters (no spaces, no special chars)
   Copy-Item public_key.pem key.pem
   python -m http.server 80 -d .\cert
   ```

   You will later download it in the guest with `wget 10.0.1.2/key.pem`.

---

### Step 1 — Generate your key pair

The device uses an EC key on the **`sect163k1`** curve:

```bash
openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:sect163k1 -out private_key.pem
openssl ec -in private_key.pem -pubout -out public_key.pem
```

Sanity check — the public key must be the 142-byte SPKI PEM:

```bash
openssl ec -in private_key.pem -text -noout
openssl pkey -pubin -in public_key.pem -text -noout
```

**Keep `private_key.pem` secret. Never commit it to the repository.**

---

### Step 2 — Create and sign your feature key

1. Copy the template (`templates/feature_key_template.txt`) and edit it for your appliance:

   ```
   Serial Number: FVE603700BD64        ← your serial number
   License ID:   FVE603700BD64
   Name:         FVE603700
   Model:        FireboxV-XLG
   Version:      2
   Feature:      ACCESS_PORTAL@Jan-01-2032
   ...                                   ← features you want
   Expiration:   never
   Signature:    <placeholder>
   ```

   The `Feature:` lines accept two value forms:
   - `Feature: NAME@MON-DD-YYYY` — expires on the given date,
   - `Feature: NAME#NUMBER` — quantity based,
   - `Feature: NAME` — permanent.

2. Sign the file (this overwrites the `Signature:` line):

   ```bash
   python scripts/sign_openssl.py feature_key.txt private_key.pem
   ```

   What happens behind the scenes:
   - All whitespace characters (` `, `\t`, `\r`, `\n`, `\v`, `\f`) are removed from the license text **before** the `Signature:` marker.
   - An **ECDSA-SHA1** signature is computed over the normalized bytes.
   - The signature is written as `Signature: <hex>`, grouped in 16-character blocks joined by `-`.

3. Result example:

   ```
   Signature: 302e02150102ab0f-14d5a4eaaa933c0a-08402dbbef74b481-6e021500ae551a23-480897d3a8b7a1eb-f384f83d98919ca3
   ```

---

### Step 3 — Verify the signature locally

Before touching the appliance, confirm the signed file validates against your public key:

```bash
python scripts/verify_openssl.py feature_key.txt public_key.pem
# → Success! This is correct feature key
```

---

### Step 4 — Modify the Firebox system partition

> This step boots the Firebox disk with GParted Live. **Back up the VMDK first** (`copy` it or take a VMware snapshot).

1. Power on the GParted Live VM (with the Firebox disk attached).

2. **Boot menu** (syslinux). The menu auto-boots the default (graphical) entry after **30 seconds**. Either:
   - Let it boot graphical mode — works fine when the VMware console has a display, or
   - For text mode (useful headless): select **Other modes of GParted Live** → **Safe graphic settings (vga=normal)**.

3. **Boot dialogs**:
   - *Policy for handling keymaps* → press Enter (accept default).
   - *Which language do you prefer?* → press Enter (default: US English).
   - *Which mode do you prefer?* → choose **`(2) Enter command line prompt`** (type `2`, or `Tab` then `2`, then Enter).

   You should land in a **root bash shell**. The messages
   ```
   bash: cannot set terminal process group (1416): Inappropriate ioctl for device
   bash: no job control in this shell
   ```
   are normal.

4. **Identify the Firebox disk and its system partition:**

   ```bash
   lsblk
   # sda  ── the Firebox disk (≈4.4 GB in our VM)
   #   sda2 ── ext partition holding /etc  (the system partition)
   ```

   The partition holding `etc/` is the one we need. In our appliance it was **`/dev/sda2`** (an ext2/ext3 partition).

5. **Mount it:**

   ```bash
   mkdir -p /mnt/firebox
   mount /dev/sda2 /mnt/firebox
   ls /mnt/firebox/etc
   # ... lickey.pem ...      ← present here
   cat /mnt/firebox/info.txt
   # Product = utm           ← must become "base"
   # Platform = 630604
   ```

6. **Transfer your public key into the guest** (using the HTTP server from Step 0):

   ```bash
   wget 10.0.1.2/key.pem
   ```

   > `wget` automatically prepends `http://` when no scheme is given, so no `://` has to be typed (which matters for headless/keyboard automation).

7. **Replace the system key:**

   ```bash
   cp key.pem /mnt/firebox/etc/lickey.pem
   ```

8. **Switch the product tier** so the license is accepted for the "base" model:

   ```bash
   sed -i 's/utm/base/' /mnt/firebox/info.txt
   ```

9. **Verify both changes:**

   ```bash
   cat /mnt/firebox/etc/lickey.pem
   # -----BEGIN PUBLIC KEY-----   ← must be YOUR key
   cat /mnt/firebox/info.txt
   # Product = base
   ```

10. **Cleanly unmount and shut down:**

    ```bash
    umount /mnt/firebox
    sync
    poweroff
    ```

    Then remove (or disconnect) the GParted VM / ISO so the disk can be attached back to the Firebox VM.

> **Why `Product = base`?** The Firebox compares the product tier reported in `/info.txt` with the one expected by the feature key. A device reporting `utm` rejects keys issued for the base model with *Invalid License*. The original research (see [Credits](#credits)) established `base` as the accepted value.

---

### Step 5 — Apply the feature key

> ⚠️ **The appliance reads `/etc/lickey.pem` at boot.** After replacing the key you **must boot the Firebox at least once** before uploading the license — otherwise the running system still verifies with the *old* key and silently rejects your new feature key.

1. Start the Firebox VM and wait for it to be reachable:

   ```powershell
   ping 10.0.1.1
   ```

2. **Interactive (recommended):** open `https://<ip>:8080`, log in, go to **System → Feature Key**, click **Update Feature Key**, paste the entire content of your signed feature key file, and click **OK**. A success message appears and the feature table reloads with your features.

3. **Scripted:** run the bundled automation (see [Headless automation](#headless-automation)):

   ```bash
   python scripts/apply_license.py --host 10.0.1.1 --port 8080 \
       --user admin --password 'your-pass' --license-file feature_key.txt
   ```

---

### Step 6 — Verify the result

**Via the Web UI** — *System → Feature Key* now lists your features (serial, name, expiration, features grid).

**Via the CLI** (SSH, port `4118`):

```
> show feature-key

Feature-Key ID      Feature-Key Name    Expiration Date
FVE603700BD64       FVE603700           never
```

The `Name` and `Expiration` fields must match the values in your feature key file (`never` = no expiry).

---

## Repository layout

```
wg-firebox-feature-key/
├── README.md                    # this guide
├── README.es.md                 # Spanish version
├── LICENSE                      # MIT
├── docs/
│   ├── headless-automation.md   # fully automated VNC-driven variant
│   └── troubleshooting.md       # pitfalls and fixes
├── scripts/
│   ├── sign_openssl.py          # sign a feature key (OpenSSL 3.x)
│   ├── verify_openssl.py        # verify a feature key (OpenSSL 3.x)
│   ├── sign_feature_key.py      # sign variant (legacy cryptography < 48)
│   ├── verify_feature_key.py    # verify variant (legacy cryptography < 48)
│   ├── apply_license.py         # Web UI automation (no dependencies)
│   └── vnc/
│       ├── vnc_cmd.py           # type a command into the VNC console
│       ├── vnc_key.py           # press raw keys
│       ├── vnc_shot.py          # capture the console as PNG
│       └── vnc_boot_menu.py     # navigate the GParted boot menu
└── templates/
    └── feature_key_template.txt # feature key template (edit + sign)
```

---

## Headless automation

If you cannot (or do not want to) interact with the consoles manually — e.g. driving the whole process from a script over VNC — see [docs/headless-automation.md](docs/headless-automation.md). It documents:

- Enabling the VMware VNC server and using `vncdotool` for keyboard/mouse/screenshot.
- The exact GParted boot-menu navigation and the dialog sequence that yields a root shell.
- VNC keyboard limitations (shift-dependent characters) and how to work around them.
- The Web UI session protocol used by `apply_license.py`.

---

## Troubleshooting

Every pitfall encountered while developing this procedure — including the silent license rejection after a key swap, the single-admin-session rule, and the `vmrun reset` trap — is collected in [docs/troubleshooting.md](docs/troubleshooting.md).

---

## Credits

This work builds on the research published in the public repository [amnemonic/wg_firebox](https://github.com/amnemonic/wg_firebox), which first documented the Firebox feature-key signing format and the `sect163k1` key pair approach.

---

## Legal

- Use only on hardware you own or are authorized to manage.
- This repository contains **no** real keys, licenses, or credentials — only scripts, documentation, and templates.
- Feature keys and licensing terms remain property of WatchGuard Technologies.