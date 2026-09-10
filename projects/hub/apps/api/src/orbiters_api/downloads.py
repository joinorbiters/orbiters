"""One way to hand a stored CV to a browser, for the admin's download and the member's."""

from fastapi import Response

from orbiters_core.schemas import CvFile


def cv_response(cv: CvFile) -> Response:
    """The bytes as an attachment. ASCII-safe filename: a quote or a newline in a name
    the applicant chose must not become a header injection, and this is the one place
    that rule lives."""
    safe = "".join(ch if ch.isalnum() or ch in "._- " else "_" for ch in cv.filename) or "cv.pdf"
    return Response(
        content=cv.content,
        media_type=cv.mime,
        headers={"Content-Disposition": f'attachment; filename="{safe}"'},
    )


def perk_response(content: bytes, filename: str) -> Response:
    """A perk's file as an attachment. Its name is ours rather than something a person
    typed, so it needs no sanitising, but it is written here anyway so a second perk
    cannot invent a shape of its own for this header."""
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
