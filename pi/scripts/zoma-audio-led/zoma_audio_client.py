"""
ZoMa Pi audio/LED -- Pi-side audio sink for ZoMa Brain's TTS pipeline.
Property of TheMechanics. Contact: mamau.mechanics@gmail.com

Runs on ZoMa's Pi as a standalone script in its own environment, separate
from the ZoMa Brain server's own venv since it lives on different hardware.
Only third-party dependency is `websockets`.

Opens a WebSocket connection to the ZoMa Brain server, registers as role
"audio_sink", and pipes incoming TTS audio straight into a persistent
`aplay` subprocess. Does zero DSP -- resampling to 16kHz (the reSpeaker's
native rate) happens server-side. This script's only job is moving bytes
from the WebSocket to ALSA in order, and honoring tts_abort promptly.

Wire protocol (matches the server's AUDIO_SINKS fan-out):
  tts_start {utt, rate, fmt}       -- new utterance beginning
  tts_chunk {utt, seq} + binary    -- JSON header immediately followed by
                                       one binary WebSocket message (raw
                                       S16_LE mono PCM at `rate`)
  tts_end   {utt}                  -- utterance complete
  tts_abort {utt}                  -- stop immediately if `utt` is the
                                       one currently playing

=====================================================================
HARDWARE: reSpeaker XVF3800 USB 4-Mic Array
=====================================================================
The physical speaker is wired to the reSpeaker board's own JST speaker
connector, not to the Pi directly -- the board's onboard amp drives it.
Playback runs at 16kHz end-to-end (mic capture, STT, and TTS playback all
at the same rate), with no resampling on the Pi side in either direction.

=====================================================================
AEC REFERENCE
=====================================================================
Per the XVF3800's device-interfaces documentation, its on-chip AEC engine
does not automatically tap whatever gets played over the USB audio
endpoint -- it reads its far-end reference specifically from the LEFT
(channel 0) of a genuinely 2-channel USB playback stream, and internally
plays that same left-channel content out both physical outputs. A plain
mono (`-c 1`) aplay stream depends on ALSA's plughw layer inventing that
second channel, which is not reliable on every device/driver combination.

FIX: send real interleaved stereo explicitly -- both channels carrying the
actual audio -- instead of relying on plughw's implicit upmix.
_mono_to_stereo() below duplicates each sample onto L and R before handing
bytes to aplay, and APLAY_CMD requests `-c 2` to match. This guarantees AEC
gets an explicit, correct left-channel reference regardless of what plughw
would otherwise do with a mono stream.
"""

import array
import asyncio
import json
import logging
import os
import subprocess

import websockets

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("zoma_audio_client")

# Point this at the ZoMa Brain server's LAN address. Avoid relying on
# mDNS hostname resolution across platforms with their own networking
# quirks (e.g. WSL2) -- an explicit IP/host sidesteps that entirely.
ZOMA_BRAIN_HOST = os.getenv("ZOMA_BRAIN_HOST", "192.168.1.50")
ZOMA_BRAIN_PORT = int(os.getenv("ZOMA_BRAIN_PORT", "8765"))
ZOMA_BRAIN_WS_URL = f"ws://{ZOMA_BRAIN_HOST}:{ZOMA_BRAIN_PORT}"

RECONNECT_DELAY = float(os.getenv("ZOMA_AUDIO_RECONNECT_DELAY", "3.0"))

# Card is addressed by NAME (Array), not index -- index shuffles across
# reboots/replugs. Device is addressed explicitly rather than relying on
# ALSA's `default`, which has proven unreliable on some Pi/ALSA
# combinations (non-48kHz playback failing outright, or playback breaking
# once capture is also active concurrently).
APLAY_CMD = ["aplay", "-D", "plughw:CARD=Array,DEV=0", "-f", "S16_LE", "-r", "16000", "-c", "2", "-q"]

# amixer addresses the card by the same name, but through the ALSA CONTROL
# interface, not a PCM device open -- unlike aplay's exclusive plughw
# handle, this doesn't contend with anything else on the card.
ALSA_CARD = "Array"
ALSA_VOLUME_CONTROL = "PCM"  # explicit, not whatever the default control is


async def apply_volume_delta(percent: int):
    """
    percent: signed step in %, e.g. +2 or -2 -- the server already resolved
    direction and step size, this just applies it. amixer's own syntax
    wants the sign as a separate suffix on the magnitude ("2%+"/"2%-"), not
    a signed number.

    Run via asyncio.to_thread: amixer normally returns quickly, but it's
    still a blocking subprocess call, and the receive loop below needs to
    keep reading incoming messages (in particular tts_abort) promptly
    regardless.
    """
    sign = "+" if percent >= 0 else "-"
    step = f"{abs(percent)}%{sign}"
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            ["amixer", "-c", ALSA_CARD, "set", ALSA_VOLUME_CONTROL, step],
            capture_output=True, text=True, timeout=5.0,
        )
        if result.returncode != 0:
            logger.warning("amixer failed (exit %d): %s", result.returncode, result.stderr.strip())
        else:
            last_line = result.stdout.strip().splitlines()[-1] if result.stdout else ""
            logger.info("Volume %s -> %s", step, last_line)
    except FileNotFoundError:
        logger.warning("amixer not found -- can't apply volume change")
    except subprocess.TimeoutExpired:
        logger.warning("amixer call timed out")


