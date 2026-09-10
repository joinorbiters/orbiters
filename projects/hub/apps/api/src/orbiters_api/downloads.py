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
