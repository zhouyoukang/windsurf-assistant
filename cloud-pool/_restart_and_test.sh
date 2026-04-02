#!/bin/bash
set -e
cd /opt/cloud_pool
fuser -k 19880/tcp 2>/dev/null || true
sleep 2
set -a; . .env; set +a
nohup python3 cloud_pool_server.py --host 127.0.0.1 --port 19880 > /var/log/cloud_pool.log 2>&1 &
sleep 3
python3 /tmp/_test_push_api.py
echo "EXIT_CODE=$?"
