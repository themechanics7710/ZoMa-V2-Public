"""
ZoMa Pi audio/LED -- Pi-side always-on mic capture for ZoMa Brain.
Property of TheMechanics. Contact: mamau.mechanics@gmail.com

Runs on ZoMa's Pi, separate from zoma_audio_client.py (that one is
output/playback; this one is input/capture -- two independent WebSocket
connections to the same server, each simple on its own rather than one
complicated bidirectional one).

Captures raw audio via `arecord` and streams it as binary WebSocket
frames -- no framing, no JSON per chunk, just raw S16_LE/16kHz/mono PCM,
the format the server's STT engine wants natively.

Wake-word gating happens server-side, not here. This script's only job is:
capture, register as role "mic_input" so the server knows to gate this
connection, stream continuously, reconnect on drop.

=====================================================================
HARDWARE: reSpeaker XVF3800 USB 4-Mic Array
=====================================================================
The XVF3800's USB firmware exposes 2 channels at 16kHz natively -- channel
0 ("Conference") and channel 1 ("ASR"), both already AEC/beamform/
noise-suppression processed on-chip. The device is 16kHz in hardware, so
no ALSA-side rate conversion is needed on this path.

Channel selection: ASR (channel 1) is purpose-built for STT and is the
default here. The two channels only really diverge under noise or while
ZoMa is talking (the barge-in scenario); if wake-word or transcription
quality ever looks off, flip CHANNEL_TO_USE to 0 -- no other changes
needed.

=====================================================================
STARTUP-ONLY USB RACE RECOVERY
=====================================================================
Occasionally after a cold boot, `arecord` fails immediately with a read
error while the device's HID control interface is already fully
functional at the same moment. That split points at a real race: the
reSpeaker's control interface and its isochronous audio streaming
interface come up on different timelines, and the streaming side isn't
always ready by the time this script's first attempt fires, even though
the device already looks fully enumerated.

A single USB re-enumeration resolves it, by forcing both interfaces
through a fresh, synchronized bring-up. This block does that ONCE, only
for the very first stream_mic() attempt of the process's life. If that
first attempt fails fast, it re-enumerates via RESET_SCRIPT and lets the
normal reconnect loop retry -- after which _startup_recovery_done-style
state is permanently set and this logic never runs again for the rest of
the session. This is deliberately narrower than an ongoing runtime
watchdog, since the failure mode is startup-timing-specific, not ongoing.

RESET_SCRIPT re-enumerates the USB device AND re-runs the DSP init script
-- both are needed even though this fix targets a timing race, not DSP
state: DSP settings are applied once at boot by a separate service, but
forcing a re-enumeration here would silently undo that (DSP state lives in
the chip's volatile memory, not USB descriptors) unless the init script
runs again right after.
"""

import array
import asyncio
import json
import logging
import os
import subprocess
import time

import websockets

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("zoma_mic_client")

# Point this at the ZoMa Brain server's LAN address.
ZOMA_BRAIN_HOST = os.getenv("ZOMA_BRAIN_HOST", "192.168.1.50")
ZOMA_BRAIN_PORT = int(os.getenv("ZOMA_BRAIN_PORT", "8765"))
ZOMA_BRAIN_WS_URL = f"ws://{ZOMA_BRAIN_HOST}:{ZOMA_BRAIN_PORT}"

RECONNECT_DELAY = float(os.getenv("ZOMA_MIC_RECONNECT_DELAY", "3.0"))

ARECORD_CMD = [
    "arecord", "-D", "plughw:CARD=Array,DEV=0",
    "-f", "S16_LE", "-r", "16000", "-c", "2", "-q", "-t", "raw",
]

CHANNEL_TO_USE = int(os.getenv("ZOMA_MIC_CHANNEL", "1"))
READ_CHUNK_BYTES = 6400
FRAME_BYTES = 4

# --- Startup-only USB race recovery (see module docstring) -----------------
STARTUP_FAST_FAILURE_SEC = float(os.getenv("ZOMA_MIC_STARTUP_FAST_FAILURE_SEC", "2.0"))
STARTUP_RESET_TIMEOUT_SEC = float(os.getenv("ZOMA_MIC_STARTUP_RESET_TIMEOUT_SEC", "30"))
# Set this to the actual path of this repo on your Raspberry Pi, or
# override ZOMA_RESPEAKER_RESET_SCRIPT directly.
RESET_SCRIPT = os.getenv(
    "ZOMA_RESPEAKER_RESET_SCRIPT",
    os.path.join(os.getenv("ZOMA_REPO_DIR", os.path.expanduser("~/ZoMa-V2")),
                 "pi/scripts/zoma-audio-led/reset_respeaker.sh"),
)


