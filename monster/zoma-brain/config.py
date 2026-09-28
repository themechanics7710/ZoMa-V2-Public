"""
ZoMa Brain — central configuration
Property of TheMechanics. Contact: mamau.mechanics@gmail.com

All runtime settings for the ZoMa Brain server: identity, language, model
backends, memory, TTS/STT, and conversation tuning. Values are env-var
overridable, and the server's CLI flags overwrite these in-process at
startup via zoma_brain_server._apply_runtime_config().

Other modules read these as `config.X` at call time (never
`from config import X`), so a runtime override is visible everywhere.
Memory files are derived per brain name, so multiple personas keep
entirely separate FAISS indices without manual file management.
"""

import os
from pathlib import Path


# =============================================================================
# IDENTITY
# =============================================================================

# The one and only place a default assistant name appears.
# CLI: --name
ASSISTANT_NAME = os.getenv("ZOMA_BRAIN_NAME", "Clorian")

# Wake word. None means "use the assistant name", which is almost always
# what you want. Set it only when they should differ (e.g. name "Athena",
# wake word "computer").
# CLI: --wake-word
WAKE_WORD = os.getenv("ZOMA_BRAIN_WAKE_WORD") or None

# Which memory database this brain uses. None means "use the assistant
# name". Set it explicitly to share one memory across several personas --
# e.g. a maintenance-persona variant that should remember everything the
# main persona does, just with a different prompt and tone.
# CLI: --memory-name
MEMORY_NAME = os.getenv("ZOMA_BRAIN_MEMORY_NAME") or None

# The human this brain primarily talks to. Used for the speaker prefix
# and LLM stop tokens.
PRIMARY_USER_NAME = os.getenv("PRIMARY_USER_NAME", "The Mechanics")


# =============================================================================
# LANGUAGE
# =============================================================================

# Active language key: one of LANGUAGES below.
# CLI: --lang
LANGUAGE = os.getenv("ZOMA_BRAIN_LANG", "eng")

# "fixed"  -> always reply in the active language.
# "mirror" -> reply in whatever language the person used.
# CLI: --reply-mode
REPLY_LANGUAGE_MODE = os.getenv("ZOMA_BRAIN_REPLY_MODE", "fixed")

# Per-language settings. Add a language by adding a dict entry -- no code
# changes needed anywhere.
#
#   label            : human-readable name, injected into the LLM directive
#   whisper          : ISO code, currently informational only (STT stays on
#                      auto-detect so EN/IT mixing keeps working)
#   stt_hint         : Whisper initial_prompt, biases the decoder toward the
#                      languages you actually speak
#   kokoro_lang_code : which KPipeline the TTS container must be running
#   kokoro_voice     : voice embedding name
#   silence          : interrupt/stop commands IN THIS LANGUAGE. The active
#                      language's list is always UNIONED with English, since
#                      "stop" works in every language in practice.
#   fillers          : rotating "still thinking" phrases for the TEXT heartbeat
#   spoken_fillers   : short natural phrases SPOKEN aloud when the model is
#                      slow to start (browser/UI + voice playback; the Pi
#                      mic client never reads the text heartbeat). Keep
#                      these genuinely short -- they are synthesized and
#                      played before the real reply in the same utterance,
#                      so a long filler delays the answer behind it.
#   halluc           : phrases Whisper commonly invents from silence, noise,
#                      or TTS bleed. Rejected in the no-wake-word follow-up
#                      path only.
LANGUAGES = {
    "eng": {
        "label": "English",
        "whisper": "en",
        "stt_hint": "Conversation in English and Italian.",
        "kokoro_lang_code": "a",          # 'b' British, 'a' American
        "kokoro_voice": "am_adam",        # Clorian/Qwen. Claude/uplink uses
                                           # CLAUDE_TTS_VOICE (af_bella) below.
        "silence": ["stop", "quiet", "shut up", "enough", "that's enough",
                    "ok", "cancel", "never mind"],
        "fillers": ["* Still reasoning... *", "* Working through it... *",
                    "* Nearly there... *", "* Holding that thought... *"],
        "spoken_fillers": ["Just a sec.", "One moment.", "Hold on.", "Let me think."],
        "halluc": ["thank you", "thanks", "thanks for watching", "bye", "goodbye",
                   "you", "so", "close", "okay", "amen", "subscribe",
                   "for more information", "please subscribe", "thank you very much"],
    },
    "it": {
        "label": "Italian",
        "whisper": "it",
        "stt_hint": "Conversazione in italiano e inglese.",
        "kokoro_lang_code": "i",
        "kokoro_voice": "im_nicola",      # if_sara for the female voice
        "silence": ["basta", "silenzio", "zitto", "annulla", "va bene", "fermo"],
        "fillers": ["* Sto ragionando... *", "* Ci sto lavorando... *",
                    "* Quasi pronto... *"],
        "spoken_fillers": ["Un attimo.", "Un momento.", "Aspetta.", "Fammi pensare."],
        "halluc": ["grazie", "ciao", "prego", "sottotitoli", "e chiusura"],
    },
    "fr": {
        "label": "French",
        "whisper": "fr",
        "stt_hint": "Conversation en français et en anglais.",
        "kokoro_lang_code": "f",
        # ff_siwis is the only French voice in Kokoro-82M, and it is female
        # -- there is no French male voice available.
        "kokoro_voice": "ff_siwis",
        "silence": ["arrête", "arrete", "silence", "tais-toi", "annule", "ça suffit"],
        "fillers": ["* Je réfléchis... *", "* J'y travaille... *", "* Presque... *"],
        "spoken_fillers": ["Un instant.", "Un moment.", "Attends.", "Laisse-moi réfléchir."],
        "halluc": ["merci", "au revoir", "salut", "sous-titres"],
    },
    "esp": {
        "label": "Spanish",
        "whisper": "es",
        "stt_hint": "Conversación en español e inglés.",
        "kokoro_lang_code": "e",
        "kokoro_voice": "em_alex",        # ef_dora for the female voice
        "silence": ["para", "basta", "silencio", "cállate", "callate", "cancela"],
        "fillers": ["* Estoy pensando... *", "* Trabajando en ello... *", "* Casi... *"],
        "spoken_fillers": ["Un momento.", "Un segundo.", "Espera.", "Déjame pensar."],
        "halluc": ["gracias", "adiós", "hola", "subtítulos"],
    },
}


