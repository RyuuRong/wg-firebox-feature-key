"""Linux/WSL offline VMDK editor. No mounts, root, or live appliance access required.

Invoked with a JSON request file; stdout is a JSON response. Requires guestfish
and qemu-img. All disk writes target an unpublished output inside a temp dir.
"""

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile


def run(args, script=None):
    result = subprocess.run(args, input=script, capture_output=True, text=True,
                            env={**os.environ, "LIBGUESTFS_BACKEND": "direct",
                                 "LIBGUESTFS_BACKEND_SETTINGS": "force_tcg"})
    if result.returncode:
        raise RuntimeError(f"{args[0]} falló: {result.stderr[-3000:]}")
    return result.stdout


def quote(value):
    # guestfish has its own command parser; JSON quoting handles spaces and quotes.
    value = str(value)
    if any(character in value for character in ("\n", "\r", "\x00")):
        raise ValueError("Ruta con caracteres de control no admitida.")
    return json.dumps(value, ensure_ascii=False)


def fish(image, commands, readonly=True):
    return run(["guestfish", "--ro" if readonly else "--rw", "--format=vmdk", "-a", str(image)],
               "run\n" + commands + "\n")


def read_info(image, partition):
    # guestfish cat appends an output newline; download preserves the exact bytes.
    with tempfile.TemporaryDirectory(prefix="firebox-info-") as directory:
        target = Path(directory) / "info.txt"
        fish(image, f"mount-ro {quote(partition)} /\ndownload /info.txt {quote(target)}\numount-all")
        return target.read_text(encoding="utf-8")


def image_info(source):
    source = Path(source).resolve(strict=True)
    if source.suffix.lower() != ".vmdk":
        raise ValueError("Selecciona un disco VMDK.")
    if list(source.parent.glob("*.lck")):
        raise ValueError("Existen bloqueos VMware. Apaga la VM y cierra Workstation.")
    info = json.loads(run(["qemu-img", "info", "--output=json", str(source)]))
    if info.get("format") != "vmdk":
        raise ValueError("El archivo no es un VMDK válido.")
    if info.get("backing-filename"):
        raise ValueError("Disco con snapshots: consolídalos en VMware antes de continuar.")
    return source, info


def adapter_type(source):
    """Read only the bounded VMDK descriptor, retaining its adapter metadata."""
    with Path(source).open("rb") as stream:
        header = stream.read(512)
        if header[:4] == b"KDMV":
            offset, sectors = struct.unpack_from("<QQ", header, 28)
            if not offset or not sectors or sectors > 2048:
                raise ValueError("Descriptor VMDK incrustado ausente o demasiado grande.")
            stream.seek(offset * 512)
            descriptor = stream.read(sectors * 512)
        else:
            stream.seek(0)
            descriptor = stream.read(1024 * 1024)
    match = re.search(rb'ddb\.adapterType\s*=\s*"([^"]+)"', descriptor)
    if not match:
        raise ValueError("No se encontró ddb.adapterType. Revisa el descriptor antes de convertir.")
    value = match[1].decode("ascii")
    if value not in ("ide", "lsilogic", "buslogic", "legacyESX"):
        raise ValueError(f"El adaptador VMDK {value} no está soportado por esta conversión.")
    return value


def inspect(source):
    source, info = image_info(source)
    filesystems = fish(source, "list-filesystems")
    candidates = []
    for line in filesystems.splitlines():
        device, separator, filesystem = line.partition(":")
        if separator and re.fullmatch(r"/dev/[a-z]+\d+", device) and filesystem.strip() in ("ext2", "ext3", "ext4"):
            # Errors on a filesystem are not silently interpreted as an absent system partition.
            exists = fish(source, f"mount-ro {quote(device)} /\nis-file /etc/lickey.pem\nis-file /info.txt\numount-all")
            if exists.splitlines() == ["true", "true"]:
                product = read_info(source, device)
                if not re.search(r"^Product\s*=\s*(utm|base)\s*$", product, re.MULTILINE):
                    raise ValueError("La partición tiene un producto no reconocido.")
                candidates.append({"partition": device, "filesystem": filesystem.strip(), "info": product})
    if len(candidates) != 1:
        raise ValueError(f"Se encontraron {len(candidates)} particiones de sistema. No se editará el disco automáticamente.")
    return {**candidates[0], "virtual_size": info["virtual-size"], "source": str(source),
            "adapter_type": adapter_type(source)}


