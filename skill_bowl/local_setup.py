"""Local-only setup. No model request is made here; secrets never go to stdout."""
import argparse
import csv
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def private_directory(path):
    path = Path(path)
    if path.is_symlink():
        raise ValueError('Private directory cannot be a symlink')
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == 'nt':
        # Set ACL before writing any tokens, using the current user's SID.
        output = subprocess.check_output(['whoami', '/user', '/fo', 'csv', '/nh'], text=True)
        sid = next(csv.reader([output.strip()]))[1]
        subprocess.run(['icacls', str(path), '/inheritance:r', '/grant:r', f'*{sid}:(OI)(CI)F'],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        path.chmod(0o700)
    return path


def read_json(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 1048576:
        raise ValueError('Unsafe or oversized local configuration')
    return json.loads(path.read_text(encoding='utf-8-sig'))


def write_json(path, value):
    if path.is_symlink():
        raise ValueError('Configuration cannot be a symlink')
    fd, temporary = tempfile.mkstemp(prefix='.skill-bowl-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        if os.name == 'nt':
            # Restrict the file before publishing it in the Cursor configuration path.
            output = subprocess.check_output(['whoami', '/user', '/fo', 'csv', '/nh'], text=True)
            sid = next(csv.reader([output.strip()]))[1]
            subprocess.run(['icacls', temporary, '/inheritance:r', '/grant:r', f'*{sid}:F'],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def prepare(root, local_dir, port=8002):
    root, local_dir = Path(root).resolve(), Path(local_dir).absolute()
    if not 1024 <= port <= 65535:
        raise ValueError('Port must be between 1024 and 65535')
    if local_dir.resolve().is_relative_to(root):
        raise ValueError('Private state must stay outside the repository')
    local_dir = private_directory(local_dir)
    state_path = local_dir / 'runtime.json'
    if state_path.exists() or state_path.is_symlink():
        state = read_json(state_path)
        if not isinstance(state, dict) or set(state) != {'rest_token', 'run_token', 'read_token'}:
            raise ValueError('Invalid local token configuration')
        tokens = list(state.values())
        if any(not isinstance(t, str) or len(t) < 24 for t in tokens) or len(set(tokens)) != 3:
            raise ValueError('Invalid local tokens')
    else:
        state = {name: secrets.token_urlsafe(32) for name in ('rest_token', 'run_token', 'read_token')}
        write_json(state_path, state)
    skills = local_dir / 'skills'
    if skills.is_symlink():
        raise ValueError('Private skills directory cannot be a symlink')
    if not skills.exists():
        shutil.copytree(root / 'examples/skills', skills)
    if not skills.is_dir():
        raise ValueError('Invalid private skills directory')
    cursor_dir = root / '.cursor'
    if cursor_dir.is_symlink():
        raise ValueError('Cursor configuration directory cannot be a symlink')
    cursor_dir.mkdir(exist_ok=True)
    cursor_path = cursor_dir / 'mcp.json'
    config = read_json(cursor_path) if cursor_path.exists() or cursor_path.is_symlink() else {}
    if not isinstance(config, dict) or not isinstance(config.get('mcpServers', {}), dict):
        raise ValueError('Invalid existing Cursor configuration; file was preserved')
    servers = config.setdefault('mcpServers', {})
    entry = {'url': f'http://127.0.0.1:{port}/mcp',
             'headers': {'Authorization': 'Bearer ' + state['run_token']}}
    existing = servers.get('skill-bowl')
    if existing is not None:
        # Only update an entry demonstrably generated with our persisted token.
        if not isinstance(existing, dict) or existing.get('headers') != entry['headers']:
            raise ValueError('Existing skill-bowl configuration conflicts; file was preserved')
    servers['skill-bowl'] = entry
    write_json(cursor_path, config)
    environment = os.environ.copy()
    environment.update(SKILL_BOWL_API_TOKEN=state['rest_token'],
                       SKILL_BOWL_MCP_RUN_TOKEN=state['run_token'],
                       SKILL_BOWL_MCP_READ_TOKEN=state['read_token'],
                       SKILL_BOWL_SKILLS_DIR=str(skills),
                       SKILL_BOWL_MCP_ALLOWED_HOSTS='127.0.0.1:*,localhost:*',
                       SKILL_BOWL_MCP_ALLOWED_ORIGINS='')
    # Provider settings are inherited in memory only, never saved to runtime.json.
    return environment, cursor_path


def main():
    parser = argparse.ArgumentParser(description='Prepare local Cursor configuration and start loopback MCP')
    parser.add_argument('--port', type=int, default=8002)
    parser.add_argument('--prepare-only', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    local_dir = Path(os.getenv('LOCALAPPDATA', str(Path.home() / '.local/share'))) / 'SkillBowl'
    try:
        environment, cursor_path = prepare(root, local_dir, args.port)
        print('Local Cursor configuration prepared (contains a private token):', cursor_path)
        print('Cursor configuration format still requires confirmation in the installed Cursor version.')
        configured = all(environment.get(k) for k in ('MODEL_API_URL', 'MODEL_NAME', 'MODEL_API_KEY'))
        print('Model configuration:', 'present; not tested' if configured else 'incomplete; execution will return an error')
        if args.prepare_only:
            return 0
        import uvicorn
        from .mcp_app import create_app
        os.environ.update(environment)
        # Run in this process so stopping the launcher cannot orphan a server child.
        uvicorn.run(create_app(), host='127.0.0.1', port=args.port, access_log=False)
        return 0
    except (ValueError, OSError, subprocess.SubprocessError):
        print('Local setup failed. Check paths, permissions, port, and existing configuration; no files were intentionally overwritten on conflict.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
