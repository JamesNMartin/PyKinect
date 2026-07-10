"""Record Kinect v2 body tracking data to a portable JSON Lines file.

This program uses Microsoft's Kinect for Windows SDK 2.0 through PyKinect2.
Run it on Windows with a Kinect v2 connected to a USB 3.0 port.
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import math
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


JOINT_SPECS = (
    ("SpineBase", "JointType_SpineBase"),
    ("SpineMid", "JointType_SpineMid"),
    ("Neck", "JointType_Neck"),
    ("Head", "JointType_Head"),
    ("ShoulderLeft", "JointType_ShoulderLeft"),
    ("ElbowLeft", "JointType_ElbowLeft"),
    ("WristLeft", "JointType_WristLeft"),
    ("HandLeft", "JointType_HandLeft"),
    ("ShoulderRight", "JointType_ShoulderRight"),
    ("ElbowRight", "JointType_ElbowRight"),
    ("WristRight", "JointType_WristRight"),
    ("HandRight", "JointType_HandRight"),
    ("HipLeft", "JointType_HipLeft"),
    ("KneeLeft", "JointType_KneeLeft"),
    ("AnkleLeft", "JointType_AnkleLeft"),
    ("FootLeft", "JointType_FootLeft"),
    ("HipRight", "JointType_HipRight"),
    ("KneeRight", "JointType_KneeRight"),
    ("AnkleRight", "JointType_AnkleRight"),
    ("FootRight", "JointType_FootRight"),
    ("SpineShoulder", "JointType_SpineShoulder"),
    ("HandTipLeft", "JointType_HandTipLeft"),
    ("ThumbLeft", "JointType_ThumbLeft"),
    ("HandTipRight", "JointType_HandTipRight"),
    ("ThumbRight", "JointType_ThumbRight"),
)

HAND_JOINT_NAMES = (
    "WristLeft",
    "HandLeft",
    "HandTipLeft",
    "ThumbLeft",
    "WristRight",
    "HandRight",
    "HandTipRight",
    "ThumbRight",
)

BONES = (
    ("Head", "Neck"), ("Neck", "SpineShoulder"),
    ("SpineShoulder", "SpineMid"), ("SpineMid", "SpineBase"),
    ("SpineShoulder", "ShoulderLeft"), ("ShoulderLeft", "ElbowLeft"),
    ("ElbowLeft", "WristLeft"), ("WristLeft", "HandLeft"),
    ("HandLeft", "HandTipLeft"), ("WristLeft", "ThumbLeft"),
    ("SpineShoulder", "ShoulderRight"), ("ShoulderRight", "ElbowRight"),
    ("ElbowRight", "WristRight"), ("WristRight", "HandRight"),
    ("HandRight", "HandTipRight"), ("WristRight", "ThumbRight"),
    ("SpineBase", "HipLeft"), ("HipLeft", "KneeLeft"),
    ("KneeLeft", "AnkleLeft"), ("AnkleLeft", "FootLeft"),
    ("SpineBase", "HipRight"), ("HipRight", "KneeRight"),
    ("KneeRight", "AnkleRight"), ("AnkleRight", "FootRight"),
)

TRACKING_STATE_NAMES = {0: "not_tracked", 1: "inferred", 2: "tracked"}
HAND_STATE_NAMES = {
    0: "unknown",
    1: "not_tracked",
    2: "open",
    3: "closed",
    4: "lasso",
}
HAND_CONFIDENCE_NAMES = {0: "low", 1: "high"}
HAND_MARKER_COLORS = {
    "open": (65, 210, 154),
    "closed": (238, 77, 92),
    "lasso": (96, 165, 250),
    "not_tracked": (145, 153, 166),
    "unknown": (145, 153, 166),
}


def selected_joint_specs(hands_only: bool) -> tuple[tuple[str, str], ...]:
    if not hands_only:
        return JOINT_SPECS
    specs_by_name = {name: constant for name, constant in JOINT_SPECS}
    return tuple((name, specs_by_name[name]) for name in HAND_JOINT_NAMES)


def patch_pykinect_source(source: str) -> tuple[str, bool]:
    """Patch two stale generated checks in legacy PyKinect2.

    STATSTG belongs to the SDK's unused audio/storage declarations. The PyPI
    bindings hard-code its old generated size even though current 64-bit
    Python/comtypes combinations report 80 bytes. The generated file also asks
    comtypes to validate an empty version string, which modern comtypes rejects.
    """
    replacements = (
        (
            "assert sizeof(tagSTATSTG) == 72, sizeof(tagSTATSTG)",
            "assert sizeof(tagSTATSTG) in (72, 80), sizeof(tagSTATSTG)",
        ),
        (
            "from comtypes import _check_version; _check_version('')",
            "# Skipped invalid empty comtypes version check (PyKinect2 compatibility).",
        ),
    )
    changed = False
    for old, new in replacements:
        if old in source:
            source = source.replace(old, new, 1)
            changed = True
    return source, changed


def import_pykinect2() -> tuple[Any, Any]:
    """Import PyKinect2, applying its known 64-bit assertion fix in memory."""
    import pykinect2

    module_name = "pykinect2.PyKinectV2"
    spec = importlib.util.find_spec(module_name)
    if spec is None or spec.origin is None:
        raise ImportError(f"Could not locate {module_name}")

    source = Path(spec.origin).read_text(encoding="utf-8")
    source, patched = patch_pykinect_source(source)
    if patched:
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        setattr(pykinect2, "PyKinectV2", module)
        try:
            exec(compile(source, spec.origin, "exec"), module.__dict__)
        except Exception:
            sys.modules.pop(module_name, None)
            if getattr(pykinect2, "PyKinectV2", None) is module:
                delattr(pykinect2, "PyKinectV2")
            raise
    else:
        module = importlib.import_module(module_name)

    runtime_module = importlib.import_module("pykinect2.PyKinectRuntime")
    return module, runtime_module


def load_kinect() -> tuple[Any, Any]:
    """Import the Windows-only dependencies and apply compatibility shims."""
    if sys.platform != "win32":
        raise RuntimeError(
            "Kinect SDK 2.0 and PyKinect2 require Windows. "
            "Run this recorder from a 64-bit Windows installation."
        )

    # PyKinect2 predates these removals in current Python/NumPy versions.
    if not hasattr(time, "clock"):
        time.clock = time.perf_counter  # type: ignore[attr-defined]
    try:
        import numpy as np

        if "object" not in np.__dict__:
            np.object = object  # type: ignore[attr-defined]
        PyKinectV2, PyKinectRuntime = import_pykinect2()
    except Exception as exc:
        raise RuntimeError(
            "Could not load PyKinect2. Install Kinect for Windows SDK 2.0, "
            "then run: py -m pip install -r requirements.txt"
        ) from exc
    return PyKinectV2, PyKinectRuntime


def finite(value: Any) -> float | None:
    number = float(value)
    return number if math.isfinite(number) else None


def vector4(value: Any) -> dict[str, float | None]:
    return {axis: finite(getattr(value, axis)) for axis in ("x", "y", "z", "w")}


def sensor_ticks(value: Any) -> int | None:
    """Normalize the SDK's RelativeTime value across comtypes versions."""
    if value is None:
        return None
    for attribute in ("value", "QuadPart"):
        if hasattr(value, attribute):
            value = getattr(value, attribute)
            break
    return int(value)


