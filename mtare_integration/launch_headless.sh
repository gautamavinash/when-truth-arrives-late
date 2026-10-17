#!/usr/bin/env bash
# Headless equivalent of run_mtare.sh — launches one robot in a detached
# tmuxp session on a virtual (Xvfb) display, computing TEST_ID with the
# exact same formula as run_mtare.sh (hand-computing it is error-prone and
# a mismatch silently crashes tare_planner_node at ReadParameters).
#
# Usage:
#   ./launch_headless.sh <environment> <comms_range> <robot_num> <robot_id> <network_interface> <display> [start_x start_y start_yaw]
#
# Example:
#   ./launch_headless.sh tunnel 30 4 0 eno12399 :50

set -euo pipefail

ENVIRONMENT="${1:?Usage: launch_headless.sh <environment> <comms_range> <robot_num> <robot_id> <network_interface> <display>}"
COMMS_RANGE="${2:?}"
ROBOT_NUM="${3:?}"
ROBOT_ID="${4:?}"
NETWORK_INTERFACE="${5:?}"
DISPLAY_ARG="${6:?}"
VX="${7:-0}"
VY="${8:-0}"
VYAW="${9:-0}"

LAUNCH_DIR="$HOME/mtare_project/launcher/mtare_docker"
cd "$LAUNCH_DIR"

if [ "$COMMS_RANGE" -lt 1000 ]; then first_char="1"; else first_char="0"; fi
case "$ENVIRONMENT" in
    tunnel) second_char="0" ;;
    garage) second_char="1" ;;
    campus) second_char="2" ;;
    indoor) second_char="3" ;;
    forest) second_char="4" ;;
    *) echo "Unknown environment: $ENVIRONMENT"; exit 1 ;;
esac
printf -v robot_num_padded "%02d" "$ROBOT_NUM"
TEST_ID="${first_char}${second_char}${robot_num_padded}${COMMS_RANGE}"

export ENVIRONMENT COMMS_RANGE ROBOT_NUM ROBOT_ID NETWORK_INTERFACE TEST_ID
export CONTAINER_NAME="robot${ROBOT_ID}"
export CONTAINER_IP="10.0.2.${ROBOT_ID}"
export DISPLAY="$DISPLAY_ARG"
export VEHICLE_X="$VX" VEHICLE_Y="$VY" VEHICLE_YAW="$VYAW"
export GAZEBO_GUI=false
export RVIZ=false   # headless: never start RViz, even for robot0

sed -i "s/^session_name:.*/session_name: launch_robot${ROBOT_ID}/" launch_robot.yml
sed -i "s/robot.*:/robot${ROBOT_ID}:/" docker-compose-launch-robot.yml

echo "[launch_headless] robot${ROBOT_ID}  env=${ENVIRONMENT}  comms=${COMMS_RANGE}  robot_num=${ROBOT_NUM}  test_id=${TEST_ID}  display=${DISPLAY}"

tmuxp load -d launch_robot.yml