def mono_to_stereo(mono: bytes) -> bytes:
    """
    Duplicate S16_LE mono PCM onto both L and R channels, interleaved as
    [L0, R0, L1, R1, ...]. See the AEC REFERENCE note in the module
    docstring -- the XVF3800's on-chip AEC reads its far-end reference from
    the LEFT channel of a genuine 2-channel USB playback stream, and this
    makes sure that channel always carries real audio.
    """
    samples = array.array("h")
    samples.frombytes(mono)
    stereo = array.array("h", bytes(len(samples) * 4))  # 2 channels x 2 bytes/sample
    stereo[0::2] = samples
    stereo[1::2] = samples
    return stereo.tobytes()


class AudioSink:
    """
    Owns exactly one persistent `aplay` subprocess. Writing PCM bytes to
    its stdin is the only interface -- ALSA/aplay handles queuing and
    back-pressure.

    Writes are decoupled from receiving via an internal queue plus a
    dedicated writer task. This matters because a pipe write to aplay's
    stdin blocks once the OS pipe buffer fills, and it only drains as fast
    as aplay actually plays audio -- i.e. in real time. A multi-second
    chunk's write() call can itself take several real seconds to return.
    If that write were awaited directly in the WebSocket receive loop, the
    loop couldn't read the next incoming message (in particular a later
    tts_abort) until the current real-time-gated write finished. Queuing
    decouples the two: receiving is always instant, and the writer task
    absorbs the real-time-bound cost on its own.
    """

    def __init__(self):
        self._proc: subprocess.Popen | None = None
        self._current_utt: str | None = None
        self._write_queue: asyncio.Queue = asyncio.Queue()
        self._writer_task: asyncio.Task | None = None
        # Guards every spawn/kill of self._proc. Without this, abort()
        # (called from the receive loop) and the writer's own
        # respawn-on-broken-pipe could race: both spawn a replacement aplay
        # process at nearly the same moment, two processes fight for the
        # same exclusive ALSA device, one gets "Device or resource busy",
        # and the failure cascades.
        self._proc_lock = asyncio.Lock()

    def ensure_writer_started(self):
        if self._writer_task is None or self._writer_task.done():
            self._writer_task = asyncio.create_task(self._writer_loop())

    def _spawn(self):
        """Caller must hold self._proc_lock."""
        self._proc = subprocess.Popen(APLAY_CMD, stdin=subprocess.PIPE)
        logger.info("aplay subprocess started (pid=%s)", self._proc.pid)

    def _ensure_running(self):
        """Caller must hold self._proc_lock."""
        if self._proc is None or self._proc.poll() is not None:
            self._spawn()

    async def start_utterance(self, utt: str):
        async with self._proc_lock:
            if self._current_utt is not None and self._current_utt != utt:
                # A new utterance arrived before the previous one finished
                # (e.g. rapid back-to-back queries). Only one thing should
                # play on a single speaker at a time -- cut the old one off
                # cleanly rather than letting them overlap.
                logger.info("New utterance %s while %s still active -- cutting over", utt, self._current_utt)
                if self._proc and self._proc.poll() is None:
                    self._proc.kill()
                    self._proc.wait()
            self._ensure_running()
            self._current_utt = utt

    def _write_sync(self, proc: subprocess.Popen, data: bytes):
        """
        Blocking write -- only ever called via asyncio.to_thread, from the
        writer task. Takes the specific proc it should write to (captured
        under the lock) rather than reading self._proc live, so it can't
        accidentally write to a process that abort() has already moved on
        from.
        """
        try:
            proc.stdin.write(data)
            proc.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            # Deliberately does NOT respawn here. Respawning would race
            # with abort()'s own respawn. If the pipe died, either an
            # abort/cutover already replaced self._proc (in which case
            # we're done with this chunk anyway), or the next
            # start_utterance() will provision a fresh one. This thread's
            # only job is "try to write, don't own process lifecycle."
            logger.warning("aplay pipe write failed (%s) -- dropping this chunk", e)

    async def _writer_loop(self):
        """
        Single consumer for queued audio, in order. Runs independently of
        the WebSocket receive loop -- this is what absorbs the
        real-time-bound pipe write cost without blocking anything else.
        """
        while True:
            utt, data = await self._write_queue.get()
            if utt != self._current_utt:
                # Stale by the time we got to it (e.g. an abort landed
                # while this was queued behind other writes). Drop it
                # rather than mixing it into whatever plays next.
                logger.debug("Dropping queued chunk for stale utt=%s (current=%s)", utt, self._current_utt)
                continue
            async with self._proc_lock:
                self._ensure_running()
                proc = self._proc
            await asyncio.to_thread(self._write_sync, proc, data)

    def write(self, utt: str, data: bytes):
        """
        Non-blocking: just enqueues. The actual (potentially slow) write
        happens in _writer_loop. Callers in the receive loop should not
        await anything here beyond this call itself.
        """
        self._write_queue.put_nowait((utt, data))

    def end_utterance(self, utt: str):
        # Deliberately does NOT clear _current_utt. tts_end only means "no
        # more chunks are coming" -- it says nothing about whether aplay
        # has actually finished draining the audio it already has.
        # Synthesis+transmission can easily outrun real playback time. If
        # this cleared _current_utt, a tts_abort arriving after tts_end but
        # while audio is still audibly playing would fail abort()'s
        # utt-match check and silently do nothing. _current_utt is only
        # ever cleared by abort() itself or by the next start_utterance()'s
        # cutover.
        pass

    async def abort(self, utt: str | None):
        """
        Hard-interrupt: kill the aplay process outright rather than try to
        flush or skip buffered audio. aplay has no clean "discard what's
        queued" API, and anything already handed to ALSA keeps playing
        until the process dies regardless -- killing it is the only way to
        actually stop sound promptly. Anything still sitting in
        _write_queue for this utt gets silently dropped by _writer_loop's
        own utt-match check once _current_utt is cleared below -- no
        separate queue-clearing needed.
        """
        async with self._proc_lock:
            if utt is not None and utt != self._current_utt:
                return  # targets an utterance that's already finished/stale
            if self._proc and self._proc.poll() is None:
                logger.info("Aborting playback (utt=%s)", utt)
                self._proc.kill()
                self._proc.wait()
            self._current_utt = None
            self._spawn()  # ready immediately for whatever comes next

    def close(self):
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.stdin.close()
            except OSError:
                pass
            self._proc.terminate()