def lang(key: str = None) -> dict:
    """Active language settings, falling back to English on an unknown key."""
    return LANGUAGES.get(key or LANGUAGE, LANGUAGES["eng"])


# =============================================================================
# PROMPT
# =============================================================================

# CLI: --prompt
PROMPT_FILE = os.getenv("ZOMA_BRAIN_PROMPT_FILE", "./clorian_prompt.txt")


# =============================================================================
# LLM BACKEND (Ollama-compatible)
# =============================================================================

OLLAMA_API_URL = os.getenv("OLLAMA_API_URL", "http://localhost:11434/api/chat")
QWEN_TEXT_MODEL = os.getenv("QWEN_TEXT_MODEL", "qwen3:14b")

# Explicit context window. Ollama's default is 4096; once memory +
# history + vision context grow past that it silently truncates and
# invalidates the prompt prefix cache, which shows up as inconsistent
# time-to-first-token. Setting it explicitly keeps latency predictable.
QWEN_NUM_CTX = int(os.getenv("QWEN_NUM_CTX", "8192"))


# =============================================================================
# VISION (Qwen-VL)
# =============================================================================

QWEN_VL_MODEL = os.getenv("QWEN_VL_MODEL", "qwen2.5vl:7b")
QWEN_VL_TIMEOUT = float(os.getenv("QWEN_VL_TIMEOUT", "30"))
QWEN_VL_KEEP_ALIVE = os.getenv("QWEN_VL_KEEP_ALIVE", "5m")


# =============================================================================
# CLAUDE (uplink sessions -- Anthropic API)
# =============================================================================

# Resolved by the `anthropic` SDK itself from this same env var (it checks
# ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN on its own). Kept here too only
# so _print_banner() can warn at startup if it's missing, the same way the
# prompt-file check does. No default -- there is no safe placeholder for a
# secret, and this must never be hardcoded or committed.
#
# If it's not already in the environment, falls back to reading it from a
# plain-text file (just the key, nothing else), resolved via Path.home()
# rather than a hardcoded machine-specific path. Only whether a key was
# found is ever logged; the value itself is never printed or written
# anywhere by this code.
def _load_anthropic_key() -> str | None:
    existing = os.getenv("ANTHROPIC_API_KEY")
    if existing:
        return existing
    key_path = Path(os.getenv("ANTHROPIC_API_KEY_FILE", str(Path.home() / "API_ANTHROPIC.txt")))
    if not key_path.exists():
        return None
    try:
        key = key_path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not key:
        return None
    os.environ["ANTHROPIC_API_KEY"] = key  # so the anthropic SDK's own env lookup finds it too
    return key


