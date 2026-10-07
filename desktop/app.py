"""Spanish desktop workflow. Run with python -m desktop.app."""

from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import json
from pathlib import Path
import queue
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from desktop import core, wsl


class Assistant(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Firebox · Asistente de laboratorio")
        self.geometry("1000x780")
        self.minsize(860, 680)
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.events = queue.Queue()
        self.busy = False
        self.buttons = []
        self.private = tk.StringVar()
        self.public = tk.StringVar()
        self.source = tk.StringVar()
        self.output = tk.StringVar()
        self.distro = tk.StringVar(value="Ubuntu")
        self.vmx = tk.StringVar()
        self.ova = tk.StringVar()
        self.ovftool = tk.StringVar(value=r"C:\Program Files\VMware\VMware OVF Tool\ovftool.exe")
        self.confirm = tk.BooleanVar()
        self.expiry = tk.StringVar(value=dt.date.today().isoformat())
        self.status = tk.StringVar(value="Selecciona un paso para comenzar.")
        style = ttk.Style(self)
        style.configure("TLabel", font=("Segoe UI", 10))
        style.configure("TButton", padding=6)
        ttk.Label(self, text="Firebox · Asistente de laboratorio", font=("Segoe UI", 19, "bold")).pack(anchor="w", padx=20, pady=(16, 4))
        ttk.Label(self, text="Claves, feature key, edición de una copia del disco y exportación a ESXi.").pack(anchor="w", padx=20)
        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True, padx=20, pady=12)
        self.prepare_tab()
        self.keys_tab()
        self.license_tab()
        self.disk_tab()
        self.export_tab()
        ttk.Label(self, textvariable=self.status, wraplength=930).pack(anchor="w", padx=20, pady=(0, 6))
        self.progress = ttk.Progressbar(self, mode="indeterminate")
        self.progress.pack(fill="x", padx=20)
        self.log = tk.Text(self, height=5, state="disabled", wrap="word", font=("Consolas", 9))
        self.log.pack(fill="x", padx=20, pady=(6, 14))
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.after(100, self.poll)

    def tab(self, title):
        frame = ttk.Frame(self.tabs, padding=16)
        self.tabs.add(frame, text=title)
        return frame

    def label(self, parent, text):
        ttk.Label(parent, text=text, wraplength=880, justify="left").pack(anchor="w", pady=(0, 12))

    def button(self, parent, title, command):
        button = ttk.Button(parent, text=title, command=command)
        button.pack(anchor="w", pady=4)
        self.buttons.append(button)
        return button

    def path(self, parent, title, variable, save=False, extension=None):
        ttk.Label(parent, text=title).pack(anchor="w", pady=(8, 2))
        row = ttk.Frame(parent)
        row.pack(fill="x")
        ttk.Entry(row, textvariable=variable).pack(side="left", fill="x", expand=True)

        def browse():
            options = {"title": title}
            if extension:
                options["filetypes"] = [(extension.upper(), "*" + extension), ("Todos", "*")]
            if save:
                options["defaultextension"] = extension
                value = filedialog.asksaveasfilename(**options)
            else:
                value = filedialog.askopenfilename(**options)
            if value:
                variable.set(value)
        button = ttk.Button(row, text="Elegir…", command=browse)
        button.pack(side="right", padx=(8, 0))
        self.buttons.append(button)

    def report(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def task(self, title, operation, finished=None):
        if self.busy:
            return
        self.busy = True
        self.status.set(title + "… Espera a que termine.")
        self.progress.start()
        for button in self.buttons:
            button.configure(state="disabled")

        def worker():
            try:
                self.events.put((title, operation(), None, finished))
            except Exception as exc:
                self.events.put((title, None, str(exc), finished))
        self.pool.submit(worker)

    def poll(self):
        try:
            title, value, error, finished = self.events.get_nowait()
        except queue.Empty:
            self.after(100, self.poll)
            return
        self.busy = False
        self.progress.stop()
        for button in self.buttons:
            button.configure(state="normal")
        if error:
            self.status.set("La operación no terminó. Revisa el mensaje.")
            self.report(title + ": " + error)
            messagebox.showerror(title, error)
        else:
            self.status.set(title + ": completado.")
            if finished:
                try:
                    finished(value)
                except Exception as exc:
                    self.status.set("No se pudo completar la acción.")
                    messagebox.showerror(title, str(exc))
            else:
                self.report(title + ": " + json.dumps(value, ensure_ascii=False))
        self.after(100, self.poll)

    def prepare_tab(self):
        page = self.tab("1 · Preparar")
        self.label(page, "Trabaja con una VM apagada y una copia de seguridad de su carpeta. Conserva juntos el descriptor VMDK y todos sus archivos de datos. Consolida snapshots desde VMware antes de usar el editor.")
        self.label(page, "La firma funciona sin OpenSSL externo. La edición de discos usa Ubuntu en WSL2, con qemu-img y libguestfs. No necesitas arrancar GParted ni montar particiones en Windows.")
        self.label(page, "Primera instalación: abre PowerShell como administrador y ejecuta el siguiente comando. Reinicia Windows si lo solicita y completa el primer inicio de Ubuntu.")
        self.command(page, "wsl --install -d Ubuntu")
        self.label(page, "Después, en la terminal de Ubuntu instala las herramientas (la contraseña se introduce allí):")
        self.command(page, "sudo apt-get update && sudo apt-get install -y python3 openssl qemu-utils libguestfs-tools linux-image-generic")
        ttk.Label(page, text="Nombre de distribución WSL (consulta wsl -l -v):").pack(anchor="w", pady=(8, 2))
        ttk.Entry(page, textvariable=self.distro, width=30).pack(anchor="w")
        self.button(page, "Comprobar herramientas de WSL", self.check_wsl)
        self.label(page, "Las claves y los discos permanecen en tu equipo. Usa únicamente equipos que administras. La aceptación local del FK no confirma acceso a servicios de suscripción del fabricante.")

    def check_wsl(self):
        distro = self.distro.get()
        self.task("Comprobar WSL", lambda: wsl.execute({"action": "check"}, distro))

    def command(self, page, command):
        row = ttk.Frame(page)
        row.pack(fill="x", pady=(0, 12))
        field = ttk.Entry(row, width=90)
        field.insert(0, command)
        field.configure(state="readonly")
        field.pack(side="left", fill="x", expand=True)
        button = ttk.Button(row, text="Copiar", command=lambda: (self.clipboard_clear(), self.clipboard_append(command)))
        button.pack(side="right", padx=8)
        self.buttons.append(button)

    def keys_tab(self):
        page = self.tab("2 · Claves")
        self.label(page, "Genera una pareja EC sect163k1 (K-163) o selecciona claves existentes. La clave privada se guarda sin contraseña: protégela y conserva una copia segura. Nunca se envía a WSL, a GitHub ni al disco del Firebox.")
        self.button(page, "Generar claves en una carpeta…", self.generate)
        self.path(page, "Clave privada", self.private, extension=".pem")
        self.path(page, "Clave pública", self.public, extension=".pem")
        self.button(page, "Validar curva de la clave pública", self.check_key)

    def generate(self):
        folder = filedialog.askdirectory(title="Carpeta para las claves (sin claves anteriores)")
        if folder:
            def done(paths):
                self.private.set(str(paths[0]))
                self.public.set(str(paths[1]))
                self.report("Claves generadas en la carpeta seleccionada. Curva: sect163k1 / K-163.")
            self.task("Generar claves", lambda: core.create_keys(folder), done)

    def check_key(self):
        selected = self.public.get()
        self.task("Validar clave pública", lambda: core.public_key(selected).curve.name,
                  lambda curve: self.report("Curva válida: " + curve))

    def license_tab(self):
        page = self.tab("3 · Feature key")
        self.label(page, "Importa o pega el FK. Puedes limpiar las etiquetas de un export y cambiar explícitamente la fecha de las características. Los límites y sufijos se conservan. Revisa el texto antes de firmar.")
        bar = ttk.Frame(page)
        bar.pack(fill="x")
        self.button(bar, "Importar FK…", self.load_license)
        self.editor = tk.Text(page, height=12, wrap="none", undo=True, font=("Consolas", 10))
        self.editor.pack(fill="both", expand=True, pady=8)
        dates = ttk.Frame(page)
        dates.pack(fill="x")
        ttk.Label(dates, text="Nueva fecha (AAAA-MM-DD):").pack(side="left")
        ttk.Entry(dates, textvariable=self.expiry, width=14).pack(side="left", padx=8)
        self.button(page, "Aplicar fecha al texto", self.change_expiration)
        self.button(page, "Firmar, verificar y guardar como archivo nuevo…", self.sign)
        self.button(page, "Verificar texto con la clave pública", self.verify)
        self.label(page, "Después del arranque del disco preparado: System → Feature Key → Update Feature Key. Pega el FK firmado, confirma la tabla de características y reinicia de forma normal. La carga se realiza en la Web UI.")

    def text(self):
        return self.editor.get("1.0", "end-1c")

    def replace_text(self, text):
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", text)

    def load_license(self):
        selected = filedialog.askopenfilename(title="Importar FK", filetypes=[("Texto", "*.txt"), ("Todos", "*")])
        if selected:
            self.task("Importar FK", lambda: core.import_license(Path(selected).read_text(encoding="utf-8-sig")), self.replace_text)

    def change_expiration(self):
        try:
            self.replace_text(core.set_expiration(self.text(), self.expiry.get()))
            self.status.set("Fecha aplicada al texto. Debes volver a firmarlo.")
        except Exception as exc:
            messagebox.showerror("Fecha", str(exc))

    def sign(self):
        output = filedialog.asksaveasfilename(title="Guardar FK firmado (archivo nuevo)", defaultextension=".txt")
        if output:
            text, private, public = self.text(), self.private.get(), self.public.get()
            def operation():
                signed = core.sign_license(text, private, public)
                core.write_new(output, signed.encode("utf-8"))
                return signed
            def done(signed):
                self.replace_text(signed)
                self.report("FK firmado y verificado. Guardado en: " + output)
            self.task("Firmar FK", operation, done)

    def verify(self):
        text, public = self.text(), self.public.get()
        self.task("Verificar FK", lambda: core.verify_license(text, public),
                  lambda _: self.report("Firma verificada correctamente con la clave pública seleccionada."))

    def disk_tab(self):
        page = self.tab("4 · Disco")
        self.label(page, "La aplicación inspecciona el original en solo lectura. Luego crea un VMDK nuevo, sustituye la clave pública, establece Product = base y verifica ambos archivos. No cambia el original ni la configuración VMX.")
        self.path(page, "VMDK original (descriptor si el disco está dividido)", self.source, extension=".vmdk")
        self.path(page, "VMDK de salida (nombre nuevo)", self.output, save=True, extension=".vmdk")
        ttk.Checkbutton(page, text="La VM está apagada, Workstation está cerrado y tengo una copia de seguridad.", variable=self.confirm).pack(anchor="w", pady=12)
        self.button(page, "Inspeccionar disco en solo lectura", self.inspect_disk)
        self.button(page, "Crear disco preparado y verificarlo", self.modify_disk)
        self.label(page, "El procesamiento puede tardar varios minutos. No cierres Windows ni inicies la VM durante la operación. Se requiere espacio libre equivalente al tamaño virtual del disco más 512 MiB.")
        self.label(page, "Después: conecta el VMDK nuevo usando el mismo controlador y posición del original (por ejemplo IDE 0:0). Cambiar IDE/SCSI/SATA puede impedir el arranque. Arranca una vez antes de cargar el FK; mantén la VM original apagada. Identifica WAN/LAN por su MAC.")

    def disk_request(self, action):
        if not self.confirm.get():
            messagebox.showerror("Preparación", "Confirma que la VM está apagada y que tienes una copia de seguridad.")
            return None
        request = {"action": action, "source": self.source.get()}
        if action == "modify":
            request.update(output=self.output.get(), key=self.public.get())
        return request

    def inspect_disk(self):
        request = self.disk_request("inspect")
        if request:
            distro = self.distro.get()
            self.task("Inspeccionar disco", lambda: wsl.execute(request, distro))

    def modify_disk(self):
        request = self.disk_request("modify")
        if request and messagebox.askyesno("Crear copia preparada", "Se creará un disco nuevo con la clave pública seleccionada y Product = base.\n\n¿Continuar?"):
            distro = self.distro.get()
            self.task("Crear y verificar disco", lambda: wsl.execute(request, distro))

    def export_tab(self):
        page = self.tab("5 · ESXi")
        self.label(page, "Primero conecta el VMDK preparado a la VM en Workstation, prueba el arranque y vuelve a apagarla. Selecciona su VMX para exportar la VM completa; VMDK y VMX son archivos diferentes.")
        self.path(page, "VMware OVF Tool (instalación oficial independiente)", self.ovftool, extension=".exe")
        self.path(page, "VMX de la VM preparada", self.vmx, extension=".vmx")
        self.path(page, "OVA de salida (nombre nuevo)", self.ova, save=True, extension=".ova")
        self.button(page, "Exportar OVA con OVF Tool", self.export)
        self.label(page, "En ESXi: Create/Register VM → Deploy a virtual machine from an OVF or OVA file. Conserva el controlador, la posición del disco y el tipo de firmware del original. Si aparece VFS: Unable to mount root fs, compara estos ajustes con la VM que arrancaba. Revisa las redes y no ejecutes las dos VMs a la vez.")
        self.label(page, "La aplicación exporta a un archivo local. No solicita credenciales de ESXi ni publica discos, claves o licencias en el repositorio.")

    def export(self):
        if not messagebox.askyesno("Exportar VM", "¿La VM está apagada y su VMX apunta al VMDK preparado?"):
            return
        tool, vmx, output = self.ovftool.get(), self.vmx.get(), self.ova.get()
        self.task("Exportar OVA", lambda: str(core.export_ova(tool, vmx, output)))

    def close(self):
        if self.busy:
            messagebox.showinfo("Operación en curso", "Espera a que termine la operación antes de cerrar la aplicación.")
            return
        self.pool.shutdown(wait=False)
        self.destroy()


if __name__ == "__main__":
    Assistant().mainloop()
