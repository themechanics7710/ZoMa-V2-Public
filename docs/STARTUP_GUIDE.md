# ZoMa — Startup Guide

How to bring the whole system up: the Raspberry Pi's OS setup, ROS 2
container, camera stream, and audio/LED processes, then the off-board GPU
machine's (**Monster** — see [ARCHITECTURE.md](ARCHITECTURE.md)) Kokoro TTS
service and the ZoMa Brain server itself, and finally the web dashboard.
Start the Pi first, then Monster — ZoMa Brain connects out to the Pi's
camera stream on startup.

---

## 1. Raspberry Pi

### 1.0 Base OS setup

- Flash **Raspberry Pi OS (64-bit)** onto the microSD card with the
  [Raspberry Pi Imager](https://www.raspberrypi.com/software/) — use its
  "Edit Settings" step to set a hostname (`rb1` throughout this repo's
  examples), enable SSH, and configure Wi-Fi, so the Pi is reachable headless
  on first boot.
- Enable the camera, I2C, and SPI interfaces. **SPI is off by default** and
  is needed for the LuMini LED ring's `spidev` driver (§1.3):
  ```bash
  sudo raspi-config
  # Interface Options -> Camera -> Enable
  # Interface Options -> I2C     -> Enable
  # Interface Options -> SPI     -> Enable
  sudo reboot
  ```
- Install Docker (needed for the ROS 2 container below):
  ```bash
  curl -fsSL https://get.docker.com | sh
  sudo usermod -aG docker $USER   # log out/in for this to take effect
  ```

### 1.1 ROS 2 container (`zoma_ros_pi_v2`)

The Pi runs a single long-lived Docker container providing ROS 2 Humble — it
hosts the micro-ROS agent that bridges `esp32_rx`'s `deploy_ros` firmware to
the rest of the system, and it's where the `-hud` diagnostics scripts (§1.3)
run, since `rclpy` isn't installed on the Pi host directly.

[`pi/docker/Dockerfile`](../pi/docker/Dockerfile) builds a container with the
same runtime characteristics as the one this build actually runs
(reconstructed against the live container's `docker inspect` output, not the
original Dockerfile — if you have your own, use it instead):

```bash
docker build -t zoma_ros_pi_v2 pi/docker/
docker run -d --name zoma_ros_pi_v2 \
  --privileged \
  --network host \
  --restart always \
  -v /dev:/dev \
  -v ~/zoma_nav_ws:/zoma_nav_ws \
  zoma_ros_pi_v2
```

- `--privileged` + `-v /dev:/dev` — device access for the micro-ROS agent
  (the RX board's USB-serial connection) and other host devices as needed.
- `--network host` — required for ROS 2's DDS discovery to work correctly
  between the container and the rest of the Pi.
- `-v ~/zoma_nav_ws:/zoma_nav_ws` — an empty workspace directory, bind-mounted
  so ROS 2 packages can be developed without rebuilding the image. Empty for
  now; this is where Season 2's Nav2 packages will eventually live.
- The container's entrypoint keeps it running (`tail -f /dev/null`) rather
  than running a single foreground process — `start_zoma_audio_hud_pi.sh`
  `docker cp`'s a script in and `docker exec`'s it there on demand, instead
  of the container doing anything on its own.

### 1.2 Camera stream (MediaMTX)

The camera feed is served by [MediaMTX](https://github.com/bluenviron/mediamtx)
(a standalone media server) running on the Pi, republishing the Pi camera as
both RTSP (for ZoMa Brain's vision pipeline) and WebRTC (for the web
dashboard's live feed), using MediaMTX's built-in Raspberry Pi Camera source
— no separate `rpicam-vid`/`ffmpeg` piping needed. MediaMTX itself isn't part
of this repo — it's a general-purpose open-source tool, installed directly on
the Pi.

**Install:**

```bash
# On the Pi (aarch64):
curl -LO https://github.com/bluenviron/mediamtx/releases/latest/download/mediamtx_linux_arm64v8.tar.gz
tar -xzf mediamtx_linux_arm64v8.tar.gz
sudo mv mediamtx /usr/local/bin/
```

**Configure:** use [`pi/mediamtx.yml`](../pi/mediamtx.yml) — MediaMTX's
standard default config with one path defined, at the ports ZoMa Brain and
the web dashboard already expect by default (RTSP `8554`, WebRTC `8889`):

```yaml
paths:
  cam:
    source: rpiCamera
    rpiCameraWidth: 1920
    rpiCameraHeight: 1080
    rpiCameraFPS: 30
    rpiCameraBitrate: 4500000
    rpiCameraCodec: hardwareH264
    rpiCameraHDR: false
    rpiCameraShutter: 8000
    rpiCameraMetering: centre
    rpiCameraEV: 0.5
    rpiCameraDenoise: "cdn_off"
```

**Run:**

```bash
mediamtx /path/to/pi/mediamtx.yml
```

Set this up as a systemd service so it starts at boot. Verify it's working
before moving on:

```bash
ffplay rtsp://<pi-host>:8554/cam       # RTSP, from another machine
# or open http://<pi-host>:8889/cam/ in a browser for the WebRTC view
```

### 1.3 Audio, mic, and LED status scripts

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
directly) inside the `zoma_ros_pi_v2` container (§1.1) — start that container
first if you want `-hud` diagnostics.

**ReSpeaker recovery:** if mic capture wedges (repeated fast `arecord`
failures), `zoma_mic_client.py`'s recovery path calls
`reset_respeaker.sh`, which reboots the XVF3800's onboard DSP firmware via
`respeaker/xvf_init.sh`. Run `xvf_init.sh` once manually after first setting
up the mic array, and wire it into a systemd unit that runs at boot, before
the audio/LED scripts start.

### 1.4 Enrolling a voice for speaker ID

ZoMa Brain's speaker ID matches incoming mic audio against a "voice gallery"
of short recordings — `monster/zoma-brain/data/voice_gallery/*.wav` on
Monster. Record with the same mic the robot actually uses — accuracy depends
on matching the real microphone, not a phone or laptop mic — directly on the
Pi:

```bash
sudo apt install -y sox

# ~8s of normal speech, using the ReSpeaker mic array:
arecord -D plughw:CARD=Array,DEV=0 -f S16_LE -r 16000 -c 2 -t wav -d 8 raw_take1.wav

# Trim leading/trailing silence, normalize volume, and down-mix to mono:
sox raw_take1.wav -c 1 Alex_take1.wav norm silence 1 0.1 1% reverse silence 1 0.1 1% reverse
```

Record a few takes per person (`Alex_take1.wav`, `Alex_take2.wav`, ...) —
`zoma_brain_server.py`'s `init_speaker_id()` groups every `.wav` file by the
part of its filename before the first underscore, and averages all of a
person's takes into one profile. The exact sample rate/channel count of the
source recording doesn't matter beyond this — every gallery file is
auto-converted to mono/16kHz on load — but the filename prefix is what
identifies the person.

Copy the finished files into `monster/zoma-brain/data/voice_gallery/` on
Monster (they're gitignored there — personal recordings are never
committed), then (re)start `zoma_brain_server.py` to pick them up.

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

### 2.2 Ollama + Qwen models

ZoMa Brain's local (Tier 1) inference and its vision-language analysis run
through [Ollama](https://ollama.com), talked to over plain HTTP — not a pip
package, so it isn't in `requirements.txt`. Install it and pull the two
models ZoMa Brain expects by default:

```bash
curl -fsSL https://ollama.com/install.sh | sh

ollama pull qwen3:14b        # text model (config.QWEN_TEXT_MODEL)
ollama pull qwen2.5vl:7b     # vision-language model (config.QWEN_VL_MODEL)
```

Ollama starts its own local API server automatically on
`http://localhost:11434`. Override either model via the `QWEN_TEXT_MODEL` /
`QWEN_VL_MODEL` environment variables if you'd rather run different model
sizes for your GPU.

### 2.3 ZoMa Brain server

**Install the Python dependencies:**

```bash
cd monster/zoma-brain/
pip install -r requirements.txt
```

`torch`/`torchaudio` pull in a CPU-only build by default on some platforms —
if `torch.cuda.is_available()` comes back `False` after installing, reinstall
from PyTorch's CUDA index instead, e.g.:

```bash
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121
```

**Prerequisites:**

- **NVIDIA CUDA GPU available** — Whisper initializes with `device="cuda"` by
  default (no CPU fallback), and Tier 1 local inference (Qwen via Ollama)
  needs it too. Running ZoMa fully GPU-free — targeting Claude for every
  query instead of local Qwen, and making Whisper's device configurable —
  isn't implemented in this build; see
  [ARCHITECTURE.md](ARCHITECTURE.md#3-software-stack).
- **Ollama running**, with the Qwen models pulled — see §2.2 above.
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

## 3. Web dashboard

`web/index.html` is a static page — no build step, no server-side code.

1. Open it in a text editor and set the two `<YOUR_ZOMA_BRAIN_HOST>`
   placeholders (in the two `<script>` blocks) to Monster's LAN address — the
   same host `zoma_brain_server.py` is running on.
2. Serve the `web/` directory with a simple HTTP server — more reliable than
   opening the file directly, since the camera `<iframe>` can hit
   mixed-content restrictions when loaded from a bare `file://` page:
   ```bash
   cd web/
   python3 -m http.server 8000
   ```
3. Open `http://<any machine on your LAN>:8000/` in a browser. Both the Pi's
   camera stream (§1.2) and `zoma_brain_server.py` (§2.3) need to be running
   first.

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
