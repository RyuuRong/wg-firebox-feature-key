# WatchGuard Firebox V — Reemplazo de la Feature Key

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> **Aviso:** Este proyecto se proporciona **exclusivamente con fines educativos y de investigación**, para usarse únicamente en hardware que sea de tu propiedad o que estés autorizado a administrar. Reemplazar la clave de firma e instalar una feature key personalizada puede violar tu acuerdo de licencia con WatchGuard Technologies. Los autores no asumen responsabilidad alguna por el uso de este material. Úsalo bajo tu propio riesgo.

---

## Índice

- [¿Qué es esto?](#qué-es-esto)
- [Cómo funciona](#cómo-funciona)
- [Requisitos](#requisitos)
- [Procedimiento](#procedimiento)
  - [Paso 0 — Preparación del entorno](#paso-0--preparación-del-entorno)
  - [Paso 1 — Generar el par de claves](#paso-1--generar-el-par-de-claves)
  - [Paso 2 — Crear y firmar la feature key](#paso-2--crear-y-firmar-la-feature-key)
  - [Paso 3 — Verificar la firma localmente](#paso-3--verificar-la-firma-localmente)
  - [Paso 4 — Modificar la partición de sistema del Firebox](#paso-4--modificar-la-partición-de-sistema-del-firebox)
  - [Paso 5 — Aplicar la feature key](#paso-5--aplicar-la-feature-key)
  - [Paso 6 — Verificar el resultado](#paso-6--verificar-el-resultado)
- [Estructura del repositorio](#estructura-del-repositorio)
- [Automatización sin pantalla (headless)](#automatización-sin-pantalla-headless)
- [Solución de problemas](#solución-de-problemas)
- [Legal](#legal)

---

## ¿Qué es esto?

WatchGuard **Firebox V** (el firewall virtual) valida la *feature key* (licencia) que se sube a través de la Web UI usando una **clave pública** criptográfica almacenada en el dispositivo:

```
/etc/lickey.pem
```

Solo se acepta una feature key cuya firma valide contra esa clave pública. Al reemplazarla por una clave de un par que **tú** controles, puedes generar, firmar e instalar tus propias feature keys que desbloquean todas las funciones del dispositivo.

Este repositorio documenta un procedimiento completo, paso a paso y reproducible para lograrlo, incluyendo:

- Generación del par de claves EC (curva `sect163k1`).
- Creación del archivo de feature key a partir de una plantilla.
- Firma y verificación de la misma.
- Inyección de tu clave pública en la imagen del disco del Firebox usando **GParted Live**.
- Instalación de la feature key a través de la Web UI (interactiva o totalmente automatizada).

---

## Cómo funciona

```
┌─────────────────┐      ┌──────────────────────┐      ┌──────────────────────┐
│ 1. Par de claves│      │ 2. Feature key       │      │ 3. Disco del Firebox │
│                 │      │                      │      │                      │
│ private_key.pem │─────▶│ feature_key.txt      │─────▶│ /etc/lickey.pem =    │
│ public_key.pem  │ firmar│ Signature: <hex>    │      │   public_key.pem     │
└─────────────────┘      └──────────────────────┘      │ /info.txt:           │
                                                       │   Product = base     │
                                                       └──────────┬───────────┘
                                                                  │ boot
                                                        ┌─────────▼───────────┐
                                                        │ 4. Web UI           │
                                                        │    System → Feature │
                                                        │    Key → pegar → OK │
                                                        └─────────────────────┘
```

El dispositivo verifica la firma de la feature key con `/etc/lickey.pem` (leído **al arrancar**), por lo que tanto el reemplazo de la clave como la carga de la licencia deben ir seguidos de un reinicio del equipo.

---

## Requisitos

| Elemento | Notas |
|---|---|
| Host Windows (esta guía se escribió en Windows 10/11) | Adaptable a Linux/macOS |
| VMware Workstation (Pro o Player) | Tanto para el Firebox V como para la VM de GParted Live |
| ISO de GParted Live (`gparted-live-1.8.x`) | [Descarga](https://gparted.org/download.php) |
| Python 3.10+ | Para los scripts de firma/automatización |
| OpenSSL 3.x | Incluido con *Git for Windows* (`C:\Program Files\Git\usr\bin\openssl.exe`) o el paquete de tu distro |
| Un Firebox V (VM) de tu propiedad | Probado con Fireware 12.6.x |

> **Nota sobre `cryptography`:** Python `cryptography >= 48` **eliminó** el soporte de la curva `sect163k1` (OID `1.3.132.0.1`) que se necesita aquí. Usa los scripts basados en OpenSSL (`sign_openssl.py` / `verify_openssl.py`) o una versión antigua de `cryptography`.

---

## Procedimiento

### Paso 0 — Preparación del entorno

1. **Localiza tu disco virtual del Firebox V.** En nuestra configuración:
   - VM: `FireboxV_12_6_2_U2.vmx`
   - Disco: `FireboxV_12_6_2_U2-disk1.vmdk` (~550 MB, de crecimiento dinámico)

2. **Crea una segunda VM** (`GPartedLinux.vmx`) que:
   - Adjunte el **VMDK del Firebox** como disco IDE (`ide0:0`).
   - Adjunte la **ISO de GParted Live** como CD-ROM (`ide1:0`).
   - Use una red **host-only** (p. ej. `VMnet1`) para que el guest pueda alcanzar al host por HTTP (se usa para transferir la clave). El lado del host en `VMnet1` suele ser `10.0.1.2`.

3. **Prepara un servidor HTTP en el host** para servir tu `public_key.pem`:

   ```powershell
   # cópialo con un nombre con caracteres "seguros" (sin espacios ni caracteres especiales)
   Copy-Item public_key.pem key.pem
   python -m http.server 80 -d .\cert
   ```

   Más adelante lo descargarás en el guest con `wget 10.0.1.2/key.pem`.

---

### Paso 1 — Generar el par de claves

El dispositivo usa una clave EC en la curva **`sect163k1`**:

```bash
openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:sect163k1 -out private_key.pem
openssl ec -in private_key.pem -pubout -out public_key.pem
```

Comprobación — la clave pública debe ser el PEM SPKI de 142 bytes:

```bash
openssl ec -in private_key.pem -text -noout
openssl pkey -pubin -in public_key.pem -text -noout
```

**Mantén `private_key.pem` en secreto. Nunca lo subas al repositorio.**

---

### Paso 2 — Crear y firmar la feature key

1. Copia la plantilla (`templates/feature_key_template.txt`) y edítala para tu equipo:

   ```
   Serial Number: FVE603700BD64        ← tu número de serie
   License ID:   FVE603700BD64
   Name:         FVE603700
   Model:        FireboxV-XLG
   Version:      2
   Feature:      ACCESS_PORTAL@Jan-01-2032
   ...                                   ← las funciones que quieras
   Expiration:   never
   Signature:    <placeholder>
   ```

   Las líneas `Feature:` admiten dos formatos de valor:
   - `Feature: NAME@MON-DD-YYYY` — caduca en la fecha indicada,
   - `Feature: NAME#NUMBER` — basado en cantidad,
   - `Feature: NAME` — permanente.

2. Firma el archivo (esto sobrescribe la línea `Signature:`):

   ```bash
   python scripts/sign_openssl.py feature_key.txt private_key.pem
   ```

   Qué ocurre internamente:
   - Se eliminan todos los caracteres de espacio en blanco (` `, `\t`, `\r`, `\n`, `\v`, `\f`) del texto de la licencia **antes** del marcador `Signature:`.
   - Se calcula una firma **ECDSA-SHA1** sobre los bytes normalizados.
   - La firma se escribe como `Signature: <hex>`, agrupada en bloques de 16 caracteres separados por `-`.

3. Ejemplo de resultado:

   ```
   Signature: 302e02150102ab0f-14d5a4eaaa933c0a-08402dbbef74b481-6e021500ae551a23-480897d3a8b7a1eb-f384f83d98919ca3
   ```

---

### Paso 3 — Verificar la firma localmente

Antes de tocar el equipo, confirma que el archivo firmado valida contra tu clave pública:

```bash
python scripts/verify_openssl.py feature_key.txt public_key.pem
# → Success! This is correct feature key
```

---

### Paso 4 — Modificar la partición de sistema del Firebox

> Este paso arranca el disco del Firebox con GParted Live. **Haz una copia del VMDK antes** (`copy` o snapshot de VMware).

1. Enciende la VM de GParted Live (con el disco del Firebox adjunto).

2. **Menú de arranque** (syslinux). El menú arranca la entrada por defecto (gráfica) tras **30 segundos**. O bien:
   - Deja que arranque en modo gráfico — funciona bien cuando la consola de VMware tiene pantalla, o
   - Para modo texto (útil sin pantalla): selecciona **Other modes of GParted Live** → **Safe graphic settings (vga=normal)**.

3. **Diálogos de arranque**:
   - *Policy for handling keymaps* → pulsa Enter (aceptar por defecto).
   - *Which language do you prefer?* → pulsa Enter (por defecto: US English).
   - *Which mode do you prefer?* → elige **`(2) Enter command line prompt`** (escribe `2`, o `Tab` y luego `2`, y Enter).

   Deberías llegar a una **shell bash de root**. Los mensajes
   ```
   bash: cannot set terminal process group (1416): Inappropriate ioctl for device
   bash: no job control in this shell
   ```
   son normales.

4. **Identifica el disco del Firebox y su partición de sistema:**

   ```bash
   lsblk
   # sda  ── el disco del Firebox (≈4.4 GB en nuestra VM)
   #   sda2 ── partición ext con /etc  (la partición de sistema)
   ```

   La partición que contiene `etc/` es la que necesitamos. En nuestro equipo fue **`/dev/sda2`** (partición ext2/ext3).

5. **Móntala:**

   ```bash
   mkdir -p /mnt/firebox
   mount /dev/sda2 /mnt/firebox
   ls /mnt/firebox/etc
   # ... lickey.pem ...      ← está aquí
   cat /mnt/firebox/info.txt
   # Product = utm           ← debe convertirse en "base"
   # Platform = 630604
   ```

6. **Transfiere tu clave pública al guest** (con el servidor HTTP del Paso 0):

   ```bash
   wget 10.0.1.2/key.pem
   ```

   > `wget` antepone automáticamente `http://` cuando no se indica esquema, así no hace falta teclear `://` (importante para automatización por teclado).

7. **Reemplaza la clave del sistema:**

   ```bash
   cp key.pem /mnt/firebox/etc/lickey.pem
   ```

8. **Cambia el nivel de producto** para que la licencia sea aceptada para el modelo "base":

   ```bash
   sed -i 's/utm/base/' /mnt/firebox/info.txt
   ```

9. **Verifica ambos cambios:**

   ```bash
   cat /mnt/firebox/etc/lickey.pem
   # -----BEGIN PUBLIC KEY-----   ← debe ser TU clave
   cat /mnt/firebox/info.txt
   # Product = base
   ```

10. **Desmonta y apaga limpiamente:**

    ```bash
    umount /mnt/firebox
    sync
    poweroff
    ```

    Luego retira (o desconecta) la VM/ISO de GParted para volver a adjuntar el disco a la VM del Firebox.

> **¿Por qué `Product = base`?** El Firebox compara el nivel de producto de `/info.txt` con el esperado por la feature key. Un equipo que reporta `utm` rechaza claves emitidas para el modelo base con *Invalid License*. La investigación original (ver [Créditos](#créditos)) estableció `base` como el valor aceptado.

---

### Paso 5 — Aplicar la feature key

> ⚠️ **El equipo lee `/etc/lickey.pem` al arrancar.** Tras reemplazar la clave **debes arrancar el Firebox al menos una vez** antes de subir la licencia — de lo contrario, el sistema en ejecución sigue verificando con la clave *antigua* y rechaza silenciosamente tu nueva feature key.

1. Inicia la VM del Firebox y espera a que responda:

   ```powershell
   ping 10.0.1.1
   ```

2. **Interactivo (recomendado):** abre `https://<ip>:8080`, inicia sesión, ve a **System → Feature Key**, pulsa **Update Feature Key**, pega el contenido completo de tu archivo de feature key firmado y pulsa **OK**. Aparece un mensaje de éxito y la tabla de funciones se recarga con tus features.

3. **Automatizado:** ejecuta la automatización incluida (ver [Automatización sin pantalla](#automatización-sin-pantalla-headless)):

   ```bash
   python scripts/apply_license.py --host 10.0.1.1 --port 8080 \
       --user admin --password 'tu-pass' --license-file feature_key.txt
   ```

---

### Paso 6 — Verificar el resultado

**Vía Web UI** — *System → Feature Key* ahora lista tus features (serial, nombre, expiración, tabla de funciones).

**Vía CLI** (SSH, puerto `4118`):

```
> show feature-key

Feature-Key ID      Feature-Key Name    Expiration Date
FVE603700BD64       FVE603700           never
```

Los campos `Name` y `Expiration` deben coincidir con los valores de tu archivo de feature key (`never` = sin caducidad).

---

## Estructura del repositorio

```
wg-firebox-feature-key/
├── README.md                    # esta guía (inglés)
├── README.es.md                 # versión en español
├── LICENSE                      # MIT
├── docs/
│   ├── headless-automation.md   # variante totalmente automatizada por VNC
│   └── troubleshooting.md       # problemas y soluciones
├── scripts/
│   ├── sign_openssl.py          # firmar feature key (OpenSSL 3.x)
│   ├── verify_openssl.py        # verificar feature key (OpenSSL 3.x)
│   ├── sign_feature_key.py      # variante de firma (cryptography < 48)
│   ├── verify_feature_key.py    # variante de verificación (cryptography < 48)
│   ├── apply_license.py         # automatización de la Web UI (sin dependencias)
│   └── vnc/
│       ├── vnc_cmd.py           # escribir un comando en la consola VNC
│       ├── vnc_key.py           # pulsar teclas
│       ├── vnc_shot.py          # capturar la consola como PNG
│       └── vnc_boot_menu.py     # navegar el menú de arranque de GParted
└── templates/
    └── feature_key_template.txt # plantilla de feature key (editar + firmar)
```

---

## Automatización sin pantalla (headless)

Si no puedes (o no quieres) interactuar manualmente con las consolas — p. ej. para dirigir todo el proceso desde un script por VNC — consulta [docs/headless-automation.md](docs/headless-automation.md). Documenta:

- Activar el servidor VNC de VMware y usar `vncdotool` para teclado/ratón/capturas.
- La navegación exacta del menú de arranque de GParted y la secuencia de diálogos que lleva a una shell de root.
- Las limitaciones del teclado VNC (caracteres dependientes de Shift) y cómo esquivarlas.
- El protocolo de sesión de la Web UI usado por `apply_license.py`.

---

## Solución de problemas

Todos los obstáculos encontrados al desarrollar este procedimiento — incluido el rechazo silencioso de la licencia tras el cambio de clave, la regla de una sola sesión admin y la trampa de `vmrun reset` — están recogidos en [docs/troubleshooting.md](docs/troubleshooting.md).

---

## Créditos

Este trabajo se basa en la investigación publicada en el repositorio público [amnemonic/wg_firebox](https://github.com/amnemonic/wg_firebox), que documentó por primera vez el formato de firma de la feature key del Firebox y el enfoque del par de claves `sect163k1`.

---

## Legal

- Usa únicamente hardware que sea de tu propiedad o que estés autorizado a administrar.
- Este repositorio **no** contiene claves, licencias ni credenciales reales — solo scripts, documentación y plantillas.
- Las feature keys y los términos de licencia siguen siendo propiedad de WatchGuard Technologies.