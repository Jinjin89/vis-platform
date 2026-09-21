"""Prepare a repository-local R runtime from already downloaded Ubuntu packages.

Usage: python scripts/setup_r_runtime.py /directory/containing/deb/files
The application also supports a separately provisioned R installation.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND / ".runtime"


def main() -> None:
    ROOT.mkdir(exist_ok=True)
    if len(sys.argv) > 1:
        for package in Path(sys.argv[1]).glob("*.deb"):
            subprocess.run(["dpkg-deb", "-x", str(package), str(ROOT)], check=True)
    r_home = ROOT / "usr/lib/R"
    for path in (r_home / "etc").iterdir():
        if path.is_symlink():
            name = path.name
            source = ROOT / "etc/R" / name
            path.unlink()
            if source.exists():
                shutil.copyfile(source, path)
    shutil.copyfile(r_home / "etc/Renviron.ucf", r_home / "etc/Renviron")
    # Keep optional packages inside the R runtime's read-only sandbox root.
    site = r_home / "site-library"
    if site.is_symlink():
        site.unlink()
    source = BACKEND / "src/vis_platform_backend/execution/sandbox.c"
    subprocess.run(
        [
            "cc",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(source),
            "-o",
            str(ROOT / "vis-r-sandbox"),
        ],
        check=True,
    )
    subprocess.run(
        [
            "cc",
            "-shared",
            "-fPIC",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(source),
            "-o",
            str(ROOT / "vis-r-sandbox.so"),
        ],
        check=True,
    )
    subprocess.run([str(ROOT / "vis-r-sandbox"), "--check"], check=True)
    print("Local R and the restricted launcher are ready.")


if __name__ == "__main__":
    main()
