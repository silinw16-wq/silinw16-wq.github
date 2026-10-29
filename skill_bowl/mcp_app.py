"""MCP transport adapter; all Skill business logic stays in the existing HTTP app."""
import asyncio
import hmac
import logging
import os
import uuid
from contextlib import asynccontextmanager
from typing import Any

import httpx
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse
from starlette.applications import Starlette
from starlette.routing import Mount

from .app import BodyLimit, ExecuteInput, create_app as create_http_app
from .core import Settings

log = logging.getLogger('skill_bowl.mcp')


class ProtocolLogFilter(logging.Filter):
    def filter(self, record):
        record.msg = 'MCP protocol event'
        record.args = ()
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        return True


def protect_protocol_logs():
    # SDK versions are pinned; cover its concrete logger names, including children
    # created before this factory. Do not change the host application's root logger.
    import importlib
    for name in ('mcp.server.transport_security', 'mcp.server.streamable_http',
                 'mcp.server.streamable_http_manager', 'mcp.server.lowlevel.server',
                 'mcp.server.session', 'mcp.shared.session', 'mcp.server.fastmcp.server'):
        importlib.import_module(name)
    for name in list(logging.Logger.manager.loggerDict):
        if name == 'mcp' or name.startswith('mcp.'):
            logger = logging.getLogger(name)
            if not any(isinstance(f, ProtocolLogFilter) for f in logger.filters):
                logger.addFilter(ProtocolLogFilter())


class SafeMCP(FastMCP):
    async def call_tool(self, name, arguments):
        try:
            return await super().call_tool(name, arguments)
        except Exception:
            # SDK validation errors can contain raw argument values. Never relay them.
            log.warning('tool_call_failed')
            raise ToolError('Tool call failed: check authorization, arguments and service availability') from None


class TokenGate:
    """Authorize before protocol parsing/dispatch, including initialization and GET."""
    def __init__(self, app, tokens, timeout):
        self.app, self.tokens, self.timeout = app, tokens, timeout

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        request_id = uuid.uuid4().hex
        status, started = 500, False
        async def safe_send(message):
            nonlocal status, started
            if message['type'] == 'http.response.start':
                started = True
                status = message['status']
                message['headers'] = list(message.get('headers', [])) + [
                    (b'cache-control', b'no-store'), (b'x-request-id', request_id.encode())]
            await send(message)
        try:
            auth = [value for key, value in scope['headers'] if key.lower() == b'authorization']
            valid = len(auth) == 1 and any(hmac.compare_digest(auth[0], b'Bearer ' + token.encode()) for token in self.tokens)
            if not valid:
                return await JSONResponse({'detail': 'Unauthorized'}, status_code=401,
                    headers={'WWW-Authenticate': 'Bearer'})(scope, receive, safe_send)
            async with asyncio.timeout(self.timeout):
                await self.app(scope, receive, safe_send)
        except TimeoutError:
            if not started:
                await JSONResponse({'detail': 'Request timed out'}, status_code=408)(scope, receive, safe_send)
        finally:
            log.info('request_id=%s status=%d', request_id, status)


def create_app(settings=None, transport=None, run_token=None, read_token=None):
    protect_protocol_logs()
    settings = settings or Settings.from_env()
    settings.validate()
    run_token = run_token if run_token is not None else os.getenv('SKILL_BOWL_MCP_RUN_TOKEN', '')
    read_token = read_token if read_token is not None else os.getenv('SKILL_BOWL_MCP_READ_TOKEN', '')
    if len(run_token) < 24 or (read_token and len(read_token) < 24):
        raise ValueError('MCP tokens must contain at least 24 characters; RUN token is required')
    tokens = [run_token] + ([read_token] if read_token else [])
    if len(set(tokens + [settings.api_token])) != len(tokens) + 1:
        raise ValueError('REST, MCP read and MCP run tokens must be distinct')
    rest = create_http_app(settings, transport)

    @asynccontextmanager
    async def lifespan(server):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=rest), base_url='http://skill-bowl-internal',
                headers={'Authorization': 'Bearer ' + settings.api_token}) as client:
            yield client

    server = SafeMCP('Skill Bowl', stateless_http=True, json_response=True,
        streamable_http_path='/mcp', max_request_body_size=65536, lifespan=lifespan,
        log_level='WARNING', transport_security=TransportSecuritySettings(
            allowed_hosts=os.getenv('SKILL_BOWL_MCP_ALLOWED_HOSTS', '127.0.0.1:*,localhost:*').split(','),
            allowed_origins=[x for x in os.getenv('SKILL_BOWL_MCP_ALLOWED_ORIGINS', '').split(',') if x]))

    def public_result(response):
        response.raise_for_status()
        data = response.json()
        def strings(value):
            if isinstance(value, str):
                yield value
            elif isinstance(value, dict):
                for key, item in value.items():
                    yield from strings(key)
                    yield from strings(item)
            elif isinstance(value, list):
                for item in value:
                    yield from strings(item)
        texts = list(strings(data))
        forbidden = tokens + [settings.api_token]
        if settings.model_key:
            forbidden.append(settings.model_key)
        forbidden.extend(skill.instructions.strip() for skill in rest.state.skills.values())
        if any(secret and secret in text for secret in forbidden for text in texts):
            raise ToolError('Private content blocked')
        return data

    @server.tool()
    async def list_skills(ctx: Context) -> dict[str, Any]:
        """List enabled Skills: public id, name and description only."""
        response = await ctx.request_context.lifespan_context.get('/v1/skills')
        return public_result(response)

    @server.tool()
    async def run_skill(skill_id: str, input: str, ctx: Context,
                        feedback: str = '', previous_result: str = '') -> dict[str, Any]:
        """Execute a Markdown Skill; optionally revise previous_result using feedback."""
        auth = ctx.request_context.request.headers.get('authorization', '')
        if not hmac.compare_digest(auth.encode(), ('Bearer ' + run_token).encode()):
            raise ToolError('Execution permission required')
        body = ExecuteInput(skill_id=skill_id, input=input, feedback=feedback, previous_result=previous_result)
        response = await ctx.request_context.lifespan_context.post('/v1/execute', json=body.model_dump())
        return public_result(response)

    protocol = server.streamable_http_app()

    @asynccontextmanager
    async def app_lifespan(app):
        # One shared business lifecycle per process, not per stateless MCP request.
        # Concurrent requests must never replace/close another request's model client.
        async with rest.router.lifespan_context(rest):
            async with server.session_manager.run():
                yield

    app = Starlette(routes=[Mount('/', app=protocol)], lifespan=app_lifespan)
    return TokenGate(BodyLimit(app), tokens, settings.timeout + 5)