def modify(source, output, key):
    source = Path(source).resolve(strict=True)
    output = Path(output).resolve()
    key = Path(key).resolve(strict=True)
    if source == output or output.exists() or output.suffix.lower() != ".vmdk":
        raise ValueError("El destino debe ser un VMDK nuevo, distinto del original.")
    key_bytes = key.read_bytes()
    # Validate SPKI and curve using system OpenSSL in WSL before any disk write.
    curve = run(["openssl", "pkey", "-pubin", "-in", str(key), "-text", "-noout"])
    if not re.search(r"ASN1 OID:\s*sect163k1\b", curve):
        raise ValueError("La clave pública no usa sect163k1.")
    details = inspect(source)
    partition = details["partition"]
    # Conservative bound: temporary output can expand to the full virtual size.
    if shutil.disk_usage(output.parent).free < details["virtual_size"] + 512 * 1024 * 1024:
        raise ValueError("Espacio insuficiente: se requiere el tamaño virtual del disco más 512 MiB.")
    with tempfile.TemporaryDirectory(prefix="firebox-disk-", dir=output.parent) as directory:
        folder = Path(directory)
        candidate = folder / "prepared.vmdk"
        options = "subformat=monolithicSparse,adapter_type=" + details["adapter_type"]
        run(["qemu-img", "convert", "-f", "vmdk", "-O", "vmdk", "-o", options, str(source), str(candidate)])
        mount = f"mount {quote(partition)} /\n"
        original_info = read_info(candidate, partition)
        updated_info, count = re.subn(r"^(Product\s*=\s*)(utm|base)(\s*)$",
                                     lambda match: match[1] + "base" + match[3], original_info, flags=re.MULTILINE)
        if count != 1:
            raise ValueError("info.txt no contiene un único campo Product válido.")
        local_info = folder / "info.txt"
        local_info.write_text(updated_info, encoding="utf-8")
        # Preserve original file attributes. cp of originals is exclusive after checking backups.
        backups = fish(candidate, f"mount-ro {quote(partition)} /\nexists /etc/lickey.pem.bak\nexists /info.txt.bak\numount-all")
        backup_commands = ""
        flags = backups.splitlines()
        if len(flags) != 2:
            raise RuntimeError("No se pudo comprobar el estado de las copias internas.")
        if flags[0] == "false":
            backup_commands += "cp /etc/lickey.pem /etc/lickey.pem.bak\n"
        if flags[1] == "false":
            backup_commands += "cp /info.txt /info.txt.bak\n"
        fish(candidate, mount + backup_commands + f"upload {quote(key)} /etc/lickey.pem\n"
             + f"upload {quote(local_info)} /info.txt\nsync\numount-all", readonly=False)
        recovered = folder / "recovered.pem"
        recovered_info = folder / "recovered-info.txt"
        fish(candidate, f"mount-ro {quote(partition)} /\ndownload /etc/lickey.pem {quote(recovered)}\ndownload /info.txt {quote(recovered_info)}\numount-all")
        if recovered.read_bytes() != key_bytes or recovered_info.read_bytes() != local_info.read_bytes():
            raise RuntimeError("La comprobación del disco editado falló. No se entregará el resultado.")
        run(["qemu-img", "check", "-f", "vmdk", str(candidate)])
        if adapter_type(candidate) != details["adapter_type"]:
            raise RuntimeError("La conversión no conservó el adaptador del VMDK.")
        # No-replace atomic publication, including a destination created during the operation.
        os.link(candidate, output)
    return {"output": str(output), "partition": partition, "key_sha256": hashlib.sha256(key_bytes).hexdigest(), "info": updated_info}


def dispatch(request):
    action = request["action"]
    if action == "check":
        for tool in ("qemu-img", "guestfish", "openssl"):
            if not shutil.which(tool):
                raise ValueError(f"Falta {tool}. Instala los requisitos de WSL indicados en la guía.")
        return {"tools": "qemu-img, guestfish y openssl disponibles", "backend": "direct"}
    if action == "inspect":
        return inspect(request["source"])
    if action == "modify":
        return modify(request["source"], request["output"], request["key"])
    raise ValueError("Operación desconocida.")


if __name__ == "__main__":
    try:
        request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
        print(json.dumps({"ok": True, "result": dispatch(request)}, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        sys.exit(1)
