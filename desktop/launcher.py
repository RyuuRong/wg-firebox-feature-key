"""PyInstaller entry point; the application is also runnable as a module."""
from desktop.app import Assistant

if __name__ == "__main__":
    Assistant().mainloop()
