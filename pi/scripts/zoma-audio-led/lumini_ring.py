"""
ZoMa Pi audio/LED -- APA102/DotStar pattern renderer for the LED status ring.
Property of TheMechanics. Contact: mamau.mechanics@gmail.com

Pure hardware library: knows how to paint patterns, nothing about WHY -- no
WebSocket, no robot state, no priorities. zoma_state.py is the layer that
decides what to show; this is just the "how".
"""

import colorsys
import math
import random
import threading
import time

import spidev

NUM_LEDS = 40
DEFAULT_BRIGHTNESS = 5  # 1-31 (APA102's 5-bit global brightness field). Kept
                         # low by default so the ring stays unobtrusive during
                         # ordinary operation -- see set_pattern()'s
                         # `brightness` param for per-call overrides.
MAX_BRIGHTNESS = 31  # ceiling of the same 5-bit field.
SPI_BUS = 0
SPI_DEVICE = 0
SPI_MAX_SPEED_HZ = 8_000_000
FPS = 40


def _clamp255(v: float) -> int:
    return max(0, min(255, int(v)))


class LuminiRing:
    """
    Hardware: DI->GPIO10 (SPI0 MOSI), CI->GPIO11 (SPI0 SCLK), hardware SPI0
    via spidev. APA102 uses a synchronous clock+data protocol (unlike
    WS2812's single-wire timing-critical bitstream), so a plain
    spidev.writebytes2() call per frame is enough -- no PWM/DMA peripheral
    or root-only driver needed.

    The render loop runs on its own background thread at a fixed tick rate,
    continuously redrawing whatever the current pattern spec is. Callers
    just call set_pattern(); a dedicated thread absorbs the real-time-bound
    rendering work.
    """

    def __init__(self, num_leds: int = NUM_LEDS, brightness: int = DEFAULT_BRIGHTNESS,
                 fps: int = FPS):
        self.num_leds = num_leds
        self.brightness = brightness
        self._fps = fps
        self._period = 1.0 / fps

        self._spi = spidev.SpiDev()
        self._spi.open(SPI_BUS, SPI_DEVICE)
        self._spi.max_speed_hz = SPI_MAX_SPEED_HZ

        # Current pattern spec, replaced wholesale by set_pattern(). Read by
        # the render thread every tick -- no lock needed for a swap this
        # simple (single-writer, single-reader, one attribute reassignment;
        # worst case is one stale frame during a transition).
        self._pattern = {"name": "off", "color": (0, 0, 0), "color2": None,
                          "speed": 1.0, "started_at": time.monotonic(), "duration": None,
                          "brightness": None}
        self._on_complete = None

        self._thread: threading.Thread | None = None
        self._running = False

    # --- lifecycle -----------------------------------------------------

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._running = True
        self._thread = threading.Thread(target=self._render_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)
        self.clear()
        self._spi.close()

    # --- public API ------------------------------------------------------

    def set_pattern(self, name: str, color=(255, 255, 255), color2=None,
                     speed: float = 1.0, duration: float | None = None,
                     on_complete=None, brightness: int | None = None):
        """
        name: one of PATTERNS' keys below.
        color / color2: (r, g, b), 0-255 each. color2 is only used by
            patterns that blend two colors (e.g. gradient); ignored otherwise.
        speed: pattern-specific multiplier, 1.0 = the pattern's own default pace.
        duration: seconds. None loops forever until the next set_pattern()
            call. A number renders for that long, then freezes on the last
            frame and fires on_complete if given -- e.g. a one-shot
            acknowledgment pulse that hands control back to whatever was
            showing before it.
        on_complete: optional zero-arg callable, invoked once from the
            render thread when a timed pattern's duration elapses.
        brightness: 1-31, overrides self.brightness for THIS pattern only.
            None (the default) uses self.brightness. Needed because
            color=(255,255,255) alone does not mean "full hardware
            brightness" -- the APA102's 5-bit brightness field scales every
            pixel's RGB value independently of the color a pattern computes,
            so an effect that needs to read as genuinely bright (e.g. a
            camera-flash pulse) overrides it explicitly rather than
            inheriting the ring's everyday dim default.
        """
        if name not in PATTERNS:
            raise ValueError(f"Unknown LED pattern: {name!r} (valid: {sorted(PATTERNS)})")
        self._on_complete = on_complete
        self._pattern = {
            "name": name, "color": color, "color2": color2,
            "speed": speed, "started_at": time.monotonic(), "duration": duration,
            "brightness": brightness,
        }

    def clear(self):
        self._show([(0, 0, 0)] * self.num_leds)

    # --- rendering ---------------------------------------------------------

    def _render_loop(self):
        fired_complete_for = None
        while self._running:
            t0 = time.monotonic()
            spec = self._pattern
            elapsed = t0 - spec["started_at"]

            duration = spec["duration"]
            done = duration is not None and elapsed >= duration
            if done:
                # Freeze: render exactly at t=duration once, then stop
                # recomputing frames for this spec until it's replaced.
                elapsed = duration

            frame = PATTERNS[spec["name"]](
                self.num_leds, elapsed, spec["color"], spec["color2"], spec["speed"],
            )
            self._show(frame, brightness=spec.get("brightness"))

            if done and fired_complete_for is not spec and self._on_complete:
                fired_complete_for = spec
                try:
                    self._on_complete()
                except Exception as e:
                    print(f" [LUMINI] on_complete callback failed: {e}")

            sleep_for = self._period - (time.monotonic() - t0)
            if sleep_for > 0:
                time.sleep(sleep_for)

    def _show(self, pixels, brightness: int | None = None):
        """pixels: list of (r, g, b) tuples, length == self.num_leds.
        brightness: per-call override (1-31) -- None uses self.brightness."""
        buffer = bytearray()
        buffer.extend([0x00, 0x00, 0x00, 0x00])  # start frame
        header = 0xE0 | ((self.brightness if brightness is None else brightness) & 0x1F)
        for r, g, b in pixels:
            buffer.extend([header, _clamp255(b), _clamp255(g), _clamp255(r)])
        end_frame_bytes = (self.num_leds + 15) // 16
        buffer.extend([0xFF] * end_frame_bytes)
        self._spi.writebytes2(buffer)


