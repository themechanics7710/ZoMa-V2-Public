"""
ZoMa Brain — camera ingestion and lightweight motion/face detection
Property of TheMechanics. Contact: mamau.mechanics@gmail.com

Tier 0: a background thread continuously pulls frames from ZoMa's RTSP
feed and holds only the latest frame in memory -- no detection, no
inference, just a live, always-fresh frame buffer that other tiers can
read from without blocking each other or the websocket event loop.

Tier 1: a second background thread that samples the latest frame
periodically and runs two cheap OpenCV checks -- frame-diff motion
detection and a Haar cascade face detector. On a trigger it logs a
vision event to the FAISS memory core.
"""

import cv2
import threading
import time
import logging
import os
import vision_engine

# Force OpenCV's FFmpeg backend to use TCP instead of UDP for RTSP,
# and set a 5-second max timeout (5000000 microseconds)
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|timeout;5000000"

logger = logging.getLogger("vision_stream")


class VisionStream:
    def __init__(
        self,
        stream_url: str,
        reconnect_delay: float = 3.0,
        memory_provider=None,
        tier1_enabled: bool = True,
        tier1_interval: float = 1.5,
        motion_threshold: int = 25,
        motion_min_area: int = 5000,
        motion_cooldown: float = 30.0,
        face_cooldown: float = 30.0,
        tier2_enabled: bool = True,
        tier2_timeout: float = 15.0,
    ):
        """
        stream_url: RTSP url, e.g. 'rtsp://rb1.local:8554/cam'
        memory_provider: zero-arg callable returning the current
            BrainMemory instance, or None if it isn't loaded yet. A
            callable rather than a direct reference avoids a
            startup-ordering dependency between vision ingestion and
            model loading -- it can keep returning None until the
            caller's global is populated, and everything quietly
            no-ops until memory is ready.
        tier1_enabled: set False to run Tier 0 only (raw frame buffer,
            no detection loop).
        tier1_interval: seconds between Tier 1 detection samples.
        motion_threshold: pixel intensity delta (0-255) that counts as
            "changed" during frame differencing.
        motion_min_area: minimum contour area (pixels) for a changed
            region to count as real motion rather than noise.
        motion_cooldown / face_cooldown: minimum seconds between two
            logged events of the same type, to avoid flooding memory.
        """
        self.tier2_enabled = tier2_enabled
        self.tier2_timeout = tier2_timeout

        self.stream_url = stream_url
        self.reconnect_delay = reconnect_delay
        self.memory_provider = memory_provider

        self._cap = None
        self._latest_frame = None
        self._frame_lock = threading.Lock()
        self._last_frame_time = 0.0

        self._running = False
        self._capture_thread = None

        # --- Tier 1 config/state ---
        self.tier1_enabled = tier1_enabled
        self.tier1_interval = tier1_interval
        self.motion_threshold = motion_threshold
        self.motion_min_area = motion_min_area
        self.motion_cooldown = motion_cooldown
        self.face_cooldown = face_cooldown

        self._tier1_thread = None
        self._prev_gray = None
        self._last_motion_event_time = 0.0
        self._last_face_event_time = 0.0
        self._face_cascade = None

    # --- lifecycle ----------------------------------------------------------

    def start(self):
        if self._running:
            return
        self._running = True

        self._capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._capture_thread.start()
        logger.info(f"[VISION] Capture thread started for {self.stream_url}")

        if self.tier1_enabled:
            if not self._load_face_cascade():
                logger.warning("[VISION] Face cascade failed to load; Tier 1 will run motion-only.")
            self._tier1_thread = threading.Thread(target=self._tier1_loop, daemon=True)
            self._tier1_thread.start()
            logger.info(f"[VISION] Tier 1 detection thread started (interval={self.tier1_interval}s).")

    def stop(self):
        self._running = False
        if self._capture_thread:
            self._capture_thread.join(timeout=2.0)
        if self._tier1_thread:
            self._tier1_thread.join(timeout=2.0)
        if self._cap:
            self._cap.release()
        logger.info("[VISION] Capture stopped.")

    # --- internal capture loop (runs in its own thread) ------------------------

    def _open_capture(self):
        cap = cv2.VideoCapture(self.stream_url, cv2.CAP_FFMPEG)
        # Keep internal buffer at 1 frame so we always read the freshest one,
        # not a queued-up backlog.
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return cap

    def _capture_loop(self):
        while self._running:
            self._cap = self._open_capture()

            if not self._cap.isOpened():
                logger.warning(
                    f"[VISION] Could not open stream at {self.stream_url}. "
                    f"Retrying in {self.reconnect_delay}s..."
                )
                self._cap.release()
                time.sleep(self.reconnect_delay)
                continue

            logger.info("[VISION] Stream connected.")

            while self._running:
                ok, frame = self._cap.read()
                if not ok:
                    logger.warning("[VISION] Frame read failed. Reconnecting...")
                    break

                with self._frame_lock:
                    self._latest_frame = frame
                    self._last_frame_time = time.time()

            self._cap.release()
            if self._running:
                time.sleep(self.reconnect_delay)

    # --- public accessors (Tier 0) -----------------------------------------------------

    def get_latest_frame(self, max_age: float = 2.0):
        """
        Returns the most recent frame (numpy BGR array), or None if either
        no frame has ever arrived, or the freshest one is older than
        max_age seconds (stream stalled/dropped).
        """
        with self._frame_lock:
            if self._latest_frame is None:
                return None
            if (time.time() - self._last_frame_time) > max_age:
                return None
            return self._latest_frame.copy()

    def is_alive(self) -> bool:
        return (
            self._latest_frame is not None
            and (time.time() - self._last_frame_time) < self.reconnect_delay * 2
        )

    # --- Tier 1: lightweight motion + face detection ---------------------------------

    def _load_face_cascade(self) -> bool:
        try:
            cascade_path = "haarcascade_frontalface_default.xml"
            cascade = cv2.CascadeClassifier(cascade_path)
            if cascade.empty():
                return False
            self._face_cascade = cascade
            return True
        except Exception as e:
            logger.warning(f"[VISION] Could not load Haar cascade: {e}")
            return False

    def _tier1_loop(self):
        # Give the capture thread a head start so we're not immediately
        # working off a None frame.
        time.sleep(min(self.tier1_interval, 2.0))

        while self._running:
            frame = self.get_latest_frame(max_age=self.tier1_interval * 3)
            if frame is None:
                time.sleep(self.tier1_interval)
                continue

            try:
                self._process_tier1_frame(frame)
            except Exception as e:
                logger.warning(f"[VISION] Tier 1 processing error: {e}")

            time.sleep(self.tier1_interval)

    def _process_tier1_frame(self, frame):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (21, 21), 0)

        # 1. Check for motion first and receive a boolean flag
        has_motion = self._check_motion(gray, frame)

        # 2. Only check for faces if there was actual frame movement!
        if has_motion:
            self._check_faces(gray, frame)

        self._prev_gray = gray

    def _check_motion(self, gray, frame) -> bool:
        if self._prev_gray is None:
            return False

        frame_delta = cv2.absdiff(self._prev_gray, gray)
        thresh = cv2.threshold(frame_delta, self.motion_threshold, 255, cv2.THRESH_BINARY)[1]
        thresh = cv2.dilate(thresh, None, iterations=2)
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        largest_area = max((cv2.contourArea(c) for c in contours), default=0)
        if largest_area < self.motion_min_area:
            return False  # No significant motion

        now = time.time()
        if now - self._last_motion_event_time >= self.motion_cooldown:
            self._last_motion_event_time = now
            self._log_event(
                frame=frame,
                trigger_reason="motion_detected",
                vl_prompt=(
                    "You are a security camera. In ONE short sentence, describe what "
                    "moved or is visible in this frame — people, animals, vehicles, or "
                    "objects. Be concrete and factual, no speculation."
                ),
                fallback_description=(
                    f"Motion detected in ZoMa's camera feed "
                    f"(largest changed region ~{int(largest_area)}px)."
                ),
            )

        return True  # Motion was confirmed

    def _check_faces(self, gray, frame):
        if self._face_cascade is None:
            return

        # minNeighbors=8 to filter out false static patterns.
        faces = self._face_cascade.detectMultiScale(
            gray, scaleFactor=1.15, minNeighbors=8, minSize=(60, 60)
        )
        if len(faces) == 0:
            return

        now = time.time()
        if now - self._last_face_event_time < self.face_cooldown:
            return
        self._last_face_event_time = now

        count = len(faces)
        self._log_event(
            frame=frame,
            trigger_reason="face_detected",
            vl_prompt=(
                "You are a security camera. In ONE short sentence, describe the "
                "person or people visible — appearance, location in frame, what "
                "they appear to be doing. Be concrete, no speculation about identity."
            ),
            fallback_description=(
                f"Face detected in ZoMa's camera feed "
                f"({count} face{'s' if count != 1 else ''})."
            ),
        )

    def _log_event(self, frame, trigger_reason: str, vl_prompt: str, fallback_description: str):
        memory = self.memory_provider() if self.memory_provider else None
        if memory is None:
            logger.info(f"[VISION] {trigger_reason} (memory not ready yet, event not logged)")
            return

        description = fallback_description
        if self.tier2_enabled:
            try:
                vl_result = vision_engine.analyze_frame(vl_prompt, frame, timeout=self.tier2_timeout)
                if vl_result and not vl_result.startswith("[SYSTEM ERROR]"):
                    description = vl_result
                else:
                    logger.warning(f"[VISION] Tier 2 analysis failed, using generic log: {vl_result}")
            except Exception as e:
                logger.warning(f"[VISION] Tier 2 analysis raised an exception: {e}")

        try:
            memory.add_vision_event(description, trigger_reason=trigger_reason)
        except Exception as e:
            logger.warning(f"[VISION] Failed to log vision event to memory: {e}")

# --- manual smoke test: `python vision_stream.py` -----------------------------
if __name__ == "__main__":
    import config

    logging.basicConfig(level=logging.INFO)

    vs = VisionStream(config.ZOMA_STREAM_URL, config.ZOMA_RECONNECT_DELAY)
    vs.start()

    try:
        while True:
            frame = vs.get_latest_frame(max_age=config.ZOMA_FRAME_MAX_AGE)
            if frame is not None:
                print(f"Got frame: {frame.shape}")
                cv2.imshow("ZoMa Feed", frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
            else:
                print("No frame yet...")
                time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        vs.stop()
        cv2.destroyAllWindows()