ANTHROPIC_API_KEY = _load_anthropic_key()

CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5")

# Server-side web search: Anthropic runs the actual search and hands
# Claude real results inside the same API call, no separate infra needed
# here. Without it, Claude only has training-cutoff knowledge.
#
# Explicit-command only (see smart_tools.is_web_search_request()), not
# attached to every uplink turn -- search-result content becomes part of
# the request context, adding real latency and input-token cost, so most
# uplink questions shouldn't pay for it by default.
# CLAUDE_WEB_SEARCH_ENABLED is a master kill-switch on top of that.
#
# CLAUDE_WEB_SEARCH_MAX_USES bounds the worst case per turn. A compound
# request (e.g. "give me the news") typically needs two searches -- one
# broad, one for specifics -- to produce a complete answer; a lower cap
# can cause the model to fall back to an incomplete reply mid-turn. Cost
# scales with how much raw page content each search pulls into context,
# not just the count, so this is kept at the minimum that covers real
# multi-part requests rather than opened further than needed.
CLAUDE_WEB_SEARCH_ENABLED = os.getenv("CLAUDE_WEB_SEARCH_ENABLED", "1") not in ("0", "false", "False")
CLAUDE_WEB_SEARCH_MAX_USES = int(os.getenv("CLAUDE_WEB_SEARCH_MAX_USES", "2"))

# Distinct Kokoro voice for Claude-sourced speech, so uplink is audibly
# distinguishable from Clorian (am_adam, LANGUAGES["eng"] above) by ear,
# not just by a console log label.
CLAUDE_TTS_VOICE = os.getenv("CLAUDE_TTS_VOICE", "af_bella") or None

# Uplink replies stay short (1-3 sentences, same brevity convention
# llm_engine uses for voice) -- far below what a general-purpose
# streaming request would default to.
CLAUDE_MAX_TOKENS = int(os.getenv("CLAUDE_MAX_TOKENS", "4096"))

# How long an uplink session may sit with no accepted turn before it
# auto-ends itself and announces it. Same refresh-on-activity shape as
# FOLLOWUP_WINDOW_SECONDS below, with a longer fuse and a louder exit,
# since hands-free listening for the session's duration is the point.
UPLINK_IDLE_TIMEOUT_SECONDS = float(os.getenv("UPLINK_IDLE_TIMEOUT_SECONDS", "60"))

# Whether uplink turns pull FAISS long-term recall in at all. Off by
# default: distance-threshold filtering and top_k capping alone were not
# enough to keep recalled entries reliably relevant to uplink questions,
# so this stays off until memory retrieval is tuned specifically for
# uplink. Flip on with UPLINK_MEMORY_ENABLED=1 once that's ready.
UPLINK_MEMORY_ENABLED = os.getenv("UPLINK_MEMORY_ENABLED", "0") not in ("0", "false", "False")

# How many FAISS memories get pulled into an uplink turn's context, IF
# UPLINK_MEMORY_ENABLED. Kept well below MEMORY_TOP_K to limit the
# input-token cost of marginally-relevant recall on uplink turns.
UPLINK_MEMORY_TOP_K = int(os.getenv("UPLINK_MEMORY_TOP_K", "3"))


# =============================================================================
# ZoMa / Raspberry Pi
# =============================================================================

# Tier 1 (background motion/face detection). Defaults OFF.
#
# Not just a logging toggle: VisionStream._log_event() runs a genuine
# Qwen-VL call (vision_engine.analyze_frame()) on every motion/face
# trigger by default (tier2_enabled=True in vision_stream.py). Since the
# text and vision models compete for the same GPU memory, frequent
# background triggers can quietly evict the text model, adding load
# latency to unrelated chat turns. Off until a real consumer of these
# events exists beyond sitting in FAISS.
TIER1_ENABLED = os.getenv("TIER1_ENABLED", "0") not in ("0", "false", "False")

# CLI: --pi-host / --pi-port / --pi-path
#
# Port reference:
#   8554 = RTSP  -> what OpenCV/ffmpeg needs. Use this one.
#   8889 = WebRTC/WHEP -> browsers only. OpenCV cannot negotiate it.
PI_HOST = os.getenv("ZOMA_PI_HOST", "rb1.local")
PI_RTSP_PORT = int(os.getenv("ZOMA_PI_RTSP_PORT", "8554"))
PI_RTSP_PATH = os.getenv("ZOMA_PI_RTSP_PATH", "cam")