# =============================================================================
# PATTERN LIBRARY
#
# Each pattern is a pure function: (num_leds, elapsed_seconds, color, color2,
# speed) -> list[(r, g, b)]. Stateless on purpose -- all "where in the
# animation are we" comes from elapsed time, not accumulated state, so
# switching patterns is just replacing which function gets called with no
# leftover state to reset.
# =============================================================================

def _pat_off(n, t, color, color2, speed):
    return [(0, 0, 0)] * n


def _pat_solid(n, t, color, color2, speed):
    return [color] * n


def _pat_breathe(n, t, color, color2, speed):
    # Sinusoidal brightness envelope, 0.15-1.0 so it never fully blacks out.
    level = 0.15 + 0.85 * (0.5 + 0.5 * math.sin(2 * math.pi * 0.3 * speed * t))
    r, g, b = color
    return [(r * level, g * level, b * level)] * n


def _pat_pulse_once(n, t, color, color2, speed):
    # Same envelope as breathe but meant to be used with a short
    # `duration` -- a single rise-and-fall, not a loop.
    level = max(0.0, math.sin(math.pi * speed * t))
    r, g, b = color
    return [(r * level, g * level, b * level)] * n


def _pat_chase(n, t, color, color2, speed):
    pos = int(t * speed * 15) % n
    frame = [(0, 0, 0)] * n
    frame[pos] = color
    return frame


def _pat_comet(n, t, color, color2, speed, tail=6):
    pos = (t * speed * 15) % n
    r, g, b = color
    frame = [(0, 0, 0)] * n
    for i in range(tail):
        idx = int(pos - i) % n
        level = 1.0 - (i / tail)
        frame[idx] = (r * level, g * level, b * level)
    return frame


def _pat_theater_chase(n, t, color, color2, speed, group=3):
    offset = int(t * speed * 8) % group
    return [color if (i % group) == offset else (0, 0, 0) for i in range(n)]


def _pat_color_wipe(n, t, color, color2, speed):
    # Loops: fills forward, then wipes off, repeating.
    cycle = (2 * n) / max(speed, 0.01)
    phase = (t * speed * n / cycle * cycle) % (2 * n)
    lit = int(phase) if phase < n else n
    off_count = int(phase - n) if phase >= n else 0
    frame = [color] * lit + [(0, 0, 0)] * (n - lit)
    if off_count:
        frame = [(0, 0, 0)] * min(off_count, n) + [color] * max(0, n - off_count)
    return frame


def _pat_sparkle(n, t, color, color2, speed, density=0.15):
    # Not time-continuous by design -- reseeds off elapsed time so it still
    # looks "random" rather than literally random every frame (which would
    # just look like noise with no readable rate).
    rng = random.Random(int(t * speed * 12))
    return [color if rng.random() < density else (0, 0, 0) for _ in range(n)]


def _pat_spinner(n, t, color, color2, speed, arc=6):
    pos = (t * speed * 12) % n
    frame = [(0, 0, 0)] * n
    for i in range(arc):
        idx = int(pos + i) % n
        frame[idx] = color
    return frame


def _pat_spin_glow(n, t, color, color2, speed, width=8, base=0.15):
    """
    Every LED lit at a dim baseline, plus a brighter glow that rotates
    around the ring -- "spinning" without ever going fully dark on any
    pixel. Use this instead of chase/spinner/comet wherever a "thinking"
    animation should still read as "all n LEDs on".
    """
    center = (t * speed * 15) % n
    r, g, b = color
    frame = []
    for i in range(n):
        d = abs(i - center)
        d = min(d, n - d)  # shortest distance around the ring
        if d < width:
            level = base + (1 - base) * (0.5 + 0.5 * math.cos(math.pi * d / width))
        else:
            level = base
        frame.append((r * level, g * level, b * level))
    return frame


def _pat_strobe(n, t, color, color2, speed):
    on = int(t * speed * 8) % 2 == 0
    return [color if on else (0, 0, 0)] * n


def _pat_rainbow_cycle(n, t, color, color2, speed):
    frame = []
    for i in range(n):
        hue = ((i / n) + t * 0.15 * speed) % 1.0
        r, g, b = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
        frame.append((r * 255, g * 255, b * 255))
    return frame


def _pat_gradient(n, t, color, color2, speed):
    c2 = color2 or (0, 0, 0)
    frame = []
    for i in range(n):
        f = i / max(n - 1, 1)
        frame.append(tuple(color[k] + (c2[k] - color[k]) * f for k in range(3)))
    return frame


PATTERNS = {
    "off": _pat_off,
    "solid": _pat_solid,
    "breathe": _pat_breathe,
    "pulse_once": _pat_pulse_once,
    "chase": _pat_chase,
    "comet": _pat_comet,
    "theater_chase": _pat_theater_chase,
    "color_wipe": _pat_color_wipe,
    "sparkle": _pat_sparkle,
    "spinner": _pat_spinner,
    "spin_glow": _pat_spin_glow,
    "strobe": _pat_strobe,
    "rainbow_cycle": _pat_rainbow_cycle,
    "gradient": _pat_gradient,
}