def extract_body(body: Any, joint_types: dict[str, int]) -> dict[str, Any]:
    """Convert a PyKinect2 body into JSON-compatible values."""
    output: dict[str, Any] = {}
    for name, joint_id in joint_types.items():
        joint = body.joints[joint_id]
        orientation = body.joint_orientations[joint_id].Orientation
        output[name] = {
            "position_m": {
                "x": finite(joint.Position.x),
                "y": finite(joint.Position.y),
                "z": finite(joint.Position.z),
            },
            "orientation_xyzw": vector4(orientation),
            "tracking_state": TRACKING_STATE_NAMES.get(
                int(joint.TrackingState), str(int(joint.TrackingState))
            ),
        }
    return output


def enum_name(value: Any, names: dict[int, str]) -> str:
    return names.get(int(value), str(int(value)))


def extract_hands(body: Any) -> dict[str, dict[str, str | None]]:
    """Convert Kinect SDK hand state and confidence values into readable data."""
    return {
        "left": {
            "state": enum_name(getattr(body, "hand_left_state", 0), HAND_STATE_NAMES),
            "confidence": enum_name(
                getattr(body, "hand_left_confidence", 0), HAND_CONFIDENCE_NAMES
            ),
        },
        "right": {
            "state": enum_name(getattr(body, "hand_right_state", 0), HAND_STATE_NAMES),
            "confidence": enum_name(
                getattr(body, "hand_right_confidence", 0), HAND_CONFIDENCE_NAMES
            ),
        },
    }


