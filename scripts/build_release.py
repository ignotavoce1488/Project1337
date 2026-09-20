"""Package only application sources; never environment files, data or backups."""

import argparse
import tarfile
from pathlib import Path

ROOT_FILES = {
    "Dockerfile",
    "compose.yaml",
    "compose.local.yaml",
    "START-WINDOWS.cmd",
    "STOP-WINDOWS.cmd",
    "LOGS-WINDOWS.cmd",
    "pyproject.toml",
    "uv.lock",
    "README.md",
    ".dockerignore",
    ".env.example",
    "package.json",
    "package-lock.json",
    "playwright.config.cjs",
    "Makefile",
}
DIRECTORIES = {
    "slovech",
    "web",
    "docs",
    "deploy",
    "scripts",
    "tests",
    ".github",
}


def package(root: Path, destination: Path):
    with tarfile.open(destination, "w:gz") as archive:
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(root)
            if not path.is_file() or path.is_symlink() or "__pycache__" in relative.parts:
                continue
            if path.name.startswith(".env") and relative.as_posix() != ".env.example":
                continue
            if relative.as_posix() in ROOT_FILES or relative.parts[0] in DIRECTORIES:
                archive.add(path, arcname=relative.as_posix())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    package(Path(__file__).resolve().parent.parent, args.destination)
