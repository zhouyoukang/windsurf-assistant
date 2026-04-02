#!/usr/bin/env python3
"""Probe all ports 19875-19885 to see what's running."""
import urllib.request, urllib.error, json, subprocess, os

for p in range(19875, 19886):
    for path in ['/api/health', '/pool/health', '/health', '/']:
        try:
            r = urllib.request.urlopen(f'http://127.0.0.1:{p}{path}', timeout=2)
            data = r.read()[:300]
            print(f'  PORT {p} {path} → 200 OK: {data[:120]}')
            break
        except urllib.error.HTTPError as e:
            body = e.read()[:120]
            print(f'  PORT {p} {path} → HTTP {e.code}: {body}')
            break
        except Exception:
            pass  # not listening / refused