def hand_marker_color(hand: dict[str, str | None]) -> tuple[int, int, int]:
    if hand.get("confidence") != "high":
        return (235, 166, 59)
    return HAND_MARKER_COLORS.get(str(hand.get("state")), HAND_MARKER_COLORS["unknown"])


@dataclass
class RecordingSession:
    output_root: Path
    joint_names: list[str]
    capture_mode: str = "full_body"
    started_perf: float | None = None
    session_dir: Path | None = None
    stream: Any = None
    frame_count: int = 0
    color_writer: Any = None
    color_timestamps: Any = None
    color_frame_count: int = 0
    color_size: tuple[int, int] | None = None

    @property
    def active(self) -> bool:
        return self.stream is not None

    def start(self) -> Path:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        candidate = self.output_root / f"mocap_{stamp}"
        suffix = 1
        while candidate.exists():
            candidate = self.output_root / f"mocap_{stamp}_{suffix:02d}"
            suffix += 1
        candidate.mkdir(parents=True)
        self.session_dir = candidate
        self.stream = (candidate / "frames.jsonl").open("w", encoding="utf-8")
        self.started_perf = time.perf_counter()
        self.frame_count = 0
        self.color_frame_count = 0
        self.color_size = None
        return candidate

    def enable_color(self, cv2: Any, size: tuple[int, int], fps: float = 30.0) -> None:
        """Start an MJPEG AVI stream alongside the skeletal data."""
        if not self.active or self.session_dir is None:
            raise RuntimeError("Start the recording session before enabling color video")
        fourcc = cv2.VideoWriter_fourcc(*"MJPG")
        writer = cv2.VideoWriter(str(self.session_dir / "color.avi"), fourcc, fps, size)
        if not writer.isOpened():
            writer.release()
            raise RuntimeError("Could not create color.avi with the MJPEG codec")
        self.color_writer = writer
        self.color_timestamps = (self.session_dir / "color_timestamps.jsonl").open(
            "w", encoding="utf-8"
        )
        self.color_size = size

    def write_color(self, bgr_frame: Any) -> None:
        if self.color_writer is None:
            return
        recording_time = time.perf_counter() - float(self.started_perf)
        self.color_writer.write(bgr_frame)
        timestamp = {
            "color_frame_index": self.color_frame_count,
            "recording_time_s": recording_time,
            "captured_utc": datetime.now(timezone.utc).isoformat(),
        }
        self.color_timestamps.write(
            json.dumps(timestamp, separators=(",", ":")) + "\n"
        )
        self.color_timestamps.flush()
        self.color_frame_count += 1

    def write(self, payload: dict[str, Any]) -> None:
        if not self.active:
            return
        payload["frame_index"] = self.frame_count
        payload["recording_time_s"] = time.perf_counter() - float(self.started_perf)
        self.stream.write(json.dumps(payload, separators=(",", ":"), allow_nan=False) + "\n")
        self.stream.flush()
        self.frame_count += 1

    def stop(self) -> Path | None:
        if not self.active:
            return self.session_dir
        duration = time.perf_counter() - float(self.started_perf)
        self.stream.close()
        self.stream = None
        if self.color_writer is not None:
            self.color_writer.release()
            self.color_writer = None
        if self.color_timestamps is not None:
            self.color_timestamps.close()
            self.color_timestamps = None
        metadata = {
            "format": "pykinect-mocap-jsonl",
            "format_version": 1,
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "coordinate_system": {
                "origin": "Kinect camera",
                "units": "meters",
                "x": "camera left/right",
                "y": "up",
                "z": "away from camera",
            },
            "orientation_order": "x,y,z,w",
            "capture_mode": self.capture_mode,
            "joint_names": self.joint_names,
            "frame_count": self.frame_count,
            "duration_s": duration,
            "frames_file": "frames.jsonl",
        }
        if self.color_size is not None:
            metadata["color_video"] = {
                "file": "color.avi",
                "timestamps_file": "color_timestamps.jsonl",
                "codec": "MJPG",
                "nominal_fps": 30.0,
                "observed_capture_fps": self.color_frame_count / duration if duration else 0.0,
                "frame_count": self.color_frame_count,
                "width": self.color_size[0],
                "height": self.color_size[1],
            }
        assert self.session_dir is not None
        (self.session_dir / "session.json").write_text(
            json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
        )
        return self.session_dir


