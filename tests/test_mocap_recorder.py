import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import mocap_recorder as recorder


def _joint(x, y, z, state=2):
    return SimpleNamespace(
        Position=SimpleNamespace(x=x, y=y, z=z), TrackingState=state
    )


class RecorderTests(unittest.TestCase):
    def test_legacy_statstg_assertion_is_patched_narrowly(self):
        source = (
            "before\n"
            "assert sizeof(tagSTATSTG) == 72, sizeof(tagSTATSTG)\n"
            "from comtypes import _check_version; _check_version('')\n"
            "after"
        )
        patched, changed = recorder.patch_pykinect_source(source)

        self.assertTrue(changed)
        self.assertIn("sizeof(tagSTATSTG) in (72, 80)", patched)
        self.assertNotIn("== 72", patched)
        self.assertNotIn("_check_version('')", patched)

    def test_extract_body_serializes_position_orientation_and_state(self):
        body = SimpleNamespace(
            joints=[_joint(1.0, 2.0, 3.0)],
            joint_orientations=[
                SimpleNamespace(Orientation=SimpleNamespace(x=0, y=0.5, z=0, w=1))
            ],
        )
        result = recorder.extract_body(body, {"Head": 0})

        self.assertEqual(
            result["Head"]["position_m"], {"x": 1.0, "y": 2.0, "z": 3.0}
        )
        self.assertEqual(result["Head"]["orientation_xyzw"]["y"], 0.5)
        self.assertEqual(result["Head"]["tracking_state"], "tracked")

    def test_extract_hands_serializes_state_and_confidence(self):
        body = SimpleNamespace(
            hand_left_state=2,
            hand_left_confidence=1,
            hand_right_state=3,
            hand_right_confidence=0,
        )
        result = recorder.extract_hands(body)

        self.assertEqual(result["left"], {"state": "open", "confidence": "high"})
        self.assertEqual(result["right"], {"state": "closed", "confidence": "low"})

    def test_selected_joint_specs_can_limit_to_hands(self):
        result = recorder.selected_joint_specs(hands_only=True)
        names = [name for name, _constant in result]

        self.assertEqual(names, list(recorder.HAND_JOINT_NAMES))
        self.assertNotIn("SpineBase", names)

    def test_session_writes_jsonl_and_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            session = recorder.RecordingSession(Path(temp_dir), ["Head"], "hands_only")
            session_dir = session.start()
            session.write({"tracking_id": 7, "joints": {}})
            session.stop()

            frame = json.loads((session_dir / "frames.jsonl").read_text().strip())
            metadata = json.loads((session_dir / "session.json").read_text())
            self.assertEqual(frame["frame_index"], 0)
            self.assertEqual(frame["tracking_id"], 7)
            self.assertEqual(metadata["frame_count"], 1)
            self.assertEqual(metadata["joint_names"], ["Head"])
            self.assertEqual(metadata["capture_mode"], "hands_only")

    def test_nearest_body_uses_spine_depth(self):
        far = SimpleNamespace(is_tracked=True, joints=[_joint(0, 0, 3.0)])
        near = SimpleNamespace(is_tracked=True, joints=[_joint(0, 0, 1.5)])
        self.assertIs(recorder.nearest_body([far, near], 0), near)


if __name__ == "__main__":
    unittest.main()
