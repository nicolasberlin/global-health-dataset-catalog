"""Opt-in real Traefik tests: TRAEFIK_TEST_IMAGE=traefik:v3.7.5 pytest -s ...

Uses Compose labels through an equivalent file-provider configuration, disposable
containers and a loopback port. No Docker socket mounts, production env or providers.
The stub isolates proxy admission; real backend quotas are tested in test_public_quotas.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time
import uuid
from pathlib import Path

import httpx
import pytest

IMAGE = os.environ.get("TRAEFIK_TEST_IMAGE")
pytestmark = pytest.mark.skipif(not IMAGE, reason="Set TRAEFIK_TEST_IMAGE for proxy tests")
ROOT = Path(__file__).resolve().parents[1]
SERVER = '''
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json, threading
class Handler(BaseHTTPRequestHandler):
    count = 0
    lock = threading.Lock()
    protocol_version = 'HTTP/1.1'
    def do_GET(self):
        with Handler.lock:
            if self.path != '/stats':
                Handler.count += 1
            payload = json.dumps({'count': Handler.count}).encode()
        self.send_response(429 if self.path == '/backend-limit' else 200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('X-Test-Origin', 'backend')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)
    def log_message(self, *args):
        pass
ThreadingHTTPServer.request_queue_size = 128
ThreadingHTTPServer(('0.0.0.0', 8000), Handler).serve_forever()
'''


def docker(*args):
    return subprocess.check_output(['docker', *args], text=True, stderr=subprocess.PIPE).strip()


def configuration():
    # Never load the developer's .env or interpolate real credentials.
    env = {key: value for key, value in os.environ.items()
           if key in ('PATH', 'HOME', 'DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_CONFIG')}
    env.update(dict.fromkeys([
        'PUBLIC_HOST', 'POSTGRES_PASSWORD', 'RCP_DEEPSEEK_API_KEY',
        'RCP_GEMMA_MEDITRON_API_KEY', 'RCP_APERTUS_MEDITRON_API_KEY',
    ], 'test.invalid'))
    compose = json.loads(subprocess.check_output([
        'docker', 'compose', '--env-file', os.devnull, '-f', str(ROOT / 'docker-compose.yml'),
        'config', '--format', 'json',
    ], env=env, text=True, stderr=subprocess.PIPE))
    http = {'routers': {}, 'middlewares': {}, 'services': {}}
    for name in ('ai-commons', 'ai-commons-api'):
        labels = compose['services'][name]['labels']
        router = f'traefik.http.routers.{name}.'
        chain = labels[router + 'middlewares'].split(',')
        http['routers'][name] = {
            'rule': labels[router + 'rule'], 'priority': int(labels[router + 'priority']),
            'entryPoints': [labels[router + 'entrypoints']],
            'middlewares': chain, 'service': name,
        }
        for middleware in chain:
            prefix = f'traefik.http.middlewares.{middleware}.'
            if prefix + 'ratelimit.average' in labels:
                http['middlewares'][middleware] = {'rateLimit': {
                    'average': int(labels[prefix + 'ratelimit.average']),
                    'period': labels[prefix + 'ratelimit.period'],
                    'burst': int(labels[prefix + 'ratelimit.burst']),
                }}
            else:
                http['middlewares'][middleware] = {'stripPrefix': {
                    'prefixes': labels[prefix + 'stripprefix.prefixes'].split(','),
                }}
        http['services'][name] = {'loadBalancer': {
            'servers': [{'url': 'http://origin:8000'}],
        }}
    return {'http': http}


@pytest.fixture
def proxy(tmp_path):
    name = 'gh-rate-test-' + uuid.uuid4().hex[:10]
    origin, gateway = name + '-origin', name + '-proxy'
    (tmp_path / 'server.py').write_text(SERVER)
    (tmp_path / 'dynamic.yml').write_text(json.dumps(configuration()))
    docker('network', 'create', name)
    try:
        docker('create', '--name', origin, '--network', name, '--network-alias', 'origin',
               'python:3.11-alpine', 'python', '/server.py')
        docker('cp', str(tmp_path / 'server.py'), origin + ':/server.py')
        docker('start', origin)
        docker('create', '--name', gateway, '--network', name, '-p', '127.0.0.1::8080',
               IMAGE, '--entrypoints.web.address=:8080',
               '--providers.file.filename=/dynamic.yml')
        docker('cp', str(tmp_path / 'dynamic.yml'), gateway + ':/dynamic.yml')
        docker('start', gateway)
        port = json.loads(docker('inspect', gateway))[0]['NetworkSettings']['Ports'][
            '8080/tcp'][0]['HostPort']
        url = 'http://127.0.0.1:' + port
        with httpx.Client(base_url=url, headers={'Host': 'test.invalid'}) as client:
            for _ in range(100):
                try:
                    if client.get('/ai-commons/api/stats').status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                time.sleep(.1)
            else:
                pytest.fail('Traefik did not become ready: ' + docker('logs', gateway))
        yield url
    finally:
        for container in (gateway, origin):
            subprocess.run(['docker', 'rm', '-f', container], capture_output=True)
        docker('network', 'rm', name)


@pytest.mark.anyio
@pytest.mark.parametrize('visitors', [5, 10, 20])
async def test_same_ip_polling(proxy, visitors):
    async with httpx.AsyncClient(base_url=proxy, headers={'Host': 'test.invalid'},
                                timeout=10, limits=httpx.Limits(max_connections=100)) as client:
        before = (await client.get('/ai-commons/api/stats')).json()['count']
        pending = []
        started = time.monotonic()
        # Distinct cookies do not create separate proxy buckets. Ten seconds drains
        # the 400-token burst when 20 visitors each offer 14 polls/second.
        for tick in range(140):
            await asyncio.sleep(max(0, started + tick / 14 - time.monotonic()))
            pending.extend(
                asyncio.create_task(client.get(
                    '/ai-commons/api/poll', headers={'Cookie': f'visitor={i}'}
                )) for i in range(visitors)
            )
        responses = await asyncio.gather(*pending)
        elapsed = time.monotonic() - started
        assert elapsed < 12, 'Load generator too slow to exercise the configured limit'
        rejected = [r for r in responses if r.status_code == 429]
        accepted = [r for r in responses if r.status_code == 200]
        assert len(accepted) + len(rejected) == visitors * 140
        assert all('x-test-origin' not in r.headers for r in rejected)
        assert all(r.text == 'Too Many Requests' for r in rejected)
        if visitors <= 10:
            assert not rejected
        else:
            assert rejected
        # Refill before diagnostic read; rejected requests never reached origin.
        await asyncio.sleep(1)
        after = (await client.get('/ai-commons/api/stats')).json()['count']
        assert after - before == len(accepted)
        print(f'\n{visitors} visitors / same IP: {len(accepted)} origin, '
              f'{len(rejected)} Traefik 429, {elapsed:.2f}s')
        backend = await client.get('/ai-commons/api/backend-limit')
        assert backend.status_code == 429
        assert backend.headers['x-test-origin'] == 'backend'


@pytest.mark.anyio
async def test_frontend_bucket_does_not_consume_api_budget(proxy):
    async with httpx.AsyncClient(base_url=proxy, headers={'Host': 'test.invalid'},
                                timeout=10) as client:
        responses = await asyncio.gather(*[client.get('/ai-commons/') for _ in range(300)])
        assert any(r.status_code == 429 for r in responses)
        assert (await client.get('/ai-commons/api/poll')).status_code == 200
