import os
import sqlite3
import subprocess
import sys
import tarfile


def test_backup_restores_database_and_media(repo, lecture, settings, tmp_path):
    repo.save(lecture)
    (settings.audio_dir / "lecture1.mp3").write_bytes(b"test audio")
    destination = tmp_path / "backup.tar.gz"
    env = {
        **os.environ,
        "DATA_DIR": str(settings.data_dir),
        "AUDIO_DIR": str(settings.audio_dir),
        "ENVIRONMENT": "test",
    }
    subprocess.run(
        [sys.executable, "-m", "scripts.backup", str(destination)],
        env=env,
        check=True,
        capture_output=True,
    )
    restored = tmp_path / "restored"
    with tarfile.open(destination) as archive:
        archive.extractall(restored, filter="data")
    connection = sqlite3.connect(restored / "data/slovech.sqlite3")
    try:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("SELECT user_id FROM lectures").fetchone()[0] == "123"
    finally:
        connection.close()
    assert (restored / "audio/lecture1.mp3").read_bytes() == b"test audio"
    repeated = subprocess.run(
        [sys.executable, "-m", "scripts.backup", str(destination)], env=env, capture_output=True
    )
    assert repeated.returncode != 0
