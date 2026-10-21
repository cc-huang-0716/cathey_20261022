"""Fail CI when files excluded by .gitignore are nevertheless tracked by Git."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
    if not tracked:
        raise SystemExit("No tracked source files found.")
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "--stdin", "-z"],
        input=tracked,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=ROOT,
        check=False,
    )
    if result.returncode not in (0, 1):
        raise SystemExit(result.stderr.decode("utf-8", errors="replace"))
    unexpected = [path.decode("utf-8") for path in result.stdout.split(b"\0") if path]
    if unexpected:
        # Only print paths; never print potentially sensitive file contents.
        raise SystemExit("Ignored files are tracked by Git:\n" + "\n".join(unexpected))
    count = len([path for path in tracked.split(b"\0") if path])
    print(f"Repository hygiene: {count} tracked files; no ignored paths are tracked.")


if __name__ == "__main__":
    main()
