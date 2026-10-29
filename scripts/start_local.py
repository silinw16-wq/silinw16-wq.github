"""Bootstrap a pinned local venv; never calls a model or prints environment values."""
import subprocess
import sys
import venv
from pathlib import Path


def main():
    if sys.version_info < (3, 12):
        print('Python 3.12+ is required.', file=sys.stderr)
        return 1
    root = Path(__file__).resolve().parents[1]
    environment = root / '.venv'
    python = environment / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
    try:
        if not python.exists():
            venv.EnvBuilder(with_pip=True).create(environment)
        subprocess.run([str(python), '-m', 'pip', 'install', '--disable-pip-version-check', '-r', str(root / 'requirements.txt')], check=True, cwd=root)
        return subprocess.call([str(python), '-m', 'skill_bowl.local_setup', *sys.argv[1:]], cwd=root)
    except (OSError, subprocess.SubprocessError):
        print('Bootstrap failed; check Python installation and package network access.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
