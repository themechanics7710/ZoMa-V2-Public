"""
ZoMa Brain — parametric WebSocket brain server
Property of TheMechanics. Contact: mamau.mechanics@gmail.com

Ties together STT (Whisper), speaker ID (pyannote), local LLM inference
(Qwen via Ollama), Claude uplink sessions, TTS (Kokoro), vision, and
FAISS memory behind a single WebSocket server that the robot's Pi and
firmware talk to. The assistant's name, wake word, memory database, and
persona prompt are all runtime parameters -- the same binary can run any
persona with no code changes.

RUNTIME PARAMETERS
------------------
  --name          Assistant name. Default: config.ASSISTANT_NAME.
  --wake-word     Spoken trigger word. Defaults to --name.
  --memory-name   Which memory database to use. Defaults to --name.
                  Set it explicitly to share one memory across several
                  personas (e.g. a maintenance-prompt variant that
                  should still remember everything).
  --prompt        Persona/system prompt file. Default: config.PROMPT_FILE.
  --lang          eng | it | fr | esp. Default: eng.
  --reply-mode    fixed (always --lang) | mirror (match the speaker).
  --pi-host       ZoMa's Pi hostname or IP. Builds the RTSP URL.
  --pi-port       RTSP port. 8554. NOT 8889 -- that's WebRTC, browsers only.
  --pi-path       RTSP path. Default: cam.
  --tts-voice     Override the language table's Kokoro voice.
  --tts-speed     Kokoro speed multiplier (1.0 normal, >1.0 faster,
                  <1.0 slower). Default: 1.0.
  --stt-prompt    Override Whisper's initial_prompt (the bilingual hint).

DESIGN NOTES
------------
  1. Whisper transcription never blocks the event loop: faster_whisper's
     transcribe() returns a lazy generator, so the generator must be
     drained inside the worker thread (_transcribe_blocking), not on the
     event loop after the thread returns.
  2. Pre-empt concurrency: a new query cancels any in-flight one, so a
     mic query landing mid-reply can't leave two TTS workers broadcasting
     to the same audio sinks at once.
  3. Barge-in is safe against odd-length PCM chunks (np.frombuffer would
     otherwise raise on an odd byte count).
  4. tts_abort and tts_end never race for the same utterance: a cancelled
     TTS worker does not also emit tts_end from its finally block.
  5. A rotating "still thinking" filler is spoken/shown every
     FILLER_INTERVAL seconds while the LLM has produced no tokens yet,
     cancelled the instant the first token arrives.
  6. Mic thresholds, barge-in level, history depth, and wake-word
     similarity are all tunable via config.py, not hardcoded here.
  7. Ollama's final streamed chunk carries the real load_duration /
     prompt_eval_duration / eval_duration split (nanoseconds), logged via
     _log_llm_breakdown() -- requires the paired llm_engine.py `metrics`
     out-param.
  8. After a vision-route reply, the text model is pre-warmed
     fire-and-forget (_prewarm_text_model()) so a likely follow-up
     question doesn't pay a full model-load cost on top of its own
     latency -- see that function's docstring for the one-directional
     reasoning.
"""

import asyncio
import websockets
import numpy as np
from faster_whisper import WhisperModel
import threading
import argparse
import time
from datetime import datetime
import os
import json
import inspect
import uuid
import difflib
import random
import re
import wave
import aiohttp
import vision_engine
import tts_engine

# --- Hugging Face Compatibility Patch ----------------------------------------
import huggingface_hub
if hasattr(huggingface_hub, "hf_hub_download"):
    _sig = inspect.signature(huggingface_hub.hf_hub_download)
    if "use_auth_token" not in _sig.parameters:
        _orig_download = huggingface_hub.hf_hub_download
        def _patched_download(*args, **kwargs):
            if "use_auth_token" in kwargs:
                kwargs["token"] = kwargs.pop("use_auth_token")
            return _orig_download(*args, **kwargs)
        huggingface_hub.hf_hub_download = _patched_download
# -----------------------------------------------------------------------------

import torch
import torchaudio
from pyannote.audio import Model, Inference

import config
import smart_tools
import pi_commands
import claude_engine
from memory_core import BrainMemory
from vision_stream import VisionStream
from llm_engine import ask_qwen_stream, classify_context_with_llm


# =============================================================================
# ARGUMENTS
# =============================================================================

parser = argparse.ArgumentParser(description="ZoMa Brain Server")

# --- identity -----------------------------------------------------------------
parser.add_argument("--name", type=str, default=None,
                    help="Assistant name. Default: config.ASSISTANT_NAME.")
parser.add_argument("--wake-word", dest="wake_word", type=str, default=None,
                    help="Spoken trigger word. Defaults to --name.")
parser.add_argument("--memory-name", dest="memory_name", type=str, default=None,
                    help="Memory database to use. Defaults to --name.")
parser.add_argument("--prompt", type=str, default=None,
                    help="Persona prompt file. Default: config.PROMPT_FILE.")

# --- language -------------------------------------------------------------------
parser.add_argument("--lang", type=str, default=None,
                    choices=sorted(config.LANGUAGES.keys()),
                    help="Active language. Default: config.LANGUAGE.")
parser.add_argument("--reply-mode", dest="reply_mode", type=str, default=None,
                    choices=["fixed", "mirror"],
                    help="fixed = always reply in --lang; mirror = match the speaker.")
parser.add_argument("--stt-prompt", dest="stt_prompt", type=str, default=None,
                    help="Override Whisper's initial_prompt bilingual hint.")
parser.add_argument("--tts-voice", dest="tts_voice", type=str, default=None,
                    help="Override the language table's Kokoro voice.")
parser.add_argument("--tts-speed", dest="tts_speed", type=float, default=None,
                    help="Kokoro speed multiplier (1.0 normal, >1.0 faster, "
                         "<1.0 slower). Default: config.KOKORO_SPEED (1.0).")

# --- ZoMa / Pi --------------------------------------------------------------------
parser.add_argument("--pi-host", dest="pi_host", type=str, default=None,
                    help="ZoMa Pi hostname or IP (e.g. rb1.local, 192.168.1.42).")
parser.add_argument("--pi-port", dest="pi_port", type=int, default=None,
                    help="RTSP port. 8554. NOT 8889 (that is WebRTC, browsers only).")
parser.add_argument("--pi-path", dest="pi_path", type=str, default=None,
                    help="RTSP stream path. Default: cam.")
parser.add_argument("--no_vision", action="store_true",
                    help="Disable ZoMa camera ingestion entirely.")

# --- existing flags, unchanged names --------------------------------------------
parser.add_argument("--whisper_model", type=str, default=config.WHISPER_MODEL_SIZE)
parser.add_argument("--beam_size", type=int, default=config.WHISPER_BEAM_SIZE)
parser.add_argument("--port", type=int, default=config.SERVER_PORT)
parser.add_argument("--gallery_dir", type=str, default=config.SPEAKER_GALLERY_DIR)
parser.add_argument("--threshold", type=float, default=config.SPEAKER_ID_THRESHOLD)

args = parser.parse_args()


# =============================================================================
# RUNTIME CONFIG RESOLUTION
# =============================================================================

def _slugify(name: str) -> str:
    """
    Brain name -> filesystem-safe slug. Only [a-z0-9_] survives, which
    also means path separators, '..', and shell metacharacters cannot
    escape MEMORY_DIR no matter what gets passed to --name.
    """
    slug = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    if not slug:
        raise SystemExit(
            "[FATAL] --name / --memory-name must contain at least one "
            "alphanumeric character."
        )
    return slug


def _apply_runtime_config(a) -> dict:
    """
    Fold CLI arguments into the config module IN PLACE, then return the
    resolved values this module needs directly.

    Mutating config is deliberate: llm_engine, tts_engine, vision_engine
    and memory_core all read `config.X` at CALL time, so overriding here
    reaches them without any of them needing to know the CLI exists.
    This only works because none of them do `from config import X`.
    """
    if a.name:
        config.ASSISTANT_NAME = a.name

    if a.lang:
        config.LANGUAGE = a.lang
    if a.reply_mode:
        config.REPLY_LANGUAGE_MODE = a.reply_mode

    if a.prompt:
        config.PROMPT_FILE = a.prompt

    if a.pi_host:
        config.PI_HOST = a.pi_host
    if a.pi_port:
        config.PI_RTSP_PORT = a.pi_port
    if a.pi_path:
        config.PI_RTSP_PATH = a.pi_path
    if a.pi_host or a.pi_port or a.pi_path:
        config.ZOMA_STREAM_URL = (
            f"rtsp://{config.PI_HOST}:{config.PI_RTSP_PORT}/{config.PI_RTSP_PATH}"
        )

    config.SPEAKER_GALLERY_DIR = a.gallery_dir
    config.SPEAKER_ID_THRESHOLD = a.threshold

    langset = config.lang()

    config.KOKORO_VOICE = a.tts_voice or config.KOKORO_VOICE or langset["kokoro_voice"]
    config.KOKORO_SPEED = a.tts_speed or config.KOKORO_SPEED

    assistant_name = config.ASSISTANT_NAME
    wake_word = (a.wake_word or config.WAKE_WORD or assistant_name).strip().lower()
    memory_name = a.memory_name or config.MEMORY_NAME or assistant_name
    memory_slug = _slugify(memory_name)
    index_file, map_file = config.memory_paths(memory_slug)

    # Silence commands: the active language's list ALWAYS unioned with
    # English, since "stop" works in every language in practice and a
    # false-positive interrupt is far cheaper than a missed one.
    silence = set(config.LANGUAGES["eng"]["silence"]) | set(langset["silence"])

    # Known Whisper hallucination phrases, same union logic as silence
    # above -- guards the wake-word-less follow-up path against a
    # transcript that's really just Whisper inventing filler from noise.
    halluc = set(config.LANGUAGES["eng"]["halluc"]) | set(langset["halluc"])

    return {
        "assistant_name": assistant_name,
        "wake_word": wake_word,
        "memory_name": memory_name,
        "memory_slug": memory_slug,
        "index_file": index_file,
        "map_file": map_file,
        "lang_key": config.LANGUAGE,
        "lang": langset,
        "silence": silence,
        "halluc": halluc,
        "stt_prompt": a.stt_prompt or langset["stt_hint"],
    }


RT = _apply_runtime_config(args)

ASSISTANT_NAME = RT["assistant_name"]
WAKE_WORD = RT["wake_word"]
LANG = RT["lang"]
SILENCE_COMMANDS = RT["silence"]
HALLUC_PHRASES = RT["halluc"]


def _print_banner():
    line = "=" * 62
    print("\n" + line)
    print(f" ZoMa Brain  ::  {ASSISTANT_NAME}")
    print(line)
    print(f"  wake word      : {WAKE_WORD}")
    print(f"  prompt file    : {config.PROMPT_FILE}")
    print(f"  language       : {RT['lang_key']} ({LANG['label']}), "
          f"reply mode {config.REPLY_LANGUAGE_MODE}")
    print(f"  memory         : {RT['memory_name']}  ->  {RT['index_file']}")
    print(f"  voice gallery  : {config.SPEAKER_GALLERY_DIR}  (shared across brains)")
    print(f"  camera         : {config.ZOMA_STREAM_URL}"
          f"{'  [DISABLED]' if args.no_vision else ''}")
    print(f"  tier 1 (motion/face) : {'ON' if config.TIER1_ENABLED else 'OFF (config.TIER1_ENABLED)'}")
    print(f"  text model     : {config.QWEN_TEXT_MODEL}")
    print(f"  vision model   : {config.QWEN_VL_MODEL}")
    print(f"  claude model   : {config.CLAUDE_MODEL}  (uplink sessions, "
          f"phrase: 'start/go/begin/initiate/open uplink')")
    print(f"  tts voice      : {config.KOKORO_VOICE} "
          f"(lang_code {LANG['kokoro_lang_code']}, speed {config.KOKORO_SPEED})")
    print(f"  listening on   : ws://{config.SERVER_HOST}:{args.port}")
    print(line)

    if not os.path.exists(config.PROMPT_FILE):
        print(f"\n[!] WARNING: prompt file not found: {config.PROMPT_FILE}")
        print("    The LLM path will raise on the first query. Fix --prompt.\n")

    if not config.ANTHROPIC_API_KEY:
        print(f"\n[!] WARNING: ANTHROPIC_API_KEY not set.")
        print("    Uplink sessions will fail on first use -- set it in the environment "
              "(see .env / docs/SETUP.md) before starting an uplink session.\n")

    if config.REPLY_LANGUAGE_MODE == "fixed" and RT["lang_key"] != "eng":
        print(f"[i] NOTE: smart_tools.route_query_heuristic still matches English")
        print(f"    keywords only. Vision/weather/finance phrasing in "
              f"{LANG['label']} will fall through to plain chat until that file")
        print(f"    is made bilingual.\n")


