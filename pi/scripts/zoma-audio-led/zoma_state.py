"""
ZoMa Pi audio/LED -- Pi-side robot behavior coordinator driving the LED status ring.
Property of TheMechanics. Contact: mamau.mechanics@gmail.com

This is the "why" layer that sits on top of lumini_ring.py's "how". It does
not decide "what pattern looks nice" (that's lumini_ring.py's pattern
library) -- it decides WHICH state should currently be showing, by
resolving every input source's opinion through a priority order rather than
"whoever spoke last wins". The LED ring is the first consumer of the
resolved state; mic-gating, arm control and mast/camera positioning are
expected to become consumers of this same resolved state later, which is
why the coordinator is kept separate from the LED-specific code rather than
folded into it.

Sources, today and future:
  - "local"  (wired)   -- this script's own boot/idle bring-up. Entirely
                          local, exists before any network connection.
  - "monster" (wired)  -- ZoMa Brain's conversation state, pushed over the
                          existing WebSocket control-plane server (role:
                          "led_ring"). Distinguishes which engine is doing
                          the work, not just "thinking"/"speaking": local
                          inference, a vision-analysis pass, and an uplink
                          reply each get their own state (thinking_local/
                          thinking_vision/thinking_uplink, speaking_local/
                          speaking_uplink) plus a separate uplink_listening
                          for the resting state during an uplink session.
  - "esp32_fault"    (placeholder) -- ESP32 RX fault/e-stop, once ROS2/
                          micro-ROS lands on the Pi. Highest priority --
                          must be able to preempt everything else.
  - "esp32_motion"   (placeholder) -- ESP32 RX drive-active status.
  - "pi_local_status"(placeholder) -- this Pi's own health (wifi, mic),
                          reusing wifi_diag_publisher.py/audio_diag_publisher.py's
                          existing signal rather than duplicating detection.

Also owns local, no-latency sound effects that must land in sync with a
local LED change -- the boot chime. This is deliberately not the same path
as ZoMa Brain's TTS speech (zoma_audio_client.py/AUDIO_SINKS): that path is
networked and only exists once the server is connected, which boot
explicitly happens before.
"""

import asyncio
import json
import logging
import os
import signal
import subprocess
from pathlib import Path

import websockets

from lumini_ring import LuminiRing, MAX_BRIGHTNESS

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("zoma_state")

# Point this at the ZoMa Brain server's LAN address.
ZOMA_BRAIN_HOST = os.getenv("ZOMA_BRAIN_HOST", "192.168.1.50")
ZOMA_BRAIN_PORT = int(os.getenv("ZOMA_BRAIN_PORT", "8765"))
ZOMA_BRAIN_WS_URL = f"ws://{ZOMA_BRAIN_HOST}:{ZOMA_BRAIN_PORT}"
RECONNECT_DELAY = float(os.getenv("ZOMA_LED_RECONNECT_DELAY", "3.0"))

SOUNDS_DIR = Path(__file__).resolve().parent / "sounds"
BOOT_SOUND = SOUNDS_DIR / "boot.wav"

# Same card this Pi's other audio scripts already address explicitly by
# name (see zoma_audio_client.py) -- not "default", for the same reasons
# documented there.
ALSA_DEVICE = "plughw:CARD=Array,DEV=0"


