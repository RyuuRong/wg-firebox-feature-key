"""Key and feature-key operations, independent of the graphical interface."""

import datetime as dt
import os
from pathlib import Path
import re
import subprocess
import tempfile
import urllib.parse
import xml.etree.ElementTree as ET

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec


MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def write_new(path, data, mode=0o600):
    """Create a new file exclusively; never overwrite a user's existing file."""
    path = Path(path)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def public_key(path):
    key = serialization.load_pem_public_key(Path(path).read_bytes())
    if not isinstance(key, ec.EllipticCurvePublicKey) or key.curve.name != "sect163k1":
        raise ValueError("La clave pública debe usar la curva sect163k1 (K-163).")
    return key


def create_keys(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    private, public = directory / "private_key.pem", directory / "public_key.pem"
    if private.exists() or public.exists():
        raise FileExistsError("Ya existen claves en esa carpeta. Selecciona una carpeta nueva.")
    key = ec.generate_private_key(ec.SECT163K1())
    write_new(private, key.private_bytes(serialization.Encoding.PEM,
              serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    try:
        write_new(public, key.public_key().public_bytes(serialization.Encoding.PEM,
                  serialization.PublicFormat.SubjectPublicKeyInfo), 0o644)
    except BaseException:
        private.unlink()
        raise
    return private, public


def import_license(text):
    """Extract the actual FK from a pasted export without its introductory labels."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    if "\x00" in text:
        raise ValueError("El FK contiene caracteres nulos.")
    marker = re.search(r"^\s*FK:\s*$", text, re.MULTILINE)
    if marker:
        text = text[marker.end():].lstrip()
    start = re.search(r"^Serial Number:\s*\S+\s*$", text, re.MULTILINE)
    if not start:
        raise ValueError("Falta el campo Serial Number del FK.")
    text = text[start.start():].strip() + "\n"
    for field in ("Serial Number", "License ID", "Name", "Model", "Version", "Expiration", "Signature"):
        if len(re.findall(r"^" + re.escape(field) + r":", text, re.MULTILINE)) != 1:
            raise ValueError(f"El FK debe contener exactamente un campo {field}.")
    if not re.search(r"^Feature:\s*\S+", text, re.MULTILINE):
        raise ValueError("El FK no contiene características.")
    if not re.fullmatch(r"\s*[0-9a-fA-F-]*\s*", text.split("Signature:", 1)[1]):
        raise ValueError("Hay contenido no válido después de Signature.")
    return text


def set_expiration(text, iso_date):
    """Replace dated feature values and Expiration, preserving quantities and suffixes."""
    text = import_license(text)
    date = dt.date.fromisoformat(iso_date)
    expiry = f"{MONTHS[date.month - 1]}-{date.day:02d}-{date.year:04d}"
    text = re.sub(r"(^Feature:.*?@)[A-Za-z]{3}-\d{1,2}-\d{4}",
                  lambda match: match[1] + expiry, text, flags=re.MULTILINE)
    text = re.sub(r"^Expiration:.*$", "Expiration: " + expiry, text, flags=re.MULTILINE)
    # Any content change requires a fresh signature, never reuse the old one.
    return text.split("Signature:", 1)[0] + "Signature: 0000\n"


def license_review(text, expected_serial="", today=None):
    """Review the cleaned FK separately from mathematical signature validity."""
    text = import_license(text)
    today = today or dt.date.today()

    def field(name):
        match = re.search(r"^" + re.escape(name) + r":[ \t]*([^\n]+)", text, re.MULTILINE)
        if not match or not match[1].strip():
            raise ValueError("El campo " + name + " está vacío.")
        return match[1].strip()

    def serial(value):
        value = re.sub(r"[\s-]", "", value).upper()
        if not re.fullmatch(r"[A-Z0-9]+", value):
            raise ValueError("El serial debe contener letras, números y separadores de espacio o guion.")
        return value

    actual = field("Serial Number")
    canonical = serial(actual)
    if expected_serial.strip() and canonical != serial(expected_serial):
        raise ValueError("El serial del FK no corresponde al serial indicado para el Firebox.")

    def parse_date(value):
        match = re.fullmatch(r"([A-Za-z]{3})-(\d{1,2})-(\d{4})", value)
        if not match or match[1] not in MONTHS:
            raise ValueError("Fecha de vencimiento no reconocida: " + value)
        return dt.date(int(match[3]), MONTHS.index(match[1]) + 1, int(match[2]))

    expired = []
    expiration = field("Expiration")
    if expiration.lower() != "never" and parse_date(expiration) < today:
        expired.append("Expiration: " + expiration)
    feature_dates = []
    for match in re.finditer(r"^Feature:[ \t]*([^@\n]+)@([^;\s]+)", text, re.MULTILINE):
        name, value = match.groups()
        feature_dates.append(value)
        if parse_date(value) < today:
            expired.append(name.strip() + ": " + value)
    return {"serial": actual, "model": field("Model"), "expiration": expiration,
            "feature_dates": sorted(set(feature_dates)), "expired": expired,
            "feature_count": len(re.findall(r"^Feature:", text, re.MULTILINE))}


def prepare_for_signing(text, expected_serial="", today=None):
    """Clean and validate the GUI's renewal workflow before selecting an output."""
    text = import_license(text)
    review = license_review(text, expected_serial, today)
    if review["expired"]:
        raise ValueError("El FK conserva fechas vencidas. Firmar no cambia las fechas. "
                         "Introduce una fecha nueva y pulsa Aplicar fecha antes de firmar.\n\n"
                         + "\n".join(review["expired"][:5]))
    return text, review


def normalized(text):
    return re.sub(r"[\t\n\v\f\r ]", "", text.split("Signature:", 1)[0]).encode("utf-8")


def sign_license(text, private_path, public_path):
    text = import_license(text)
    key = serialization.load_pem_private_key(Path(private_path).read_bytes(), password=None)
    if not isinstance(key, ec.EllipticCurvePrivateKey) or key.curve.name != "sect163k1":
        raise ValueError("La clave privada debe usar sect163k1 (K-163).")
    expected = public_key(public_path)
    if key.public_key().public_numbers() != expected.public_numbers():
        raise ValueError("La clave pública no corresponde a la clave privada seleccionada.")
    signature = key.sign(normalized(text), ec.ECDSA(hashes.SHA1())).hex()
    grouped = "-".join(signature[i:i + 16] for i in range(0, len(signature), 16))
    signed = text.split("Signature:", 1)[0] + "Signature: " + grouped + "\n"
    verify_license(signed, public_path)
    return signed


def verify_license(text, public_path):
    text = import_license(text)
    signature = bytes.fromhex(text.split("Signature:", 1)[1].strip().replace("-", ""))
    try:
        public_key(public_path).verify(signature, normalized(text), ec.ECDSA(hashes.SHA1()))
    except InvalidSignature as exc:
        raise ValueError("Firma inválida: el contenido fue alterado o la clave no corresponde.") from exc


def inspect_vmx(path):
    """Read controller/disk bindings without changing VM configuration."""
    values = {}
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        match = re.match(r'^\s*([\w:.]+)\s*=\s*"(.*?)"\s*$', line)
        if match:
            values[match[1].lower()] = match[2]
    disks = []
    for name, value in values.items():
        match = re.fullmatch(r"((ide|sata|scsi|nvme)\d+:\d+)\.filename", name)
        if match and value.lower().endswith(".vmdk") and values.get(match[1] + ".present", "true").lower() == "true":
            controller = match[1].split(":")[0]
            disks.append({"position": match[1], "file": value,
                          "controller": values.get(controller + ".virtualdev", match[2])})
    return {"firmware": values.get("firmware", "bios"), "disks": disks,
            "warning": "Hay más de un disco VMDK conectado; revisa cuál contiene el sistema." if len(disks) > 1 else ""}


def inspect_ovf(path):
    """Validate all manifest hashes and report the attached disk controllers."""
    import hashlib
    path = Path(path).resolve(strict=True)
    if path.suffix.lower() != ".ovf" or path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("Selecciona un descriptor OVF de menos de 16 MiB.")
    manifest = path.with_suffix(".mf")
    if not manifest.is_file():
        raise ValueError("Falta el manifiesto .mf junto al OVF.")
    namespaces = {"o": "http://schemas.dmtf.org/ovf/envelope/1",
                  "r": "http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/CIM_ResourceAllocationSettingData"}
    tree = ET.parse(path)
    referenced = {path.name}
    for reference in tree.findall(".//o:References/o:File", namespaces):
        referenced.add(urllib.parse.unquote(reference.get("{" + namespaces["o"] + "}href", "")))
    validated = set()
    for line in manifest.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(r"(SHA1|SHA256|SHA512)\((.+)\)\s*=\s*([0-9a-fA-F]+)", line.strip())
        if not match:
            raise ValueError("El manifiesto contiene una línea o algoritmo no reconocido.")
        algorithm, filename, digest = match.groups()
        filename = urllib.parse.unquote(filename)
        candidate = (path.parent / filename).resolve(strict=True)
        if not candidate.is_relative_to(path.parent) or Path(filename).is_absolute():
            raise ValueError("El manifiesto referencia archivos fuera de la carpeta del paquete.")
        checksum = hashlib.new(algorithm.lower())
        with candidate.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                checksum.update(block)
        if checksum.hexdigest().lower() != digest.lower():
            raise ValueError("El hash no coincide para " + filename + ". No importes ese paquete.")
        validated.add(filename)
    if not referenced.issubset(validated):
        raise ValueError("El manifiesto no cubre todos los archivos referenciados: " + ", ".join(sorted(referenced - validated)))
    items = []
    for item in tree.findall(".//o:VirtualHardwareSection/o:Item", namespaces):
        items.append({name: item.findtext("r:" + name, default="", namespaces=namespaces)
                      for name in ("ResourceType", "ResourceSubType", "InstanceID", "Parent", "AddressOnParent")})
    controllers = {item["InstanceID"]: item for item in items if item["ResourceType"] in ("5", "6", "20")}
    disks = []
    for item in items:
        if item["ResourceType"] == "17":
            controller = controllers.get(item["Parent"], {})
            kind = "IDE" if controller.get("ResourceType") == "5" else controller.get("ResourceSubType", "desconocido")
            disks.append({"controller": kind, "position": item["AddressOnParent"]})
    return {"manifest": "todos los hashes verificados", "files": sorted(validated), "disks": disks,
            "interfaces": sum(item["ResourceType"] == "10" for item in items),
            "key": "El manifiesto no demuestra qué clave pública está instalada. Usa la pareja original del disco."}


def export_ova(tool, vmx, output):
    vmx, output = Path(vmx).resolve(), Path(output).resolve()
    if vmx.suffix.lower() != ".vmx" or not vmx.is_file():
        raise ValueError("Selecciona un archivo VMX existente.")
    if output.suffix.lower() != ".ova":
        raise ValueError("El destino debe tener extensión .ova.")
    if output.exists():
        raise FileExistsError("El destino ya existe; selecciona otro nombre.")
    if list(vmx.parent.glob("*.lck")):
        raise ValueError("Hay bloqueos de VMware. Apaga la VM y cierra Workstation antes de exportar.")
    # Keep partial exports separate; only publish the file after OVF Tool succeeds.
    with tempfile.TemporaryDirectory(prefix="firebox-export-", dir=output.parent) as directory:
        candidate = Path(directory) / "export.ova"
        result = subprocess.run([str(tool), str(vmx), str(candidate)], capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError("OVF Tool falló:\n" + result.stderr[-2000:] + result.stdout[-2000:])
        if not candidate.is_file() or not candidate.stat().st_size:
            raise RuntimeError("OVF Tool no produjo un archivo OVA.")
        # Hard-link publication is atomic and fails rather than overwriting an existing path.
        os.link(candidate, output)
    return output