# =============================================================================
# GLOBAL STATE
# =============================================================================

whisper_model = None
model_ready = False
speaker_inference = None
gallery_mean = {}
brain_memory: BrainMemory = None
vision_stream: VisionStream = None
chat_history = []

# ZoMa's Pi registers here (role: "audio_sink") over the same WebSocket
# port as browser/text clients. TTS audio fans out to whatever's
# registered -- zero sinks just means silence, not an error.
AUDIO_SINKS: set = set()

# ZoMa's Pi LED-ring logic layer registers here separately (role:
# "led_ring"). Kept distinct from AUDIO_SINKS -- LED state pushes don't
# care whether an audio sink is also connected, and vice versa.
LED_SINKS: set = set()

# Whatever utterance is currently "in flight" -- set the moment a query
# starts generating (text arrives fast; synthesis lags behind), not when
# audio starts playing. A stop command must be able to cancel synthesis
# that hasn't produced audio yet.
_active_utt_id: str | None = None
_active_tts_task: asyncio.Task | None = None

# Timestamp (time.time()) until which the mic gate stays closed
# regardless of _active_utt_id. Set by _stop_active_tts() on every stop
# (barge-in or a transcribed "stop" command) -- see config.STOP_COOLDOWN_
# SECONDS for why this exists: clearing _active_utt_id alone reopened the
# gate instantly, before the shout/echo/in-flight audio behind the stop
# had actually decayed.
_mic_mute_until: float = 0.0

# Pre-empt: the single in-flight query. A new query cancels this one.
_active_query_task: asyncio.Task | None = None

# Short-term "what did I just actually see" cache.
last_vision_summary = {"text": None, "timestamp": 0.0}

# UPLINK: whether the current conversation is being routed to Claude
# instead of the local Qwen model. Module-level, not per-connection --
# same reasoning as chat_history/_active_utt_id above: this is a single-
# conversation device, and a reconnecting Pi mic client must not silently
# drop an active session. See smart_tools.detect_uplink_command() and
# _start_uplink_session()/_end_uplink_session() below.
_uplink_active: bool = False

# Cancelled and replaced on every accepted uplink turn (refresh-on-
# activity, same shape as the FOLLOWUP_WINDOW_SECONDS window) -- fires
# _end_uplink_session(reason="idle_timeout") if nothing is heard for
# config.UPLINK_IDLE_TIMEOUT_SECONDS.
_uplink_idle_task: asyncio.Task | None = None


# =============================================================================
# SPEAKER ID
# =============================================================================

def cosine(a, b):
    a = a / (np.linalg.norm(a) + 1e-9)
    b = b / (np.linalg.norm(b) + 1e-9)
    return float(np.dot(a, b))


def l2_normalize(x, eps=1e-12):
    return x / (np.linalg.norm(x) + eps)


def gallery_centroid(emb_list):
    c = np.mean(np.stack(emb_list, axis=0), axis=0)
    return l2_normalize(c.astype(np.float32))


def load_audio_mono(path, target_sr=16000):
    wav, sr = torchaudio.load(str(path))
    if wav.shape[0] > 1:
        wav = wav.mean(dim=0, keepdim=True)
    if sr != target_sr:
        wav = torchaudio.functional.resample(wav, sr, target_sr)
        sr = target_sr
    return wav, sr


def embed_tensor(inference_obj, wav, sr):
    swf = inference_obj({"waveform": wav, "sample_rate": sr})
    vec = swf.data.mean(axis=0).astype(np.float32).flatten()
    return l2_normalize(vec)


def embed_file(inference_obj, wav_path):
    wav, sr = load_audio_mono(wav_path)
    return embed_tensor(inference_obj, wav, sr)


def decide_identity(sorted_scores, thr_hi=0.72, thr_lo=0.40, margin=0.30, second_cap=0.45):
    if not sorted_scores:
        return "UNKNOWN", 0.0, 0.0, "NO"
    best_name, best_score = sorted_scores[0]
    second_score = sorted_scores[1][1] if len(sorted_scores) > 1 else -1.0
    if best_score >= thr_hi:
        return best_name, best_score, second_score, "HI"
    if best_score >= thr_lo and (best_score - second_score) >= margin and second_score < second_cap:
        return best_name, best_score, second_score, "LO"
    return "UNKNOWN", best_score, second_score, "NO"


def init_speaker_id():
    global speaker_inference, gallery_mean
    from pathlib import Path

    print("\n[*] Initializing Speaker Identification...")
    token = os.environ.get(config.HF_TOKEN_ENV) or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    if not token:
        print("[WARNING] HF token not found. Speaker ID disabled.")
        return False
    try:
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        embedding_model = Model.from_pretrained("pyannote/embedding", token=token)
        speaker_inference = Inference(embedding_model, device=device)

        gallery_dir = Path(config.SPEAKER_GALLERY_DIR)
        gallery_files = sorted(gallery_dir.glob("*.wav"))
        if not gallery_files:
            print(f"[WARNING] No .wav files in {gallery_dir}. Speaker ID disabled.")
            return False

        by_name = {}
        for fp in gallery_files:
            name = fp.stem.split("_")[0].capitalize()
            by_name.setdefault(name, []).append(embed_file(speaker_inference, fp))

        gallery_mean = {name: gallery_centroid(v) for name, v in by_name.items()}
        print(f"[*] Voice Gallery Loaded: {list(gallery_mean.keys())}")
        return True
    except Exception as e:
        print(f"[ERROR] Failed to initialize Speaker ID: {e}")
        return False


def identify_speaker(audio_np, sr=16000):
    if not speaker_inference or not gallery_mean:
        return "UNKNOWN"
    try:
        wav_tensor = torch.from_numpy(audio_np).unsqueeze(0)
        emb = embed_tensor(speaker_inference, wav_tensor, sr)
        scores = {name: cosine(emb, gemb) for name, gemb in gallery_mean.items()}
        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        best_name, best_score, second_score, conf = decide_identity(
            sorted_scores, thr_hi=config.SPEAKER_ID_THRESHOLD,
            thr_lo=0.40, margin=0.30, second_cap=0.45,
        )
        if best_name != "UNKNOWN":
            print(f" [*] Speaker ID Match -> {best_name} (Score: {best_score:.4f}, Conf: {conf})")
        return best_name
    except Exception:
        return "UNKNOWN"


# =============================================================================
# STARTUP (heavy model loads run in a background thread)
# =============================================================================

def load_ai():
    global whisper_model, model_ready, brain_memory
    print("\n" + "=" * 62)
    print(f" INITIALIZING BRAIN: Whisper {args.whisper_model.upper()} "
          f"& {config.QWEN_TEXT_MODEL.upper()}")
    print("=" * 62)
    try:
        start_time = time.time()
        whisper_model = WhisperModel(args.whisper_model, device="cuda", compute_type="float16")
        init_speaker_id()
        brain_memory = BrainMemory(
            index_file=RT["index_file"],
            map_file=RT["map_file"],
            assistant_name=ASSISTANT_NAME,
        )
        elapsed = time.time() - start_time
        model_ready = True
        print(f"\n {ASSISTANT_NAME.upper()} IS ONLINE (Ready in {elapsed:.1f}s)\n")
    except Exception as e:
        print(f"[FATAL ERROR] {e}")
        os._exit(1)


# =============================================================================
# TTS FAN-OUT
# =============================================================================

# This keepalive is deliberately per-sink, not a global
# websockets.serve(ping_interval=...) setting. Audio sinks never call
# into Whisper, so they get their own explicit ping loop, leaving the
# main server's ping_interval=None untouched for everyone else.
async def _sink_keepalive(websocket):
    try:
        while True:
            await asyncio.sleep(config.AUDIO_SINK_PING_INTERVAL)
            try:
                pong_waiter = await websocket.ping()
                await asyncio.wait_for(pong_waiter, timeout=config.AUDIO_SINK_PING_INTERVAL)
            except (asyncio.TimeoutError, websockets.exceptions.ConnectionClosed):
                print(" [AUDIO_SINK] Ping timeout -- dropping stale sink connection.")
                await websocket.close()
                return
    except asyncio.CancelledError:
        return


async def _broadcast_sinks(payload):
    """Send one frame (JSON header str or raw PCM bytes) to every sink."""
    if not AUDIO_SINKS:
        return
    dead = []
    for sink in list(AUDIO_SINKS):
        try:
            await sink.send(payload)
        except websockets.exceptions.ConnectionClosed:
            dead.append(sink)
    for sink in dead:
        AUDIO_SINKS.discard(sink)


async def _broadcast_led(payload: str):
    """Send one led_state JSON message to every registered LED sink."""
    if not LED_SINKS:
        return
    dead = []
    for sink in list(LED_SINKS):
        try:
            await sink.send(payload)
        except websockets.exceptions.ConnectionClosed:
            dead.append(sink)
    for sink in dead:
        LED_SINKS.discard(sink)


# =============================================================================
# LED STATE BROADCAST (see docs/ARCHITECTURE.md section 3.3, the WS2812
# interaction ring)
# =============================================================================

async def _publish_led_state(state: str, duration: float | None = None):
    """
    Tells the Pi's LED ring logic (role "led_ring") which of Monster's
    states is currently active, over LED_SINKS/pi_commands.py -- a
    connection dedicated to this, separate from AUDIO_SINKS. Call sites
    pass a source-specific state (thinking_local vs. thinking_vision vs.
    thinking_uplink, etc.) so the ring can visually distinguish which
    engine is doing the work rather than showing one generic animation
    for all three -- see pi_commands.VALID_LED_STATES.
    """
    await _broadcast_led(pi_commands.led_state_message(state, duration=duration))


def _listening_state_and_duration() -> tuple[str, float | None]:
    """
    Ground truth for "what should the ring show while nothing is actively
    being generated/spoken", computed fresh at each call site:

      - mid Claude-uplink session -> uplink_listening, no expiry (uplink
        has its own idle timeout, handled separately).
      - the follow-up window is genuinely open right now (per
        _conversation_open()) -> listening, with the actual remaining
        seconds until it closes, so the Pi can locally revert to
        "awaiting wake word" exactly when the window really closes, even
        if no further message ever arrives to tell it so.
      - otherwise (window closed, or never opened) -> idle_wake_word,
        the "say the wake word" state.
    """
    if _uplink_active:
        return "uplink_listening", None
    if _conversation_open():
        remaining = max(0.0, _conversation["expires_at"] - time.time())
        return "listening", remaining
    return "idle_wake_word", None