ZOMA_STREAM_URL = os.getenv(
    "ZOMA_STREAM_URL", f"rtsp://{PI_HOST}:{PI_RTSP_PORT}/{PI_RTSP_PATH}"
)
ZOMA_RECONNECT_DELAY = float(os.getenv("ZOMA_RECONNECT_DELAY", "3.0"))
ZOMA_FRAME_MAX_AGE = float(os.getenv("ZOMA_FRAME_MAX_AGE", "2.0"))

# How long a Tier 2 observation stays available as short-term context on
# ordinary chat turns.
VISION_CONTEXT_TTL = float(os.getenv("VISION_CONTEXT_TTL", "300"))


# =============================================================================
# WEBSOCKET SERVER
# =============================================================================

SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("SERVER_PORT", "8765"))
AUDIO_SINK_PING_INTERVAL = float(os.getenv("AUDIO_SINK_PING_INTERVAL", "20"))


# =============================================================================
# SPEECH-TO-TEXT (Whisper)
# =============================================================================

WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "turbo")
WHISPER_BEAM_SIZE = int(os.getenv("WHISPER_BEAM_SIZE", "10"))


# =============================================================================
# SPEAKER ID
# =============================================================================

# Shared across every brain name on purpose: a person's voice is the same
# regardless of which persona is active, so every brain recognizes them
# without separate enrollment.
SPEAKER_GALLERY_DIR = os.getenv("SPEAKER_GALLERY_DIR", "./data/voice_gallery/")
SPEAKER_ID_THRESHOLD = float(os.getenv("SPEAKER_ID_THRESHOLD", "0.72"))
HF_TOKEN_ENV = os.getenv("HF_TOKEN_ENV", "HF_TOKEN")


# =============================================================================
# MEMORY (FAISS) -- PER BRAIN NAME
# =============================================================================

MEMORY_DIR = os.getenv("MEMORY_DIR", "./data/memory")
MEMORY_INDEX_TEMPLATE = os.getenv("MEMORY_INDEX_TEMPLATE", "{slug}_index.faiss")
MEMORY_MAP_TEMPLATE = os.getenv("MEMORY_MAP_TEMPLATE", "{slug}_memory.json")

MEMORY_EMBED_MODEL = os.getenv("MEMORY_EMBED_MODEL", "all-MiniLM-L6-v2")
MEMORY_TOP_K = int(os.getenv("MEMORY_TOP_K", "8"))
MEMORY_DISTANCE_THRESHOLD = float(os.getenv("MEMORY_DISTANCE_THRESHOLD", "1.8"))
MEMORY_AUTOSAVE_SECONDS = int(os.getenv("MEMORY_AUTOSAVE_SECONDS", "300"))

# What to do when the .faiss index and the .json map disagree on how many
# entries exist (i.e. one file was deleted/restored without the other).
#   "raise" -> refuse to start, name both files. Safe default.
#   "reset" -> wipe both and start clean. Convenient, destructive.
MEMORY_ON_MISMATCH = os.getenv("MEMORY_ON_MISMATCH", "raise")


def memory_paths(slug: str) -> tuple[str, str]:
    """(index_file, map_file) for a given brain-name slug."""
    return (
        os.path.join(MEMORY_DIR, MEMORY_INDEX_TEMPLATE.format(slug=slug)),
        os.path.join(MEMORY_DIR, MEMORY_MAP_TEMPLATE.format(slug=slug)),
    )


# =============================================================================
# TTS (Kokoro, containerized)
# =============================================================================

KOKORO_SERVICE_URL = os.getenv("KOKORO_SERVICE_URL", "http://127.0.0.1:8770")
KOKORO_TIMEOUT = float(os.getenv("KOKORO_TIMEOUT", "15.0"))

# Resolved from the language table at startup; overridable with --tts-voice.
KOKORO_VOICE = os.getenv("KOKORO_VOICE", "") or None

# Kokoro's own speed multiplier (1.0 = normal, >1.0 faster, <1.0 slower).
# Not per-language in LANGUAGES: a single server process only ever runs
# one --lang for its whole life, so a plain --tts-speed override at
# launch is already per-language in effect.
KOKORO_SPEED = float(os.getenv("KOKORO_SPEED", "1.0"))


# =============================================================================
# CONVERSATION / MIC / BARGE-IN TUNING
#   Tunable per room, per mic, per wake word without editing code.
# =============================================================================

