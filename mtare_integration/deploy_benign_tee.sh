#!/usr/bin/env bash
# Deploy the benign sender + tee into a robot container, so its legitimate
# traffic also reaches the monitoring_receiver.py detector (needed for
# false-positive measurement — deploy_attack.sh only tees the attacker).
#
# Usage:
#   ./deploy_benign_tee.sh <robot_id> <robot0_ip> [monitor_port]
#
# Example:
#   ./deploy_benign_tee.sh 1 10.0.2.0

set -euo pipefail

ROBOT_ID="${1:?Usage: deploy_benign_tee.sh <robot_id> <robot0_ip> [monitor_port]}"
ROBOT0_IP="${2:?}"
MONITOR_PORT="${3:-15001}"
PORT=15000
SECURITY_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CONTAINER="robot${ROBOT_ID}"

SENDER_SCRIPT="${SECURITY_DIR}/mtare_integration/benign_sender.py"
TEE_SCRIPT="${SECURITY_DIR}/mtare_integration/udp_tee.py"

echo "======================================================"
echo " Deploying benign (teed) sender on $CONTAINER"
echo " Target: $ROBOT0_IP:$PORT (mirrored to :$MONITOR_PORT)"
echo "======================================================"

docker cp "$SENDER_SCRIPT" "${CONTAINER}:/home/docker-user/benign_sender.py"
docker cp "$TEE_SCRIPT" "${CONTAINER}:/home/docker-user/udp_tee.py"

# Kill any existing sender / tee in this container
docker exec "$CONTAINER" pkill -f mtare_position_sender.py 2>/dev/null || true
docker exec "$CONTAINER" pkill -f sla_sender.py            2>/dev/null || true
docker exec "$CONTAINER" pkill -f bla_sender.py              2>/dev/null || true
docker exec "$CONTAINER" pkill -f benign_sender.py           2>/dev/null || true
docker exec "$CONTAINER" pkill -f udp_tee.py                 2>/dev/null || true

sleep 1

docker exec -d "$CONTAINER" bash -lc "
nohup python3 /home/docker-user/udp_tee.py \
  '${PORT}' '${ROBOT0_IP}:${PORT}' '${ROBOT0_IP}:${MONITOR_PORT}' \
  > /tmp/udp_tee_${ROBOT_ID}.log 2>&1 < /dev/null &
"

sleep 1

docker exec -d "$CONTAINER" bash -lc "
source /opt/ros/noetic/setup.bash
source /home/docker-user/mtare/autonomous_exploration_development_environment/devel/setup.bash
source /home/docker-user/mtare/tare_system/devel/setup.bash

nohup python3 /home/docker-user/benign_sender.py \
  '${ROBOT_ID}' '127.0.0.1' '${PORT}' \
  > /tmp/benign_sender_${ROBOT_ID}.log 2>&1 < /dev/null &
"

sleep 2

echo ""
echo "Verifying tee + benign sender are running..."
docker exec "$CONTAINER" bash -lc \
  "ps aux | grep -E 'udp_tee.py|benign_sender.py' | grep -v grep || echo 'NOT running'"
