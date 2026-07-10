# PyKinect v2 motion capture recorder

This program records the 25-joint skeleton produced by a Kinect v2. Each frame
contains camera-space joint positions (meters), Kinect tracking confidence, and
joint orientation quaternions. It also provides a live stick-figure preview.

## Hardware and platform

- 64-bit Windows (the legacy SDK's published requirements predate current Windows releases)
- Kinect for Xbox One or Kinect for Windows v2, with its power/USB adapter
- A compatible USB 3.0 controller (connect the Kinect directly, not through a hub)
- [Kinect for Windows SDK 2.0](https://www.microsoft.com/en-us/download/details.aspx?id=44561)
- 64-bit Windows Python 3.8–3.11. Python 3.11 is recommended for a new install.

This implementation uses Microsoft's Windows-only Kinect v2 SDK. It will not
open the camera on Linux or macOS.

### Using this repository from WSL

The recorder cannot run under WSL's Linux Python because the Kinect SDK and
PyKinect2 use Windows APIs. You can keep the repository in WSL and launch it
with Windows Python through WSL interoperability. Leave the Kinect connected to
the Windows host; do not attach it to WSL with `usbipd`.

First, install the Kinect SDK and 64-bit Python 3.11 on Windows. From an
Administrator PowerShell terminal, Python can be installed with:

```powershell
winget install --exact --id Python.Python.3.11
```

Restart WSL after installation. Then, from this
WSL repository, install the dependencies into **Windows Python**:

```bash
py.exe -3.11 -m pip install -r "\\wsl.localhost\Ubuntu-24.04\home\james\Projects\PyKinect\requirements.txt"
```

Run the supplied launcher from WSL:

```bash
./run_from_wsl.sh
```

Arguments are forwarded to the recorder, for example:

```bash
./run_from_wsl.sh --headless --duration 30
```

The recordings are written to this repository's `recordings/` directory. If
Windows Python or PyKinect2 has trouble loading files over the WSL network path,
move or clone the repository somewhere under `/mnt/c/` and run it there.

## Setup

Open PowerShell in this directory and create a virtual environment:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Before running the Python program, use the **Kinect Configuration Verifier**
installed with the SDK to confirm that the sensor and USB controller work.

## Record

```powershell
python mocap_recorder.py
```

Stand about 1.5–3.5 meters from the sensor with your full body visible. In the
preview:

- Press **Space** to start or stop a take.
- Press **Esc** or **Q** to quit. An active take is finalized automatically.

For an unattended fixed-length take:

```powershell
python mocap_recorder.py --headless --duration 30 --output recordings
```

The nearest visible person is selected and their Kinect tracking ID remains
locked. If they disappear for about one second, the recorder selects the nearest
visible person again.

## Output

Every take creates a timestamped folder:

```text
recordings/mocap_20260710_143000/
  frames.jsonl
  session.json
```

`frames.jsonl` has one JSON object per captured body frame. Streaming frames to
disk keeps long recordings memory-efficient and preserves completed lines if the
program is interrupted. `session.json` describes the coordinate system, joints,
duration, and frame count.

Positions use the Kinect camera coordinate system: `x` is horizontal, `y` is up,
and `z` points away from the camera. Values are meters. Orientations are Kinect
SDK quaternions in `x, y, z, w` order.

## Troubleshooting

- **Camera does not open:** install SDK 2.0, reconnect the power adapter, and try
  another USB 3.0 controller/port.
- **PyKinect2 import fails on a recent Python:** use 64-bit Python 3.11 as shown
  above. The recorder includes compatibility shims for the wrapper's obsolete
  `tagSTATSTG` size assertion and removed Python/NumPy names, but the wrapper
  and SDK are legacy software.
- **No skeleton:** face the camera, keep your whole body in view, improve room
  lighting, and move into the recommended distance range.

## Tests

The data writer can be tested without a Kinect or extra test dependencies:

```powershell
python -m unittest discover -v
```