async def _tts_utterance_worker(utt_id: str, sentence_queue: asyncio.Queue,
                                query_start_time: float | None = None,
                                source: str = "local",
                                speaker_name: str | None = None,
                                client_type: str | None = None):
    """
    source distinguishes which model produced this utterance's text
    ("local" for Qwen, "claude" for an uplink reply) -- picks which
    status state (_publish_led_state) fires when playback starts, AND
    which Kokoro voice synthesizes it (config.CLAUDE_TTS_VOICE), so
    uplink audibly sounds different from the local persona rather than
    just answering in the same voice under a different label.

    speaker_name/client_type exist for exactly one thing: re-anchoring
    the follow-up window (see below) to when THIS reply actually
    finishes, for VOICE replies only. Callers that aren't a real voice
    conversational reply (_speak_system_line's short announcements)
    leave both at their None default, which is what keeps this from
    firing there.

    Single consumer for one utterance's sentences, processed strictly in
    submission order -- that ordering is what guarantees playback
    matches the order sentences were written, even though per-sentence
    synthesis latency varies. Runs as its own task so it never blocks
    the text stream still arriving from the LLM.

    Cancellable: _stop_active_tts() cancels this directly so synthesis
    stops immediately, not just playback -- otherwise already-queued
    sentences keep getting synthesized and sent after the abort fires.

    On cancellation this does not emit tts_end -- only _stop_active_tts()'s
    own tts_abort broadcast fires, so the Pi never sees tts_end after
    tts_abort for the same utterance.

    MIC-GATE RELEASE: handle_connection() drops Pi mic input entirely
    while _active_utt_id is not None, specifically so the mic's own TTS
    echo can't get transcribed as a fresh command. That gate has to be
    released again once real playback finishes, or the mic stays deaf.
    _active_utt_id previously only got cleared by _stop_active_tts()
    (barge-in / a silence command) -- if neither ever fires for a given
    reply (echo under the barge-in threshold, or the room just being
    quiet), the gate would never reopen and even genuine follow-up
    speech would go nowhere. The fix below computes how long the audio
    actually sent should take to finish PLAYING (not synthesizing --
    synthesis reliably finishes well before real-time playback does)
    from the raw byte count, at TTS's fixed 16kHz/16-bit/mono output
    format, and clears the gate itself once that much wall-clock time
    has passed.
    """
    global _active_utt_id, _active_tts_task
    seq = 0
    started = False
    cancelled = False
    total_audio_bytes = 0
    playback_start_time = None
    voice = config.CLAUDE_TTS_VOICE if source == "claude" else None
    try:
        while True:
            sentence = await sentence_queue.get()
            if sentence is None:  # sentinel: this utterance's text stream ended
                break
            try:
                audio = await tts_engine.synthesize(sentence, voice=voice)
            except Exception as e:
                print(f" [TTS ERROR] Synthesis failed for utt={utt_id}: {e}")
                continue
            if not audio or not AUDIO_SINKS:
                continue
            if not started:
                if query_start_time is not None:
                    print(f" [TIMER] Time to first audio: {time.time() - query_start_time:.2f}s")
                # 16000 matches tts_engine.synthesize()'s actual output
                # rate -- NOT the Pi's playback pipe, which reads its own
                # hardcoded rate regardless of what's broadcast here.
                # This field exists for any OTHER sink that does trust it.
                await _broadcast_sinks(json.dumps({
                    "type": "tts_start", "utt": utt_id, "rate": 16000, "fmt": "s16le_mono",
                }))
                await _publish_led_state("speaking_uplink" if source == "claude" else "speaking_local")
                started = True
                playback_start_time = time.time()
            await _broadcast_sinks(json.dumps({"type": "tts_chunk", "utt": utt_id, "seq": seq}))
            await _broadcast_sinks(audio)
            total_audio_bytes += len(audio)
            seq += 1
    except asyncio.CancelledError:
        cancelled = True
        raise
    finally:
        if started and not cancelled:
            await _broadcast_sinks(json.dumps({"type": "tts_end", "utt": utt_id}))

            # Release the mic gate once real playback should actually be
            # done, computed from bytes sent rather than guessed: S16LE
            # mono 16kHz = 32000 bytes/sec. A cancelled/aborted utterance
            # skips this entirely -- _stop_active_tts() already cleared
            # the gate immediately in that case, which is the faster,
            # correct path for a real interrupt.
            BYTES_PER_SECOND = 2 * 16000  # 16-bit mono, 16kHz
            total_duration_s = total_audio_bytes / BYTES_PER_SECOND
            elapsed = time.time() - playback_start_time
            # Small safety margin for network transmission + the Pi's own
            # audio buffering latency, so the gate doesn't reopen a beat
            # before the physical speaker actually goes quiet.
            SAFETY_MARGIN_S = 0.6
            remaining = total_duration_s - elapsed + SAFETY_MARGIN_S
            if remaining > 0:
                try:
                    await asyncio.sleep(remaining)
                except asyncio.CancelledError:
                    # Pre-empted by a newer query while waiting out this
                    # utterance's tail -- _stop_active_tts() (called by
                    # whatever cancelled us) already cleared the gate for
                    # its own utt_id, so there's nothing left to do here.
                    raise
            if _active_utt_id == utt_id:
                _active_utt_id = None
                _active_tts_task = None
                # Re-anchor the follow-up window to NOW, not to whenever
                # the original utterance was accepted -- a slow reply
                # (vision analysis in particular) can eat most or all of
                # the window just thinking and talking, leaving little
                # real time to follow up once a reply can be heard.
                # VOICE replies only: a typed browser query getting a
                # spoken reply shouldn't silently open a wake-word-free
                # voice window. Only reached on normal completion (this
                # whole branch is skipped when cancelled), so a barge-in/
                # "stop" still can't extend it.
                if client_type == "voice":
                    _open_or_refresh_conversation(speaker_name)
                _led_state, _led_duration = _listening_state_and_duration()
                await _publish_led_state(_led_state, duration=_led_duration)


async def _stop_active_tts():
    """
    Cancels whatever is currently synthesizing AND tells sinks to stop
    playing. Both halves matter: cancelling stops synthesis of queued
    sentences; tts_abort stops what already reached a sink.

    Also cancels the in-flight QUERY (_active_query_task), not just
    audio: a barge-in during a slow uplink turn (a web search can run
    well past ten seconds) must stop the whole exchange, not just
    silence playback -- otherwise the Claude call keeps generating
    unmanaged in the background and later tries to speak a stale reply
    through a brand-new TTS utterance, re-arming the idle timer along
    the way. Safe to call even when dispatch_query() already
    cancelled/is about to cancel the same task -- cancelling an
    already-done task is a no-op.
    """
    global _active_utt_id, _active_tts_task, _mic_mute_until, _active_query_task

    query_task = _active_query_task
    if query_task and not query_task.done():
        query_task.cancel()

    if _active_utt_id is None:
        return
    utt_id = _active_utt_id
    if _active_tts_task and not _active_tts_task.done():
        _active_tts_task.cancel()
    await _broadcast_sinks(json.dumps({"type": "tts_abort", "utt": utt_id}))
    _active_utt_id = None
    _active_tts_task = None
    _mic_mute_until = time.time() + config.STOP_COOLDOWN_SECONDS
    _led_state, _led_duration = _listening_state_and_duration()
    await _publish_led_state(_led_state, duration=_led_duration)


# =============================================================================
# FILLER HEARTBEAT
# =============================================================================

async def _filler_heartbeat(websocket, phrases, interval):
    """
    Emits a rotating "still thinking" message every `interval` seconds
    for as long as it runs. Started right before the LLM call, cancelled
    the instant the first token arrives -- so if the model is fast, the
    user never sees a single one.

    Text/UI only. Spoken fillers stay behind config.SPOKEN_FILLERS
    because a spoken filler and the real reply share one utterance id and
    would collide on the Pi's single playback pipe.
    """
    i = 0
    try:
        while True:
            await asyncio.sleep(interval)
            try:
                await websocket.send(json.dumps({
                    "type": "filler", "text": phrases[i % len(phrases)],
                }))
            except Exception:
                return  # connection gone; nothing to do
            i += 1
    except asyncio.CancelledError:
        return


async def _spoken_filler(sentence_queue: asyncio.Queue, phrases, delay: float):
    """
    Speaks a short "just a sec" if the model hasn't started producing text
    within `delay` seconds. Cancelled the instant the first token arrives,
    so a fast reply never triggers one.

    The filler is pushed onto the SAME utterance's sentence_queue as the
    real reply -- it is sentence zero, not a separate utterance. That's
    what makes it safe: one utt id stays in flight, so ordering, abort,
    end and the pre-empt path all keep working with no changes. Emitting
    it as its own utterance would collide on the Pi's single playback
    pipe.

    Does NOT touch full_response, the websocket text stream, FAISS, or
    chat_history. The filler is spoken and then forgotten -- it must
    never end up as something the assistant "said" and can later recall.

    Fires at most once per utterance: after one filler this returns,
    rather than nagging every few seconds while a genuinely slow reply
    generates.
    """
    try:
        await asyncio.sleep(delay)
        phrase = random.choice(list(phrases))
        await sentence_queue.put(phrase)
        print(f" [FILLER-VOICE] {phrase!r} (model silent >{delay:.1f}s)")
    except asyncio.CancelledError:
        return


# =============================================================================
# LANGUAGE DIRECTIVE
# =============================================================================

def _language_directive() -> str:
    """
    Injected into system_context (which llm_engine prepends to the USER
    message), NOT into the system prompt -- that keeps llm_engine.py
    untouched and keeps the system prompt prefix stable for Ollama's
    prompt cache.
    """
    if config.REPLY_LANGUAGE_MODE == "mirror":
        return (
            "[LANGUAGE DIRECTIVE]\n"
            "Reply in the same language the person just used. Do not translate "
            "or switch languages unless asked.\n\n"
        )
    return (
        "[LANGUAGE DIRECTIVE]\n"
        f"Reply in {LANG['label']}, regardless of which language the incoming "
        f"message is written in, unless explicitly asked to switch.\n\n"
    )


def _date_context() -> str:
    """
    Gives the model the real current date so a live-web-search query
    (e.g. "today's news") can be phrased with a concrete, dateable query
    instead of relative terms like "today"/"now", which tend to match
    stale evergreen content rather than anything freshly dated. Shared by
    both process_brain_query and process_uplink_query, same as
    _language_directive() -- knowing today's date is broadly useful, not
    just for search.
    """
    return f"[SYSTEM: TODAY'S DATE] {datetime.now().strftime('%A, %B %d, %Y')}\n\n"


# =============================================================================
# VISION
# =============================================================================

async def process_vision_query(user_text: str, websocket) -> str:
    """Manual inspection: grab the freshest frame and ask Qwen-VL about it."""
    if vision_stream is None:
        return "[SYSTEM: VISION] No camera stream is currently configured."
    if not vision_stream.is_alive():
        return "[SYSTEM: VISION] Camera stream is configured but currently offline/unreachable."

    frame = vision_stream.get_latest_frame(max_age=config.ZOMA_FRAME_MAX_AGE)
    if frame is None:
        return "[SYSTEM: VISION] Stream is alive but no fresh frame is currently available."

    await websocket.send(json.dumps({"type": "filler", "text": "* Analyzing live frame... *"}))

    # Language stated explicitly: Qwen-VL has no other signal about which
    # language to answer in. (Tier 1's background prompts live in
    # vision_stream.py and are still English-only -- separate pass.)
    vl_prompt = (
        "You are looking through a live security camera feed. Answer the "
        "following question about what is currently visible, in 1-3 concise, "
        f"factual sentences. Answer in {LANG['label']}. Question: {user_text}"
    )

    # analyze_frame is blocking (requests) -> keep it off the event loop.
    description = await asyncio.to_thread(
        vision_engine.analyze_frame, vl_prompt, frame, config.QWEN_VL_TIMEOUT
    )

    if description.startswith("[SYSTEM ERROR]"):
        return description

    last_vision_summary["text"] = description
    last_vision_summary["timestamp"] = time.time()

    if brain_memory:
        try:
            brain_memory.add_vision_event(description, trigger_reason="live_query")
        except Exception as e:
            print(f" [!] Failed to log Tier 2 vision observation to memory: {e}")

    return f"[SYSTEM: LIVE VISION ANALYSIS] {description}"


# =============================================================================
# PRE-WARM
# =============================================================================

