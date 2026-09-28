"""
ZoMa Brain — Monster-to-Pi peripheral command builder
Property of TheMechanics. Contact: mamau.mechanics@gmail.com

Builds outbound messages for the Pi's peripherals: LED ring state and
volume nudges. Callers hand the result to a broadcast helper rather than
constructing this JSON by hand.
"""

import json

# Every state Monster can send the Pi-side LED logic layer.
#
# "idle" is deliberately NOT here: it's a Pi-local-only state (boot
# bring-up, or the fallback while disconnected from Monster) that never
# travels over the wire.
#
# "idle_wake_word" IS sent by Monster: it's the ground-truth "no wake
# word has been said and no follow-up window is open" state, distinct
# from the Pi-local "idle" used only at boot/while disconnected. They
# render the same on the Pi, but Monster's version reflects real
# conversation state rather than just "not connected yet".
#
# local/vision/uplink are kept as distinct states, not one generic
# "thinking"/"speaking", so the ring can visually distinguish which
# engine is doing the work.
#
# "barge_in" and "photo_capture" are one-shot flashes, not resting
# states -- they overlay briefly on top of whatever state is currently
# showing and then self-clear, revealing whatever was underneath. Their
# durations are baked into the Pi-side pattern table, so no duration
# needs sending here.
VALID_LED_STATES = frozenset({
    "listening", "uplink_listening", "idle_wake_word",
    "thinking_local", "thinking_vision", "thinking_uplink",
    "speaking_local", "speaking_uplink",
    "barge_in", "photo_capture",
})


def led_state_message(state: str, duration: float | None = None) -> str:
    """
    JSON string for a `led_state` directive, sent whenever ZoMa Brain's
    conversation state changes (wake word heard, generating a reply,
    speaking). Raises on an unknown state so a typo fails loudly at the
    call site instead of silently doing nothing on the Pi.

    duration: seconds until the Pi should consider this state expired and
    fall back to whatever's next. None means "no expiry" -- the Pi holds
    this state until the next message changes it.
    """
    if state not in VALID_LED_STATES:
        raise ValueError(f"Unknown LED state: {state!r} (valid: {sorted(VALID_LED_STATES)})")
    payload = {"type": "led_state", "state": state}
    if duration is not None:
        payload["duration"] = duration
    return json.dumps(payload)


def volume_delta_message(percent: int) -> str:
    """
    JSON string for a `volume_delta` directive -- a signed step in
    percent (e.g. +5 or -5, see config.VOLUME_STEP_PERCENT). Sent over
    the Pi's audio_sink connection, which already owns the ALSA card for
    TTS playback and is the natural place to apply a volume step too.
    """
    return json.dumps({"type": "volume_delta", "percent": percent})
