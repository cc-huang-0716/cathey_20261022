"""Package tracked source only; excludes ignored environments, tools and secrets."""

import subprocess
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from check_repository import main as check_repository

ROOT = Path(__file__).resolve().parents[1]


def main():
    check_repository()
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
    paths = [Path(path.decode("utf-8")) for path in tracked.split(b"\0") if path]
    if not paths:
        raise SystemExit("No tracked source. Stage or commit the project first.")
    output = ROOT / ".artifacts" / "market-brief-source.zip"
    output.parent.mkdir(exist_ok=True)
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for path in paths:
            absolute = (ROOT / path).resolve()
            if not absolute.is_relative_to(ROOT) or not absolute.is_file():
                raise SystemExit(f"Invalid tracked path: {path}")
            archive.write(absolute, Path("market-brief") / path)
    with ZipFile(output) as archive:
        assert archive.testzip() is None
    print(f"Packaged {len(paths)} source files: {output}")


if __name__ == "__main__":
    main()
