"""Unified Video Stream Manager & Ingestion Engine for Sentinel CCTV.

Coordinates on-demand RTSP connections, bounded frame queues with drop-oldest
backpressure, live snapshot caching, real-time health telemetry, and AI worker distribution.
"""

import asyncio
import collections
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Deque, Dict, List, Optional

import cv2
import numpy as np

from app.core.config import get_settings
from app.core.logging import get_logger
from app.integrations.sentinel.client import sentinel_client
from app.integrations.sentinel.rtsp import build_public_rtsp_path, redact_url, validate_camera_id
from app.schemas.stream import StreamWorkerState, VideoFrame

logger = get_logger(__name__)
settings = get_settings()


class CameraStreamSession:
    """Active streaming session for an individual CCTV camera."""

    def __init__(
        self,
        camera_id: str,
        max_queue_size: int = 10,
        frame_callback: Optional[Callable[[VideoFrame], None]] = None,
    ):
        self.camera_id = validate_camera_id(camera_id)
        self.max_queue_size = max_queue_size
        self.frame_callback = frame_callback

        self._frame_queue: Deque[VideoFrame] = collections.deque(maxlen=max_queue_size)
        self._latest_jpeg: Optional[bytes] = None
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        # Telemetry
        self.state = StreamWorkerState.INITIALIZING
        self.is_online = False
        self.total_frames_received = 0
        self.dropped_frames = 0
        self.reconnect_count = 0
        self.decode_errors = 0
        self.last_frame_time: Optional[datetime] = None
        self.latency_ms = 0.0
        self.codec = "h264"
        self.width = 1920
        self.height = 1080
        self.measured_fps = 0.0
        self.last_error: Optional[str] = None

        # Rolling FPS calculation
        self._timestamps: Deque[float] = collections.deque(maxlen=30)

    def start(self):
        """Start ingestion thread for this camera."""
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop_event.clear()
            self.state = StreamWorkerState.CONNECTING
            self._thread = threading.Thread(
                target=self._run_loop,
                name=f"SentinelStream-{self.camera_id}",
                daemon=True,
            )
            self._thread.start()
            logger.info(f"Started video ingestion session for camera '{self.camera_id}'")

    def stop(self, timeout: float = 2.0):
        """Signal ingestion loop to stop."""
        self._stop_event.set()
        with self._lock:
            self.state = StreamWorkerState.STOPPED
            self.is_online = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def get_latest_frame(self) -> Optional[VideoFrame]:
        """Retrieve most recent decoded frame with zero waiting."""
        with self._lock:
            if self._frame_queue:
                return self._frame_queue[-1]
            return None

    def _generate_standby_frame(self) -> bytes:
        """Generate tactical CCTV standby frame when waiting for remote RTSP packets."""
        now_utc = datetime.now(timezone.utc)
        width, height = 640, 360
        img = np.zeros((height, width, 3), dtype=np.uint8)
        img[:, :] = (12, 17, 28)

        # Tactical border
        cv2.rectangle(img, (10, 10), (width - 10, height - 10), (35, 45, 70), 1)

        cv2.putText(
            img,
            "GUJARAT POLICE SURVEILLANCE NODE",
            (25, 45),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (0, 200, 255),
            1,
            cv2.LINE_AA,
        )
        cv2.putText(
            img,
            f"CAMERA: {self.camera_id.upper()}",
            (25, 95),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )

        status_text = "STATUS: LIVE RTSP INGESTION ACTIVE" if self.is_online else f"STATUS: CONNECTING (Attempt #{self.reconnect_count + 1})"
        status_color = (0, 255, 120) if self.is_online else (0, 180, 255)

        cv2.putText(
            img,
            status_text,
            (25, 140),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.48,
            status_color,
            1,
            cv2.LINE_AA,
        )
        cv2.putText(
            img,
            now_utc.strftime("%Y-%m-%d %H:%M:%S UTC"),
            (25, 180),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (180, 180, 180),
            1,
            cv2.LINE_AA,
        )
        cv2.putText(
            img,
            "25 FPS | 1920x1080 | TCP RTSP",
            (25, 220),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.42,
            (130, 150, 180),
            1,
            cv2.LINE_AA,
        )

        ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        return buf.tobytes() if ok else b""

    def get_latest_jpeg(self) -> bytes:
        """Retrieve cached JPEG snapshot or tactical frame."""
        with self._lock:
            if self._latest_jpeg:
                return self._latest_jpeg
        return self._generate_standby_frame()

    async def mjpeg_generator(self):
        """Generates continuous multipart JPEG stream for real-time browser playback."""
        last_sent = None
        placeholder = (
            b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00\xff\xdb\x00C\x00\x08\x06"
            b"\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f"
            b"\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342\xff\xc0"
            b"\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01"
            b"\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t"
            b"\n\x0b\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xbf\x00\xff\xd9"
        )
        while not self._stop_event.is_set():
            jpeg = self.get_latest_jpeg()
            if jpeg and jpeg != last_sent:
                last_sent = jpeg
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
                )
            elif last_sent is None:
                last_sent = placeholder
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + placeholder + b"\r\n"
                )
            await asyncio.sleep(0.04)  # ~25 FPS

    def _run_loop(self):
        """Continuous video frame ingestion loop with exponential reconnect."""
        reconnect_attempt = 0
        seq = 0

        while not self._stop_event.is_set():
            raw_url = sentinel_client.get_rtsp_url(self.camera_id)
            redacted = redact_url(raw_url)
            sentinel_client._configure_tcp_transport()

            cap = None
            try:
                self.state = StreamWorkerState.CONNECTING
                start_t = time.time()
                cap = cv2.VideoCapture(raw_url, cv2.CAP_FFMPEG)
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

                if not cap.isOpened():
                    raise ConnectionError(f"Failed to open RTSP socket at {redacted}")

                # Read first test frame
                ret, first_frame = cap.read()
                if not ret or first_frame is None or first_frame.size == 0:
                    raise ConnectionError(f"Connected to {redacted} but received 0-byte frame")

                self.latency_ms = round((time.time() - start_t) * 1000, 1)
                self.height, self.width = first_frame.shape[:2]
                self.is_online = True
                self.state = StreamWorkerState.STREAMING
                self.last_error = None
                reconnect_attempt = 0
                logger.info(f"Stream connected for '{self.camera_id}' ({self.width}x{self.height} @ {self.latency_ms}ms)")

                # Process initial frame
                seq += 1
                self._handle_frame(first_frame, seq)

                # Continuous frame ingestion
                while not self._stop_event.is_set():
                    ret, frame = cap.read()
                    if not ret or frame is None or frame.size == 0:
                        logger.warning(f"Frame grab failed or stream stalled for '{self.camera_id}'")
                        self.decode_errors += 1
                        break

                    seq += 1
                    self._handle_frame(frame, seq)

            except Exception as e:
                self.last_error = redact_url(str(e))
                self.is_online = False
                self.state = StreamWorkerState.ERROR
                self.decode_errors += 1
                logger.warning(f"Stream error on '{self.camera_id}': {self.last_error}")

            finally:
                if cap is not None:
                    cap.release()

            if self._stop_event.is_set():
                break

            # Calculate exponential backoff reconnect delay: 1s, 2s, 4s, 8s, 16s, max 30s
            reconnect_attempt += 1
            self.reconnect_count += 1
            delay = sentinel_client.calculate_reconnect_delay(reconnect_attempt, settings.SENTINEL_RECONNECT_MAX_DELAY)
            self.state = StreamWorkerState.RECONNECTING
            logger.info(f"Reconnecting stream for '{self.camera_id}' in {delay:.1f}s (Attempt #{reconnect_attempt})")

            # Sleep in increments to respond promptly to stop signal
            sleep_intervals = int(delay * 10)
            for _ in range(sleep_intervals):
                if self._stop_event.is_set():
                    break
                time.sleep(0.1)

    def _handle_frame(self, frame: np.ndarray, sequence_number: int):
        """Process incoming raw frame, measure FPS, and update bounded queue."""
        now_utc = datetime.now(timezone.utc)
        now_ts = time.time()

        self._timestamps.append(now_ts)
        if len(self._timestamps) >= 2:
            duration = self._timestamps[-1] - self._timestamps[0]
            if duration > 0:
                self.measured_fps = round((len(self._timestamps) - 1) / duration, 1)

        self.last_frame_time = now_utc
        self.total_frames_received += 1

        # Smooth JPEG encoding for real-time browser stream
        try:
            ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
            if ok:
                with self._lock:
                    self._latest_jpeg = buf.tobytes()
        except Exception:
            pass

        video_frame = VideoFrame(
            camera_id=self.camera_id,
            frame_index=sequence_number,
            timestamp_utc=now_utc,
            image=frame,
            width=self.width,
            height=self.height,
            fps=self.measured_fps,
        )

        with self._lock:
            # Backpressure: If queue is full, drop oldest frame to keep AI ingestion realtime
            if len(self._frame_queue) == self.max_queue_size:
                self.dropped_frames += 1
            self._frame_queue.append(video_frame)

        if self.frame_callback:
            try:
                self.frame_callback(video_frame)
            except Exception as e:
                logger.error(f"Error in frame_callback for '{self.camera_id}': {e}")

    def get_health_telemetry(self) -> Dict[str, Any]:
        """Return real-time sanitized health telemetry for this camera."""
        return {
            "camera_id": self.camera_id,
            "is_online": self.is_online,
            "state": self.state.value if hasattr(self.state, "value") else str(self.state),
            "measured_fps": self.measured_fps,
            "latency_ms": self.latency_ms,
            "resolution_width": self.width,
            "resolution_height": self.height,
            "codec": self.codec,
            "reconnect_count": self.reconnect_count,
            "decoder_errors": self.decode_errors,
            "total_frames_received": self.total_frames_received,
            "dropped_frames": self.dropped_frames,
            "last_frame_time": self.last_frame_time.isoformat() if self.last_frame_time else None,
            "last_error": self.last_error,
        }


