#!/usr/bin/env bash
set -euo pipefail

# The Kinect v2 SDK is Windows-only. Keep editing in WSL, but execute the
# recorder with Windows Python through WSL interoperability.
if ! command -v py.exe >/dev/null 2>&1; then
    echo "Error: Windows Python launcher (py.exe) was not found." >&2
    echo "Install 64-bit Python 3.11 on Windows, then restart WSL." >&2
    exit 1
fi

python_version="${PYKINECT_PYTHON_VERSION:-}"
if [[ -z "$python_version" ]]; then
    # Prefer a modern version known to work with this program's legacy-library
    # compatibility shims, while accepting an existing older installation.
    for candidate in 3.11 3.10 3.9 3.8; do
        if py.exe "-$candidate" -c "import sys" >/dev/null 2>&1; then
            python_version="$candidate"
            break
        fi
    done
fi

if [[ -z "$python_version" ]]; then
    echo "Error: py.exe is present, but no supported Windows Python runtime was found." >&2
    echo "Install one from an Administrator PowerShell terminal:" >&2
    echo "  winget install --exact --id Python.Python.3.11" >&2
    echo "Then restart WSL and run this launcher again." >&2
    exit 1
fi

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
script_path="$(wslpath -w "$repo_dir/mocap_recorder.py")"
output_path="$(wslpath -w "$repo_dir/recordings")"

exec py.exe "-$python_version" "$script_path" --output "$output_path" "$@"