# Short-term history: number of LINES kept (one per speaker turn), so 6
# means the last three exchanges.
CHAT_HISTORY_LINES = int(os.getenv("CHAT_HISTORY_LINES", "6"))

# Wake-word fuzzy matching. These are RATIO thresholds, and the right
# value depends on wake-word length -- a 7-letter word behaves
# differently from a 6-letter one. Retune if you rename.
WAKE_WORD_SIMILARITY = float(os.getenv("WAKE_WORD_SIMILARITY", "0.72"))
# Looser bar, applied ONLY when what follows is itself a stop command.
WAKE_WORD_SIMILARITY_LENIENT = float(os.getenv("WAKE_WORD_SIMILARITY_LENIENT", "0.55"))

MIC_FLUSH_MAX_INTERVAL = float(os.getenv("MIC_FLUSH_MAX_INTERVAL", "8.0"))
MIC_MIN_BUFFERED_SECONDS = float(os.getenv("MIC_MIN_BUFFERED_SECONDS", "1.0"))
MIC_TRAILING_SILENCE_MS = int(os.getenv("MIC_TRAILING_SILENCE_MS", "1300"))
MIC_SILENCE_RMS_THRESHOLD = float(os.getenv("MIC_SILENCE_RMS_THRESHOLD", "500.0"))

# The Pi's mic (reSpeaker XVF3800) captures natively at 16kHz -- Whisper's
# own native rate -- so no server-side rate conversion is needed.
MIC_CAPTURE_RATE = int(os.getenv("MIC_CAPTURE_RATE", "16000"))

# Loud-sound-during-playback interrupt. Must sit above normal echo
# bleed-through but below a deliberate interrupt. This is the ONLY
# channel that can stop mid-speech: handle_connection() drops every mic
# chunk during active playback UNCONDITIONALLY except this raw-RMS
# check -- there is no transcription and no word-content check while
# ZoMa is talking, so a real "stop" only works if it's loud enough to
# cross this number. What it's said as does not matter; how loud it is
# does.
#
# handle_connection() also logs the RMS of every gated chunk during
# playback (not just ones that cross this threshold), which is useful
# for retuning this value against real echo levels and real interrupt
# volume for a given mic/room.
BARGE_IN_RMS_THRESHOLD = float(os.getenv("BARGE_IN_RMS_THRESHOLD", "10000.0"))

# How long to keep the mic gate closed after ANY stop -- a loud barge-in
# or a transcribed "stop" command -- regardless of whether TTS is still
# marked active. Without this, clearing the active-utterance id reopens
# the gate on the very next mic chunk, before the shout, its room echo,
# or in-flight TTS audio has actually decayed -- that trailing noise
# would otherwise get captured as the next "follow-up" and answered.
STOP_COOLDOWN_SECONDS = float(os.getenv("STOP_COOLDOWN_SECONDS", "1.2"))


# =============================================================================
# FILLER HEARTBEAT
# =============================================================================

# TEXT/UI fillers. Seconds between "still thinking" messages while the LLM
# has produced no tokens yet, cancelled the instant the first token arrives.
#
# These are only ever seen by a client that reads incoming JSON (i.e. the
# browser UI). The Pi's mic client streams audio up and never parses
# messages coming back, so on a voice-only session these are invisible no
# matter how they're tuned -- SPOKEN_FILLER_* below covers that case.
FILLER_INTERVAL = float(os.getenv("FILLER_INTERVAL", "3.5"))
FILLER_ENABLED = os.getenv("FILLER_ENABLED", "1") not in ("0", "false", "False")

# SPOKEN fillers -- "just a sec" / "hold on", actually said aloud.
#
# Safe because of how they're injected: the filler is pushed as the FIRST
# SENTENCE OF THE SAME UTTERANCE, not as a separate one, so there is still
# exactly one utterance id in flight and ordering/abort/end handling all
# keep working untouched. Injecting it as its own utterance would collide
# on the Pi's single playback pipe.
#
# The filler goes ONLY to the TTS sentence queue: never into the full
# response, the websocket text stream, or memory. It is spoken and then
# forgotten.
SPOKEN_FILLERS = os.getenv("SPOKEN_FILLERS", "1") not in ("0", "false", "False")

# How long the model may stay silent before a filler is spoken. Kokoro then
# needs its own synthesis time, so the filler is heard somewhat after this
# delay. Raise it if the filler is heard immediately followed by the real
# answer; lower it if the gap feels dead.
SPOKEN_FILLER_DELAY = float(os.getenv("SPOKEN_FILLER_DELAY", "1.0"))


