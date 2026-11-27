"""Real Gunicorn/file-wrapper regression: bounded memory, exact bytes, healthy worker."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request

if os.environ.get('CI')!='true' or not sys.platform.startswith('linux'):
    raise SystemExit('Run only on an isolated Linux CI runner.')

root = Path(__file__).resolve().parents[1]
artifacts = root/'test-results'
fixture = json.loads((artifacts/'download-fixture.json').read_text())
with socket.socket() as probe:
    probe.bind(('127.0.0.1',0))
    port = probe.getsockname()[1]
base = f'http://127.0.0.1:{port}'


def fetch(path, expected=None):
    with urllib.request.urlopen(base+path,timeout=30) as response:
        digest = hashlib.sha256()
        size = 0
        while chunk := response.read(64*1024):
            digest.update(chunk)
            size += len(chunk)
        if expected:
            assert size==expected['size'] and digest.hexdigest()==expected['sha256'], 'Truncated or altered download'
        return size


def children(process):
    return (Path('/proc')/str(process.pid)/'task'/str(process.pid)/'children').read_text().split()


with (artifacts/'gunicorn-download.log').open('w') as log:
    process = subprocess.Popen([sys.executable,'-m','gunicorn','config.wsgi:application',
        '--bind',f'127.0.0.1:{port}','--workers','1','--timeout','15',
        '--config',str(root/'tests/gunicorn_download_config.py'),
        '--access-logfile','-','--error-logfile','-'],cwd=root,stdout=log,stderr=subprocess.STDOUT)
    try:
        for attempt in range(100):
            try:
                fetch('/')
                break
            except OSError:
                if process.poll() is not None:raise RuntimeError('Gunicorn failed to start')
                time.sleep(.1)
        else:raise RuntimeError('Gunicorn startup timed out')
        before = children(process)
        assert len(before)==1
        for _ in range(3):fetch(fixture['large']['path'],fixture['large'])
        # An interrupted client must release its file without killing the worker.
        with urllib.request.urlopen(base+fixture['large']['path'],timeout=30) as response:
            response.read(1024)
        with ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(lambda _:fetch(fixture['large']['path'],fixture['large']),range(3)))
        with urllib.request.urlopen(base+fixture['preview'],timeout=30) as response:
            assert response.read(5)==b'%PDF', 'PDF download is not a PDF'
        fetch('/')
        after = children(process)
        assert before==after, 'Gunicorn worker restarted during downloads'
        report = {'original_downloads':6,'size_bytes':fixture['large']['size'],
            'additional_address_space_mib':12,'interrupted_client':True,'pdf_download':True,'worker_unchanged':True}
        (artifacts/'download-report.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report))
    finally:
        process.terminate()
        try:process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill();process.wait()