async def _prewarm_text_model():
    """
    Fire-and-forget: ask Ollama to load config.QWEN_TEXT_MODEL back into
    VRAM without generating any real output. Called ONLY right after a
    vision short-circuit reply has been sent.

    WHY THIS EXISTS: the vision and text models don't both fit in VRAM at
    once, so Ollama evicts one to load the other. A chat turn immediately
    following a vision turn otherwise pays a full model-load cost on top
    of its own latency. This tries to pay that reload cost during the
    idle gap between "here's what I see" and the person's follow-up
    question, instead of during the follow-up itself.

    WHY ONE-DIRECTIONAL: this fires after VISION replies only, never
    after ordinary CHAT replies. Vision is usually followed by a chat
    question about what was seen; the reverse (warming the text model
    after every chat turn, on the chance the next turn is vision) would
    actively hurt back-to-back vision queries by evicting the vision
    model right when a second vision call needs it.

    KNOWN TRADE-OFF: if two vision queries ARE asked back-to-back, this
    can still evict the vision model right before the second call needs
    it -- there's no way to distinguish "vision query with a chat
    follow-up coming" from "vision query with another vision query
    coming" until the second query actually arrives.

    Uses Ollama's documented no-prompt trick against /api/generate:
    posting {"model": ..., "keep_alive": ...} with no "prompt" key loads
    the model without running inference.

    THE OPTIONS BLOCK BELOW IS LOAD-BEARING. Ollama keys a loaded runner
    by model AND by the options that define that runner, num_ctx chief
    among them -- if this prewarm requests a different context size than
    ask_qwen_stream's own payload, it loads a second, differently-keyed
    runner and buys nothing: the next real chat turn still pays a full
    load. If you ever change the runner-defining options in
    ask_qwen_stream's payload, mirror them here too.

    Never raises. This is a pure optimization -- a failure here must
    never surface to the person; worst case, the next chat turn simply
    pays the normal load cost, exactly as it did before this existed.
    """
    generate_url = config.OLLAMA_API_URL.rsplit("/api/", 1)[0] + "/api/generate"
    payload = {
        "model": config.QWEN_TEXT_MODEL,
        "think": False,
        "keep_alive": "30m",
        "options": {"num_ctx": config.QWEN_NUM_CTX},
    }
    t0 = time.time()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(generate_url, json=payload) as resp:
                await resp.read()
        print(f" [PREWARM] {config.QWEN_TEXT_MODEL} warm-up triggered "
              f"({time.time() - t0:.2f}s)")
    except Exception as e:
        print(f" [PREWARM] Skipped -- {e}")


# =============================================================================
# CORE QUERY PROCESSING
# =============================================================================

def _trim_history():
    global chat_history
    if len(chat_history) > config.CHAT_HISTORY_LINES:
        chat_history = chat_history[-config.CHAT_HISTORY_LINES:]


def _log_llm_breakdown(llm_metrics: dict):
    """
    Prints the real load/prompt/generation split from Ollama's own
    numbers, instead of inferring it from wall-clock deltas around "time
    to first token". Empty dict (pre-emption before the "done" line
    arrived, or Ollama omitted the fields) prints a one-line note instead
    of silently omitting the log line.
    """
    if not llm_metrics:
        print(" [TIMER-BREAKDOWN] unavailable (pre-empted before completion, "
              "or Ollama didn't return timing fields)")
        return
    print(
        f" [TIMER-BREAKDOWN] model_load={llm_metrics.get('load_duration_s', 0):.2f}s  "
        f"prompt_eval={llm_metrics.get('prompt_eval_duration_s', 0):.2f}s "
        f"({llm_metrics.get('prompt_eval_count', 0)} tok)  "
        f"generation={llm_metrics.get('eval_duration_s', 0):.2f}s "
        f"({llm_metrics.get('eval_count', 0)} tok)  "
        f"ollama_total={llm_metrics.get('total_duration_s', 0):.2f}s"
    )
    # model_load answers "how long did it take to load the model into
    # memory" -- ~0.00s means the model was already resident; several
    # seconds means this call paid a cold-load or post-eviction reload.


async def process_brain_query(user_text, speaker_name, websocket, client_type="voice"):
    """
    Local-model (Qwen) query path. Always invoked through dispatch_query(),
    never directly -- that's what enforces the pre-empt policy.
    """
    global chat_history, _active_utt_id, _active_tts_task
    start_time = time.time()
    filler_task = None
    spoken_filler_task = None

    # 1. Fast heuristic route, LLM fallback only when it says "auto"
    route, optimized_query = smart_tools.route_query_heuristic(user_text)
    if route == "auto":
        router_t0 = time.time()
        recent_context = " ".join(chat_history[-2:]) if chat_history else "No previous context."
        route, optimized_query = await classify_context_with_llm(user_text, recent_context)
        print(f" [TIMER] Router LLM classification: {time.time() - router_t0:.2f}s")
    print(f" [ROUTER] -> {route.upper()}")

    external_context = ""
    if route == "finance":
        await websocket.send(json.dumps({"type": "filler", "text": "* Accessing financial markets... *"}))
        external_context = await asyncio.to_thread(smart_tools.get_live_stock, optimized_query)
    elif route == "weather":
        await websocket.send(json.dumps({"type": "filler", "text": "* Checking meteorological data... *"}))
        external_context = await asyncio.to_thread(smart_tools.get_live_weather, optimized_query)
    elif route == "news":
        await websocket.send(json.dumps({"type": "filler", "text": "* Scanning live headlines... *"}))
        external_context = await asyncio.to_thread(smart_tools.get_live_news, optimized_query)
    elif route == "vision":
        await _publish_led_state("thinking_vision")
        vision_t0 = time.time()
        external_context = await process_vision_query(user_text, websocket)
        print(f" [TIMER] Vision analysis: {time.time() - vision_t0:.2f}s")

        if not external_context.startswith("[SYSTEM ERROR]") \
                and not external_context.startswith("[SYSTEM: VISION]"):
            # SHORT-CIRCUIT: speak Qwen-VL's own description directly and
            # skip the text model's personality pass, so a vision reply
            # doesn't also pay the text model's own time-to-first-token
            # cost on top of the vision call. Revisit if the text model's
            # first-token latency drops enough that this stops earning
            # its keep -- [TIMER-BREAKDOWN] logging on every text-model
            # call makes that decision measurable rather than guessed.
            spoken_text = external_context.replace("[SYSTEM: LIVE VISION ANALYSIS] ", "", 1).strip()

            await websocket.send(json.dumps({"type": "stream_start"}))
            await websocket.send(json.dumps({"type": "stream_chunk", "text": spoken_text}))
            await websocket.send(json.dumps({"type": "stream_end"}))

            utt_id = uuid.uuid4().hex[:8]
            chunker = tts_engine.SentenceChunker()
            sentence_queue: asyncio.Queue = asyncio.Queue()
            tts_task = asyncio.create_task(
                _tts_utterance_worker(utt_id, sentence_queue, query_start_time=start_time,
                                      speaker_name=speaker_name, client_type=client_type)
            )
            _active_utt_id = utt_id
            _active_tts_task = tts_task
            for sentence in chunker.feed(spoken_text):
                await sentence_queue.put(sentence)
            trailing = chunker.flush()
            if trailing:
                await sentence_queue.put(trailing)
            await sentence_queue.put(None)

            if brain_memory:
                await asyncio.to_thread(brain_memory.add_memory, speaker_name, user_text, spoken_text)
            chat_history.append(f"{speaker_name}: {user_text}")
            chat_history.append(f"{ASSISTANT_NAME}: {spoken_text}")
            _trim_history()

            # Fired here, not awaited: the vision reply is already fully
            # sent at this point, so this races purely against the
            # person's own reaction time on their likely follow-up. See
            # _prewarm_text_model()'s docstring for the one-directional
            # reasoning and its known trade-off.
            asyncio.create_task(_prewarm_text_model())

            print(f" [{ASSISTANT_NAME.upper()}] (vision, direct): {spoken_text}")
            print(f" [TIMER] Total processing time: {time.time() - start_time:.2f}s")
            return
        # else: vision failed/unavailable -- fall through to the normal LLM
        # pipeline so the problem gets explained in the assistant's own
        # voice rather than surfacing a raw error string.

    # 2. Short-term conversation history
    history_context = ""
    if chat_history:
        history_context = "[SYSTEM: RECENT CONVERSATION LOG]\n" + "\n".join(chat_history) + "\n\n"

    # 3. Long-term FAISS memory (skipped when a tool route already answered)
    past_context = ""
    inventory_context = ""
    if brain_memory and route in ["auto", "local", "chat"]:
        recent_context = " ".join(chat_history[-2:]) if chat_history else "No previous context."
        smart_search_query = f"{recent_context} {speaker_name} says: {user_text}"

        await websocket.send(json.dumps({"type": "filler", "text": "* Scanning memory core... *"}))
        retrieved = await asyncio.to_thread(brain_memory.search_memory, smart_search_query)

        if retrieved:
            await websocket.send(json.dumps({
                "type": "filler",
                "text": f"* Found {len(retrieved)} relevant records. Analyzing... *",
            }))
            past_context = "\n[SYSTEM: RELEVANT PAST MEMORIES]\n" + "\n".join(retrieved) + "\n\n"

            known_docs = [
                f" - {e['filename']} (Context: {e.get('full_text', 'No summary available.')})"
                for e in brain_memory.memory_map.values()
                if isinstance(e, dict) and e.get("type") == "doc_summary" and "filename" in e
            ]
            if known_docs:
                inventory_context = (
                    "[SYSTEM INVENTORY: You hold the following uploaded files:\n"
                    + "\n".join(known_docs) + "]\n\n"
                )

    # 3b. Short-term vision continuity
    vision_recent_context = ""
    if route != "vision" and last_vision_summary["text"]:
        age = time.time() - last_vision_summary["timestamp"]
        if age < config.VISION_CONTEXT_TTL:
            vision_recent_context = (
                f"[SYSTEM: RECENT VISION CONTEXT — what you actually saw {int(age)}s ago, "
                f"still fresh]\n{last_vision_summary['text']}\n\n"
            )

    await websocket.send(json.dumps({"type": "filler", "text": "* Booting primary reasoning engine... *"}))
    await _publish_led_state("thinking_local")

    system_context = (
        f"{_language_directive()}{_date_context()}"
        f"{inventory_context}{past_context}{vision_recent_context}{history_context}\n{external_context}"
    )

    # 4. Stream: text to the browser immediately, audio to AUDIO_SINKS as
    #    sentence boundaries complete, so playback starts well before the
    #    full reply has finished generating.
    await websocket.send(json.dumps({"type": "stream_start"}))
    full_response = ""
    utt_id = uuid.uuid4().hex[:8]
    chunker = tts_engine.SentenceChunker()
    sentence_queue: asyncio.Queue = asyncio.Queue()
    tts_task = asyncio.create_task(
        _tts_utterance_worker(utt_id, sentence_queue, query_start_time=start_time,
                              speaker_name=speaker_name, client_type=client_type)
    )

    # Registered at task creation, not on first audio: a stop command must
    # be able to cancel this before any audio exists.
    _active_utt_id = utt_id
    _active_tts_task = tts_task

    if config.FILLER_ENABLED:
        filler_task = asyncio.create_task(
            _filler_heartbeat(websocket, LANG["fillers"], config.FILLER_INTERVAL)
        )

    # Spoken filler: voice clients only. A text client already sees the
    # heartbeat above and gets tokens streamed as they arrive, so it has no
    # dead air to fill -- speaking at it would just be noise.
    if config.SPOKEN_FILLERS and client_type == "voice" and LANG.get("spoken_fillers"):
        spoken_filler_task = asyncio.create_task(
            _spoken_filler(sentence_queue, LANG["spoken_fillers"],
                           config.SPOKEN_FILLER_DELAY)
        )

    llm_t0 = time.time()
    first_token_logged = False

    # Populated in place by ask_qwen_stream once Ollama's final "done"
    # line arrives -- see llm_engine.py. Stays {} if the query is
    # pre-empted before that line arrives.
    llm_metrics: dict = {}

    # Held as a named generator so it can be explicitly aclose()d. On
    # pre-emption the task is cancelled mid-`async for`; without the
    # explicit close, the aiohttp session inside ask_qwen_stream is only
    # released whenever the loop's async-generator finalizer gets round
    # to it, which leaks a connection per pre-empted query.
    stream = ask_qwen_stream(
        user_text=user_text, system_context=system_context, client_type=client_type,
        metrics=llm_metrics,
    )
    try:
        async for chunk in stream:
            if not first_token_logged:
                print(f" [TIMER] Time to first LLM token: {time.time() - llm_t0:.2f}s")
                first_token_logged = True
                if filler_task:
                    filler_task.cancel()
                    filler_task = None
                # Cancelled on the FIRST TOKEN, not on first audio: if the
                # model has started producing text there is no dead air
                # left to cover, and a filler queued now would delay the
                # real reply sitting behind it in the same queue.
                if spoken_filler_task:
                    spoken_filler_task.cancel()
                    spoken_filler_task = None
            full_response += chunk
            await websocket.send(json.dumps({"type": "stream_chunk", "text": chunk}))
            for sentence in chunker.feed(chunk):
                await sentence_queue.put(sentence)
    finally:
        if filler_task:
            filler_task.cancel()
        if spoken_filler_task:
            spoken_filler_task.cancel()
        await stream.aclose()

    print(f" [TIMER] LLM streaming complete: {time.time() - llm_t0:.2f}s")
    _log_llm_breakdown(llm_metrics)

    trailing = chunker.flush()
    if trailing:
        await sentence_queue.put(trailing)
    await sentence_queue.put(None)  # sentinel
    # Not awaited: synthesis/playback shouldn't hold up memory writes or
    # the next query. tts_task cleans itself up via its own finally.

    await websocket.send(json.dumps({"type": "stream_end"}))

    if brain_memory:
        await asyncio.to_thread(brain_memory.add_memory, speaker_name, user_text, full_response)

    chat_history.append(f"{speaker_name}: {user_text}")
    chat_history.append(f"{ASSISTANT_NAME}: {full_response}")
    _trim_history()

    print(f" [{ASSISTANT_NAME.upper()}]: {full_response}")
    print(f" [TIMER] Total processing time: {time.time() - start_time:.2f}s")