# =============================================================================
# FOLLOW-UP CONVERSATION WINDOW
#
# After a wake-word-triggered exchange, keep listening for a short while so
# follow-ups don't each need the wake word again. Any accepted turn (wake
# word OR follow-up) refreshes the window; once it lapses, wake-word gating
# resumes and the participant list is cleared.
# =============================================================================

FOLLOWUP_WINDOW_SECONDS = float(os.getenv("FOLLOWUP_WINDOW_SECONDS", "30"))

# A "stop" (loud barge-in, or a transcribed silence command) is a hard
# reset, not an extension -- it closes the follow-up window immediately
# (see zoma_brain_server._close_conversation()) rather than opening or
# refreshing it. Whatever comes next needs the wake word again. Refreshing
# the window on barge-in instead was tried and reverted: the same
# plausibility checks that let a genuine quick follow-up through also let
# background media dialogue through just as easily, since clean media
# audio can transcribe with higher confidence than mumbled real speech.

# STRICT MODE. True = only speakers who were positively identified during a
# wake-word turn may follow up without it; everyone else is ignored.
#
# Defaults to False, because this feature is only as good as speaker ID,
# and speaker ID is the weaker link today -- enrollment quality varies
# enough that turning this on prematurely would mean ignoring the primary
# user some of the time, which is worse than requiring the wake word every
# turn. The fix is channel-matched re-enrollment: gallery samples recorded
# through the same mic, rate and downsample path as live audio. Use
# enroll_speaker.py on the Pi, then flip this to True.
FOLLOWUP_REQUIRE_KNOWN_SPEAKER = os.getenv(
    "FOLLOWUP_REQUIRE_KNOWN_SPEAKER", "0") not in ("0", "false", "False")

# --- Hallucination guards, applied ONLY to wake-word-less follow-ups ---------
#
# The wake word is itself a strong filter: Whisper inventing filler
# phrases out of room noise is harmless while a wake word is required,
# because it never matches. With an open follow-up window those
# inventions become real queries that reach the LLM and get written to
# memory. These checks are NOT applied to wake-word turns.

FOLLOWUP_MIN_WORDS = int(os.getenv("FOLLOWUP_MIN_WORDS", "2"))

# Whisper's own confidence, computed per segment. avg_logprob nearer 0 is
# more confident; below about -1.0 is usually noise. no_speech_prob above
# ~0.6 means "probably wasn't speech".
FOLLOWUP_MIN_AVG_LOGPROB = float(os.getenv("FOLLOWUP_MIN_AVG_LOGPROB", "-1.0"))
FOLLOWUP_MAX_NO_SPEECH = float(os.getenv("FOLLOWUP_MAX_NO_SPEECH", "0.6"))


# =============================================================================
# TICKER MAP -- shared across brain names (learned world data, not persona)
# =============================================================================

TICKER_MAP_FILE = os.getenv("TICKER_MAP_FILE", "./data/ticker_map.json")


# =============================================================================
# PI DEVICE COMMANDS -- see pi_commands.py
# =============================================================================

# Percent nudge applied per "increase/decrease the volume" voice command
# (amixer's own relative-step syntax on the Pi, e.g. "2%+"/"2%-").
VOLUME_STEP_PERCENT = int(os.getenv("VOLUME_STEP_PERCENT", "5"))


# =============================================================================
# PHOTO CAPTURE -- "take a picture" voice command (see
# smart_tools.detect_photo_command(), zoma_brain_server._take_photo())
# =============================================================================

# Captured stills are saved here, relative to monster/zoma-brain's own
# cwd on a normal launch (same convention as MEMORY_DIR above).
PICTURES_DIR = os.getenv("PICTURES_DIR", "./pictures")

# Photos are captured from vision_stream's already-decoded RTSP frame
# rather than a direct still-capture call on the Pi: the Pi's camera
# library opens the camera exclusively, so there is no safe way to run a
# separate still-capture command while the RTSP feed is live.
#
# The shutter click is sent to the Pi over the existing AUDIO_SINKS
# connection (zoma_audio_client.py), reusing the same wire protocol a
# spoken TTS reply uses rather than a new message type. This file must
# exist on Monster's own disk -- Monster reads and resamples its own copy
# before transmitting; it does not reach into the Pi's directory tree.
SHUTTER_SOUND_FILE = os.getenv("SHUTTER_SOUND_FILE", "./sounds/shutter.wav")
