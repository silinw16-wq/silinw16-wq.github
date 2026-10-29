"""Local protocol verifier; never claims to test the Cursor UI."""
import argparse
import asyncio
import os
from pathlib import Path

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from .local_setup import read_json


async def verify(url, token, run_skills=False):
    # Deliberately test invalid authentication before initializing a valid session.
    async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
        response = await client.post(url, headers={'Authorization': 'Bearer invalid-test-token'}, json={})
        if response.status_code != 401:
            raise RuntimeError('Invalid-token rejection failed')
    async with httpx.AsyncClient(headers={'Authorization': 'Bearer ' + token}, timeout=130,
                                 trust_env=False) as client:
        async with streamable_http_client(url, http_client=client) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = {tool.name for tool in (await session.list_tools()).tools}
                if tools != {'list_skills', 'run_skill'}:
                    raise RuntimeError('Tool discovery failed')
                result = await session.call_tool('list_skills', {})
                if result.isError or not result.structuredContent:
                    raise RuntimeError('Skill discovery failed')
                ids = {skill['id'] for skill in result.structuredContent['skills']}
                if not {'writer', 'reviewer'} <= ids:
                    raise RuntimeError('Both demo Skills must be enabled for this check')
                if run_skills:
                    for skill in ('writer', 'reviewer'):
                        result = await session.call_tool('run_skill', {'skill_id': skill,
                            'input': '为社区读书活动写一句简短介绍。' if skill == 'writer' else '审阅这句话：所有读书活动都能保证参与者成功。'})
                        if result.isError or not result.structuredContent or not result.structuredContent.get('result', '').strip():
                            raise RuntimeError('Skill execution failed')
    return {'protocol': 'passed', 'invalid_token': 'rejected', 'skills': 2,
            'skill_execution': 'passed' if run_skills else 'not_run', 'cursor_ui': 'not_tested'}


def main():
    parser = argparse.ArgumentParser(description='Verify local MCP; Cursor UI is not tested')
    parser.add_argument('--port', type=int, default=8002)
    parser.add_argument('--run-skills', action='store_true', help='Send two requests to the configured model')
    parser.add_argument('--confirm-model-call', action='store_true', help='Explicitly confirm provider use and any costs before model calls')
    args = parser.parse_args()
    if args.run_skills and not args.confirm_model_call:
        parser.error('--run-skills requires --confirm-model-call; model requests may incur charges')
    local_dir = Path(os.getenv('LOCALAPPDATA', str(Path.home() / '.local/share'))) / 'SkillBowl'
    try:
        token = read_json(local_dir / 'runtime.json')['run_token']
        result = asyncio.run(verify(f'http://127.0.0.1:{args.port}/mcp', token, args.run_skills))
        print(result)
        return 0
    except Exception:
        print('Verification failed. Check service, configuration and authorization. No private response details were printed.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
