#!/usr/bin/env python3
"""Root-only administrative commands for an installer-managed IMS-DMS host."""
import json
import os
from pathlib import Path
import sys


def main():
    if os.geteuid() != 0:
        sys.exit('Bitte sudo ims-dms-manage verwenden.')
    # Read credentials only as root; never execute/source an environment file.
    from install_linux import STATE, BASE, environment
    state = json.loads(STATE.read_text())
    root = (BASE / 'current').resolve(strict=True)
    os.chdir(root)
    env = dict(os.environ, **environment(state, 'owner'))
    os.execve(str(root / '.venv/bin/python'), [str(root / '.venv/bin/python'),
              str(root / 'manage.py'), *sys.argv[1:]], env)


if __name__ == '__main__':
    main()
