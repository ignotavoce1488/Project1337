"""Shared DOCX rendering without temporary files or framework dependencies."""

from io import BytesIO

from docx import Document

from slovech.core.models import Lecture


def render_docx(lecture: Lecture, lang: str = "ru") -> tuple[bytes, str]:
    translated = lang == lecture.translation_language and bool(lecture.summary_translated)
    legacy_ru = lang == "ru" and lecture.language == "en" and bool(lecture.summary_ru)
    title = (lecture.title_translated or lecture.title) if translated else (
        (lecture.title_ru or lecture.title) if legacy_ru else lecture.title
    )
    summary = (lecture.summary_translated or lecture.summary) if translated else (
        (lecture.summary_ru or lecture.summary) if legacy_ru else lecture.summary
    )
    points = (lecture.key_points_translated or lecture.key_points) if translated else (
        (lecture.key_points_ru or lecture.key_points) if legacy_ru else lecture.key_points
    )
    document = Document()
    headings = {
        "ru": ("Дата", "Главные мысли", "Конспект", "Полная расшифровка"),
        "en": ("Date", "Key points", "Notes", "Full transcript"),
        "es": ("Fecha", "Puntos clave", "Notas", "Transcripción completa"),
        "fr": ("Date", "Points clés", "Notes", "Transcription complète"),
        "de": ("Datum", "Kernaussagen", "Notizen", "Vollständiges Transkript"),
        "it": ("Data", "Punti chiave", "Appunti", "Trascrizione completa"),
        "pt": ("Data", "Pontos principais", "Notas", "Transcrição completa"),
        "tr": ("Tarih", "Önemli noktalar", "Notlar", "Tam döküm"),
        "ar": ("التاريخ", "النقاط الرئيسية", "الملخص", "التفريغ الكامل"),
        "hi": ("तारीख", "मुख्य बातें", "नोट्स", "पूरा प्रतिलेख"),
        "tk": ("Sene", "Esasy pikirler", "Bellikler", "Doly ýazgy"),
    }.get(lang if translated or legacy_ru else lecture.language,
          ("Date", "Key points", "Notes", "Full transcript"))
    document.add_heading(title, 0)
    document.add_paragraph(f"{headings[0]}: {lecture.created_at}")
    document.add_heading(headings[1], 1)
    for point in points:
        document.add_paragraph(point.replace("**", ""), style="List Bullet")
    document.add_heading(headings[2], 1)
    for line in summary.splitlines():
        line = line.strip()
        if line.startswith("#"):
            document.add_heading(line.lstrip("# "), 2)
        elif line.startswith(("- ", "* ")):
            document.add_paragraph(line[2:].replace("**", ""), style="List Bullet")
        elif line:
            document.add_paragraph(line.replace("**", ""))
    document.add_heading(headings[3], 1)
    for line in lecture.transcription.splitlines():
        if line.strip():
            document.add_paragraph(line.strip())
    output = BytesIO()
    document.save(output)
    name = "".join(c for c in title if c.isalnum() or c in " _-").strip()[:60] or "Конспект"
    return output.getvalue(), f"{name}.docx"
