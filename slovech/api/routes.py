from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, RedirectResponse, Response

from slovech.core.auth import get_authenticated_user_id
from slovech.core.config import SAFE_AUDIO_REGEX, SAFE_ID_REGEX
from slovech.core.documents import render_docx
from slovech.core.storage import Repository

router = APIRouter()
Owner = Annotated[str, Depends(get_authenticated_user_id)]


def get_repository(request: Request) -> Repository:
    return request.app.state.repository


Repo = Annotated[Repository, Depends(get_repository)]


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
    lecture_id: str, user_id: Owner, repo: Repo, lang: Literal["ru", "en"] = "ru"
):
    body, name = render_docx(require_lecture(lecture_id, user_id, repo), lang)
    return Response(
        body,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"},
    )
