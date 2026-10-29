import json
import shutil
import tempfile
import unittest
from pathlib import Path

import httpx
from fastapi.testclient import TestClient
from skill_bowl.app import create_app
from skill_bowl.core import Settings, load_skills

TOKEN = 'test-access-token-at-least-24-characters'
AUTH = {'Authorization': 'Bearer ' + TOKEN}

class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name) / 'skills'
        shutil.copytree(Path(__file__).resolve().parents[1] / 'examples/skills', self.directory)
        self.requests = []

    def handler(self, request):
        self.requests.append(json.loads(request.content))
        return httpx.Response(200, json={'choices': [{'message': {'content': '模拟结果'}}]})

    def client(self, handler=None, configured=True):
        settings = Settings(self.directory, TOKEN,
                            'https://model.example/v1/chat/completions' if configured else '',
                            'test-model', 'fake-unit-test-key')
        return TestClient(create_app(settings, httpx.MockTransport(handler or self.handler)))

    def execute(self, client, **extra):
        return client.post('/v1/execute', headers=AUTH,
                           json={'skill_id': 'writer', 'input': '测试输入', **extra})

    def test_list_auth_and_privacy(self):
        with self.client() as client:
            self.assertEqual(client.get('/health').json(), {'status': 'ok'})
            self.assertEqual(client.get('/v1/skills').status_code, 401)
            response = client.get('/v1/skills', headers=AUTH)
            self.assertEqual(len(response.json()['skills']), 2)
            self.assertNotIn('instructions', response.text)
            self.assertNotIn('你是一名', response.text)
            self.assertEqual(client.get('/docs').status_code, 404)
            self.assertEqual(client.get('/SKILL.md').status_code, 404)

    def test_execute_feedback_and_switch(self):
        with self.client() as client:
            with self.assertLogs('skill_bowl', level='INFO') as logs:
                response = self.execute(client, feedback='秘密修改意见', previous_result='秘密上一版')
            self.assertEqual(response.json()['result'], '模拟结果')
            self.assertNotIn('秘密', str(logs.output))
            self.assertNotIn('fake-unit-test-key', str(logs.output))
            self.assertEqual(json.loads(self.requests[0]['messages'][1]['content'])['feedback'], '秘密修改意见')
            self.assertEqual(self.execute(client, skill_id='reviewer').status_code, 200)
            self.assertNotEqual(self.requests[0]['messages'][0], self.requests[1]['messages'][0])

    def test_add_disable_and_restart(self):
        source = self.directory / 'writer'
        shutil.copytree(source, self.directory / 'third')
        manifest = json.loads((source / 'manifest.json').read_text())
        manifest['id'] = 'third'
        (self.directory / 'third/manifest.json').write_text(json.dumps(manifest))
        manifest['id'] = 'writer'
        manifest['enabled'] = False
        (source / 'manifest.json').write_text(json.dumps(manifest))
        with self.client() as client:
            ids = {s['id'] for s in client.get('/v1/skills', headers=AUTH).json()['skills']}
            self.assertEqual(ids, {'reviewer', 'third'})
            self.assertEqual(self.execute(client).status_code, 404)
            self.assertEqual(self.execute(client, skill_id='third').status_code, 200)
        manifest['enabled'] = True
        (source / 'manifest.json').write_text(json.dumps(manifest))
        with self.client() as client:
            ids = {s['id'] for s in client.get('/v1/skills', headers=AUTH).json()['skills']}
            self.assertEqual(ids, {'writer', 'reviewer', 'third'})
            self.assertEqual(self.execute(client).status_code, 200)

    def test_input_limits(self):
        with self.client() as client:
            for fields in [{'input': 'x'*8001}, {'input': ' '}, {'input': 123},
                           {'feedback': 'x'*4001}, {'previous_result': 'x'*16001},
                           {'skill_id': '../writer'}, {'extra': 'private'}]:
                response = self.execute(client, **fields)
                self.assertEqual(response.status_code, 422)
                self.assertNotIn('private', response.text)
            response = client.post('/v1/execute', headers=AUTH, content=b'x'*65537)
            self.assertEqual(response.status_code, 413)
            response = client.post('/v1/execute', headers=AUTH, content=b'{bad secret')
            self.assertEqual(response.status_code, 422)
            self.assertNotIn('secret', response.text)

    def test_missing_model_configuration(self):
        with self.client(configured=False) as client:
            self.assertEqual(self.execute(client).status_code, 503)

    def test_upstream_failures_are_sanitized(self):
        def timeout(request):
            raise httpx.ReadTimeout('secret upstream details')
        cases = [(lambda r: httpx.Response(401, text='secret upstream details'), 502),
                 (lambda r: httpx.Response(200, text='secret upstream details'), 502),
                 (lambda r: httpx.Response(200, json={'choices': []}), 502),
                 (lambda r: httpx.Response(200, content=b'x'*262145), 502),
                 (timeout, 504)]
        for handler, status in cases:
            with self.subTest(status=status), self.client(handler) as client:
                response = self.execute(client)
                self.assertEqual(response.status_code, status)
                self.assertNotIn('secret', response.text)

    def test_full_instruction_echo_blocked(self):
        text = (self.directory / 'writer/SKILL.md').read_text().strip()
        with self.client(lambda r: httpx.Response(200, json={'choices': [{'message': {'content': text}}]})) as client:
            response = self.execute(client)
            self.assertEqual(response.status_code, 502)
            self.assertNotIn(text, response.text)

    def test_invalid_skill_rejected(self):
        path = self.directory / 'writer/manifest.json'
        original = json.loads(path.read_text())
        for update in [{'type': 'python'}, {'enabled': 'false'}, {'id': '../bad'}, {'name': ''}]:
            path.write_text(json.dumps({**original, **update}))
            with self.subTest(update=update), self.assertRaises(ValueError):
                load_skills(self.directory)
        path.write_text(json.dumps(original))
        (self.directory / 'writer/SKILL.md').write_text(' ')
        with self.assertRaises(ValueError):
            load_skills(self.directory)

    def test_symlink_and_duplicate_rejected(self):
        (self.directory / 'escape').symlink_to(self.directory / 'writer', target_is_directory=True)
        with self.assertRaises(ValueError):
            load_skills(self.directory)
        (self.directory / 'escape').unlink()
        shutil.copytree(self.directory / 'writer', self.directory / 'duplicate')
        with self.assertRaises(ValueError):
            load_skills(self.directory)

    def test_configuration_validation(self):
        with self.assertRaises(ValueError):
            create_app(Settings(self.directory, 'short'))
        with self.assertRaises(ValueError):
            create_app(Settings(self.directory, TOKEN, 'http://insecure.example'))
        with self.assertRaises(ValueError):
            create_app(Settings(self.directory, TOKEN, timeout=0))

if __name__ == '__main__':
    unittest.main()
