"""Key and feature-key operations, independent of the graphical interface."""

import datetime as dt
import os
from pathlib import Path
import re
import subprocess
import tempfile

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
    return re.sub(r"^Expiration:.*$", "Expiration: " + expiry, text, flags=re.MULTILINE)


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