async def dispatch_query(user_text, speaker_name, websocket, client_type="voice"):
    """
    PRE-EMPT POLICY. Exactly one query may be in flight at a time; a new
    one cancels the old.

    Without this, a mic query landing during a browser query would leave
    two _tts_utterance_workers broadcasting to the same AUDIO_SINKS at
    once -- two voices interleaved on the Pi's single playback pipe --
    plus interleaved chat_history writes and a clobbered _active_utt_id.

    Cancellation order matters: cancel the QUERY task first (stops
    generation), then _stop_active_tts() (stops synthesis + playback).
    The tts worker is a separate task, so cancelling the query alone
    would leave it happily synthesizing the dead reply.
    """
    global _active_query_task

    prev = _active_query_task
    if prev and not prev.done():
        print(" [PRE-EMPT] New query arrived -- cancelling in-flight response.")
        prev.cancel()
        try:
            await prev
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f" [PRE-EMPT] Previous query ended with: {e}")
        await _stop_active_tts()
        # The pre-empted query never sent its stream_end. The browser
        # only re-enables the input box on stream_end, so without this
        # it stays locked forever. Harmless if that client wasn't the
        # one being pre-empted.
        try:
            await websocket.send(json.dumps({"type": "stream_end"}))
        except Exception:
            pass

    query_fn = process_uplink_query if _uplink_active else process_brain_query
    task = asyncio.create_task(
        query_fn(user_text, speaker_name, websocket, client_type=client_type)
    )
    _active_query_task = task
    try:
        await task
    except asyncio.CancelledError:
        # This task was pre-empted by a newer query. Note that catching
        # CancelledError from an AWAITED task does not cancel the
        # awaiting coroutine, so the connection loop continues normally.
        pass
    except websockets.exceptions.ConnectionClosed:
        raise
    except Exception as e:
        print(f" [!] Query failed: {e}")
        try:
            await websocket.send(json.dumps({"type": "stream_end"}))
        except Exception:
            pass
    finally:
        if _active_query_task is task:
            _active_query_task = None


# =============================================================================
# UPLINK SESSIONS (Claude)
# =============================================================================

async def _speak_system_line(websocket, text: str):
    """
    Speaks a short ZoMa Brain system announcement (uplink start/end)
    through the normal TTS pipeline. NOT written to chat_history or
    FAISS -- same convention as _spoken_filler()'s fillers: this is ZoMa
    Brain narrating its own state, not something said in character that
    should be recalled later.

    websocket can be stale here: _uplink_idle_task holds whatever
    connection was current when the timer was last (re)armed, but
    _uplink_active/_uplink_idle_task are module-level and survive a Pi
    mic reconnect by design -- if the mic reconnects with a new websocket
    while a session sits idle, the watchdog still fires against the old
    one. Caught here and NOT treated as fatal to the announcement: the
    actual spoken audio goes out over AUDIO_SINKS (a separate
    registration), independent of this specific text-stream websocket,
    so a stale mic-side connection shouldn't silence a still-good audio
    sink.
    """
    global _active_utt_id, _active_tts_task

    try:
        await websocket.send(json.dumps({"type": "stream_start"}))
        await websocket.send(json.dumps({"type": "stream_chunk", "text": text}))
        await websocket.send(json.dumps({"type": "stream_end"}))
    except websockets.exceptions.ConnectionClosed:
        print(f" [UPLINK] Text-stream send failed for ({text!r}) -- stale connection; "
              f"still speaking via AUDIO_SINKS.")

    utt_id = uuid.uuid4().hex[:8]
    sentence_queue: asyncio.Queue = asyncio.Queue()
    tts_task = asyncio.create_task(_tts_utterance_worker(utt_id, sentence_queue))
    _active_utt_id = utt_id
    _active_tts_task = tts_task
    await sentence_queue.put(text)
    await sentence_queue.put(None)


# =============================================================================
# VOLUME (Pi speaker)
# =============================================================================

async def _apply_volume_delta(websocket, direction: str):
    """
    direction: "up" or "down", already resolved by
    smart_tools.detect_volume_command() at the call site. Sends the
    volume step to the Pi over the existing AUDIO_SINKS connection and
    speaks a fixed confirmation over the same TTS pipeline everything
    else uses -- no LLM call, no new mechanism.
    """
    percent = config.VOLUME_STEP_PERCENT if direction == "up" else -config.VOLUME_STEP_PERCENT
    await _broadcast_sinks(pi_commands.volume_delta_message(percent))
    await _speak_system_line(
        websocket, "Volume increased." if direction == "up" else "Volume decreased."
    )


# =============================================================================
# PHOTO CAPTURE ("take a picture" voice command, see smart_tools.detect_
# photo_command() and config.py's PHOTO CAPTURE section)
# =============================================================================

_shutter_audio_cache: bytes | None = None

# See _take_photo()'s use of this -- how long to hold the LED flash back
# so it lands closer to when the shutter click actually becomes audible.
PHOTO_FLASH_SYNC_DELAY_S = 0.1


def _load_shutter_audio() -> bytes:
    """
    Loads + resamples config.SHUTTER_SOUND_FILE ONCE to S16LE mono 16kHz
    -- the exact format tts_engine.synthesize() already produces -- so
    the shutter click flows through AUDIO_SINKS as just another
    utterance's audio, no protocol change needed on the Pi side. Cached
    after the first call, since this is a fixed asset on disk. Returns
    b"" (never raises) on any failure -- callers already treat empty
    audio as "nothing to play", same as tts_engine.synthesize()'s own
    empty-string convention.

    Uses torchaudio.functional.resample rather than a hand-rolled
    rational resampler: the shutter sample's rate doesn't reduce to a
    clean small integer ratio against 16kHz the way 24kHz does, so a
    general-purpose resampler is the right tool here. torchaudio is
    already a dependency (speaker ID uses it -- see load_audio_mono()
    above), so this reuses it rather than adding another library for one
    call.
    """
    global _shutter_audio_cache
    if _shutter_audio_cache is not None:
        return _shutter_audio_cache

    path = config.SHUTTER_SOUND_FILE
    if not os.path.exists(path):
        print(f" [PHOTO] Shutter sound file not found, skipping: {path}")
        _shutter_audio_cache = b""
        return _shutter_audio_cache

    try:
        with wave.open(path, "rb") as wf:
            rate, width, channels = wf.getframerate(), wf.getsampwidth(), wf.getnchannels()
            raw = wf.readframes(wf.getnframes())
        if width != 2:
            print(f" [PHOTO] Unsupported shutter sound sample width: "
                  f"{width * 8}-bit (need 16-bit) -- {path}")
            _shutter_audio_cache = b""
            return _shutter_audio_cache

        pcm = np.frombuffer(raw, dtype=np.int16)
        if channels > 1:
            pcm = pcm.reshape(-1, channels).mean(axis=1).astype(np.int16)
        if rate != 16000:
            tensor = torchaudio.functional.resample(
                torch.from_numpy(pcm.astype(np.float32)), rate, 16000
            )
            pcm = tensor.numpy().astype(np.int16)
        _shutter_audio_cache = pcm.tobytes()
    except Exception as e:
        print(f" [PHOTO] Failed to load/resample shutter sound ({path}): {e}")
        _shutter_audio_cache = b""

    return _shutter_audio_cache


async def _play_sound_worker(utt_id: str, audio: bytes):
    """
    Plays one pre-rendered PCM blob (S16LE mono 16kHz) through
    AUDIO_SINKS. Reuses the exact tts_start/tts_chunk/tts_end wire
    messages AND the same _active_utt_id/mic-gate-release timing math as
    _tts_utterance_worker's finally block, rather than a bespoke send --
    a raw sound effect (the shutter click) needs the same barge-in/
    mic-gate behavior a spoken reply gets, not a side channel that
    bypasses that machinery. No sentence queue/synthesis step here -- the
    audio is already fully rendered by the caller (_load_shutter_audio()).
    """
    global _active_utt_id, _active_tts_task
    if not audio or not AUDIO_SINKS:
        return

    cancelled = False
    playback_start_time = time.time()
    try:
        await _broadcast_sinks(json.dumps({
            "type": "tts_start", "utt": utt_id, "rate": 16000, "fmt": "s16le_mono",
        }))
        await _broadcast_sinks(json.dumps({"type": "tts_chunk", "utt": utt_id, "seq": 0}))
        await _broadcast_sinks(audio)
    except asyncio.CancelledError:
        cancelled = True
        raise
    finally:
        if not cancelled:
            await _broadcast_sinks(json.dumps({"type": "tts_end", "utt": utt_id}))

            # Same mic-gate release math as _tts_utterance_worker's
            # finally block -- see that docstring for why this is
            # computed from bytes sent rather than guessed.
            BYTES_PER_SECOND = 2 * 16000  # 16-bit mono, 16kHz
            total_duration_s = len(audio) / BYTES_PER_SECOND
            elapsed = time.time() - playback_start_time
            SAFETY_MARGIN_S = 0.6
            remaining = total_duration_s - elapsed + SAFETY_MARGIN_S
            if remaining > 0:
                try:
                    await asyncio.sleep(remaining)
                except asyncio.CancelledError:
                    raise
            if _active_utt_id == utt_id:
                _active_utt_id = None
                _active_tts_task = None
                _led_state, _led_duration = _listening_state_and_duration()
                await _publish_led_state(_led_state, duration=_led_duration)


async def _play_shutter_sound():
    """Fires the camera-shutter click over AUDIO_SINKS. See _play_sound_
    worker()'s docstring for why this goes through the same utt-id/
    mic-gate lifecycle as a spoken reply instead of a bespoke send."""
    global _active_utt_id, _active_tts_task
    audio = _load_shutter_audio()
    if not audio or not AUDIO_SINKS:
        return
    utt_id = uuid.uuid4().hex[:8]
    task = asyncio.create_task(_play_sound_worker(utt_id, audio))
    _active_utt_id = utt_id
    _active_tts_task = task