# =============================================================================
# STATE -> PATTERN MAPPING
#
# state: (pattern_name, color, color2, speed, duration, on_expire, brightness).
# Every pattern used here lights all NUM_LEDS at some level -- solid/breathe/
# rainbow_cycle/spin_glow -- never a chase/spinner/comet-style effect where
# most of the ring sits dark and only a few pixels are lit. WHITE (solid for
# the brief booting moment, spin_glow once settled into idle) means "no
# ZoMa Brain connected" -- booting and idle (Pi-local: never connected yet,
# or dropped) are the same signal at heart, just a different pace since idle
# can persist far longer than the boot moment ever does. RAINBOW_CYCLE means
# the opposite and only that: idle_wake_word, i.e. the server is connected
# and awaiting the wake word -- white vs. rainbow is the at-a-glance "is the
# brain even there" signal, so these two must never share a look. SPIN_GLOW
# is otherwise the general "holding/waiting on something" family -- both
# "thinking_*" (color-coded by engine: local=amber, vision=yellow,
# uplink=orange) and listening/uplink_listening (purple family) -- a
# spinning glow rather than a flat fill reads better on hardware for both
# white/idle and purple/listening. BREATHE is used for "talking"
# (speaking_*). duration is a per-state DEFAULT only -- the server overrides
# it per-message with the real remaining follow-up-window time for
# "listening"; None here means "loop forever unless overridden".
#
# Extra entries beyond what "local" ever sends (moving/fault/arm_busy) are
# defined now so the future ESP32 sources have somewhere to land without a
# second pass through lumini_ring.py's pattern library. photo_capture is
# sent for real by the server on a "take a picture" voice command.
# =============================================================================

# 6th field, on_expire: what this state's OWN source should become when a
# timed instance of it naturally runs out, with no new message ever
# arriving to say otherwise. None means "just disappear this source" --
# correct for an overlay like barge_in's one-shot flash on the "flash"
# source, which should reveal whatever "monster" is holding underneath. It
# is NOT correct for a timed state that lives ON the "monster" source
# itself (listening) -- disappearing "monster" entirely falls all the way
# back to the Pi-local "idle" (as if the server had disconnected), which is
# wrong: the server is still connected, only the follow-up window closed.
#
# 7th field, brightness: per-state override of the APA102's global
# brightness field (see lumini_ring.LuminiRing.set_pattern()'s own
# docstring for why color=(255,255,255) alone isn't "full brightness").
# None means "use the ring's everyday DEFAULT_BRIGHTNESS" -- correct for
# every ambient status state here, which are deliberately dim so the ring
# isn't glaring during normal conversation. A real camera flash needs to
# actually read as bright, so photo_capture is the one state that
# overrides it to MAX_BRIGHTNESS.
STATE_PATTERNS = {
    "booting":          ("solid",         (255, 255, 255), None, 1.0, None, None, None),
    # "idle" (Pi-local: no connection to the server, whether never-yet or
    # dropped) stays in the same WHITE family as booting, spinning rather
    # than flat since it can persist indefinitely -- deliberately NOT
    # rainbow: rainbow means "ZoMa Brain is connected and awaiting the wake
    # word", true only once the "monster" source says so via
    # idle_wake_word. White = no brain, rainbow = brain's there listening.
    "idle":             ("spin_glow",     (255, 255, 255), None, 1.0, None, None, None),
    "idle_wake_word":   ("rainbow_cycle", (0, 0, 0),       None, 1.0, None, None, None),
    "listening":        ("spin_glow",     (150, 0, 255),   None, 1.0, None, "idle_wake_word", None),
    "uplink_listening": ("spin_glow",     (170, 0, 220),   None, 1.0, None, "idle_wake_word", None),

    "thinking_local":   ("spin_glow",     (255, 170, 0),   None, 1.0, None, None, None),
    "thinking_vision":  ("spin_glow",     (255, 255, 0),   None, 1.0, None, None, None),
    "thinking_uplink":  ("spin_glow",     (255, 90, 0),    None, 1.0, None, None, None),

    "speaking_local":   ("breathe",       (0, 200, 90),    None, 1.0, None, None, None),
    "speaking_uplink":  ("breathe",       (255, 0, 170),   None, 1.0, None, None, None),

    # One-shot flash on a loud barge-in -- see the "flash" source below.
    # speed is tuned so pulse_once's single rise-and-fall completes exactly
    # at `duration` (pulse_once's envelope finishes one half-cycle at
    # t = 1/speed). on_expire=None here is correct: "flash" should just
    # disappear and reveal whatever "monster" is holding underneath.
    "barge_in":         ("pulse_once",    (140, 0, 90),    None, 1.0 / 0.6, 0.6, None, None),

    # Placeholders -- nothing sets these yet (see run_esp32_*_input below).
    # spin_glow/strobe again, not comet/theater_chase/chase/spinner -- same
    # "every LED lit at some level" rule as everything above.
    "moving":           ("spin_glow",     (0, 180, 255),   None, 1.2, None, None, None),
    "arm_busy":         ("spin_glow",     (255, 80, 0),    None, 1.0, None, None, None),
    "fault":            ("strobe",        (255, 0, 0),     None, 1.0, None, None, None),

    # Camera-flash effect for the "take a picture" command -- a single
    # bright rise-and-fall (pulse_once, same envelope/speed-duration
    # coupling as barge_in above: speed = 1/duration makes the one
    # half-cycle land exactly at 0.35s), not a strobe blink -- a real
    # camera flash doesn't flicker. Duration is baked in here rather than
    # left to the server's message, same reasoning as barge_in: this must
    # self-clear even if a duration is never sent. Routed through the
    # "flash" source (see run_led_client below), not "monster" -- it's a
    # one-shot overlay that reveals whatever "monster" is already holding
    # underneath once it's done, not a new resting state. brightness=
    # MAX_BRIGHTNESS (not None) so the flash actually reads as bright
    # rather than inheriting the ring's everyday dim default.
    "photo_capture":    ("pulse_once",    (255, 255, 255), None, 1.0 / 0.35, 0.35, None, MAX_BRIGHTNESS),
}


