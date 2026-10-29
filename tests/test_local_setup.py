import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from skill_bowl.local_setup import prepare


class LocalSetupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'checkout'
        self.root.mkdir()
        self.private = Path(self.tmp.name) / 'local-private'
        shutil.copytree(Path(__file__).resolve().parents[1] / 'examples/skills', self.root / 'examples/skills')

    def test_repeatable_private_setup_and_merge(self):
        (self.root / '.cursor').mkdir()
        config = self.root / '.cursor/mcp.json'
        config.write_text(json.dumps({'mcpServers': {'existing': {'command': 'untouched'}}, 'other': True}))
        with patch.dict(os.environ, {'MODEL_API_KEY': 'test-provider-key-only'}, clear=False):
            env, target = prepare(self.root, self.private)
        before = (self.private / 'runtime.json').read_bytes()
        self.assertEqual(target, config)
        state = json.loads(before)
        self.assertEqual(len(set(state.values())), 3)
        self.assertNotIn('test-provider-key-only', before.decode())
        self.assertNotIn('test-provider-key-only', config.read_text())
        self.assertEqual(env['MODEL_API_KEY'], 'test-provider-key-only')
        data = json.loads(config.read_text())
        self.assertEqual(data['mcpServers']['existing'], {'command': 'untouched'})
        self.assertTrue(data['other'])
        self.assertEqual(data['mcpServers']['skill-bowl']['url'], 'http://127.0.0.1:8002/mcp')
        skill = self.private / 'skills/writer/SKILL.md'
        skill.write_text('private local edits')
        prepare(self.root, self.private, 8003)
        self.assertEqual(before, (self.private / 'runtime.json').read_bytes())
        self.assertEqual(skill.read_text(), 'private local edits')
        if os.name != 'nt':
            self.assertEqual(config.stat().st_mode & 0o777, 0o600)
            self.assertEqual(self.private.stat().st_mode & 0o777, 0o700)

    def test_existing_conflicting_config_is_preserved(self):
        (self.root / '.cursor').mkdir()
        path = self.root / '.cursor/mcp.json'
        original = json.dumps({'mcpServers': {'skill-bowl': {'command': 'existing-server'}}})
        path.write_text(original)
        with self.assertRaises(ValueError):
            prepare(self.root, self.private)
        self.assertEqual(path.read_text(), original)

    def test_reject_state_in_repository_and_bad_port(self):
        for path, port in ((self.root / 'private', 8002), (self.private, 0)):
            with self.assertRaises(ValueError):
                prepare(self.root, path, port)

    def test_reject_symlink_and_malformed_config(self):
        self.private.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            prepare(self.root, self.private)
        self.private.unlink()
        (self.root / '.cursor').mkdir()
        path = self.root / '.cursor/mcp.json'
        path.write_text('{malformed')
        with self.assertRaises(ValueError):
            prepare(self.root, self.private)
        self.assertEqual(path.read_text(), '{malformed')
