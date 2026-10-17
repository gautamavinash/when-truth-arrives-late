#!/usr/bin/env bash
# Restore the stock mtare_position_sender.py in a robot container, sending
# directly to robot0 (undoes deploy_attack.sh / deploy_benign_tee.sh).
#
# Usage:
#   ./restore_sender.sh <robot_id> <robot0_ip>

set -euo pipefail

ROBOT_ID="${1:?Usage: restore_sender.sh <robot_id> <robot0_ip>}"
ROBOT0_IP="${2:?}"
PORT=15000
CONTAINER="robot${ROBOT_ID}"

docker exec "$CONTAINER" pkill -f mtare_position_sender.py 2>/dev/null || true
docker exec "$CONTAINER" pkill -f sla_sender.py            2>/dev/null || true
docker exec "$CONTAINER" pkill -f bla_sender.py              2>/dev/null || true
docker exec "$CONTAINER" pkill -f benign_sender.py           2>/dev/null || true
docker exec "$CONTAINER" pkill -f udp_tee.py                 2>/dev/null || true

sleep 1

docker exec -d "$CONTAINER" bash -lc "
source /opt/ros/noetic/setup.bash
source /home/docker-user/mtare/autonomous_exploration_development_environment/devel/setup.bash
source /home/docker-user/mtare/tare_system/devel/setup.bash

nohup python3 /home/docker-user/mtare_position_sender.py \
  '${ROBOT_ID}' '${ROBOT0_IP}' '${PORT}' \
  > /tmp/mtare_position_sender_${ROBOT_ID}.log 2>&1 < /dev/null &
"

sleep 2
echo "Restored stock sender on $CONTAINER:"
docker exec "$CONTAINER" bash -lc \
  "ps aux | grep mtare_position_sender.py | grep -v grep || echo 'NOT running'"