# =============================================================================
# COORDINATOR
# =============================================================================

class RobotStateCoordinator:
    """
    Resolves the robot's actual state across every source that has an
    opinion, by priority. Adding a real source later (ESP32 fault/motion,
    Pi-local status) is "call set_state()/clear_source() from somewhere
    new" -- the priority slots already exist below.

    "flash" sits above "monster" on purpose: a one-shot overlay (the
    barge-in flash today) has to visually win over whatever "monster" is
    currently showing, on its OWN source key, so a message that updates
    "monster" a moment later doesn't clobber the flash before it's had a
    chance to play -- and when the flash's own duration expires, clearing
    just "flash" reveals whatever "monster" is holding underneath, not a
    hardcoded fallback.
    """

    PRIORITY = {
        "esp32_fault": 100,      # placeholder -- not wired yet
        "esp32_motion": 80,      # placeholder -- not wired yet
        "pi_local_status": 40,   # placeholder -- not wired yet
        "flash": 30,
        "monster": 20,
        "local": 0,
    }

    def __init__(self, on_change):
        """on_change(source, state, meta) is called on every resolved
        state CHANGE, where meta is whatever dict (if any) was passed to
        set_state() for the winning source -- e.g. {"duration": 12.4}."""
        self._on_change = on_change
        self._sources: dict[str, str] = {}
        self._meta: dict[str, dict] = {}
        self._resolved: str | None = None

    def set_state(self, source: str, state: str, meta: dict | None = None):
        self._sources[source] = state
        self._meta[source] = meta or {}
        self._resolve()

    def clear_source(self, source: str):
        self._sources.pop(source, None)
        self._meta.pop(source, None)
        self._resolve()

    def _resolve(self):
        if not self._sources:
            return
        top_source = max(self._sources, key=lambda s: self.PRIORITY.get(s, -1))
        new_state = self._sources[top_source]
        if new_state != self._resolved:
            logger.info("Resolved state -> %s (source=%s, active=%s)",
                        new_state, top_source, self._sources)
            self._resolved = new_state
            self._on_change(top_source, new_state, self._meta.get(top_source) or {})


def apply_pattern(ring: LuminiRing, coordinator: RobotStateCoordinator,
                   source: str, state: str, meta: dict):
    name, color, color2, speed, default_duration, on_expire, brightness = STATE_PATTERNS.get(
        state, STATE_PATTERNS["idle"]
    )
    duration = meta.get("duration") if meta.get("duration") is not None else default_duration
    on_complete = None
    if duration is not None:
        if on_expire is not None:
            # Stay on the SAME source, just become a different state --
            # e.g. listening -> idle_wake_word. The server is still
            # connected; only the follow-up window closed.
            on_complete = lambda: coordinator.set_state(source, on_expire)
        else:
            # No defined next state -- this source should just disappear
            # (e.g. barge_in's "flash" overlay), revealing whatever the
            # next-highest-priority source is already holding.
            on_complete = lambda: coordinator.clear_source(source)
    ring.set_pattern(name, color=color, color2=color2, speed=speed,
                      duration=duration, on_complete=on_complete, brightness=brightness)