def nearest_body(bodies: Iterable[Any], spine_base_id: int) -> Any | None:
    tracked = [body for body in bodies if body is not None and body.is_tracked]
    if not tracked:
        return None
    return min(tracked, key=lambda body: float(body.joints[spine_base_id].Position.z))


def project(position: dict[str, float | None], width: int, height: int) -> tuple[int, int] | None:
    x, y, z = position["x"], position["y"], position["z"]
    if x is None or y is None or z is None or z <= 0:
        return None
    # Perspective projection for the simple preview (recorded values remain 3D).
    scale = min(width, height) * 1.15 / z
    return int(width / 2 + x * scale), int(height / 2 - y * scale)


def draw_preview(
    pygame: Any,
    screen: Any,
    font: Any,
    joints: dict[str, Any] | None,
    hands: dict[str, dict[str, str | None]] | None,
    recording: RecordingSession,
    tracking_id: int | None,
    color_surface: Any = None,
    color_points: dict[str, tuple[float, float] | None] | None = None,
) -> None:
    width, height = screen.get_size()
    if color_surface is not None:
        screen.blit(pygame.transform.smoothscale(color_surface, (width, height)), (0, 0))
    else:
        screen.fill((17, 20, 27))
        pygame.draw.line(screen, (45, 50, 61), (0, height // 2), (width, height // 2), 1)
        pygame.draw.line(screen, (45, 50, 61), (width // 2, 0), (width // 2, height), 1)

    if joints:
        if color_points:
            points = {
                name: (
                    (int(point[0] * width / 1920), int(point[1] * height / 1080))
                    if point is not None else None
                )
                for name, point in color_points.items()
            }
        else:
            points = {
                name: project(data["position_m"], width, height)
                for name, data in joints.items()
            }
        for start, end in BONES:
            a, b = points.get(start), points.get(end)
            if a and b:
                inferred = (
                    joints[start]["tracking_state"] != "tracked"
                    or joints[end]["tracking_state"] != "tracked"
                )
                pygame.draw.line(screen, (235, 166, 59) if inferred else (65, 210, 154), a, b, 4)
        for name, point in points.items():
            if point and joints[name]["tracking_state"] != "not_tracked":
                pygame.draw.circle(screen, (235, 238, 243), point, 5)
        if hands:
            hand_joints = {
                "left": ("HandLeft", "HandTipLeft", "ThumbLeft"),
                "right": ("HandRight", "HandTipRight", "ThumbRight"),
            }
            for side, names in hand_joints.items():
                marker_color = hand_marker_color(hands.get(side, {}))
                for name in names:
                    point = points.get(name)
                    if point and joints[name]["tracking_state"] != "not_tracked":
                        pygame.draw.circle(screen, marker_color, point, 9)
                        pygame.draw.circle(screen, (12, 15, 20), point, 9, 2)

    status = "RECORDING" if recording.active else "READY"
    color = (238, 77, 92) if recording.active else (65, 210, 154)
    left_hand = right_hand = "n/a"
    hand_color = (145, 153, 166)
    if hands:
        left = hands.get("left", {})
        right = hands.get("right", {})
        left_hand = f"{left.get('state', 'unknown')} ({left.get('confidence', 'low')})"
        right_hand = f"{right.get('state', 'unknown')} ({right.get('confidence', 'low')})"
        hand_color = (
            (210, 215, 224)
            if left.get("confidence") == "high" or right.get("confidence") == "high"
            else (235, 166, 59)
        )

    lines = [
        (status, color),
        (f"Body: {tracking_id if tracking_id is not None else 'none'}", (210, 215, 224)),
        (f"Frames: {recording.frame_count}", (210, 215, 224)),
        (f"L hand: {left_hand}", hand_color),
        (f"R hand: {right_hand}", hand_color),
        ("SPACE record/stop   ESC quit", (145, 153, 166)),
    ]
    pygame.draw.rect(screen, (12, 15, 20), (8, 8, 430, 170))
    y = 18
    for text_value, text_color in lines:
        screen.blit(font.render(text_value, True, text_color), (18, y))
        y += 27
    pygame.display.flip()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Record Kinect v2 skeletal motion capture.")
    parser.add_argument(
        "--output", type=Path, default=Path("recordings"),
        help="Directory in which session folders are created (default: recordings).",
    )
    parser.add_argument(
        "--headless", action="store_true",
        help="Record immediately without a preview; stop with Ctrl+C.",
    )
    parser.add_argument(
        "--auto-record", action="store_true",
        help="Begin recording as soon as the camera opens.",
    )
    parser.add_argument(
        "--duration", type=float,
        help="Stop automatically after this many seconds (also enables auto-record).",
    )
    parser.add_argument(
        "--record-color", action="store_true",
        help="Record the 1920x1080 color stream to color.avi with timestamps.",
    )
    parser.add_argument(
        "--hands-only", action="store_true",
        help=(
            "Record and preview only wrist, hand, hand-tip, thumb, and SDK hand "
            "state/confidence data."
        ),
    )
    parser.add_argument(
        "--export-fbx", action="store_true",
        help="Export each completed take to motion.fbx using Blender.",
    )
    parser.add_argument(
        "--blender", help="Path to Blender executable (used with --export-fbx).",
    )
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    if args.duration is not None and args.duration <= 0:
        raise ValueError("--duration must be greater than zero")
    if args.hands_only and args.export_fbx:
        raise ValueError("--export-fbx requires full skeleton data; omit --hands-only")

    v2, runtime_module = load_kinect()
    all_joint_types = {name: int(getattr(v2, constant)) for name, constant in JOINT_SPECS}
    joint_types = {
        name: int(getattr(v2, constant))
        for name, constant in selected_joint_specs(args.hands_only)
    }
    capture_mode = "hands_only" if args.hands_only else "full_body"
    session = RecordingSession(args.output, list(joint_types), capture_mode)
    kinect = None
    pygame = None
    cv2 = None
    np = None
    screen = font = clock = None

    try:
        use_color = not args.headless or args.record_color
        frame_sources = v2.FrameSourceTypes_Body
        if use_color:
            frame_sources |= v2.FrameSourceTypes_Color
        try:
            kinect = runtime_module.PyKinectRuntime(frame_sources)
        except Exception as exc:
            raise RuntimeError(
                "Could not open the Kinect v2. Check its power and USB 3.0 "
                "connection, then run Kinect Configuration Verifier."
            ) from exc
        if use_color:
            import numpy as numpy_module

            np = numpy_module
        if args.record_color:
            try:
                import cv2 as cv2_module
            except ImportError as exc:
                raise RuntimeError(
                    "Color recording requires OpenCV; reinstall requirements.txt"
                ) from exc
            cv2 = cv2_module
        if not args.headless:
            try:
                import pygame as pygame_module
            except ImportError as exc:
                raise RuntimeError("Preview requires pygame; install requirements.txt") from exc
            pygame = pygame_module
            pygame.init()
            screen = pygame.display.set_mode((960, 600), pygame.RESIZABLE)
            title = "Kinect v2 Hand Capture" if args.hands_only else "Kinect v2 Motion Capture"
            pygame.display.set_caption(title)
            font = pygame.font.SysFont("Segoe UI", 21)
            clock = pygame.time.Clock()

        def start_take() -> Path:
            path = session.start()
            if args.record_color:
                size = (int(kinect.color_frame_desc.Width), int(kinect.color_frame_desc.Height))
                session.enable_color(cv2, size)
            print(f"Recording to {path.resolve()}")
            return path

        def finish_take() -> Path | None:
            saved = session.stop()
            if saved is None:
                return None
            print(f"Saved {session.frame_count} frames to {saved.resolve()}")
            if args.export_fbx:
                try:
                    from export_fbx import run_export

                    output = run_export(saved, blender_path=args.blender)
                    print(f"Created {output}")
                except RuntimeError as exc:
                    print(f"FBX export failed: {exc}", file=sys.stderr)
            return saved

        if args.headless or args.auto_record or args.duration is not None:
            start_take()

        running = True
        locked_tracking_id: int | None = None
        missed_frames = 0
        latest_joints: dict[str, Any] | None = None
        latest_hands: dict[str, dict[str, str | None]] | None = None
        latest_color_surface = None
        latest_color_points: dict[str, tuple[float, float] | None] | None = None

        while running:
            if pygame:
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        running = False
                    elif event.type == pygame.KEYDOWN:
                        if event.key in (pygame.K_ESCAPE, pygame.K_q):
                            running = False
                        elif event.key == pygame.K_SPACE:
                            if session.active:
                                finish_take()
                            else:
                                start_take()

            if use_color and kinect.has_new_color_frame():
                color_frame = kinect.get_last_color_frame()
                if color_frame is not None:
                    color_height = int(kinect.color_frame_desc.Height)
                    color_width = int(kinect.color_frame_desc.Width)
                    bgra = color_frame.reshape((color_height, color_width, 4))
                    bgr = np.ascontiguousarray(bgra[:, :, :3])
                    if session.active and args.record_color:
                        session.write_color(bgr)
                    if pygame:
                        rgb_for_pygame = np.transpose(bgr[:, :, ::-1], (1, 0, 2))
                        latest_color_surface = pygame.surfarray.make_surface(rgb_for_pygame)

            if kinect.has_new_body_frame():
                body_frame = kinect.get_last_body_frame()
                if body_frame is not None:
                    bodies = [body for body in body_frame.bodies if body is not None and body.is_tracked]
                    body = next(
                        (item for item in bodies if int(item.tracking_id) == locked_tracking_id), None
                    )
                    if body is None:
                        missed_frames += 1
                        if locked_tracking_id is None or missed_frames >= 30:
                            body = nearest_body(bodies, all_joint_types["SpineBase"])
                            locked_tracking_id = int(body.tracking_id) if body else None
                            missed_frames = 0
                    else:
                        missed_frames = 0

                    if body is not None:
                        latest_joints = extract_body(body, joint_types)
                        latest_hands = extract_hands(body)
                        if pygame:
                            mapped = kinect.body_joints_to_color_space(body.joints)
                            latest_color_points = {}
                            for name, joint_id in joint_types.items():
                                point = mapped[joint_id]
                                x, y = float(point.x), float(point.y)
                                latest_color_points[name] = (
                                    (x, y) if math.isfinite(x) and math.isfinite(y) else None
                                )
                        if session.active:
                            body_payload = {
                                "captured_utc": datetime.now(timezone.utc).isoformat(),
                                "sensor_relative_time_100ns": sensor_ticks(
                                    getattr(body_frame, "relative_time", None)
                                ),
                                "floor_clip_plane": vector4(body_frame.floor_clip_plane),
                                "tracking_id": int(body.tracking_id),
                                "joints": latest_joints,
                                "hands": latest_hands,
                            }
                            if session.color_size is not None:
                                body_payload["nearest_color_frame_index"] = max(
                                    0, session.color_frame_count - 1
                                )
                            session.write(body_payload)
                    else:
                        latest_joints = None
                        latest_hands = None
                        latest_color_points = None

            if args.duration is not None and session.active:
                elapsed = time.perf_counter() - float(session.started_perf)
                if elapsed >= args.duration:
                    running = False

            if pygame:
                draw_preview(
                    pygame, screen, font, latest_joints, latest_hands, session, locked_tracking_id,
                    latest_color_surface, latest_color_points,
                )
                clock.tick(60)
            else:
                time.sleep(0.002)
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        was_recording = session.active
        if was_recording:
            finish_take()
        if kinect is not None:
            kinect.close()
        if pygame:
            pygame.quit()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return run(args)
    except (RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
