"""
ZoMa Brain — TTS chunker, speech-text normalizer, and Kokoro HTTP client
Property of TheMechanics. Contact: mamau.mechanics@gmail.com

Holds no Kokoro/torch import itself -- Kokoro runs isolated in its own
Docker container, reached only over localhost HTTP. This module is the
thin client side of that boundary, plus the pieces of logic that belong
on the caller's side regardless of which TTS engine sits behind the call:

  1. SentenceChunker  -- buffers streamed LLM text and yields complete
     sentences as boundaries are found, so audio can start well before
     the full reply has finished generating.
  2. normalize_for_speech() -- strips things that make sense on screen
     but not out loud ([SYSTEM: ...] blocks, markdown, emoji) and fixes
     pronunciation-affecting patterns (currency, percentages). Display
     text (what the chat UI shows) and spoken text are different strings
     downstream -- this function produces the spoken one only.
  3. synthesize() -- calls the kokoro-service container's /synthesize
     endpoint, validates the returned format, and resamples 24kHz
     (Kokoro native) to 16kHz (the Pi mic's native rate) via a 2:3
     rational-ratio resample: a 2x linear-interpolation upsample to
     48kHz, then a 3:1 boxcar-average decimation down to 16kHz. Both
     stages are clean integer ratios, so no general-purpose resampler is
     needed for this conversion.

The audio-sink registry, the WebSocket role-branching, and the
tts_start/tts_chunk/tts_end/tts_abort wire protocol live in
zoma_brain_server.py -- this module only produces audio bytes, it
doesn't know who's listening for them.
"""

import io
import re
import wave

import aiohttp
import numpy as np

import config


# --- Sentence chunker --------------------------------------------------------

class SentenceChunker:
    """
    Feed it streamed text chunks (e.g. from llm_engine.ask_qwen_stream);
    it yields complete sentences as soon as a safe boundary is found,
    without waiting for the full response.

    Flushes on . ! ? … or newline, guarded against:
      - decimals ("3.14" won't split on the '.')
      - common abbreviations ("Dr. Smith" won't split on the '.')
      - an ambiguous trailing period at the very end of the buffer so
        far (streaming may still deliver the digit/word that would
        have disqualified the split -- wait for more text first)
    Also hard-flushes at ~200 chars (at the last word boundary, not
    mid-word) so a single very long unpunctuated stretch doesn't stall
    audio output indefinitely.
    """

    MAX_CHARS = 200
    BOUNDARY_CHARS = ".!?…"
    ABBREVIATIONS = {
        "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs",
        "etc", "eg", "ie", "us", "uk", "approx", "no", "vol",
    }

    def __init__(self):
        self._buf = ""

    def feed(self, text_chunk: str) -> list[str]:
        """Add streamed text; return zero or more complete sentences."""
        self._buf += text_chunk
        sentences = []
        while True:
            idx = self._find_boundary()
            if idx is None:
                break
            sentence = self._buf[: idx + 1].strip()
            self._buf = self._buf[idx + 1 :]
            if sentence:
                sentences.append(sentence)
        return sentences

    def flush(self) -> str | None:
        """Call once the source stream has ended to get any trailing partial sentence."""
        remaining = self._buf.strip()
        self._buf = ""
        return remaining or None

    def _find_boundary(self) -> int | None:
        buf = self._buf

        for i, ch in enumerate(buf):
            if ch == "\n":
                return i
            if ch in self.BOUNDARY_CHARS:
                if i == len(buf) - 1:
                    # Could still be a decimal point or abbreviation --
                    # the disambiguating character hasn't streamed in
                    # yet. Wait for more text rather than guessing.
                    continue
                if self._is_guarded(buf, i):
                    continue
                return i

        if len(buf) >= self.MAX_CHARS:
            cut = buf.rfind(" ", 0, self.MAX_CHARS)
            return cut if cut != -1 else self.MAX_CHARS - 1

        return None

    def _is_guarded(self, buf: str, i: int) -> bool:
        ch = buf[i]
        before = buf[i - 1] if i > 0 else ""
        after = buf[i + 1] if i + 1 < len(buf) else ""

        if ch == "." and before.isdigit() and after.isdigit():
            return True  # decimal point, e.g. "3.14"

        if ch == "." and (before == "." or after == "."):
            # Part of a literal "..." ellipsis (three ASCII dots -- what
            # LLMs actually output; the single Unicode "…" character never
            # reaches here as three chars). Without this guard, a run of
            # dots splits on every dot, and each resulting fragment gets
            # synthesized separately as an isolated period with no real
            # content -- audibly garbled. Guarding here means the run is
            # skipped entirely; the sentence doesn't end until whatever
            # real terminal punctuation follows.
            return True

        if ch == ".":
            j = i
            while j > 0 and buf[j - 1].isalpha():
                j -= 1
            word = buf[j:i].lower()
            if word in self.ABBREVIATIONS:
                return True

        return False


