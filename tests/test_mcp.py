"""Real localhost Streamable HTTP protocol tests; only model responses are mocked."""
import asyncio
import json
import logging
import socket
import threading
import time
import unittest
from pathlib import Path

import httpx
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from skill_bowl.check_mcp import verify
from skill_bowl.core import Settings
from skill_bowl.mcp_app import create_app

REST = 'rest-test-only-token-at-least-32-chars'
RUN = 'run-test-only-token-at-least-32-chars'
READ = 'read-test-only-token-at-least-32-chars'
SENTINEL = 'sensitive-input-do-not-log'


class MCPTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.calls = []
        async def model(request):
            body = json.loads(request.content)
            cls.calls.append(body)
            value = json.loads(body['messages'][1]['content'])['input']
            if value == 'deadline':
                await asyncio.sleep(2)
            else:
                await asyncio.sleep(.01)
            if value == 'leak-key':
                return httpx.Response(200, json={'choices': [{'message': {'content': 'fake-model-key'}}]})
            if value == 'leak-token':
                return httpx.Response(200, json={'choices': [{'message': {'content': RUN}}]})
            if value == 'timeout':
                raise httpx.ReadTimeout('private-provider-error')
            if value == 'failure':
                return httpx.Response(500, text='private-provider-error')
            if value == 'invalid-response':
                return httpx.Response(200, json={'choices': []})
            return httpx.Response(200, json={'choices': [{'message': {'content': 'mock-model-result'}}]})
        cls.settings = Settings(Path(__file__).resolve().parents[1] / 'examples/skills', REST,
                                'https://model.example/v1/chat/completions', 'mock-model', 'fake-model-key', 1)
        app = create_app(cls.settings, httpx.MockTransport(model), RUN, READ)
        cls.sock = socket.socket()
        cls.sock.bind(('127.0.0.1', 0))
        cls.url = f'http://127.0.0.1:{cls.sock.getsockname()[1]}/mcp'
        cls.server = uvicorn.Server(uvicorn.Config(app, log_level='warning', access_log=False))
        cls.thread = threading.Thread(target=cls.server.run, kwargs={'sockets': [cls.sock]}, daemon=True)
        cls.thread.start()
        for _ in range(100):
            if cls.server.started:
                break
            time.sleep(.05)
        else:
            cls.server.should_exit = True
            raise RuntimeError('MCP server did not start')

    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit = True
        cls.thread.join(timeout=10)
        cls.sock.close()
        if cls.thread.is_alive():
            raise RuntimeError('MCP server did not stop')

    async def session_call(self, token, callback):
        async with httpx.AsyncClient(headers={'Authorization': 'Bearer ' + token}, timeout=5) as client:
            async with streamable_http_client(self.url, http_client=client) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    return await callback(session)

    async def test_tool_discovery_and_private_resources(self):
        async def check(session):
            tools = await session.list_tools()
            self.assertEqual({t.name for t in tools.tools}, {'list_skills', 'run_skill'})
            self.assertEqual((await session.list_resources()).resources, [])
            self.assertEqual((await session.list_resource_templates()).resourceTemplates, [])
            self.assertEqual((await session.list_prompts()).prompts, [])
            result = await session.call_tool('list_skills', {})
            self.assertFalse(result.isError)
            data = result.structuredContent
            self.assertEqual({s['id'] for s in data['skills']}, {'writer', 'reviewer'})
            self.assertNotIn('instructions', result.model_dump_json())
            with self.assertRaises(Exception):
                await session.read_resource('file:///SKILL.md')
        await self.session_call(READ, check)

    async def test_multiple_skills_and_revision(self):
        before = len(self.calls)
        async def check(session):
            for skill in ('writer', 'reviewer'):
                result = await session.call_tool('run_skill', {'skill_id': skill, 'input': 'draft',
                    'feedback': 'shorter', 'previous_result': 'old draft'})
                self.assertFalse(result.isError, result.model_dump_json())
                self.assertEqual(result.structuredContent['skill_id'], skill)
                self.assertEqual(result.structuredContent['result'], 'mock-model-result')
        await self.session_call(RUN, check)
        calls = self.calls[before:]
        self.assertEqual(len(calls), 2)
        self.assertNotEqual(calls[0]['messages'][0], calls[1]['messages'][0])
        data = json.loads(calls[0]['messages'][1]['content'])
        self.assertEqual(data['feedback'], 'shorter')
        self.assertEqual(data['previous_result'], 'old draft')

    async def test_invalid_and_missing_token_no_dispatch(self):
        before = len(self.calls)
        async with httpx.AsyncClient() as client:
            for token in ('', 'invalid', REST):
                headers = {'Authorization': 'Bearer ' + token} if token else {}
                for method in ('GET', 'POST', 'DELETE'):
                    response = await client.request(method, self.url, headers=headers,
                        json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                              'params': {'name': 'run_skill', 'arguments': {'skill_id': 'writer', 'input': 'draft'}}})
                    self.assertEqual(response.status_code, 401)
        self.assertEqual(len(self.calls), before)

    async def test_read_only_token_cannot_execute(self):
        before = len(self.calls)
        async def check(session):
            result = await session.call_tool('run_skill', {'skill_id': 'writer', 'input': SENTINEL})
            self.assertTrue(result.isError)
            self.assertNotIn(SENTINEL, result.model_dump_json())
        await self.session_call(READ, check)
        self.assertEqual(len(self.calls), before)

    async def test_concurrent_token_isolation(self):
        before = len(self.calls)
        async def attempt(token):
            async def check(session):
                return await session.call_tool('run_skill', {'skill_id': 'writer', 'input': 'draft'})
            return await self.session_call(token, check)
        results = await asyncio.gather(attempt(READ), attempt(RUN), attempt(READ), attempt(RUN))
        self.assertEqual([r.isError for r in results], [True, False, True, False])
        self.assertEqual(len(self.calls) - before, 2)

    async def test_errors_limits_and_safe_logging(self):
        before = len(self.calls)
        async def check(session):
            with self.assertLogs('skill_bowl.mcp', level='INFO') as logs:
                for arguments in ({'skill_id': 'missing', 'input': SENTINEL},
                    {'skill_id': 'writer', 'input': SENTINEL * 1000},
                    {'skill_id': 'writer', 'input': {'secret': SENTINEL}},
                    {'skill_id': '../SKILL.md', 'input': SENTINEL}):
                    result = await session.call_tool('run_skill', arguments)
                    self.assertTrue(result.isError)
                    self.assertNotIn(SENTINEL, result.model_dump_json())
            self.assertNotIn(SENTINEL, '\n'.join(logs.output))
            self.assertNotIn('fake-model-key', '\n'.join(logs.output))
            for value in ('failure', 'timeout', 'invalid-response', 'leak-key', 'leak-token'):
                result = await session.call_tool('run_skill', {'skill_id': 'writer', 'input': value})
                self.assertTrue(result.isError)
                self.assertNotIn('private-provider-error', result.model_dump_json())
                self.assertNotIn('fake-model-key', result.model_dump_json())
                self.assertNotIn(RUN, result.model_dump_json())
        await self.session_call(RUN, check)
        self.assertEqual(len(self.calls) - before, 5)

    async def test_local_verifier_without_model_and_with_mock_model(self):
        before = len(self.calls)
        result = await verify(self.url, RUN)
        self.assertEqual(result['skill_execution'], 'not_run')
        self.assertEqual(result['cursor_ui'], 'not_tested')
        self.assertEqual(len(self.calls), before)
        result = await verify(self.url, RUN, run_skills=True)
        self.assertEqual(result['skill_execution'], 'passed')
        self.assertEqual(len(self.calls) - before, 2)

    async def test_real_total_timeout(self):
        async def check(session):
            started = time.monotonic()
            result = await session.call_tool('run_skill', {'skill_id': 'writer', 'input': 'deadline'})
            self.assertTrue(result.isError)
            self.assertLess(time.monotonic() - started, 1.8)
        await self.session_call(RUN, check)

    async def test_body_and_host_origin_limits(self):
        headers = {'Authorization': 'Bearer ' + RUN}
        async with httpx.AsyncClient() as client:
            response = await client.post(self.url, headers=headers, content=b'x'*65537)
            self.assertEqual(response.status_code, 413)
            for extra in ({'Host': 'untrusted.example'}, {'Origin': 'https://untrusted.example'}):
                response = await client.post(self.url, headers={**headers, **extra},
                    json={'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {}})
                self.assertIn(response.status_code, (403, 421))
            response = await client.post(self.url, headers=[('Authorization', 'Bearer '+RUN),
                ('Authorization', 'Bearer '+READ)], content=b'{}')
            self.assertEqual(response.status_code, 401)
            with self.assertLogs('mcp.server.transport_security', level='WARNING') as logs:
                response = await client.post(self.url, headers={**headers, 'Host': SENTINEL}, json={})
            self.assertEqual(response.status_code, 421)
            self.assertNotIn(SENTINEL, '\n'.join(logs.output))
            response = await client.get(self.url.replace('/mcp', '/SKILL.md'), headers=headers)
            self.assertEqual(response.status_code, 404)

    async def test_token_configuration(self):
        for run, read in (('', READ), ('short', READ), (REST, READ), (RUN, RUN)):
            with self.subTest(run=run), self.assertRaises(ValueError):
                create_app(self.settings, run_token=run, read_token=read)