# =============================================================================
# LOCAL SOUND (boot chime only -- see module docstring for why this isn't
# the TTS/audio_sink path)
# =============================================================================

BOOT_SOUND_TIMEOUT_S = 5.0


def play_local_sound(path: Path):
    """
    Blocking on purpose: called from the synchronous boot sequence in
    main(), right next to the LED pattern change, so both start together
    with no network or queue in between. aplay reads the WAV header itself
    -- no format flags needed for a real .wav file (unlike the raw-PCM path
    elsewhere in this repo).

    Bounded on purpose too: this Pi's USB audio device has documented
    startup-timing flakiness on the capture side (see zoma_mic_client.py's
    notes on cold-boot arecord races on this exact reSpeaker). A
    hung/stalled aplay on the playback side is the same class of risk, and
    this call sits directly in front of the "local" -> "idle" state
    transition in main() -- an unbounded hang here would leave the ring
    stuck on "booting" (white) indefinitely, with no boot chime ever heard,
    regardless of the server's connection state. A timeout guarantees the
    boot sequence always proceeds within a few seconds even if this one
    play attempt is lost.
    """
    if not path.exists():
        logger.warning("Sound file not found, skipping: %s", path)
        return
    try:
        result = subprocess.run(
            ["aplay", "-D", ALSA_DEVICE, str(path)],
            check=False, timeout=BOOT_SOUND_TIMEOUT_S,
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            if "busy" in stderr.lower():
                logger.warning(
                    "Boot chime skipped: %s device is busy -- something else "
                    "(zoma_audio_client.py, if it's already running, holds this "
                    "same card persistently) already has it open. Not a bug in "
                    "this script -- only one process can hold an ALSA hw device "
                    "at once. In the intended boot order this script should start "
                    "before zoma_audio_client.py claims the card.",
                    ALSA_DEVICE,
                )
            else:
                logger.warning("Boot chime failed (aplay exit %d): %s",
                                result.returncode, stderr or "<no stderr>")
    except FileNotFoundError:
        logger.warning("aplay not found -- skipping local sound playback")
    except subprocess.TimeoutExpired:
        logger.warning("Boot chime playback stalled past %.0fs -- continuing without it "
                        "(likely the same USB audio timing race documented in "
                        "zoma_mic_client.py, on the playback side this time)",
                        BOOT_SOUND_TIMEOUT_S)


# =============================================================================
# SERVER INPUT (wired)
# =============================================================================

async def run_led_client(coordinator: RobotStateCoordinator):
    """
    Dials the ZoMa Brain server's existing WebSocket control-plane, registers
    role "led_ring", and feeds every led_state message it receives into the
    coordinator as the "monster" source. Same connect/register/reconnect
    shape as zoma_mic_client.py and zoma_audio_client.py.
    """
    while True:
        try:
            logger.info("Connecting to %s ...", ZOMA_BRAIN_WS_URL)
            async with websockets.connect(ZOMA_BRAIN_WS_URL, max_size=None, ping_interval=None) as ws:
                await ws.recv()  # identity message -- informational only
                await ws.send(json.dumps({"type": "register", "role": "led_ring"}))
                ack = json.loads(await ws.recv())
                if ack.get("type") != "register_ack":
                    logger.warning("Unexpected registration response: %s", ack)
                logger.info("Registered as led_ring. Waiting for state updates...")

                async for message in ws:
                    data = json.loads(message)
                    if data.get("type") == "led_state":
                        state = data.get("state")
                        if state not in STATE_PATTERNS:
                            logger.warning("Unknown led_state from server: %s", state)
                            continue
                        meta = {"duration": data["duration"]} if "duration" in data else None
                        # barge_in and photo_capture are one-shot overlays,
                        # not resting "monster" states -- see
                        # RobotStateCoordinator's "flash" source docstring
                        # for why they need their own key rather than
                        # sharing "monster"'s.
                        source = "flash" if state in ("barge_in", "photo_capture") else "monster"
                        coordinator.set_state(source, state, meta=meta)
                    elif data.get("type") == "register_ack":
                        pass  # already consumed above; ignore if resent

        except (websockets.exceptions.ConnectionClosed, OSError) as e:
            logger.warning("Connection lost (%s). Reconnecting in %.1fs...", e, RECONNECT_DELAY)
        except Exception:
            logger.exception("Unexpected error in LED client loop")
        finally:
            # Server isn't reachable/registered right now -- fall back to
            # whatever the next-highest-priority source says (today:
            # "local" -> idle).
            coordinator.clear_source("monster")

        await asyncio.sleep(RECONNECT_DELAY)


# =============================================================================
# FUTURE INPUT SOURCES -- placeholders, not wired yet.
#
# Once ROS2/micro-ROS lands on the Pi, these become real subscriptions that
# call coordinator.set_state()/clear_source() the same way run_led_client()
# does above for the server. Priority slots already exist in
# RobotStateCoordinator.PRIORITY, so wiring one of these up later is "start
# this task", not a resolution-logic rewrite.
# =============================================================================

async def run_esp32_fault_input(coordinator: RobotStateCoordinator):
    """
    Subscribe to the ESP32 RX's fault/e-stop status over micro-ROS.
    coordinator.set_state("esp32_fault", "fault") on a fault, clear_source
    on recovery. Highest priority -- must preempt LISTENING/THINKING/
    SPEAKING/MOVING/ARM_BUSY unconditionally.
    """
    raise NotImplementedError("wire up once the Pi's micro-ROS agent exists")


async def run_esp32_motion_input(coordinator: RobotStateCoordinator):
    """
    Subscribe to the ESP32 RX's drive-active status. set_state(
    "esp32_motion", "moving") while wheels are actually turning; clear
    once stopped.
    """
    raise NotImplementedError("wire up once the Pi's micro-ROS agent exists")


async def run_pi_local_status_input(coordinator: RobotStateCoordinator):
    """
    Feed this Pi's own health in (wifi down, mic fault) -- reuse
    wifi_diag_publisher.py/audio_diag_publisher.py's existing detection
    rather than duplicating it here.
    """
    raise NotImplementedError("wire up once a concrete Pi-local status signal is picked")


# =============================================================================
# ENTRY POINT
# =============================================================================

def _handle_sigterm(signum, frame):
    """
    `kill`/`pkill` send SIGTERM by default, which Python does not turn into
    a catchable exception on its own -- only SIGINT (Ctrl+C) does that
    automatically, as KeyboardInterrupt. Without this, `pkill -f
    zoma_state.py` skips main()'s `finally: ring.stop()` entirely, and the
    APA102s just keep showing whatever they were last sent -- they have no
    concept of "the process driving me died", they hold the last color
    forever until a new frame arrives. Raising KeyboardInterrupt here
    routes SIGTERM through the exact same cleanup path SIGINT already has.
    """
    raise KeyboardInterrupt()


def main():
    signal.signal(signal.SIGTERM, _handle_sigterm)

    ring = LuminiRing()
    ring.start()

    coordinator = RobotStateCoordinator(
        on_change=lambda source, state, meta: apply_pattern(ring, coordinator, source, state, meta)
    )

    # Local boot sequence: entirely synchronous, entirely before any
    # network connection exists -- BOOTING has to be visible the instant
    # this process starts, not once the server happens to connect. The
    # pattern change and the chime are triggered back-to-back from this
    # same thread so they start together; the ring's render thread is
    # already running by the time play_local_sound() blocks on the chime,
    # so the spin keeps animating while the sound plays instead of
    # freezing for it.
    coordinator.set_state("local", "booting")
    play_local_sound(BOOT_SOUND)
    coordinator.set_state("local", "idle")

    try:
        asyncio.run(run_led_client(coordinator))
    except KeyboardInterrupt:
        logger.info("Shutting down.")
    finally:
        ring.stop()


if __name__ == "__main__":
    main()
