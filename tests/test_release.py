import tarfile

from scripts.build_release import package


def test_release_excludes_credentials_and_backups(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / ".env").write_text("SECRET=do-not-package")
    (source / "SECRETS.md").write_text("private")
    (source / ".env.example").write_text("SECRET=")
    (source / "slovech").mkdir()
    (source / "slovech" / "server.py").write_text("pass")
    (source / "web").mkdir()
    (source / "web" / "index.html").write_text("<html></html>")
    (source / "docs").mkdir()
    (source / "docs" / "operations.md").write_text("Operations")
    (source / ".local").mkdir()
    (source / ".local" / "SECRETS.md").write_text("private")
    (source / "backups").mkdir()
    (source / "backups" / "private.tar.gz").write_bytes(b"secret data")
    archive_path = tmp_path / "release.tar.gz"
    package(source, archive_path)
    with tarfile.open(archive_path) as archive:
        assert set(archive.getnames()) == {
            ".env.example",
            "slovech/server.py",
            "web/index.html",
            "docs/operations.md",
        }
