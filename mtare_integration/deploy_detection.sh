#!/usr/bin/env bash
# Deploy the monitoring receiver into robot0 for live detection.
#
# Usage:
#   ./deploy_detection.sh <n_robots> [listen_port] [alpha] [window] [snapshot_path]
#
# Example:
#   ./deploy_detection.sh 5 15001 2.0 10 /tmp/detection_snapshot.json

set -euo pipefail

N_ROBOTS="${1:?Usage: deploy_detection.sh <n_robots> [listen_port] [alpha] [window] [snapshot_path]}"
LISTEN_PORT="${2:-15001}"
ALPHA="${3:-2.0}"
WINDOW="${4:-10}"
SNAPSHOT_PATH="${5:-/tmp/detection_snapshot.json}"
SECURITY_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CONTAINER="robot0"

MONITOR_SCRIPT="${SECURITY_DIR}/mtare_integration/monitoring_receiver.py"
if [[ ! -f "$MONITOR_SCRIPT" ]]; then
  echo "ERROR: $MONITOR_SCRIPT not found"
  exit 1
fi

echo "======================================================"
echo " Deploying delay detector on robot0"
echo " Robots: $N_ROBOTS  |  Port: $LISTEN_PORT"
echo " Alpha:  $ALPHA      |  Window: $WINDOW"
echo "======================================================"

docker cp "$MONITOR_SCRIPT" "${CONTAINER}:/home/docker-user/monitoring_receiver.py"

# Kill any existing monitor and BLOCK until it's actually gone -- a bare
# pkill+sleep let a slow-to-die prior instance survive into this mission
# and keep a stale socket bound alongside the new one (SO_REUSEADDR splits
# traffic between them silently instead of erroring).
docker exec "$CONTAINER" pkill -f monitoring_receiver.py 2>/dev/null || true
for i in $(seq 1 20); do
  docker exec "$CONTAINER" pgrep -f monitoring_receiver.py >/dev/null 2>&1 || break
  sleep 0.5
done
docker exec "$CONTAINER" pkill -9 -f monitoring_receiver.py 2>/dev/null || true
sleep 1

# Start monitor (no ROS needed — pure UDP)
docker exec "$CONTAINER" rm -f "$SNAPSHOT_PATH"
docker exec -d "$CONTAINER" bash -lc "
nohup python3 /home/docker-user/monitoring_receiver.py \
  '${N_ROBOTS}' '${LISTEN_PORT}' '${ALPHA}' '${WINDOW}' '${SNAPSHOT_PATH}' \
  > /tmp/monitoring_receiver.log 2>&1 < /dev/null &
"

sleep 2

echo ""
echo "Verifying monitor is running..."
docker exec "$CONTAINER" bash -lc \
  "ps aux | grep monitoring_receiver.py | grep -v grep || echo 'NOT running'"

echo ""
echo "Monitor log:"
docker exec "$CONTAINER" bash -lc \
  "tail -10 /tmp/monitoring_receiver.log 2>/dev/null || echo '(no log yet)'"

echo ""
echo "Detection running. Follow live output:"
echo "  docker exec robot0 tail -f /tmp/monitoring_receiver.log"