async def run_client():
    sink = AudioSink()

    while True:
        try:
            logger.info("Connecting to %s ...", ZOMA_BRAIN_WS_URL)
            # max_size=None: TTS audio chunks can exceed the websockets
            # library's default 1MiB-per-message cap, enforced on BOTH
            # sides of the connection independently -- without this on the
            # client too, the connection closes (code 1009) the first time
            # a sentence's synthesized audio crosses 1MiB.
            async with websockets.connect(ZOMA_BRAIN_WS_URL, max_size=None, ping_interval=None) as ws:
                await ws.recv()  # identity message -- informational only, not needed here
                await ws.send(json.dumps({"type": "register", "role": "audio_sink"}))
                ack = json.loads(await ws.recv())
                if ack.get("type") != "register_ack":
                    logger.warning("Unexpected registration response: %s", ack)
                logger.info("Registered as audio_sink. Waiting for TTS audio...")

                sink.ensure_writer_started()
                pending_chunk_utt = None

                async for message in ws:
                    if isinstance(message, bytes):
                        if pending_chunk_utt is not None:
                            # Non-blocking enqueue -- deliberately NOT
                            # awaited beyond the call itself, so this loop
                            # can immediately go back to reading the next
                            # message (a tts_abort in particular) regardless
                            # of how much real-time-gated writing is still
                            # queued up.
                            sink.write(pending_chunk_utt, mono_to_stereo(message))
                            pending_chunk_utt = None
                        else:
                            logger.warning("Binary audio with no preceding tts_chunk header -- dropped")
                        continue

                    data = json.loads(message)
                    msg_type = data.get("type")

                    if msg_type == "tts_start":
                        await sink.start_utterance(data.get("utt"))
                        logger.info(
                            "tts_start utt=%s rate=%s fmt=%s",
                            data.get("utt"), data.get("rate"), data.get("fmt"),
                        )
                    elif msg_type == "tts_chunk":
                        pending_chunk_utt = data.get("utt")
                    elif msg_type == "tts_end":
                        sink.end_utterance(data.get("utt"))
                        logger.info("tts_end utt=%s", data.get("utt"))
                    elif msg_type == "tts_abort":
                        logger.info("tts_abort utt=%s", data.get("utt"))
                        await sink.abort(data.get("utt"))
                    elif msg_type == "volume_delta":
                        await apply_volume_delta(data.get("percent", 0))
                    elif msg_type == "register_ack":
                        pass  # already consumed at registration; ignore if resent
                    else:
                        logger.debug("Ignoring unrelated message type: %s", msg_type)

        except (websockets.exceptions.ConnectionClosed, OSError) as e:
            logger.warning("Connection lost (%s). Reconnecting in %.1fs...", e, RECONNECT_DELAY)
        except Exception:
            logger.exception("Unexpected error in client loop")

        await asyncio.sleep(RECONNECT_DELAY)


if __name__ == "__main__":
    try:
        asyncio.run(run_client())
    except KeyboardInterrupt:
        logger.info("Shutting down.")