async def _take_photo(websocket):
    """
    Handles a "take a picture" command: flash the ring + play the
    shutter click, then save the freshest already-decoded camera frame
    to disk.

    Captures from vision_stream -- the same live RTSP decode process_
    vision_query()/uplink snapshots already read from -- rather than
    asking the Pi to run a separate still-capture command: the Pi's
    camera library opens the camera exclusively, so there is no safe
    way to run a second still-capture path while the RTSP feed is live.

    Frame availability is checked BEFORE flashing/clicking on purpose --
    a flash+click for a photo that didn't actually get captured would be
    a false confirmation.
    """
    if vision_stream is None or not vision_stream.is_alive():
        await _speak_system_line(websocket, "The camera feed isn't available right now.")
        return

    frame = vision_stream.get_latest_frame(max_age=config.ZOMA_FRAME_MAX_AGE)
    if frame is None:
        await _speak_system_line(websocket, "No fresh camera frame is available right now.")
        return

    # Shutter sound fires first, flash delayed a beat behind it: the
    # audio path has more latency between "sent" and "audible" than the
    # LED path does, so sending both at once puts the flash visibly ahead
    # of the click. PHOTO_FLASH_SYNC_DELAY_S is a rough estimate of that
    # gap -- retune if it looks off on real hardware.
    await _play_shutter_sound()
    await asyncio.sleep(PHOTO_FLASH_SYNC_DELAY_S)
    await _publish_led_state("photo_capture")

    os.makedirs(config.PICTURES_DIR, exist_ok=True)
    filename = f"ZoMa_picture_{datetime.now().strftime('%y%m%d%H%M%S')}.jpg"
    path = os.path.join(config.PICTURES_DIR, filename)
    ok = await asyncio.to_thread(vision_engine.save_frame_jpeg, frame, path)
    if ok:
        print(f" [PHOTO] Saved {path}")
    else:
        await _speak_system_line(websocket, "Something went wrong saving the photo.")


async def _uplink_idle_watchdog(websocket):
    """
    Started/reset on every accepted uplink turn (see _reset_uplink_idle_
    timer()). If nothing is heard for config.UPLINK_IDLE_TIMEOUT_SECONDS,
    ends the session itself and announces it -- unlike the ordinary
    follow-up window (which just silently starts requiring the wake word
    again), an uplink session is a deliberate, higher-stakes mode switch
    (routes to a paid external API), so it doesn't lapse quietly.
    """
    try:
        await asyncio.sleep(config.UPLINK_IDLE_TIMEOUT_SECONDS)
        print(" [UPLINK] Idle timeout -- ending session.")
        await _end_uplink_session(websocket, reason="idle_timeout")
    except asyncio.CancelledError:
        return


def _reset_uplink_idle_timer(websocket):
    global _uplink_idle_task
    if _uplink_idle_task and not _uplink_idle_task.done():
        _uplink_idle_task.cancel()
    _uplink_idle_task = asyncio.create_task(_uplink_idle_watchdog(websocket))


async def _start_uplink_session(websocket):
    global _uplink_active
    await _stop_active_tts()
    _uplink_active = True
    print(f" [UPLINK] Session started -- hands-free until an end phrase or "
          f"{config.UPLINK_IDLE_TIMEOUT_SECONDS:.0f}s of silence.")
    await _publish_led_state("uplink_listening")
    await _speak_system_line(websocket, "Uplink established.")
    _reset_uplink_idle_timer(websocket)


async def _end_uplink_session(websocket, reason: str):
    global _uplink_active, _uplink_idle_task
    await _stop_active_tts()
    _uplink_active = False
    if _uplink_idle_task and not _uplink_idle_task.done():
        _uplink_idle_task.cancel()
    _uplink_idle_task = None
    print(f" [UPLINK] Session ended ({reason}).")
    ack = "Uplink ended." if reason == "requested" else "Uplink ended. No activity, back to normal."
    await _speak_system_line(websocket, ack)


async def process_uplink_query(user_text, speaker_name, websocket, client_type="voice"):
    """
    Uplink counterpart to process_brain_query(): every turn goes to
    Claude (claude_engine.ask_claude_stream), never through smart_tools.
    route_query_heuristic -- weather/finance/news tool calls don't fire
    while an uplink session is active. Vision stays available: if the
    transcript looks like a snapshot/vision request, the latest camera
    frame is attached to the SAME Claude call (Claude is natively
    multimodal), answered in-character in one shot rather than
    llm_engine/vision_engine's separate describe-then-personality split.

    Context passed to Claude is the same full assembly
    process_brain_query gives Qwen (FAISS long-term recall, doc
    inventory, short-term history, vision summary) -- no restricted
    "session-only" tier.

    Always invoked through dispatch_query() -> never directly, same as
    process_brain_query -- that's what enforces the pre-empt policy.
    """
    global chat_history, _active_utt_id, _active_tts_task
    start_time = time.time()

    _reset_uplink_idle_timer(websocket)

    frame = None
    if smart_tools.is_vision_request(user_text):
        if vision_stream is not None and vision_stream.is_alive():
            frame = vision_stream.get_latest_frame(max_age=config.ZOMA_FRAME_MAX_AGE)
        if frame is None:
            print(" [UPLINK] Vision request but no fresh frame available -- continuing text-only.")

    await _publish_led_state("thinking_uplink")

    # 1. Short-term conversation history (unchanged from process_brain_query)
    history_context = ""
    if chat_history:
        history_context = "[SYSTEM: RECENT CONVERSATION LOG]\n" + "\n".join(chat_history) + "\n\n"

    # 2. Long-term FAISS memory + doc inventory -- OFF by default for now
    #    (config.UPLINK_MEMORY_ENABLED). See config.py for the flag;
    #    short-term chat_history above is unaffected.
    past_context = ""
    inventory_context = ""
    if brain_memory and config.UPLINK_MEMORY_ENABLED:
        recent_context = " ".join(chat_history[-2:]) if chat_history else "No previous context."
        smart_search_query = f"{recent_context} {speaker_name} says: {user_text}"
        retrieved = await asyncio.to_thread(
            brain_memory.search_memory, smart_search_query, top_k=config.UPLINK_MEMORY_TOP_K
        )
        if retrieved:
            past_context = "\n[SYSTEM: RELEVANT PAST MEMORIES]\n" + "\n".join(retrieved) + "\n\n"
            known_docs = [
                f" - {e['filename']} (Context: {e.get('full_text', 'No summary available.')})"
                for e in brain_memory.memory_map.values()
                if isinstance(e, dict) and e.get("type") == "doc_summary" and "filename" in e
            ]
            if known_docs:
                inventory_context = (
                    "[SYSTEM INVENTORY: You hold the following uploaded files:\n"
                    + "\n".join(known_docs) + "]\n\n"
                )

    # 3. Short-term vision continuity -- only when THIS turn isn't itself
    #    attaching a fresh frame (mirrors process_brain_query's route != "vision" guard).
    vision_recent_context = ""
    if frame is None and last_vision_summary["text"]:
        age = time.time() - last_vision_summary["timestamp"]
        if age < config.VISION_CONTEXT_TTL:
            vision_recent_context = (
                f"[SYSTEM: RECENT VISION CONTEXT — what you actually saw {int(age)}s ago, "
                f"still fresh]\n{last_vision_summary['text']}\n\n"
            )

    system_context = (
        f"{_language_directive()}{_date_context()}"
        f"{inventory_context}{past_context}{vision_recent_context}{history_context}"
    )

    await websocket.send(json.dumps({"type": "stream_start"}))
    full_response = ""
    utt_id = uuid.uuid4().hex[:8]
    chunker = tts_engine.SentenceChunker()
    sentence_queue: asyncio.Queue = asyncio.Queue()
    tts_task = asyncio.create_task(
        _tts_utterance_worker(utt_id, sentence_queue, query_start_time=start_time, source="claude",
                              speaker_name=speaker_name, client_type=client_type)
    )
    _active_utt_id = utt_id
    _active_tts_task = tts_task

    # Web search (see claude_engine.py) can turn a quick reply into a
    # much longer one. Without a filler that silence reads as "stuck",
    # not "thinking" -- same reasoning process_brain_query already has
    # these for, just more important here given the added latency.
    filler_task = None
    if config.FILLER_ENABLED:
        filler_task = asyncio.create_task(
            _filler_heartbeat(websocket, LANG["fillers"], config.FILLER_INTERVAL)
        )
    spoken_filler_task = None
    if config.SPOKEN_FILLERS and client_type == "voice" and LANG.get("spoken_fillers"):
        spoken_filler_task = asyncio.create_task(
            _spoken_filler(sentence_queue, LANG["spoken_fillers"], config.SPOKEN_FILLER_DELAY)
        )

    llm_metrics: dict = {}
    first_chunk = True
    web_search = smart_tools.is_web_search_request(user_text)
    stream = claude_engine.ask_claude_stream(
        user_text=user_text, system_context=system_context, client_type=client_type,
        metrics=llm_metrics, frame=frame, web_search=web_search, speaker_name=speaker_name,
    )
    try:
        async for chunk in stream:
            if first_chunk:
                first_chunk = False
                if filler_task:
                    filler_task.cancel()
                    filler_task = None
                if spoken_filler_task:
                    spoken_filler_task.cancel()
                    spoken_filler_task = None
            full_response += chunk
            await websocket.send(json.dumps({"type": "stream_chunk", "text": chunk}))
            for sentence in chunker.feed(chunk):
                await sentence_queue.put(sentence)
    finally:
        if filler_task:
            filler_task.cancel()
        if spoken_filler_task:
            spoken_filler_task.cancel()
        await stream.aclose()

    print(f" [TIMER] Uplink (Claude) streaming complete: {time.time() - start_time:.2f}s")
    if llm_metrics:
        print(f" [TIMER-BREAKDOWN] uplink total={llm_metrics.get('total_duration_s', 0):.2f}s  "
              f"input_tokens={llm_metrics.get('input_tokens', '?')}  "
              f"output_tokens={llm_metrics.get('output_tokens', '?')}")

    trailing = chunker.flush()
    if trailing:
        await sentence_queue.put(trailing)
    await sentence_queue.put(None)  # sentinel

    await websocket.send(json.dumps({"type": "stream_end"}))

    if brain_memory:
        await asyncio.to_thread(
            brain_memory.add_memory, speaker_name, user_text, full_response,
            source="claude", responder_name="Claude",
        )
        if frame is not None:
            await asyncio.to_thread(
                brain_memory.add_vision_event, full_response,
                trigger_reason="uplink_snapshot", source="claude",
            )

    # "Claude", not ASSISTANT_NAME (the local persona's identity belongs
    # to the local model only) -- this log line is what both models read
    # back as recent history on their next turn, so misattributing it
    # here would have the local model "remember" saying something Claude
    # actually said.
    chat_history.append(f"{speaker_name}: {user_text}")
    chat_history.append(f"Claude: {full_response}")
    _trim_history()

    if frame is not None:
        last_vision_summary["text"] = full_response
        last_vision_summary["timestamp"] = time.time()

    # The idle timer is reset again here, once the reply is actually
    # ready, not just at turn acceptance -- a slow uplink turn (e.g. a
    # web search) can burn most of the idle budget before the reply even
    # starts speaking, so the 60s "silence" clock should start from when
    # the person could realistically reply, not from when they asked.
    if _uplink_active:
        _reset_uplink_idle_timer(websocket)

    print(f" [CLAUDE] (uplink): {full_response}")
    print(f" [TIMER] Total uplink processing time: {time.time() - start_time:.2f}s")


# =============================================================================
# AUDIO HELPERS
# =============================================================================

def _has_trailing_silence(buf: bytearray, rate: int, ms: int, rms_threshold: float) -> bool:
    """
    Whether the most recent `ms` milliseconds are quiet -- i.e. the
    speaker just paused. Only looks at the tail, so cost is constant
    regardless of how long the buffer has grown.
    """
    n_bytes = int(rate * (ms / 1000) * 2)  # 2 bytes per int16 sample
    n_bytes -= n_bytes % 2
    if len(buf) < n_bytes or n_bytes == 0:
        return False
    tail = np.frombuffer(bytes(buf[-n_bytes:]), dtype=np.int16)
    if tail.size == 0:
        return False
    rms = float(np.sqrt(np.mean(tail.astype(np.float64) ** 2)))
    return rms < rms_threshold


def _chunk_rms(message: bytes) -> float:
    """
    RMS of a raw PCM chunk, safe against odd byte counts:
    np.frombuffer(..., dtype=np.int16) raises on an odd-length buffer,
    and np.mean on an empty array warns and returns NaN, so both are
    guarded explicitly here rather than left to a generic exception
    handler upstream.
    """
    n = len(message) - (len(message) % 2)
    if n < 2:
        return 0.0
    samples = np.frombuffer(message[:n], dtype=np.int16)
    if samples.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))


# =============================================================================
# WAKE WORD
# =============================================================================

