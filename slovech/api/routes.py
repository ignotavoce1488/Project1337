import html
import re
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response

from slovech.core.auth import get_authenticated_user_id
from slovech.core.config import SAFE_AUDIO_REGEX, SAFE_ID_REGEX
from slovech.core.documents import render_docx
from slovech.core.languages import LANGUAGES
from slovech.core.legal import DOCUMENTS
from slovech.core.storage import ProcessingCancelled, QueueFull, Repository, TranslationBusy

router = APIRouter()


def get_repository(request: Request) -> Repository:
    return request.app.state.repository


Repo = Annotated[Repository, Depends(get_repository)]


def require_legal_owner(
    user_id: Annotated[str, Depends(get_authenticated_user_id)], repo: Repo
) -> str:
    stage = repo.legal_stage(user_id)
    if stage == "deleting":
        raise HTTPException(403, "Данные аккаунта удаляются. Дождитесь подтверждения в боте.")
    if repo.settings.legal_enforcement and stage != "ready":
        raise HTTPException(403, "Примите условия в чате с ботом через команду /start.")
    try:
        repo.touch(user_id)
    except ProcessingCancelled as exc:
        raise HTTPException(403, "Данные аккаунта удаляются.") from exc
    return user_id


Owner = Annotated[str, Depends(require_legal_owner)]


@router.get("/api/preferences")
def get_preferences(user_id: Owner, repo: Repo):
    saved = repo.get_preferences(user_id)
    return {
        "interface_language": saved["interface_language"] or "ru",
        "languages": LANGUAGES,
    }


def render_legal_markdown(source: str) -> str:
    blocks = []
    paragraph = []

    def inline(value: str) -> str:
        escaped = html.escape(value)
        escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
        escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
        for name in DOCUMENTS:
            escaped = re.sub(
                rf"\[([^\]]+)\]\(\./{name}\.md\)",
                rf'<a href="/legal/{name}">\1</a>',
                escaped,
            )
        return escaped

    def flush() -> None:
        if paragraph:
            blocks.append(f"<p>{inline(' '.join(paragraph))}</p>")
            paragraph.clear()

    for line in source.splitlines():
        if not line.strip():
            flush()
        elif line.startswith("## "):
            flush()
            blocks.append(f"<h2>{inline(line[3:])}</h2>")
        elif line.startswith("# "):
            flush()
            blocks.append(f"<h1>{inline(line[2:])}</h1>")
        else:
            paragraph.append(line.strip())
    flush()
    return "\n".join(blocks)


