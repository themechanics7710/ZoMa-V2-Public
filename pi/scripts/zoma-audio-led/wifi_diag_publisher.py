#!/usr/bin/env python3
"""
ZoMa Pi audio/LED -- publishes active WiFi interface/RSSI as a ROS2 diagnostic topic.
Property of TheMechanics. Contact: mamau.mechanics@gmail.com

Runs on the Pi inside whichever ROS2 container already has rclpy. Publishes
a std_msgs/String (JSON) on /wifi_diag at 1Hz:
    {"rssi": -54, "mac": "aa:bb:cc:dd:ee:ff", "iface": "wlan1", "ts": 1234.5}

Deliberately does not touch the video/streaming path -- this stays a single
cheap `iw` subprocess call plus a small ROS message per second, so it never
competes with the Pi's video encode budget.
"""

import json
import re
import subprocess
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

PUBLISH_HZ = 1.0


def list_wifi_ifaces():
    """Return every wireless interface name reported by `iw dev`. There can
    be more than one (e.g. a real station interface plus an auto-created
    P2P/WiFi-Direct virtual interface) -- picking "the first one" blindly
    can grab the wrong interface's MAC instead of the actually-connected one."""
    try:
        out = subprocess.run(
            ["iw", "dev"], capture_output=True, text=True, timeout=2
        ).stdout
        return re.findall(r"Interface\s+(\S+)", out)
    except Exception:
        return []


def read_mac(iface):
    try:
        with open(f"/sys/class/net/{iface}/address") as f:
            return f.read().strip()
    except Exception:
        return None


def read_rssi(iface):
    """Parse `iw dev <iface> link` for 'signal: -54 dBm'. Returns int or None.
    None also means "not actually associated" -- used to pick the real
    interface out of however many `iw dev` lists."""
    try:
        out = subprocess.run(
            ["iw", "dev", iface, "link"], capture_output=True, text=True, timeout=2
        ).stdout
        if "Not connected" in out:
            return None
        m = re.search(r"signal:\s*(-?\d+)\s*dBm", out)
        return int(m.group(1)) if m else None
    except Exception:
        return None


def find_active_iface():
    """Re-scan every cycle (cheap: a couple subprocess calls at 1Hz) and
    return the first interface that's actually associated -- i.e. reports a
    real RSSI -- rather than caching one interface name once at startup.
    Returns (iface, mac, rssi) or (None, None, None) if nothing is
    associated."""
    for iface in list_wifi_ifaces():
        rssi = read_rssi(iface)
        if rssi is not None:
            return iface, read_mac(iface), rssi
    return None, None, None


class WifiDiagPublisher(Node):
    def __init__(self):
        super().__init__("wifi_diag_publisher")
        self.pub = self.create_publisher(String, "/wifi_diag", 10)
        self._last_logged_iface = None
        self.timer = self.create_timer(1.0 / PUBLISH_HZ, self.tick)

    def tick(self):
        iface, mac, rssi = find_active_iface()

        if iface is None:
            # Nothing associated right now -- skip publishing this cycle.
            # Silence is the signal; a downstream watchdog handles it.
            if self._last_logged_iface is not None:
                self.get_logger().warn("no associated wifi interface found")
                self._last_logged_iface = None
            return

        if iface != self._last_logged_iface:
            self.get_logger().info(f"active interface: {iface}  mac: {mac}")
            self._last_logged_iface = iface

        msg = String()
        msg.data = json.dumps(
            {
                "rssi": rssi,
                "mac": mac,
                "iface": iface,
                "ts": time.time(),
            }
        )
        self.pub.publish(msg)


def main():
    rclpy.init()
    node = WifiDiagPublisher()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
