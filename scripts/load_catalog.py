#!/usr/bin/env python3
"""Read-only parallel catalogue smoke test. Run only against an authorized target."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request


def measure(base, requests=100, workers=10):
    parsed = urllib.parse.urlsplit(base)
    if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('','/'):
        raise ValueError('Nur die Basisadresse ohne Zugangsdaten, Pfad oder Suchparameter angeben.')
    if not 1<=workers<=100 or not 1<=requests<=10000:
        raise ValueError('1–100 parallele Anfragen und 1–10.000 Anfragen insgesamt verwenden.')
    sorts = ('number','title','department','type','due')
    def request_one(index):
        url = base.rstrip('/')+'/documents/?'+urllib.parse.urlencode({'sort':sorts[index%len(sorts)],'fragment':'1'})
        start = time.monotonic()
        try:
            with urllib.request.urlopen(urllib.request.Request(url,headers={'Accept':'application/json','User-Agent':'IMS-DMS-load-check'}),timeout=30) as response:
                payload = json.loads(response.read(4*1024*1024))
                if response.status!=200 or not isinstance(payload.get('total_count'),int) or not isinstance(payload.get('html'),str):
                    raise ValueError('Invalid catalogue response')
            return time.monotonic()-start,True
        except (OSError,ValueError,urllib.error.URLError):
            return time.monotonic()-start,False
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(request_one,range(requests)))
    duration = time.monotonic()-started
    times = sorted(seconds for seconds,ok in results)
    return {'requests':requests,'concurrency':workers,'successful':sum(ok for seconds,ok in results),'failed':sum(not ok for seconds,ok in results),
        'duration_seconds':round(duration,3),'requests_per_second':round(requests/duration,2),
        'median_ms':round(statistics.median(times)*1000,2),'p95_ms':round(times[min(len(times)-1, int(len(times)*.95))]*1000,2)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url',required=True)
    parser.add_argument('--requests',type=int,default=100)
    parser.add_argument('--workers',type=int,default=10)
    parser.add_argument('--output',type=Path)
    args = parser.parse_args()
    report = measure(args.base_url,args.requests,args.workers)
    text = json.dumps(report,indent=2)+'\n'
    if args.output:args.output.write_text(text)
    print(text,end='')
    return 1 if report['failed'] else 0


if __name__=='__main__':
    raise SystemExit(main())
