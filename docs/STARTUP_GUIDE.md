# Starting ZoMa Brain

How to launch the ZoMa Brain server on the off-board GPU machine (**Monster** —
see [ARCHITECTURE.md](ARCHITECTURE.md)), along with its CLI parameters and the
Kokoro TTS container it depends on.

---

## Prerequisites

Before running `zoma_brain_server.py`, verify the following:

- **NVIDIA CUDA GPU available** — Whisper initializes with `device="cuda"` by
  default; a functional CUDA GPU is required.
- **Ollama running** locally (`http://localhost:11434/api/chat`).
- **Kokoro TTS running** — verify with `curl http://127.0.0.1:8770/health`.
- **Environment variables**:
  - `ANTHROPIC_API_KEY` — required for Claude uplink sessions (warns if missing).
  - `HF_TOKEN` — required for speaker diarization/ID (speaker ID disables itself
    with a warning if unset).
- **System prompt file** — the target prompt file (e.g. `clorian_prompt.txt`) must
  exist relative to `monster/zoma-brain/`.

---

## Starting the server

Activate your Python environment and move into the server directory:

```bash
source /path/to/your/venv/bin/activate
cd /path/to/ZoMa-V2-Public/monster/zoma-brain/
```

### English (default)

```bash
python zoma_brain_server.py --name Clorian --prompt clorian_prompt.txt --lang eng --tts-voice am_adam
```

### Italian

```bash
python zoma_brain_server.py --name Clorian --prompt clorian_prompt.txt --lang it --tts-voice im_nicola --tts-speed 1.15
```

### French

```bash
python zoma_brain_server.py --name Clorian --prompt clorian_prompt.txt --lang fr --tts-voice ff_siwis --tts-speed 1.15
```

### Spanish

```bash
python zoma_brain_server.py --name Clorian --prompt clorian_prompt.txt --lang esp --tts-voice em_alex --tts-speed 1.15
```

---

## Parameter reference

| Flag | Type | Default | Description |
|---|---|---|---|
| `--name` | `str` | `Clorian` (`ZOMA_BRAIN_NAME`) | Assistant name; fallback for memory & wake-word |
| `--wake-word` | `str` | `--name` fallback | Spoken trigger keyword |
| `--memory-name` | `str` | `--name` fallback | Memory database slug to load |
| `--prompt` | `str` | `./clorian_prompt.txt` | System persona prompt file path |
| `--lang` | `choice` | `eng` (`eng`, `it`, `fr`, `esp`) | Active conversation language |
| `--reply-mode` | `choice` | `fixed` (`fixed`, `mirror`) | `fixed` locks to `--lang`; `mirror` matches speaker |
| `--stt-prompt` | `str` | Language table hint | Whisper bilingual initialization prompt |
| `--tts-voice` | `str` | Language default | Voice ID override for Kokoro TTS |
| `--tts-speed` | `float` | `1.0` | Voice playback speed multiplier |
| `--pi-host` | `str` | `rb1.local` (`ZOMA_PI_HOST`) | Raspberry Pi hostname or IP for the camera RTSP stream |
| `--pi-port` | `int` | `8554` | RTSP camera port (not the WebRTC port, 8889) |
| `--pi-path` | `str` | `cam` | RTSP stream endpoint path |
| `--no_vision` | `flag` | `off` | Disables camera ingestion and the vision pipeline |
| `--whisper_model` | `str` | `turbo` | Faster-Whisper model size |
| `--beam_size` | `int` | `10` | Whisper beam search width |
| `--port` | `int` | `8765` (`SERVER_PORT`) | WebSocket listening port |
| `--gallery_dir` | `str` | `./data/voice_gallery/` | Voice gallery directory for speaker ID |
| `--threshold` | `float` | `0.72` | Cosine similarity threshold for speaker ID |

---

## Additional examples

### Defaults only (Clorian, English, port 8765)

```bash
python zoma_brain_server.py
```

### Custom Pi RTSP host & tuned Italian persona

```bash
python zoma_brain_server.py --lang it --tts-voice im_nicola --tts-speed 0.9 \
  --pi-host rb1.local
```

### Secondary persona sharing Clorian's memory (no camera)

```bash
python zoma_brain_server.py --name Athena --wake-word computer \
  --memory-name Clorian --prompt ./athena_prompt.txt --no_vision
```

---

## Kokoro TTS service management

Kokoro runs inside Docker and starts automatically at boot
(`--restart unless-stopped`).

### Start the container (if stopped)

```bash
docker start kokoro-service
```

### View live logs

```bash
docker logs -f kokoro-service
```

### Check health status

```bash
curl http://127.0.0.1:8770/health
```

### Rebuild and run (if Kokoro is down or unresponsive)

```bash
cd ~/kokoro-service
docker stop kokoro-service && docker rm kokoro-service
docker build -t kokoro-service .
docker run -d --name kokoro-service \
  --restart unless-stopped \
  -p 127.0.0.1:8770:8770 \
  kokoro-service
```

---

*ZoMa is property of TheMechanics. Contact: mamau.mechanics@gmail.com*
