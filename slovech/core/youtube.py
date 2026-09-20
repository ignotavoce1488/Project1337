import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from slovech.core.config import get_settings
from slovech.core.process import run_process

VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}\Z")


def youtube_video_id(url: str) -> str:
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"https", "http"}
        or parsed.username
        or parsed.password
        or parsed.port not in {None, 443, 80}
    ):
        raise ValueError("Invalid YouTube URL")
    if parsed.hostname == "youtu.be":
        video = parsed.path.strip("/")
    elif parsed.hostname in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        if parsed.path == "/watch":
            video = parse_qs(parsed.query).get("v", [""])[0]
        elif parsed.path.startswith(("/shorts/", "/embed/", "/live/")):
            video = parsed.path.split("/")[2]
        else:
            raise ValueError("Unsupported YouTube URL")
    else:
        raise ValueError("Only YouTube URLs are supported")
    if not VIDEO_ID.fullmatch(video):
        raise ValueError("Invalid video ID")
    return video


async def download_youtube_audio(url: str, output_path: str) -> None:
    video = youtube_video_id(url)
    settings = get_settings()
    args = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--ignore-config",
        "--no-cache-dir",
        "--no-playlist",
        "--no-progress",
        "--quiet",
        "--no-warnings",
        "--socket-timeout",
        "20",
        "--retries",
        "2",
        "--fragment-retries",
        "2",
        "--max-filesize",
        str(settings.max_upload_bytes),
        "--match-filter",
        f"duration <= {settings.max_audio_seconds}",
        "-f",
        "bestaudio",
        "--output",
        output_path,
    ]
    if settings.youtube_proxy:
        args.extend(["--proxy", settings.youtube_proxy])
    await run_process(
        *args,
        f"https://www.youtube.com/watch?v={video}",
        timeout=600,
        file_limit=(Path(output_path), settings.max_upload_bytes),
    )


async def fetch_youtube_transcript(video_id: str) -> str | None:
    if not VIDEO_ID.fullmatch(video_id):
        raise ValueError("Invalid video ID")
    try:
        output = await run_process(sys.executable, "-m", "core.youtube", video_id, timeout=40)
        text = output.decode().strip()
        return text if text and len(text) <= 2000000 else None
    except (RuntimeError, TimeoutError):
        return None


if __name__ == "__main__":
    from youtube_transcript_api import YouTubeTranscriptApi

    video = sys.argv[1]
    if not VIDEO_ID.fullmatch(video):
        raise SystemExit(1)
    transcript = YouTubeTranscriptApi().fetch(video, languages=["ru", "en"])
    prefix = "[LANG:EN]" if transcript.language_code.startswith("en") else "[LANG:RU]"
    print(prefix + "\n" + " ".join(item.text for item in transcript))