class MicStartupRaceError(Exception):
    """arecord died fast enough, on the FIRST attempt of this process's
    life, to indicate the USB streaming interface wasn't ready yet. See
    module docstring."""
    pass


def extract_channel(stereo_chunk: bytes, channel: int) -> bytes:
    samples = array.array("h")
    samples.frombytes(stereo_chunk)
    return samples[channel::2].tobytes()


async def stream_mic(ws: websockets.ClientConnection, check_startup_race: bool):
    """
    check_startup_race is only True for the very first call of the
    process's life (see run_client). When True, a fast death raises
    MicStartupRaceError instead of just logging + returning -- every later
    call in this process's life behaves exactly as before, unconditionally.
    """
    proc = subprocess.Popen(ARECORD_CMD, stdout=subprocess.PIPE)
    start_time = time.monotonic()
    logger.info("arecord started (pid=%s), using channel %d", proc.pid, CHANNEL_TO_USE)
    leftover = b""
    try:
        while True:
            chunk = await asyncio.to_thread(proc.stdout.read, READ_CHUNK_BYTES)
            if not chunk:
                elapsed = time.monotonic() - start_time
                logger.warning("arecord stdout closed unexpectedly after %.2fs", elapsed)
                if check_startup_race and elapsed < STARTUP_FAST_FAILURE_SEC:
                    raise MicStartupRaceError(
                        f"arecord died after {elapsed:.2f}s on process startup -- "
                        f"likely USB streaming-interface race"
                    )
                break

            data = leftover + chunk
            usable_len = (len(data) // FRAME_BYTES) * FRAME_BYTES
            leftover = data[usable_len:]

            mono = extract_channel(data[:usable_len], CHANNEL_TO_USE)
            if mono:
                await ws.send(mono)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


async def _run_startup_reset():
    logger.warning("Startup USB race detected -- running one-time reset via %s", RESET_SCRIPT)
    try:
        proc = await asyncio.create_subprocess_exec(
            "sudo", RESET_SCRIPT,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=STARTUP_RESET_TIMEOUT_SEC)
        output = stdout.decode(errors="replace").strip()
        if proc.returncode == 0:
            logger.info("Startup reset succeeded:\n%s", output)
        else:
            logger.error("Startup reset script exited %d:\n%s", proc.returncode, output)
    except FileNotFoundError:
        logger.error("Reset script not found at %s -- startup race will just retry "
                      "on the normal %.1fs reconnect loop instead", RESET_SCRIPT, RECONNECT_DELAY)
    except asyncio.TimeoutError:
        logger.error("Startup reset script timed out after %.0fs", STARTUP_RESET_TIMEOUT_SEC)
    except Exception:
        logger.exception("Unexpected error running startup reset script")


async def run_client():
    # True only until the first stream_mic() attempt either succeeds or
    # triggers the one-time reset -- whichever comes first. Permanently
    # False after that for the rest of this process's life.
    startup_phase = True
    startup_reset_attempted = False

    while True:
        try:
            logger.info("Connecting to %s ...", ZOMA_BRAIN_WS_URL)
            async with websockets.connect(ZOMA_BRAIN_WS_URL, max_size=None, ping_interval=None) as ws:
                await ws.recv()
                await ws.send(json.dumps({"type": "register", "role": "mic_input"}))
                ack = json.loads(await ws.recv())
                if ack.get("type") != "register_ack":
                    logger.warning("Unexpected registration response: %s", ack)
                logger.info("Registered as mic_input. Waiting for the wake word...")

                await stream_mic(ws, check_startup_race=startup_phase)
                # Reached only on a normal return -- real capture ran past
                # the startup race window (or startup_phase was already
                # False). Either way, startup handling is done for good.
                startup_phase = False

        except MicStartupRaceError as e:
            logger.warning("%s", e)
            if not startup_reset_attempted:
                startup_reset_attempted = True
                await _run_startup_reset()
            else:
                # Already tried the one-time reset once and it's still
                # racing -- don't loop resets forever. Fall through to the
                # normal reconnect delay; startup_phase stays True so a
                # LATER successful attempt still correctly clears it.
                logger.warning("Startup reset already attempted once -- "
                                "falling back to normal retry without resetting again")

        except (websockets.exceptions.ConnectionClosed, OSError) as e:
            logger.warning("Connection lost (%s). Reconnecting in %.1fs...", e, RECONNECT_DELAY)
        except Exception:
            logger.exception("Unexpected error in mic client loop")

        await asyncio.sleep(RECONNECT_DELAY)


if __name__ == "__main__":
    try:
        asyncio.run(run_client())
    except KeyboardInterrupt:
        logger.info("Shutting down.")
