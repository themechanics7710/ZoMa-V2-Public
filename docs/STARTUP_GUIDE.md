# ZoMa — Startup Guide

How to bring the whole system up: the Raspberry Pi's camera stream and
audio/LED processes, then the off-board GPU machine's (**Monster** — see
[ARCHITECTURE.md](ARCHITECTURE.md)) Kokoro TTS service and the ZoMa Brain
server itself. Start the Pi first, then Monster — ZoMa Brain connects out to
the Pi's camera stream on startup.

---

## 1. Raspberry Pi

### 1.1 Camera stream (MediaMTX)

The camera feed is served by [MediaMTX](https://github.com/bluenviron/mediamtx)
(a standalone media server) running on the Pi, republishing the Pi camera as
both RTSP (for ZoMa Brain's vision pipeline) and WebRTC (for the web
dashboard's live feed). It isn't part of this repo — it's a general-purpose
open-source tool, installed and configured directly on the Pi.

**Install:**

```bash
# On the Pi (aarch64):
curl -LO https://github.com/bluenviron/mediamtx/releases/latest/download/mediamtx_linux_arm64v8.tar.gz
tar -xzf mediamtx_linux_arm64v8.tar.gz
sudo mv mediamtx /usr/local/bin/
sudo apt install -y ffmpeg   # rpicam-apps ships preinstalled on Raspberry Pi OS
```

**Configure** (`mediamtx.yml`) to publish the Pi camera on the `cam` path, at
the ports ZoMa Brain and the web dashboard already expect by default (RTSP
`8554`, WebRTC `8889`):

```yaml
rtspAddress: :8554
webrtcAddress: :8889

paths:
  cam:
    runOnInit: >
      rpicam-vid -t 0 --width 1280 --height 720 --framerate 30 --codec h264
      --inline --listen -o - |
      ffmpeg -f h264 -i - -c copy -f rtsp rtsp://localhost:8554/cam
    runOnInitRestart: yes
```

**Run:**

```bash
mediamtx /path/to/mediamtx.yml
```

Set this up as a systemd service so it starts at boot. Verify it's working
before moving on:

```bash
ffplay rtsp://<pi-host>:8554/cam       # RTSP, from another machine
# or open http://<pi-host>:8889/cam/ in a browser for the WebRTC view
```

### 1.2 Audio, mic, and LED status scripts

These are the scripts in [`pi/scripts/zoma-audio-led/`](../pi/scripts/zoma-audio-led/):
`zoma_audio_client.py` (plays ZoMa Brain's TTS output), `zoma_mic_client.py`
(streams the mic to ZoMa Brain), and `zoma_state.py` (drives the LuMini LED
ring based on ZoMa Brain's state).

**Prerequisites:**

```bash
pip install websockets spidev
```

`websockets` is used by all three clients; `spidev` is needed by
`zoma_state.py` (via `lumini_ring.py`) to drive the LuMini ring over the Pi's
hardware SPI. `arecord`/`aplay` (ALSA utilities) are used for mic capture and
TTS playback — install with `sudo apt install alsa-utils` if not already
present. If you're using the ReSpeaker XVF3800 mic array, install its vendor
SDK (the `xvf_host` binary that `respeaker/xvf_init.sh` calls) from Seeed
Studio's own SDK repository, and point `RESPEAKER_SDK_DIR` at it (see below).

**Point the scripts at your ZoMa Brain server**, and (optionally) at wherever
you clone this repo and the ReSpeaker SDK on your Pi:

```bash
export ZOMA_BRAIN_HOST=<your Monster machine's LAN address>
export ZOMA_REPO_DIR=$HOME/ZoMa-V2-Public          # optional, defaults shown
export ZOMA_AUDIO_STATE_DIR=$HOME/zoma-audio        # optional, logs/PIDs
export RESPEAKER_SDK_DIR=$HOME/reSpeaker_XVF3800_USB_4MIC_ARRAY/host_control/rpi_64bit  # optional
```

**Start:**

```bash
cd pi/scripts/zoma-audio-led
./start_zoma_audio_hud_pi.sh          # audio + mic + LED ring
./start_zoma_audio_hud_pi.sh -hud     # also starts wifi/audio HUD diagnostics
                                       # (requires rclpy — see below)
```

Logs land in `$ZOMA_AUDIO_STATE_DIR/logs/`; tail the current day's file to
watch startup.

**Stop:**

```bash
./stop_zoma_audio_hud_pi.sh
```

**The `-hud` flag** runs `wifi_diag_publisher.py` and `audio_diag_publisher.py`
as ROS 2 nodes (they need `rclpy`, which isn't installed on the Pi host
directly). The launcher expects a running ROS 2 Humble container named
`zoma_ros_pi_v2` and `docker cp`'s each script into it before running it
there — start that container first if you want `-hud` diagnostics.

**ReSpeaker recovery:** if mic capture wedges (repeated fast `arecord`
failures), `zoma_mic_client.py`'s recovery path calls
`reset_respeaker.sh`, which reboots the XVF3800's onboard DSP firmware via
`respeaker/xvf_init.sh`. Run `xvf_init.sh` once manually after first setting
up the mic array, and wire it into a systemd unit that runs at boot, before
the audio/LED scripts start.

---

## 2. Monster (off-board GPU machine)

### 2.1 Kokoro TTS service

ZoMa Brain's text-to-speech runs as a separate local HTTP service — a
Docker container wrapping the open-weights [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M)
model — rather than being built into `zoma_brain_server.py`. This service
itself isn't part of this repo (it's generic, reusable infrastructure, kept
and versioned separately on Monster at `~/kokoro-service/`); what's documented
here is the contract `tts_engine.py` expects from it, so you can stand up a
compatible one.

**API contract** (what `tts_engine.py` calls):

- `POST /synthesize` — JSON body `{"text": str, "voice": str, "lang_code": str, "speed": float}`,
  returns the raw WAV audio bytes. One [`KPipeline`](https://github.com/hexgrad/kokoro)
  per `lang_code`, built lazily on first use, so the service can serve every
  language ZoMa Brain supports (`eng`/`it`/`fr`/`esp`) without a restart.
- `GET /health` — returns 200 once the service is ready.

**Minimal setup**, if you're building your own from scratch:

```bash
pip install kokoro torch fastapi uvicorn
```

Wrap `KPipeline(lang_code=...)` (from the `kokoro` package) in a small FastAPI
app exposing the two endpoints above, keeping a dict of pipelines keyed by
`lang_code` so each is only built once. Dockerize it with GPU passthrough and
build/run it as `kokoro-service`, listening on `127.0.0.1:8770` (the default
`KOKORO_SERVICE_URL` in `config.py`).

**Once built**, Kokoro runs inside Docker and starts automatically at boot
(`--restart unless-stopped`):

```bash
# Start the container (if stopped)
docker start kokoro-service

# View live logs
docker logs -f kokoro-service

# Check health
curl http://127.0.0.1:8770/health

# Rebuild and run (if Kokoro is down or unresponsive)
cd ~/kokoro-service
docker stop kokoro-service && docker rm kokoro-service
docker build -t kokoro-service .
docker run -d --name kokoro-service \
  --restart unless-stopped \
  --gpus all \
  -p 127.0.0.1:8770:8770 \
  kokoro-service
```

### 2.2 ZoMa Brain server

**Prerequisites:**

- **NVIDIA CUDA GPU available** — Whisper initializes with `device="cuda"` by
  default; a functional CUDA GPU is required.
- **Ollama running** locally (`http://localhost:11434/api/chat`).
- **Kokoro TTS running** — verify with `curl http://127.0.0.1:8770/health`
  (see §2.1 above).
- **The Pi's camera stream running** — see §1.1 above.
- **Environment variables**:
  - `ANTHROPIC_API_KEY` — required for Claude uplink sessions (warns if missing).
  - `HF_TOKEN` — required for speaker diarization/ID (speaker ID disables itself
    with a warning if unset).
- **System prompt file** — the target prompt file (e.g. `clorian_prompt.txt`) must
  exist relative to `monster/zoma-brain/`.

**Starting the server:**

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

*ZoMa is property of TheMechanics. Contact: mamau.mechanics@gmail.com*