def strip_wake_word(text: str, min_similarity: float = None) -> str | None:
    """
    Searches EVERY word in the transcript for a fuzzy match against the
    configured wake word -- not anchored to the first word. Removes that
    one word and returns the rest (words before AND after, rejoined).

    Deliberately unbounded rather than restricted to the first few words,
    so "Hello Clorian, what's up" and "Clorian, hello" both work. Trade-
    off, stated plainly: the wake word appearing anywhere in a longer
    sentence -- including someone merely relaying what the assistant said
    earlier -- will trigger a command. Accepted for a single-user home
    device where false triggers are cheap; reconsider for a shared
    setting.

    Fuzzy rather than exact substring: a clearly-spoken wake word can
    come back from Whisper with a single phonetically-plausible letter
    substitution that an exact match would silently discard.

    THRESHOLD WARNING: difflib ratios are length-sensitive. A 7-letter
    wake word does not behave like a 6-letter one, and a short wake word
    will collide with far more ordinary vocabulary. After renaming, test
    against real transcripts and retune config.WAKE_WORD_SIMILARITY.
    """
    if min_similarity is None:
        min_similarity = config.WAKE_WORD_SIMILARITY

    t = text.strip()
    if not t:
        return None

    words = t.split()
    for i, word in enumerate(words):
        candidate = word.strip(" ,.:;-!?").lower()
        if not candidate:
            continue
        similarity = difflib.SequenceMatcher(None, candidate, WAKE_WORD).ratio()
        if similarity >= min_similarity:
            remaining = words[:i] + words[i + 1:]
            command = " ".join(remaining).strip(" ,.:;-")
            return command or None

    return None


# =============================================================================
# FOLLOW-UP CONVERSATION WINDOW
# =============================================================================

# Module-level, deliberately NOT per-connection. The Pi's mic client
# reconnects periodically in normal operation, and per-connection state
# would be wiped each time -- a follow-up would stop working precisely
# because the mic blipped, which is invisible to the person and
# impossible to reason about.
_conversation = {"expires_at": 0.0, "participants": {}}

# Classes of Whisper invention seen when the room is quiet (e.g. a
# transcript inventing a URL or a "subscribe" phrase from noise).
# Harmless under wake-word gating; would become real queries once the
# follow-up window is open, hence guarded here too.
_HALLUCINATION_RE = re.compile(
    r"(www\.|https?://|\.com\b|\.org\b|subtitle|amara\.org|subscribe|"
    r"thanks for watching)", re.IGNORECASE
)


def _conversation_open() -> bool:
    return time.time() < _conversation["expires_at"]


def _open_or_refresh_conversation(speaker_name: str):
    """
    Called on every ACCEPTED turn, wake-word or follow-up alike, so the
    window slides forward for as long as the conversation is actually alive
    rather than expiring mid-exchange.
    """
    now = time.time()
    if not _conversation_open():
        # Lapsed since last time: this is a brand-new conversation, so the
        # old participant list must not carry over. Otherwise someone
        # identified an hour ago could still follow up without the wake word.
        _conversation["participants"] = {}
    if speaker_name and speaker_name != "UNKNOWN":
        _conversation["participants"][speaker_name] = now
    _conversation["expires_at"] = now + config.FOLLOWUP_WINDOW_SECONDS


def _close_conversation():
    """
    Hard reset: "stop" means stop, full stop -- not "keep listening a
    little longer." Called immediately BEFORE _stop_active_tts() by
    every genuine hard-stop trigger (a loud barge-in, a transcribed
    "stop"/"quiet"/etc., with or without the wake word) -- BEFORE, not
    after, because _stop_active_tts() itself computes and publishes the
    next LED state from the current conversation/follow-up-window state;
    closing it afterward would leave the ring showing a stale "listening"
    state a beat past the reset it was supposed to reflect. Not called
    from inside _stop_active_tts() itself -- that function is also used
    for plain pre-emption (a new query cutting off an old one) and uplink
    session start/end, neither of which should force the wake word again.
    """
    _conversation["expires_at"] = 0.0
    _conversation["participants"] = {}


def _may_follow_up(speaker_name: str) -> bool:
    """Whether this speaker may be heard right now WITHOUT the wake word."""
    if not _conversation_open():
        return False
    if not config.FOLLOWUP_REQUIRE_KNOWN_SPEAKER:
        return True
    return speaker_name in _conversation["participants"]


def _plausible_followup(text: str, avg_logprob: float, no_speech_prob: float) -> bool:
    """
    Cheap sanity checks applied ONLY to wake-word-less follow-ups. A
    wake-word turn skips all of this -- matching the wake word is already
    far stronger evidence than any of these signals.
    """
    if len(text.split()) < config.FOLLOWUP_MIN_WORDS:
        return False
    if _HALLUCINATION_RE.search(text):
        return False
    if text.strip(" ,.:;-!?").lower() in HALLUC_PHRASES:
        return False
    if avg_logprob < config.FOLLOWUP_MIN_AVG_LOGPROB:
        return False
    if no_speech_prob > config.FOLLOWUP_MAX_NO_SPEECH:
        return False
    return True


# =============================================================================
# TRANSCRIPTION
# =============================================================================

def _transcribe_blocking(audio_np, beam_size: int, initial_prompt: str):
    """
    Runs ENTIRELY inside a worker thread, including the generator drain.

    faster_whisper's transcribe() returns a LAZY GENERATOR: iterating it
    is where the actual GPU decode happens, so the generator must be
    drained here, inside the thread, not by the caller after
    asyncio.to_thread returns -- otherwise the decode would run back on
    the event loop.
    """
    segments, info = whisper_model.transcribe(
        audio_np,
        initial_prompt=initial_prompt,
        beam_size=beam_size,
        vad_filter=True,
    )
    # Materialize once: the generator can only be consumed a single time,
    # and the confidence fields below live on the segments themselves.
    segs = list(segments)
    text = " ".join(s.text.strip() for s in segs).strip()

    # Whisper's own confidence, needed by the follow-up window, where
    # there's no wake word left to filter out invented transcripts.
    # avg_logprob is averaged across segments; no_speech_prob takes the
    # WORST (max) segment, since one clearly non-speech segment is enough
    # to distrust the whole utterance.
    if segs:
        avg_logprob = sum(s.avg_logprob for s in segs) / len(segs)
        no_speech_prob = max(s.no_speech_prob for s in segs)
    else:
        avg_logprob, no_speech_prob = 0.0, 1.0

    return text, (info.language or "??").upper(), avg_logprob, no_speech_prob


async def _transcribe_and_route(audio_buffer: bytearray, websocket,
                                requires_wake_word: bool, mic_capture_rate: int):
    """
    Shared by two trigger mechanisms: the browser's push-to-talk
    (triggered by a silence GAP -- the TimeoutError branch below) and the
    Pi's always-on mic (triggered by detected trailing silence in the
    audio itself, since a continuous stream never produces a gap). Both
    need identical transcribe -> gate -> route logic; only the trigger
    differs.

    mic_capture_rate is accepted for parity with the caller's connection
    state (and stays meaningful for _has_trailing_silence's buffer-size
    math upstream). Both the browser and the Pi's mic capture natively at
    16kHz, Whisper's own rate, so no server-side rate conversion happens
    here.
    """
    if len(audio_buffer) == 0 or not model_ready:
        return

    n = len(audio_buffer) - (len(audio_buffer) % 2)
    if n < 2:
        return
    audio_int16 = np.frombuffer(bytes(audio_buffer[:n]), dtype=np.int16)
    if audio_int16.size == 0:
        return
    audio_np = audio_int16.astype(np.float32) / 32768.0

    user_text, detected_lang, avg_logprob, no_speech_prob = await asyncio.to_thread(
        _transcribe_blocking, audio_np, args.beam_size, RT["stt_prompt"]
    )
    if not user_text:
        return

    # pyannote embedding forward pass -- synchronous and blocking. With
    # an always-on mic this fires every few seconds, so it's kept off the
    # event loop like the transcription call above.
    speaker_name = await asyncio.to_thread(identify_speaker, audio_np)

    via_followup = False

    # Uplink sessions are hands-free for their duration: an always-on Pi
    # mic connection stops needing the wake word the moment a session is
    # active, the same way the follow-up window already relaxes it --
    # just with no fixed window to expire out from under an active
    # exchange (the idle watchdog handles that instead; see
    # _uplink_idle_watchdog()). Reuses the same noise/hallucination guard
    # normal wake-word-less follow-ups get, since there's no wake word at
    # all here to act as a strong filter, and every accepted turn now
    # costs a real, paid Claude API call.
    if requires_wake_word and _uplink_active:
        if not _plausible_followup(user_text, avg_logprob, no_speech_prob):
            print(f" [UPLINK] Rejected as likely noise/hallucination: {user_text!r} "
                  f"(logprob={avg_logprob:.2f}, no_speech={no_speech_prob:.2f})")
            return
        print(f" [UPLINK] Accepted hands-free (speaker={speaker_name})")

    elif requires_wake_word:
        print(f" [DEBUG-WAKE] Raw transcript: {user_text!r}")
        command = strip_wake_word(user_text)

        if command is None:
            # Second pass with a much looser wake-word bar, acted on ONLY
            # if what follows is itself a recognized stop command. A
            # marginal wake-word match plus an unrelated phrase still
            # triggers nothing; a marginal match plus "stop" is very
            # likely a real interrupt the strict threshold wrongly
            # rejected, and a missed interrupt costs far more than a
            # false one.
            lenient = strip_wake_word(user_text, min_similarity=config.WAKE_WORD_SIMILARITY_LENIENT)
            if lenient is not None and lenient.lower().strip() in SILENCE_COMMANDS:
                command = lenient

        if command is None:
            # No wake word. Still allowed IF a conversation is currently
            # open and this speaker is entitled to continue it -- that's
            # the whole point of the window: not having to say the name
            # again for every follow-up.
            if not _may_follow_up(speaker_name):
                return
            if not _plausible_followup(user_text, avg_logprob, no_speech_prob):
                print(f" [FOLLOWUP] Rejected as likely noise/hallucination: "
                      f"{user_text!r} (logprob={avg_logprob:.2f}, "
                      f"no_speech={no_speech_prob:.2f})")
                return
            via_followup = True
            remaining = int(_conversation["expires_at"] - time.time())
            # Confidence values logged on ACCEPT as well as reject, on
            # purpose: seeing the numbers for utterances known to be real
            # speech is the only reliable way to tune FOLLOWUP_MIN_AVG_
            # LOGPROB / FOLLOWUP_MAX_NO_SPEECH against a specific mic/room
            # rather than guessing.
            print(f" [FOLLOWUP] Accepted without wake word "
                  f"({remaining}s left, speaker={speaker_name}, "
                  f"logprob={avg_logprob:.2f}, no_speech={no_speech_prob:.2f})")
        else:
            user_text = command

        # Refreshed for BOTH paths, and only after the turn is accepted:
        # every real exchange slides the window forward, so a conversation
        # never expires out from under an active back-and-forth.
        _open_or_refresh_conversation(speaker_name)

    tag = "FOLLOWUP" if via_followup else detected_lang
    print(f"\n [{speaker_name}]-[{tag}]: {user_text}")

    uplink_cmd = smart_tools.detect_uplink_command(user_text)
    if uplink_cmd == "start" and not _uplink_active:
        await _start_uplink_session(websocket)
        return
    if uplink_cmd == "end" and _uplink_active:
        await _end_uplink_session(websocket, reason="requested")
        return

    volume_cmd = smart_tools.detect_volume_command(user_text)
    if volume_cmd:
        await _apply_volume_delta(websocket, volume_cmd)
        return

    if smart_tools.detect_photo_command(user_text):
        await _take_photo(websocket)
        return

    if user_text.lower().strip() in SILENCE_COMMANDS:
        _close_conversation()
        await _stop_active_tts()
    else:
        await dispatch_query(user_text, speaker_name, websocket, client_type="voice")


# =============================================================================
# CONNECTION HANDLER
# =============================================================================

