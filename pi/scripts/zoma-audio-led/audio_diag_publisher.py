#!/usr/bin/env python3
"""
ZoMa Pi audio/LED -- publishes ALSA mic/speaker presence as a ROS2 diagnostic topic.
Property of TheMechanics. Contact: mamau.mechanics@gmail.com

Runs on the Pi inside the ROS2 container. Publishes a std_msgs/String (JSON)
on /audio_diag at 1Hz: {"mic_active": bool, "speaker_connected": bool, "ts": float}.
"""

import json
import os
import re
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

PUBLISH_HZ = 1.0
HEARTBEAT_PATH = "/tmp/zoma_audio_heartbeat"
HEARTBEAT_TIMEOUT_SEC = 3.0


def find_respeaker_card_index():
    """Resolve the reSpeaker's ALSA card index by scanning /proc/asound/cards
    for the entry containing "Array", rather than hardcoding an index --
    USB enumeration order can shift which card index it lands on."""
    try:
        with open("/proc/asound/cards") as f:
            for line in f:
                m = re.match(r"\s*(\d+)\s+\[.*Array.*\]", line)
                if m:
                    return m.group(1)
    except Exception:
        pass
    return None


def pcm_stream_running(card_index, device, direction):
    """True if the given PCM substream is actively RUNNING, not just present."""
    path = f"/proc/asound/card{card_index}/pcm{device}{direction}/sub0/status"
    try:
        with open(path) as f:
            content = f.read()
        return "state: RUNNING" in content
    except Exception:
        return False


def pcm_device_present(card_index, device, direction):
    path = f"/proc/asound/card{card_index}/pcm{device}{direction}/sub0/status"
    try:
        with open(path):
            return True
    except Exception:
        return False


def heartbeat_is_fresh(path, timeout_sec):
    try:
        mtime = os.path.getmtime(path)
        return (time.time() - mtime) < timeout_sec
    except OSError:
        return False


class AudioDiagPublisher(Node):
    """Publishes mic/speaker presence at PUBLISH_HZ.

    speaker_connected combines ALSA hardware presence with a heartbeat
    file's freshness. If the heartbeat file doesn't exist (its writer is
    not yet implemented), this falls back to hardware presence alone.
    """

    def __init__(self):
        super().__init__("audio_diag_publisher")
        self.pub = self.create_publisher(String, "/audio_diag", 10)
        self._card_index = None
        self._last_logged_card = None
        self._last_logged_speaker_state = None
        self.get_logger().info(f"audio_diag_publisher starting -- heartbeat path: {HEARTBEAT_PATH}")
        self.timer = self.create_timer(1.0 / PUBLISH_HZ, self.tick)

    def tick(self):
        current_index = find_respeaker_card_index()
        if current_index is None:
            self._card_index = None
            return
        if current_index != self._last_logged_card:
            self.get_logger().info(f"reSpeaker found at ALSA card index {current_index}")
            self._last_logged_card = current_index
        self._card_index = current_index

        mic_active = pcm_stream_running(self._card_index, 0, "c")
        speaker_connected = self._speaker_connected()

        msg = String()
        msg.data = json.dumps({
            "mic_active": mic_active,
            "speaker_connected": speaker_connected,
            "ts": time.time(),
        })
        self.pub.publish(msg)

    def _speaker_connected(self):
        hw_ok = pcm_device_present(self._card_index, 0, "p")
        hb_exists = os.path.exists(HEARTBEAT_PATH)

        if not hw_ok:
            result, reason = False, "hardware not present (pcm_device_present=False)"
        elif not hb_exists:
            result, reason = True, "heartbeat file doesn't exist -- hardware-only fallback"
        else:
            fresh = heartbeat_is_fresh(HEARTBEAT_PATH, HEARTBEAT_TIMEOUT_SEC)
            result = fresh
            reason = "heartbeat fresh" if fresh else "heartbeat exists but stale"

        state_key = (hw_ok, hb_exists, result)
        if state_key != self._last_logged_speaker_state:
            self.get_logger().info(
                f"speaker_connected -> {result}  (hw_ok={hw_ok}, heartbeat_exists={hb_exists}, reason: {reason})"
            )
            self._last_logged_speaker_state = state_key

        return result


def main():
    rclpy.init()
    node = AudioDiagPublisher()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