@router.get("/legal/{kind}", response_class=HTMLResponse)
def legal_document(kind: str, repo: Repo):
    if not repo.settings.legal_enforcement:
        raise HTTPException(404, "Документ не опубликован")
    path = DOCUMENTS.get(kind)
    if path is None:
        raise HTTPException(404, "Документ не найден")
    body = render_legal_markdown(path.read_text(encoding="utf-8"))
    return HTMLResponse(
        '<!doctype html><html lang="ru"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{html.escape(kind)} — Конспект</title>"
        "<style>body{margin:0;background:#111311;color:#e9ebe6;font:16px/1.7 system-ui,sans-serif}"
        "main{max-width:760px;margin:auto;padding:28px 20px 80px}h1{font-size:1.8rem;line-height:1.2}"
        "h2{font-size:1.2rem;margin-top:2rem}p{margin:1rem 0}a{color:#f19bbf}"
        "nav{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:2rem}</style></head><body><main>"
        '<nav><a href="/legal/terms">Соглашение</a><a href="/legal/privacy">Политика</a>'
        '<a href="/legal/consent">Согласие на обработку данных</a></nav>'
        f"{body}</main></body></html>",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/")
def root_redirect():
    return RedirectResponse("/app")


@router.get("/health")
def health_check():
    return {"status": "ok"}


@router.get("/ready")
def readiness(repo: Repo):
    try:
        repo.ready()
    except Exception as exc:
        raise HTTPException(503, "Storage unavailable") from exc
    return {"status": "ready"}


@router.get("/app")
def serve_webapp(request: Request):
    return FileResponse(
        request.app.state.settings.static_dir / "index.html", media_type="text/html"
    )


@router.get("/api/lectures")
def list_lectures(
    user_id: Owner, repo: Repo, limit: int = Query(100, ge=1, le=100), offset: int = Query(0, ge=0)
):
    return repo.previews(user_id, limit, offset)


@router.get("/api/lectures/count")
def count_lectures(user_id: Owner, repo: Repo):
    return {"count": repo.count(user_id)}


@router.get("/api/lectures/search")
def search_lectures(user_id: Owner, repo: Repo, q: str = Query(min_length=1, max_length=120)):
    return repo.search_lectures(user_id, q)


@router.get("/api/lecture/latest")
def get_latest_lecture(user_id: Owner, repo: Repo):
    items = repo.list(user_id, 1)
    return items[0] if items else {"empty": True}


def require_lecture(lecture_id: str, user_id: str, repo: Repository):
    if not SAFE_ID_REGEX.fullmatch(lecture_id):
        raise HTTPException(400, "Некорректный идентификатор")
    lecture = repo.get(lecture_id, user_id)
    if not lecture:
        raise HTTPException(404, "Конспект не найден")
    return lecture


@router.get("/api/lecture/{lecture_id}")
def get_lecture(lecture_id: str, user_id: Owner, repo: Repo):
    return require_lecture(lecture_id, user_id, repo)


@router.post("/api/lecture/{lecture_id}/translation")
def request_lecture_translation(lecture_id: str, user_id: Owner, repo: Repo):
    require_lecture(lecture_id, user_id, repo)
    language = repo.get_preferences(user_id)["interface_language"] or "ru"
    try:
        state = repo.enqueue_translation(lecture_id, user_id, language)
    except TranslationBusy as exc:
        raise HTTPException(409, "Another translation is in progress") from exc
    except QueueFull as exc:
        raise HTTPException(429, "Processing queue is full") from exc
    except ProcessingCancelled as exc:
        raise HTTPException(403, "Account is being deleted") from exc
    return {"state": state, "language": language}


@router.get("/api/lecture/{lecture_id}/translation")
def get_lecture_translation_status(lecture_id: str, user_id: Owner, repo: Repo):
    require_lecture(lecture_id, user_id, repo)
    language = repo.get_preferences(user_id)["interface_language"] or "ru"
    return {"state": repo.translation_status(lecture_id, user_id, language),
            "language": language}


@router.post("/api/lecture/{lecture_id}/transcript-translation")
def request_transcript_translation(lecture_id: str, user_id: Owner, repo: Repo):
    require_lecture(lecture_id, user_id, repo)
    language = repo.get_preferences(user_id)["interface_language"] or "ru"
    try:
        state = repo.enqueue_transcript_translation(lecture_id, user_id, language)
    except TranslationBusy as exc:
        raise HTTPException(409, "Another transcript translation is in progress") from exc
    except QueueFull as exc:
        raise HTTPException(429, "Processing queue is full") from exc
    except ProcessingCancelled as exc:
        raise HTTPException(403, "Account is being deleted") from exc
    return {"state": state, "language": language}


@router.get("/api/lecture/{lecture_id}/transcript-translation")
def get_transcript_translation_status(lecture_id: str, user_id: Owner, repo: Repo):
    require_lecture(lecture_id, user_id, repo)
    language = repo.get_preferences(user_id)["interface_language"] or "ru"
    return {**repo.transcript_translation_status(lecture_id, user_id, language),
            "language": language}


@router.get("/audio/{filename}")
def get_audio(filename: str, user_id: Owner, repo: Repo):
    if not SAFE_AUDIO_REGEX.fullmatch(filename):
        raise HTTPException(400, "Недопустимое имя файла")
    root = repo.settings.audio_dir.resolve()
    path = root / filename
    if (
        path.is_symlink()
        or not path.is_file()
        or path.resolve().parent != root
        or not repo.owns_audio(filename, user_id)
    ):
        raise HTTPException(404, "Аудиофайл не найден")
    return FileResponse(path)


@router.get("/api/download/{lecture_id}")
def download_lecture_docx(
    lecture_id: str, user_id: Owner, repo: Repo, lang: str = "ru"
):
    if lang not in LANGUAGES:
        raise HTTPException(422, "Unsupported document language")
    body, name = render_docx(require_lecture(lecture_id, user_id, repo), lang)
    return Response(
        body,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"},
    )