# --- Speech-text normalization ------------------------------------------------

_SYSTEM_BLOCK_RE = re.compile(r"\[SYSTEM[^\]]*\].*?(?=\[SYSTEM|\Z)", re.IGNORECASE | re.DOTALL)
# Stage-direction-style tokens the persona prompt asks the model to emit
# (e.g. a literal "[SILENCE]" reply). Nothing downstream used to
# intercept that literal string, so it streamed straight into Kokoro,
# which tried to phonemize it letter by letter. Deliberately narrow
# (short, ALL-CAPS, single bracket) so it can't eat a real sentence that
# happens to contain a bracket.
_BRACKET_TAG_RE = re.compile(r"\[[A-Z][A-Z _]{0,20}\]")
_MARKDOWN_HEADER_RE = re.compile(r"^#{1,6}\s*", re.MULTILINE)
_MARKDOWN_EMPHASIS_RE = re.compile(r"[*_`]{1,3}")
_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U0001F1E6-\U0001F1FF"
    "]+"
)
# Typographic punctuation the persona's voice reaches for constantly
# (curly quotes, em dashes) but that Kokoro's espeak-ng phonemizer
# doesn't handle as cleanly as plain ASCII.
_CURLY_QUOTES = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"',
})
# En/em dash WITH surrounding whitespace only -- a bare hyphen in e.g.
# "3-1" or "well-known" must not be touched, and isn't: this pattern only
# matches U+2013/U+2014, never ASCII "-".
_DASH_RE = re.compile(r"\s*[–—]\s*")
_ELLIPSIS_RE = re.compile(r"…")
# Literal "..." (three ASCII dots, as LLMs actually type it, vs. the
# single Unicode "…" char _ELLIPSIS_RE above catches). Runs AFTER that
# substitution so a converted Unicode ellipsis is caught by this too.
# Chunker-level fragmentation is guarded separately in SentenceChunker;
# this is the text-level cleanup for whatever reaches Kokoro as a single
# chunk -- collapsed to a comma-pause rather than trusting the phonemizer
# with raw multi-dot punctuation.
_MULTI_DOT_RE = re.compile(r"\.{2,}\s*")
_CURRENCY_RE = re.compile(r"\$(\d+(?:\.\d+)?)")
_PERCENT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_for_speech(text: str) -> str:
    """
    Convert raw chat-stream text into text safe/sensible to speak aloud.
    Chat display keeps the original digit-preferred text; this is the
    TTS-only branch of that split.
    """
    text = _SYSTEM_BLOCK_RE.sub("", text)
    text = _BRACKET_TAG_RE.sub("", text)
    text = _MARKDOWN_HEADER_RE.sub("", text)
    text = _MARKDOWN_EMPHASIS_RE.sub("", text)
    text = text.translate(_CURLY_QUOTES)
    text = _DASH_RE.sub(", ", text)
    text = _ELLIPSIS_RE.sub("...", text)
    text = _MULTI_DOT_RE.sub(", ", text)
    text = _EMOJI_RE.sub("", text)
    text = _CURRENCY_RE.sub(lambda m: f"{m.group(1)} dollars", text)
    text = _PERCENT_RE.sub(lambda m: f"{m.group(1)} percent", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text


# --- Kokoro HTTP client + resampling -------------------------------------------

async def _call_kokoro(text: str, voice: str = None, lang_code: str = None,
                        speed: float = None) -> bytes:
    """POST to kokoro-service, return the raw WAV response body."""
    payload = {
        "text": text,
        "voice": voice or config.KOKORO_VOICE,
        # kokoro-service holds one KPipeline per lang_code (built lazily on
        # first use) -- this selects WHICH one phonemizes the text. Must
        # actually match the voice's language (e.g. "im_nicola" needs "i")
        # or the service produces fluent-sounding gibberish, not an error.
        "lang_code": lang_code or config.lang()["kokoro_lang_code"],
        "speed": speed or config.KOKORO_SPEED,
    }
    timeout = aiohttp.ClientTimeout(total=config.KOKORO_TIMEOUT)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(
            f"{config.KOKORO_SERVICE_URL}/synthesize", json=payload
        ) as resp:
            resp.raise_for_status()
            return await resp.read()


def _resample_24k_to_16k(pcm: np.ndarray) -> np.ndarray:
    """
    24kHz (Kokoro native) -> 16kHz, via a clean 2:3 rational ratio --
    gcd(24000, 16000) = 8000, so up=2/down=3 stays an exact integer pair
    and no general-purpose resampler is needed:

      Stage 1: 2x upsample via linear interpolation (24kHz -> 48kHz).
      Stage 2: 3:1 boxcar-average decimation (48kHz -> 16kHz) -- averaging
               each group of 3 consecutive samples (a crude low-pass)
               before collapsing to one sample per group, rather than
               naively keeping every 3rd sample, which would alias
               high-frequency content into the result.
    """
    if len(pcm) < 2:
        return pcm.astype(np.int16)

    midpoints = ((pcm[:-1].astype(np.int32) + pcm[1:].astype(np.int32)) // 2).astype(np.int16)
    upsampled = np.empty(len(pcm) * 2 - 1, dtype=np.int16)
    upsampled[0::2] = pcm
    upsampled[1::2] = midpoints
    upsampled = np.append(upsampled, pcm[-1])  # exact 2x multiple -- now 48kHz

    n = len(upsampled) - (len(upsampled) % 3)
    if n <= 0:
        return np.zeros(0, dtype=np.int16)
    trimmed = upsampled[:n].astype(np.int32)
    grouped = trimmed.reshape(-1, 3)
    return grouped.mean(axis=1).astype(np.int16)


async def synthesize(sentence: str, voice: str = None, lang_code: str = None,
                      speed: float = None) -> bytes:
    """
    Text in, S16_LE mono 16kHz PCM bytes out -- headerless, ready to hand
    straight to the Pi's playback pipe on the other end of the wire
    protocol.

    voice overrides config.KOKORO_VOICE for this call only (e.g. a
    distinct voice for uplink/Claude replies -- see config.CLAUDE_TTS_
    VOICE). None uses the configured default.

    lang_code overrides the active language's kokoro_lang_code for this
    call only. None uses whatever config.LANGUAGE currently resolves to.
    Keep voice/lang_code paired to the same language when overriding
    both; kokoro-service does not validate that pairing itself.

    speed overrides config.KOKORO_SPEED for this call only. None uses the
    configured default.

    Applies normalize_for_speech() internally, so callers always pass raw
    chat-stream sentences, never pre-cleaned text. Returns b"" if
    normalization strips the sentence down to nothing (e.g. a sentence
    that was purely a [SYSTEM: ...] block).
    """
    spoken_text = normalize_for_speech(sentence)
    if not spoken_text:
        return b""

    wav_bytes = await _call_kokoro(spoken_text, voice=voice, lang_code=lang_code, speed=speed)

    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        if (wf.getframerate(), wf.getsampwidth(), wf.getnchannels()) != (24000, 2, 1):
            raise ValueError(
                f"Unexpected kokoro-service output format: "
                f"{wf.getframerate()}Hz, {wf.getsampwidth() * 8}-bit, "
                f"{wf.getnchannels()}ch (expected 24000Hz/16-bit/mono). "
                f"Did the service or voice change?"
            )
        raw = wf.readframes(wf.getnframes())

    pcm = np.frombuffer(raw, dtype=np.int16)
    resampled = _resample_24k_to_16k(pcm)
    return resampled.tobytes()