class VideoStreamManager:
    """Manages pool of active CCTV camera stream sessions."""

    def __init__(self):
        self._sessions: Dict[str, CameraStreamSession] = {}
        self._lock = threading.Lock()

    def get_or_create_session(
        self,
        camera_id: str,
        frame_callback: Optional[Callable[[VideoFrame], None]] = None,
    ) -> CameraStreamSession:
        """Get or initialize active stream session for a camera."""
        valid_id = validate_camera_id(camera_id)
        with self._lock:
            if valid_id not in self._sessions:
                session = CameraStreamSession(
                    camera_id=valid_id,
                    frame_callback=frame_callback,
                )
                self._sessions[valid_id] = session
                session.start()
            return self._sessions[valid_id]

    def stop_session(self, camera_id: str):
        """Stop and tear down stream session for a camera."""
        valid_id = validate_camera_id(camera_id)
        with self._lock:
            session = self._sessions.pop(valid_id, None)
            if session:
                session.stop()

    def get_session(self, camera_id: str) -> Optional[CameraStreamSession]:
        """Get active session if running."""
        valid_id = validate_camera_id(camera_id)
        with self._lock:
            return self._sessions.get(valid_id)

    def get_camera_health(self, camera_id: str) -> Dict[str, Any]:
        """Get current health telemetry for a camera."""
        valid_id = validate_camera_id(camera_id)
        session = self.get_session(valid_id)
        if session:
            return session.get_health_telemetry()

        # Fallback default offline structure
        return {
            "camera_id": valid_id,
            "is_online": False,
            "state": "OFFLINE",
            "measured_fps": 0.0,
            "latency_ms": 0.0,
            "resolution_width": 1920,
            "resolution_height": 1080,
            "codec": "h264",
            "reconnect_count": 0,
            "decoder_errors": 0,
            "total_frames_received": 0,
            "dropped_frames": 0,
            "last_frame_time": None,
            "last_error": "Stream not active in session pool",
        }

    def shutdown_all(self):
        """Stop all active camera ingestion threads upon system shutdown."""
        with self._lock:
            for cid, session in list(self._sessions.items()):
                try:
                    session.stop()
                except Exception:
                    pass
            self._sessions.clear()
            logger.info("All camera stream sessions stopped cleanly.")


# Singleton video stream manager
video_stream_manager = VideoStreamManager()
