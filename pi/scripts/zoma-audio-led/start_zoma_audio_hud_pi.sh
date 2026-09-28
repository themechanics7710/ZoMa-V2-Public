#!/usr/bin/env bash
# ZoMa Pi audio/LED -- boot launcher for the Pi-side audio/mic/LED processes.
# Property of TheMechanics. Contact: mamau.mechanics@gmail.com
#
# Default (no args):  zoma_audio_client.py + zoma_mic_client.py + zoma_state.py
# With -hud flag:      also launches wifi_diag_publisher.py and
#                       audio_diag_publisher.py, which need rclpy. rclpy is
#                       not installed on the Pi host -- only inside the
#                       ROS2 container, which does not have the host
#                       filesystem mounted. So each HUD launch docker cp's
#                       the current script into the container, then docker
#                       exec's it there.
#
# Usage:
#   ./start_zoma_audio_hud_pi.sh          # audio + mic only
#   ./start_zoma_audio_hud_pi.sh -hud     # audio + mic + HUD diagnostics
#
# Logging: every process appends to one shared log file.
#
# NOTE on killing the HUD processes: the docker-exec PID written to
# $PID_DIR belongs to the docker-exec client on the HOST, not the python
# process inside the container -- killing it only closes the exec session,
# it does not stop the process inside. stop_zoma_audio_hud_pi.sh handles
# this correctly via `docker exec ... pkill -f`; don't kill these two by
# PID alone.

set -uo pipefail   # deliberately NOT -e: background launches must not
                    # abort the rest of the script if one exits non-zero

### ------------------------------------------------------------------ ###
### CONFIG                                                              ###
### ------------------------------------------------------------------ ###

# Set this to the actual path of this repo on your Raspberry Pi.
ZOMA_REPO_DIR="${ZOMA_REPO_DIR:-$HOME/ZoMa-V2}"

# Host-side (run directly on the Pi -- NOT in Docker)
HOST_SCRIPT_DIR="$ZOMA_REPO_DIR/pi/scripts/zoma-audio-led"
PYTHON_BIN="python3"                        # point at a venv's python3 if you have one

AUDIO_SCRIPT="$HOST_SCRIPT_DIR/zoma_audio_client.py"
MIC_SCRIPT="$HOST_SCRIPT_DIR/zoma_mic_client.py"
STATE_SCRIPT="$HOST_SCRIPT_DIR/zoma_state.py"

# HUD diagnostics -- live on the host filesystem but MUST run inside the
# container (rclpy isn't installed on the Pi host)
CONTAINER_NAME="zoma_ros_pi_v2"
DIAG_SCRIPT_DIR="$HOST_SCRIPT_DIR"              # source location on the HOST
CONTAINER_TMP_DIR="/tmp"                        # destination inside the container
ROS_SETUP="/opt/ros/humble/setup.bash"          # path INSIDE the container

# Point this at your ZoMa Brain server's LAN address.
export ZOMA_BRAIN_HOST="${ZOMA_BRAIN_HOST:-192.168.1.50}"

WIFI_DIAG_SCRIPT="$DIAG_SCRIPT_DIR/wifi_diag_publisher.py"
AUDIO_DIAG_SCRIPT="$DIAG_SCRIPT_DIR/audio_diag_publisher.py"

# Logging / PID tracking (host-side paths -- both live outside Docker)
ZOMA_AUDIO_STATE_DIR="${ZOMA_AUDIO_STATE_DIR:-$HOME/zoma-audio}"
LOG_DIR="$ZOMA_AUDIO_STATE_DIR/logs"
LOG_FILE="$LOG_DIR/zoma_$(date +%Y%m%d).log"
PID_DIR="$ZOMA_AUDIO_STATE_DIR/run"

mkdir -p "$LOG_DIR" "$PID_DIR"

### ------------------------------------------------------------------ ###

HUD=0
for arg in "$@"; do
    case "$arg" in
        -hud|--hud)
            HUD=1
            ;;
        *)
            echo "Unknown argument: $arg" >&2
            echo "Usage: $0 [-hud]" >&2
            exit 1
            ;;
    esac
done

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') [LAUNCHER] $*" | tee -a "$LOG_FILE"
}

start_host_process() {
    local name="$1" script="$2"
    local pidfile="$PID_DIR/${name}.pid"

    if [[ -f "$pidfile" ]] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
        log "$name already running (pid $(cat "$pidfile")), skipping"
        return
    fi

    if [[ ! -f "$script" ]]; then
        log "ERROR: $script not found -- skipping $name"
        return
    fi

    nohup "$PYTHON_BIN" "$script" >> "$LOG_FILE" 2>&1 &
    echo $! > "$pidfile"
    log "started $name (pid $!) -> $script"
}

start_container_process() {
    local name="$1" host_script="$2"
    local pidfile="$PID_DIR/${name}.pid"
    local container_script="$CONTAINER_TMP_DIR/$(basename "$host_script")"

    if [[ -f "$pidfile" ]] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
        log "$name already running (pid $(cat "$pidfile")), skipping"
        return
    fi

    if [[ ! -f "$host_script" ]]; then
        log "ERROR: $host_script not found -- skipping $name"
        return
    fi

    if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER_NAME"; then
        log "ERROR: container '$CONTAINER_NAME' is not running -- skipping $name"
        return
    fi

    # Copy the current version of the script in fresh each time, so local
    # edits are picked up without needing a bind mount.
    docker cp "$host_script" "$CONTAINER_NAME:$container_script"

    # Foreground `docker exec`, backgrounded on the HOST side (no -d): its
    # stdout/stderr stream straight back to this shell and into the unified
    # log file -- no bind mount required just to get logs out. Trade-off:
    # killing this PID only closes the exec session, it does NOT signal the
    # python process inside the container. See stop_zoma_audio_hud_pi.sh,
    # which uses `docker exec ... pkill -f` instead.
    nohup docker exec "$CONTAINER_NAME" bash -c \
        "source '$ROS_SETUP' && exec python3 '$container_script'" \
        >> "$LOG_FILE" 2>&1 &
    echo $! > "$pidfile"
    log "started $name (pid $!, in $CONTAINER_NAME) -> $container_script"
}

log "=== start_zoma_audio_hud_pi.sh invoked (hud=$HUD) ==="

start_host_process "zoma_audio_client" "$AUDIO_SCRIPT"
start_host_process "zoma_mic_client" "$MIC_SCRIPT"
start_host_process "zoma_state" "$STATE_SCRIPT"

if [[ "$HUD" -eq 1 ]]; then
    start_container_process "wifi_diag_publisher" "$WIFI_DIAG_SCRIPT"
    start_container_process "audio_diag_publisher" "$AUDIO_DIAG_SCRIPT"
fi

log "=== launch sequence complete -- tail with: tail -f $LOG_FILE ==="
