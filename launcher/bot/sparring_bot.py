"""PyInstaller entry point: the same as `python -m sparring.play` (PyInstaller takes a script, not a module)."""
import sys

from sparring.play import main

if __name__ == "__main__":
    sys.exit(main())
