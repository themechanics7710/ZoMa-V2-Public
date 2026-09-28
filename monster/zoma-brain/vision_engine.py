"""
ZoMa Brain — Tier 2 vision analysis (Qwen-VL)
Property of TheMechanics. Contact: mamau.mechanics@gmail.com

Frame-to-description calls against Qwen-VL over Ollama, plus the shared
frame-encoding helpers used by both the local vision path and the Claude
uplink path.
"""

import base64
import cv2
import requests

import config


def encode_frame_b64(frame) -> str:
    """BGR numpy array (from cv2/VisionStream) -> base64 JPEG, no data URI prefix."""
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        raise ValueError("Failed to JPEG-encode frame")
    return base64.b64encode(buf).decode("utf-8")


def save_frame_jpeg(frame, path: str) -> bool:
    """
    BGR numpy array (from vision_stream.get_latest_frame()) -> JPEG file
    on disk, for the "take a picture" command. Returns False on failure
    instead of raising, so callers can check the result rather than
    wrapping this in a try/except.
    """
    try:
        return bool(cv2.imwrite(path, frame))
    except Exception as e:
        print(f" [VISION] Failed to save frame to {path}: {e}")
        return False


def analyze_frame(prompt: str, frame, timeout: float = None) -> str:
    """
    Blocking call to Qwen-VL via Ollama. Returns a plain-text description,
    or a "[SYSTEM ERROR] ..." string on failure -- same convention as
    smart_tools.py's other live-data tools, so callers can just check the
    prefix instead of catching exceptions. Deliberately synchronous
    (requests, not aiohttp): the Tier 1 background thread that also calls
    this has no event loop to protect in the first place, so one blocking
    implementation serves both callers.
    """
    if frame is None:
        return "[SYSTEM ERROR] No frame available to analyze."

    timeout = timeout or config.QWEN_VL_TIMEOUT

    try:
        image_b64 = encode_frame_b64(frame)
    except Exception as e:
        return f"[SYSTEM ERROR] Frame encoding failed: {e}"

    payload = {
        "model": config.QWEN_VL_MODEL,
        "messages": [
            {"role": "user", "content": prompt, "images": [image_b64]}
        ],
        "stream": False,
        "options": {"temperature": 0.3, "num_predict": 200},
        # Ollama-specific: how long to keep Qwen-VL resident in VRAM
        # after this call. Kept short since the vision and text models
        # compete for the same GPU memory.
        "keep_alive": getattr(config, "QWEN_VL_KEEP_ALIVE", "5m"),
    }

    try:
        resp = requests.post(config.OLLAMA_API_URL, json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        description = data.get("message", {}).get("content", "").strip()
        return description or "[SYSTEM ERROR] Qwen-VL returned an empty response."
    except requests.exceptions.Timeout:
        return "[SYSTEM ERROR] Qwen-VL analysis timed out."
    except Exception as e:
        return f"[SYSTEM ERROR] Qwen-VL analysis failed: {e}"