async def handle_connection(websocket):
    print(" [DEBUG] Connection attempt received!")
    await websocket.send(json.dumps({
        "type": "identity",
        "name": config.PRIMARY_USER_NAME,
        "assistant": ASSISTANT_NAME,
        "language": RT["lang_key"],
    }))

    audio_buffer = bytearray()
    sink_keepalive_task = None

    # Only the always-on Pi mic connection sets this True. Browser voice
    # stays push-to-talk, which already implies "this is addressed to the
    # assistant" -- a wake word there would just be annoying.
    requires_wake_word = False

    # Both browser voice and the Pi's mic capture at 16kHz -- Whisper's
    # native rate -- directly, so no server-side rate conversion is
    # needed either way. mic_capture_rate is kept as an explicit
    # per-connection flag (set from config.MIC_CAPTURE_RATE for the Pi
    # below) rather than a hardcoded constant, in case a future mic ever
    # needs a different native rate -- it still feeds
    # _has_trailing_silence's buffer math either way.
    mic_capture_rate = 16000

    # Flushing on detected TRAILING SILENCE keeps a whole utterance
    # together regardless of how long it takes to say, unlike a fixed
    # flush interval, which would cut sentences in half mid-utterance.
    # MIC_FLUSH_MAX_INTERVAL remains a safety net only.
    last_mic_flush = time.time()

    print(f"[*] {ASSISTANT_NAME} ready for audio and text queries "
          f"({LANG['label']}, wake word '{WAKE_WORD}')...")

    try:
        while True:
            try:
                message = await asyncio.wait_for(websocket.recv(), timeout=0.8)

                if isinstance(message, bytes):
                    if requires_wake_word and (
                        _active_utt_id is not None or time.time() < _mic_mute_until
                    ):
                        # ZoMa has a query in flight or is actively
                        # speaking. The mic's own echo cancellation does
                        # not fully cancel its own TTS bleeding back into
                        # the mic, so fragments of the assistant's own
                        # reply can otherwise get transcribed and even
                        # accepted as a genuine follow-up command -- a
                        # self-triggering feedback loop, not the user
                        # being heard.
                        #
                        # Anything below the barge-in threshold here is
                        # almost certainly that echo (or, briefly, the
                        # thinking gap before audio starts), not a real
                        # command -- drop it rather than accumulating it
                        # into audio_buffer, where the trailing-silence
                        # flush logic below would eventually hand it to
                        # Whisper. A genuine interrupt still works: it's
                        # loud enough to cross BARGE_IN_RMS_THRESHOLD, which
                        # is checked on every chunk regardless.
                        rms = _chunk_rms(message)
                        if rms > config.BARGE_IN_RMS_THRESHOLD:
                            print(f" [BARGE-IN] Loud sound during playback (RMS={rms:.0f}) -- stopping.")
                            # Brief flash first, on its own overlay
                            # "flash" source so it isn't immediately
                            # clobbered by _stop_active_tts()'s own
                            # trailing listening/idle_wake_word push a
                            # few lines below -- the two land on
                            # different sources and don't race.
                            await _publish_led_state("barge_in")
                            # "Stop" is a hard reset, not an invitation to
                            # keep listening: this path is pure RMS on raw
                            # bytes (no transcription, no speaker-ID), so it
                            # can't tell you continuing from background
                            # noise or someone else talking. Close the
                            # follow-up window rather than open/extend it --
                            # whatever comes next needs the wake word again,
                            # regardless of source. Closed BEFORE
                            # _stop_active_tts() so ITS trailing LED publish
                            # already reflects the closed window, not a
                            # stale still-open one.
                            _close_conversation()
                            await _stop_active_tts()
                        elif rms > 500:
                            # Diagnostic only: shows what's getting gated
                            # (residual echo vs. a spoken interrupt that
                            # isn't loud enough) to help retune
                            # BARGE_IN_RMS_THRESHOLD against real numbers.
                            print(f" [GATED] Dropped mic chunk during playback (RMS={rms:.0f}, "
                                  f"threshold={config.BARGE_IN_RMS_THRESHOLD:.0f})")
                        audio_buffer.clear()
                        last_mic_flush = time.time()

                    else:
                        audio_buffer.extend(message)

                        if requires_wake_word:
                            elapsed = time.time() - last_mic_flush
                            min_buffered = len(audio_buffer) >= int(
                                mic_capture_rate * config.MIC_MIN_BUFFERED_SECONDS * 2
                            )
                            paused = min_buffered and _has_trailing_silence(
                                audio_buffer, mic_capture_rate,
                                config.MIC_TRAILING_SILENCE_MS,
                                config.MIC_SILENCE_RMS_THRESHOLD,
                            )
                            if paused or elapsed >= config.MIC_FLUSH_MAX_INTERVAL:
                                await _transcribe_and_route(
                                    audio_buffer, websocket, requires_wake_word, mic_capture_rate
                                )
                                audio_buffer.clear()
                                last_mic_flush = time.time()

                elif isinstance(message, str):
                    data = json.loads(message)

                    if data.get("type") == "register" and data.get("role") == "audio_sink":
                        AUDIO_SINKS.add(websocket)
                        print(f" [AUDIO_SINK] Registered ({websocket.remote_address}). "
                              f"Active sinks: {len(AUDIO_SINKS)}")
                        await websocket.send(json.dumps({"type": "register_ack"}))
                        sink_keepalive_task = asyncio.create_task(_sink_keepalive(websocket))
                        continue

                    if data.get("type") == "register" and data.get("role") == "led_ring":
                        LED_SINKS.add(websocket)
                        print(f" [LED_RING] Registered ({websocket.remote_address}). "
                              f"Active LED sinks: {len(LED_SINKS)}")
                        await websocket.send(json.dumps({"type": "register_ack"}))
                        # Push the ground-truth current state right away:
                        # this connection's own booting/idle sequence is
                        # entirely local and finishes before it ever gets
                        # here. Right after boot this correctly resolves
                        # to idle_wake_word (no conversation has happened
                        # yet), not "listening".
                        _led_state, _led_duration = _listening_state_and_duration()
                        await websocket.send(
                            pi_commands.led_state_message(_led_state, duration=_led_duration)
                        )
                        continue

                    if data.get("type") == "register" and data.get("role") == "mic_input":
                        requires_wake_word = True
                        mic_capture_rate = config.MIC_CAPTURE_RATE
                        print(f" [MIC_INPUT] Registered ({websocket.remote_address}). "
                              f"Wake-word gating on ('{WAKE_WORD}'), "
                              f"capture rate {mic_capture_rate}Hz.")
                        await websocket.send(json.dumps({"type": "register_ack"}))
                        _led_state, _led_duration = _listening_state_and_duration()
                        await _publish_led_state(_led_state, duration=_led_duration)
                        continue

                    if data.get("type") == "text_query":
                        user_text = data.get("text") or ""
                        speaker_name = data.get("speaker", config.PRIMARY_USER_NAME)
                        print(f"\n [{speaker_name}]-[TXT]: {user_text}")

                        cmd = user_text.strip().lower()

                        if cmd == "/reload":
                            if brain_memory:
                                await asyncio.to_thread(brain_memory.reload)
                            await websocket.send(json.dumps({"type": "stream_start"}))
                            await websocket.send(json.dumps({"type": "stream_chunk", "text": "Memory synced."}))
                            await websocket.send(json.dumps({"type": "stream_end"}))
                            continue

                        if cmd == "/clear":
                            chat_history.clear()
                            await websocket.send(json.dumps({"type": "stream_start"}))
                            await websocket.send(json.dumps({"type": "stream_chunk", "text": "Buffer wiped."}))
                            await websocket.send(json.dumps({"type": "stream_end"}))
                            continue

                        if cmd == "/whoami":
                            info = (f"{ASSISTANT_NAME} | lang={RT['lang_key']} | "
                                    f"wake='{WAKE_WORD}' | memory={RT['memory_name']} | "
                                    f"prompt={config.PROMPT_FILE}")
                            await websocket.send(json.dumps({"type": "stream_start"}))
                            await websocket.send(json.dumps({"type": "stream_chunk", "text": info}))
                            await websocket.send(json.dumps({"type": "stream_end"}))
                            continue

                        uplink_cmd = smart_tools.detect_uplink_command(user_text)
                        if uplink_cmd == "start" and not _uplink_active:
                            await _start_uplink_session(websocket)
                            continue

                        if uplink_cmd == "end" and _uplink_active:
                            await _end_uplink_session(websocket, reason="requested")
                            continue

                        volume_cmd = smart_tools.detect_volume_command(user_text)
                        if volume_cmd:
                            await _apply_volume_delta(websocket, volume_cmd)
                            continue

                        if smart_tools.detect_photo_command(user_text):
                            await _take_photo(websocket)
                            continue

                        if cmd in SILENCE_COMMANDS:
                            _close_conversation()
                            await _stop_active_tts()
                            # Empty stream: acknowledges without speaking,
                            # but still completes the request/response
                            # cycle the browser waits on. The browser only
                            # re-enables chatInput on stream_end.
                            await websocket.send(json.dumps({"type": "stream_start"}))
                            await websocket.send(json.dumps({"type": "stream_end"}))
                            continue

                        if user_text.strip():
                            await dispatch_query(user_text, speaker_name, websocket, client_type="text")

            except asyncio.exceptions.TimeoutError:
                # Nested try needed specifically here: an exception raised
                # INSIDE this except block is NOT caught by the sibling
                # `except ConnectionClosed` below -- sibling except clauses
                # only catch exceptions from the original try body, not
                # from each other.
                try:
                    await _transcribe_and_route(
                        audio_buffer, websocket, requires_wake_word, mic_capture_rate
                    )
                except websockets.exceptions.ConnectionClosed:
                    break
                audio_buffer.clear()

            except websockets.exceptions.ConnectionClosed:
                break
            except Exception as e:
                print(f" [!] Unhandled error in connection loop: {e}")
                continue
    finally:
        if websocket in AUDIO_SINKS:
            AUDIO_SINKS.discard(websocket)
            print(f" [AUDIO_SINK] Unregistered ({websocket.remote_address}). "
                  f"Active sinks: {len(AUDIO_SINKS)}")
        if websocket in LED_SINKS:
            LED_SINKS.discard(websocket)
            print(f" [LED_RING] Unregistered ({websocket.remote_address}). "
                  f"Active LED sinks: {len(LED_SINKS)}")
        if sink_keepalive_task:
            sink_keepalive_task.cancel()


# =============================================================================
# ENTRY POINT
# =============================================================================

async def main():
    global vision_stream

    _print_banner()
    threading.Thread(target=load_ai, daemon=True).start()

    if not args.no_vision:
        vision_stream = VisionStream(
            config.ZOMA_STREAM_URL,
            config.ZOMA_RECONNECT_DELAY,
            memory_provider=lambda: brain_memory,
            tier1_enabled=config.TIER1_ENABLED,
        )
        vision_stream.start()
    else:
        print("[*] Vision ingestion disabled (--no_vision).")

    async def memory_save_worker():
        while True:
            await asyncio.sleep(config.MEMORY_AUTOSAVE_SECONDS)
            if brain_memory:
                await asyncio.to_thread(brain_memory.save_to_disk)

    asyncio.create_task(memory_save_worker())

    # max_size=None: the default 1MiB-per-message cap applies to BOTH
    # directions, and a single ~200-char sentence's synthesized audio can
    # exceed it. Safe here because this server is LAN-only, not
    # internet-facing -- same trust assumption behind disabling pings.
    async with websockets.serve(
        handle_connection, config.SERVER_HOST, args.port,
        ping_interval=None, ping_timeout=None, max_size=None,
    ):
        print(f"[*] {ASSISTANT_NAME} listening on ws://{config.SERVER_HOST}:{args.port}")
        await asyncio.Future()


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        print("\n[!] Ctrl+C detected. Initiating graceful shutdown...")
    finally:
        if vision_stream and vision_stream.is_alive():
            print(" [*] Stopping camera stream...")
            vision_stream.stop()

        if brain_memory:
            print(" [*] Saving memory core to disk...")
            brain_memory.save_to_disk()

        print(" [*] Cleaning up background tasks...")
        pending = asyncio.all_tasks(loop=loop)
        for task in pending:
            task.cancel()
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))

        loop.close()
        print(f"[+] {ASSISTANT_NAME} shutdown complete.")
