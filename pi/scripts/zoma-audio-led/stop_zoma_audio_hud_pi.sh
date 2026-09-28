#!/usr/bin/env bash
# ZoMa Pi audio/LED -- stops everything start_zoma_audio_hud_pi.sh may have started.
# Property of TheMechanics. Contact: mamau.mechanics@gmail.com
#
# zoma_audio_client / zoma_mic_client / zoma_state are plain host
# processes, stopped by PID. wifi_diag_publisher / audio_diag_publisher run
# INSIDE the ROS2 container (rclpy isn't installed on the Pi host), so
# their host-side PID (the docker-exec client) can't signal them directly
# -- they're stopped via `docker exec ... pkill -f` instead.
#
# Safe to run even if -hud was never used, or if some processes were never
# started -- everything is a no-op if its PID file/process is already gone.
#
# Usage:
#   ./stop_zoma_audio_hud_pi.sh

set -uo pipefail

ZOMA_AUDIO_STATE_DIR="${ZOMA_AUDIO_STATE_DIR:-$HOME/zoma-audio}"
PID_DIR="$ZOMA_AUDIO_STATE_DIR/run"
LOG_FILE="$ZOMA_AUDIO_STATE_DIR/logs/zoma_$(date +%Y%m%d).log"
CONTAINER_NAME="zoma_ros_pi_v2"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') [LAUNCHER] $*" | tee -a "$LOG_FILE" 2>/dev/null || echo "$*"
}

stop_host_process() {
    local name="$1"
    local pidfile="$PID_DIR/${name}.pid"

    if [[ ! -f "$pidfile" ]]; then
        log "$name: no pidfile, nothing to stop"
        return
    fi

    local pid
    pid="$(cat "$pidfile")"
    if kill -0 "$pid" 2>/dev/null; then
        kill "$pid" 2>/dev/null
        log "stopped $name (pid $pid)"
    else
        log "$name: pid $pid not running"
    fi
    rm -f "$pidfile"
}

stop_container_process() {
    local name="$1" match="$2"
    local pidfile="$PID_DIR/${name}.pid"

    if docker ps --format '{{.Names}}' | grep -qx "$CONTAINER_NAME"; then
        if docker exec "$CONTAINER_NAME" pkill -f "$match" 2>/dev/null; then
            log "stopped $name inside $CONTAINER_NAME (matched '$match')"
        else
            log "$name: no matching process inside $CONTAINER_NAME"
        fi
    else
        log "$CONTAINER_NAME not running -- skipping $name"
    fi
    rm -f "$pidfile"
}

log "=== stop_zoma_audio_hud_pi.sh invoked ==="

stop_host_process "zoma_audio_client"
stop_host_process "zoma_mic_client"
stop_host_process "zoma_state"
stop_container_process "wifi_diag_publisher" "wifi_diag_publisher.py"
stop_container_process "audio_diag_publisher" "audio_diag_publisher.py"

log "=== all stop commands sent ==="
