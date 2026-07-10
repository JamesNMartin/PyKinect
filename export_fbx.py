"""Convert a recorded Kinect JSONL session into an animated FBX armature.

Run normally to launch Blender in the background, or run through Blender's
``--python`` option (the launcher handles this automatically).
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


BONES = (
    ("SpineBase", "SpineMid"),
    ("SpineMid", "SpineShoulder"),
    ("SpineShoulder", "Neck"),
    ("Neck", "Head"),
    ("SpineShoulder", "ShoulderLeft"),
    ("ShoulderLeft", "ElbowLeft"),
    ("ElbowLeft", "WristLeft"),
    ("WristLeft", "HandLeft"),
    ("HandLeft", "HandTipLeft"),
    ("WristLeft", "ThumbLeft"),
    ("SpineShoulder", "ShoulderRight"),
    ("ShoulderRight", "ElbowRight"),
    ("ElbowRight", "WristRight"),
    ("WristRight", "HandRight"),
    ("HandRight", "HandTipRight"),
    ("WristRight", "ThumbRight"),
    ("SpineBase", "HipLeft"),
    ("HipLeft", "KneeLeft"),
    ("KneeLeft", "AnkleLeft"),
    ("AnkleLeft", "FootLeft"),
    ("SpineBase", "HipRight"),
    ("HipRight", "KneeRight"),
    ("KneeRight", "AnkleRight"),
    ("AnkleRight", "FootRight"),
)


def find_blender(explicit: str | None = None) -> str:
    """Locate Blender on Windows or a conventional command-line install."""
    candidates = [explicit, os.environ.get("BLENDER_PATH"), shutil.which("blender")]
    if sys.platform == "win32":
        candidates.extend(
            sorted(
                glob.glob("C:/Program Files/Blender Foundation/Blender */blender.exe"),
                reverse=True,
            )
        )
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate))
    raise RuntimeError(
        "Blender was not found. Install it with: "
        "winget install --exact --id BlenderFoundation.Blender"
    )


def run_export(
    session_dir: Path,
    output_file: Path | None = None,
    blender_path: str | None = None,
) -> Path:
    session_dir = session_dir.resolve()
    frames_file = session_dir / "frames.jsonl"
    if not frames_file.is_file():
        raise RuntimeError(f"Missing recording data: {frames_file}")
    output_file = (output_file or session_dir / "motion.fbx").resolve()
    blender = find_blender(blender_path)
    command = [
        blender,
        "--background",
        "--python",
        str(Path(__file__).resolve()),
        "--",
        str(session_dir),
        str(output_file),
    ]
    result = subprocess.run(command, check=False)
    if result.returncode:
        raise RuntimeError(f"Blender FBX export failed with exit code {result.returncode}")
    if not output_file.is_file():
        raise RuntimeError("Blender finished without creating the FBX file")
    return output_file


def _arguments_after_double_dash() -> list[str]:
    return sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []


def _load_frames(session_dir: Path) -> list[dict[str, Any]]:
    frames = []
    with (session_dir / "frames.jsonl").open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if line.strip():
                try:
                    frames.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise RuntimeError(
                        f"Invalid JSON on frames.jsonl line {line_number}"
                    ) from exc
    if not frames:
        raise RuntimeError("The recording contains no tracked skeleton frames")
    return frames


def _blender_export(session_dir: Path, output_file: Path) -> None:
    import bpy
    from mathutils import Matrix, Vector

    frames = _load_frames(session_dir)

    def position(frame: dict[str, Any], joint_name: str) -> Any | None:
        joint = frame.get("joints", {}).get(joint_name)
        if not joint or joint.get("tracking_state") == "not_tracked":
            return None
        point = joint.get("position_m", {})
        if any(point.get(axis) is None for axis in ("x", "y", "z")):
            return None
        # Kinect: X left, Y up, Z away. Blender: X right, Z up, -Y forward.
        return Vector((-point["x"], -point["z"], point["y"]))

    rest: dict[str, Any] = {}
    joint_names = {"SpineBase"}
    for parent, child in BONES:
        joint_names.update((parent, child))
    for frame in frames:
        for name in joint_names - rest.keys():
            point = position(frame, name)
            if point is not None:
                rest[name] = point
    if "SpineBase" not in rest:
        raise RuntimeError("No tracked SpineBase joint was found")

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    armature_data = bpy.data.armatures.new("KinectV2_Skeleton")
    armature = bpy.data.objects.new("KinectV2_Armature", armature_data)
    bpy.context.collection.objects.link(armature)
    bpy.context.view_layer.objects.active = armature
    armature.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")

    root = armature_data.edit_bones.new("SpineBase")
    root.head = rest["SpineBase"]
    root.tail = rest["SpineBase"] + Vector((0.0, 0.0, 0.1))
    created = {"SpineBase": root}
    rest_lengths = {"SpineBase": 0.1}

    for parent_name, child_name in BONES:
        if parent_name not in rest or child_name not in rest:
            continue
        bone = armature_data.edit_bones.new(child_name)
        bone.head = rest[parent_name]
        bone.tail = rest[child_name]
        if bone.length < 0.001:
            bone.tail = bone.head + Vector((0.0, 0.05, 0.0))
        bone.parent = created.get(parent_name)
        bone.use_connect = False
        created[child_name] = bone
        rest_lengths[child_name] = bone.length

    bpy.ops.object.mode_set(mode="POSE")
    for pose_bone in armature.pose.bones:
        pose_bone.rotation_mode = "QUATERNION"

    scene = bpy.context.scene
    scene.render.fps = 30
    frame_end = 1
    for sample in frames:
        frame_number = max(1, round(float(sample.get("recording_time_s", 0.0)) * 30) + 1)
        frame_end = max(frame_end, frame_number)
        scene.frame_set(frame_number)

        root_position = position(sample, "SpineBase")
        if root_position is not None:
            root_pose = armature.pose.bones.get("SpineBase")
            root_pose.matrix = Matrix.Translation(root_position)
            root_pose.keyframe_insert("location", frame=frame_number)
            root_pose.keyframe_insert("rotation_quaternion", frame=frame_number)
            root_pose.keyframe_insert("scale", frame=frame_number)

        for parent_name, child_name in BONES:
            pose_bone = armature.pose.bones.get(child_name)
            head = position(sample, parent_name)
            tail = position(sample, child_name)
            if pose_bone is None or head is None or tail is None:
                continue
            direction = tail - head
            length = direction.length
            if length < 0.001:
                continue
            up_axis = "X" if abs(direction.normalized().z) > 0.95 else "Z"
            rotation = direction.to_track_quat("Y", up_axis).to_matrix().to_4x4()
            scale = Matrix.Diagonal((1.0, length / rest_lengths[child_name], 1.0, 1.0))
            pose_bone.matrix = Matrix.Translation(head) @ rotation @ scale
            pose_bone.keyframe_insert("location", frame=frame_number)
            pose_bone.keyframe_insert("rotation_quaternion", frame=frame_number)
            pose_bone.keyframe_insert("scale", frame=frame_number)

    bpy.ops.object.mode_set(mode="OBJECT")
    scene.frame_start = 1
    scene.frame_end = frame_end
    action = armature.animation_data.action if armature.animation_data else None
    if action is not None and hasattr(action, "fcurves"):
        for curve in action.fcurves:
            for keyframe in curve.keyframe_points:
                keyframe.interpolation = "LINEAR"

    bpy.ops.object.select_all(action="DESELECT")
    armature.select_set(True)
    bpy.context.view_layer.objects.active = armature
    output_file.parent.mkdir(parents=True, exist_ok=True)
    result = bpy.ops.export_scene.fbx(
        filepath=str(output_file),
        use_selection=True,
        object_types={"ARMATURE"},
        axis_forward="-Z",
        axis_up="Y",
        add_leaf_bones=False,
        bake_anim=True,
        bake_anim_use_all_bones=True,
        bake_anim_use_nla_strips=False,
        bake_anim_use_all_actions=False,
        bake_anim_simplify_factor=0.0,
    )
    if "FINISHED" not in result:
        raise RuntimeError(f"FBX exporter returned {result}")
    print(f"Exported animated FBX: {output_file}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export a Kinect recording to FBX via Blender.")
    parser.add_argument("session", type=Path, help="Recording session directory.")
    parser.add_argument("--output", type=Path, help="Output FBX path (default: SESSION/motion.fbx).")
    parser.add_argument("--blender", help="Path to Blender executable.")
    args = parser.parse_args(argv)
    try:
        output = run_export(args.session, args.output, args.blender)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Created {output}")
    return 0


if __name__ == "__main__":
    try:
        import bpy  # type: ignore[import-not-found]  # noqa: F401
    except ImportError:
        raise SystemExit(main())
    blender_args = _arguments_after_double_dash()
    if len(blender_args) != 2:
        raise SystemExit("Blender mode expects: -- SESSION_DIR OUTPUT_FILE")
    _blender_export(Path(blender_args[0]), Path(blender_args[1]))
