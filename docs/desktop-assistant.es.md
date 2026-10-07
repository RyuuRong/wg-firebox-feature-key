# Asistente gráfico para Windows

Cinco pasos visuales: preparar WSL, generar claves, importar y firmar un FK,
editar una copia del VMDK y exportar una VM a OVA. Usa únicamente equipos que
administres. La aceptación local del FK no garantiza que los servicios del
fabricante acepten las credenciales de suscripción que contiene.

## Ejecutar y compilar

Instala Python 3.12 para Windows con Tcl/Tk. Desde la raíz del repositorio:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r desktop/requirements.txt
.\.venv\Scripts\python -m desktop.app
```

La firma usa `cryptography==46.0.5`; la versión 47 ya no tiene `sect163k1`.
No necesita OpenSSL externo en Windows. Para compilar desde Windows:

```powershell
.\.venv\Scripts\Activate.ps1
.\desktop\build.ps1
```

El resultado es `dist\FireboxAssistant.exe`. PyInstaller no compila para Windows
desde Linux. El workflow **Desktop tests and Windows build** construye el `.exe`
en un runner Windows. Descarga **FireboxAssistant-Windows** de una ejecución
correcta de Actions. Los artefactos duran 30 días; no se publica una release
automáticamente. El ejecutable no tiene firma Authenticode.

## Preparar WSL2

En PowerShell como administrador:

```powershell
wsl --install -d Ubuntu
```

Reinicia si lo solicita y completa el primer inicio de Ubuntu. Allí ejecuta:

```bash
sudo apt-get update
sudo apt-get install -y python3 openssl qemu-utils libguestfs-tools linux-image-generic
```

Consulta `wsl -l -v` para introducir el nombre de la distribución en la app.
`linux-image-generic` proporciona el kernel necesario para libguestfs. El editor
usa QEMU por software para no depender de virtualización anidada; puede tardar
varios minutos. No necesita privilegios de root para editar imágenes.

## Claves y FK

Genera la pareja en una carpeta nueva o selecciona claves existentes. La privada
se guarda sin contraseña: protégela con los permisos de Windows y conserva una
copia segura. Nunca se envía a WSL, a GitHub ni al disco del Firebox.

Importa o pega el FK; la importación admite un export con una línea `FK:`. Para
cambiar fechas introduce `AAAA-MM-DD` y pulsa **Aplicar fecha**. Se modifican las
fechas de características y `Expiration`, conservando cantidades y sufijos.
Revisa el texto antes de firmar. La app comprueba que las claves correspondan,
firma, verifica y guarda en un archivo nuevo. No sobrescribe el original. Si
editas el texto firmado debes volver a firmarlo.

## Disco y arranque

Apaga completamente la VM, cierra Workstation y guarda una copia de toda la
carpeta. Consolida snapshots en VMware. Selecciona el descriptor VMDK si está
dividido; conserva todos los archivos de datos junto a él.

**Inspeccionar** busca exactamente una partición ext2/ext3/ext4 con
`/etc/lickey.pem` y `/info.txt`; no presupone `sda2`. **Crear disco preparado**
genera un VMDK nuevo `monolithicSparse`, conserva copias internas si no existían,
sustituye la clave pública y establece `Product = base`. Vuelve a leer y comparar
los archivos y ejecuta `qemu-img check` antes de entregar el resultado. El
original se abre solo para lectura. Reserva su tamaño virtual más 512 MiB.
Espera a que termine; no hay cancelación de una operación en curso.

La ausencia de `.lck` no demuestra por sí sola que la VM esté apagada: debes
comprobarlo. La aplicación no modifica el VMX ni prueba el arranque del Firebox.
El botón **Ver controlador y posición en un VMX** muestra estas propiedades
y avisa si hay varios VMDK conectados. La conversión conserva `ddb.adapterType`;
eso no sustituye conservar el controlador y la posición en el VMX.
Conecta **solo el disco preparado**, con el mismo controlador y posición del
original (por ejemplo `IDE 0:0`) y conserva BIOS/UEFI. Arrancar con el original
todavía conectado no valida la copia. No ejecutes las dos VMs a la vez.

`VFS: Unable to mount root fs on unknown-block(0,0)` indica que el kernel no
localizó/montó la raíz. Compara controlador, posición y firmware antes de
concluir que el disco está dañado. El nombre del VMDK puede cambiar si el VMX
apunta al nuevo archivo. En discos divididos conserva las referencias a extents.

Arranca una vez para cargar la clave. En la Web UI: **System → Feature Key →
Update Feature Key**, pega el FK firmado y verifica el resultado. La app guía
este paso; no automatiza login ni envío al equipo.

## ESXi

Instala VMware OVF Tool desde su distribución oficial. Selecciona el ejecutable,
el VMX de la VM probada y apagada y un OVA de destino nuevo. El destino solo se
entrega después de que OVF Tool termine correctamente.

En ESXi: **Create/Register VM → Deploy a virtual machine from an OVF or OVA
file**. Comprueba la compatibilidad con tu versión ESXi y conserva controlador,
posición y firmware. Asigna WAN/LAN por sus MAC. La app no modifica hardware
virtual ni solicita credenciales de ESXi.

## Pruebas

```bash
python -m unittest discover -s tests -v
```

Con libguestfs, QEMU y un kernel disponibles en Linux:

```bash
FIREBOX_DISK_INTEGRATION=1 python -m unittest discover -s tests -v
```

El workflow Linux prueba un VMDK sintético: partición detectada, archivos
preparados, copias internas y hash del original sin cambios. Un fallo bloquea
ese job. WSL en tu Windows, el arranque del Firebox real y OVF Tool requieren
validación en tu equipo. No subas discos, claves ni FK al repositorio.
