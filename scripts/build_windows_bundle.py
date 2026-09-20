"""Create a portable source bundle; the Windows launcher builds or loads its image."""

import argparse
import tempfile
import zipfile
from pathlib import Path

from scripts.build_release import package


def build(destination: Path):
    import tarfile

    root = Path(__file__).resolve().parent.parent
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary:
        release = Path(temporary) / "sources.tar.gz"
        package(root, release)
        with (
            tarfile.open(release) as source,
            zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as bundle,
        ):
            for member in source.getmembers():
                if member.isfile():
                    content = source.extractfile(member).read()
                    if member.name.endswith((".cmd", ".ps1")):
                        content = content.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
                    bundle.writestr(f"Slovech-Windows/{member.name}", content)
    print(destination)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "destination", type=Path, nargs="?", default=Path("dist/Slovech-Windows.zip")
    )
    build(parser.parse_args().destination)
