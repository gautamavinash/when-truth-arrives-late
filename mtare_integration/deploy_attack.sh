#!/usr/bin/env bash
# Deploy an attack sender into a robot container.
# Replaces the position sender in the target robot with the attack variant.
#
# Usage:
#   ./deploy_attack.sh <robot_id> <attack_type> <robot0_ip> [lambda_secs] [monitor_port]
#
# Example:
#   ./deploy_attack.sh 2 sla 10.0.2.0 1.5
#
# The sender is pointed at a local udp_tee.py instead of robot0 directly, so
# that every packet is mirrored to both the real receiver (port $PORT) and
# the monitoring_receiver.py detector (port $MONITOR_PORT) on robot0.

set -euo pipefail

ROBOT_ID="${1:?Usage: deploy_attack.sh <robot_id> <attack_type> <robot0_ip> [lambda_secs] [monitor_port]}"
ATTACK_TYPE="${2:?}"
ROBOT0_IP="${3:?}"
LAMBDA="${4:-1.0}"
MONITOR_PORT="${5:-15001}"
PORT=15000
SECURITY_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CONTAINER="robot${ROBOT_ID}"

if [[ "$ATTACK_TYPE" != "sla" && "$ATTACK_TYPE" != "bla" ]]; then
  echo "attack_type must be 'sla' or 'bla'"
  exit 1
fi

SENDER_SCRIPT="${SECURITY_DIR}/mtare_integration/${ATTACK_TYPE}_sender.py"
TEE_SCRIPT="${SECURITY_DIR}/mtare_integration/udp_tee.py"
if [[ ! -f "$SENDER_SCRIPT" ]]; then
  echo "ERROR: $SENDER_SCRIPT not found"
  exit 1
fi
if [[ ! -f "$TEE_SCRIPT" ]]; then
  echo "ERROR: $TEE_SCRIPT not found"
  exit 1
fi

echo "======================================================"
echo " Deploying $ATTACK_TYPE attack on $CONTAINER"
echo " Target: $ROBOT0_IP:$PORT (mirrored to :$MONITOR_PORT)  lambda=${LAMBDA}s"
echo "======================================================"

# Copy attack sender + tee into the container
docker cp "$SENDER_SCRIPT" "${CONTAINER}:/home/docker-user/${ATTACK_TYPE}_sender.py"
docker cp "$TEE_SCRIPT" "${CONTAINER}:/home/docker-user/udp_tee.py"

# Kill any existing position sender / tee in this container
docker exec "$CONTAINER" pkill -f mtare_position_sender.py  2>/dev/null || true
docker exec "$CONTAINER" pkill -f "${ATTACK_TYPE}_sender.py" 2>/dev/null || true
docker exec "$CONTAINER" pkill -f udp_tee.py 2>/dev/null || true

sleep 1

# Start the tee: mirrors every packet to the real receiver and the monitor
docker exec -d "$CONTAINER" bash -lc "
nohup python3 /home/docker-user/udp_tee.py \
  '${PORT}' '${ROBOT0_IP}:${PORT}' '${ROBOT0_IP}:${MONITOR_PORT}' \
  > /tmp/udp_tee_${ROBOT_ID}.log 2>&1 < /dev/null &
"

sleep 1

# Start attack sender, pointed at the local tee instead of robot0 directly
docker exec -d "$CONTAINER" bash -lc "
source /opt/ros/noetic/setup.bash
source /home/docker-user/mtare/autonomous_exploration_development_environment/devel/setup.bash
source /home/docker-user/mtare/tare_system/devel/setup.bash

nohup python3 /home/docker-user/${ATTACK_TYPE}_sender.py \
  '${ROBOT_ID}' '127.0.0.1' '${PORT}' '${LAMBDA}' \
  > /tmp/${ATTACK_TYPE}_sender_${ROBOT_ID}.log 2>&1 < /dev/null &
"

sleep 2

echo ""
echo "Verifying tee + attack sender are running..."
docker exec "$CONTAINER" bash -lc \
  "ps aux | grep -E 'udp_tee.py|${ATTACK_TYPE}_sender.py' | grep -v grep || echo 'NOT running'"

echo ""
echo "Tee log (last 5 lines):"
docker exec "$CONTAINER" bash -lc \
  "tail -5 /tmp/udp_tee_${ROBOT_ID}.log 2>/dev/null || echo '(no log yet)'"

echo ""
echo "Sender log (last 10 lines):"
docker exec "$CONTAINER" bash -lc \
  "tail -10 /tmp/${ATTACK_TYPE}_sender_${ROBOT_ID}.log 2>/dev/null || echo '(no log yet)'"

echo ""
echo "Attack deployed. Monitor with:"
echo "  docker exec $CONTAINER tail -f /tmp/${ATTACK_TYPE}_sender_${ROBOT_ID}.log"
echo "  docker exec $CONTAINER tail -f /tmp/udp_tee_${ROBOT_ID}.log"
