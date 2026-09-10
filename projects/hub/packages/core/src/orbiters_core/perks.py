"""The files a member gets, read off this package's own data.

One perk today: the guide to the first steps as a freelancer. It is a generated PDF,
committed here rather than built in the image, and `../../../tools/build_guide_pdf.py`
explains why at length. This module is only the way in: the path, the bytes and the
name a browser saves, so the API layer holds no path of its own and a test can name the
same file the route serves.

It lives beside the code rather than in the website's `dist` because it is behind the
member session: a perk of being in the community, not a public download (Lorenzo, ORB-70,
2026-09-10).
"""

from pathlib import Path

PERKS_DIR = Path(__file__).resolve().parent / "perks"

GUIDE_FILENAME = "orbiters-guida-primi-passi-freelance.pdf"
GUIDE_PATH = PERKS_DIR / GUIDE_FILENAME


def guide_bytes() -> bytes:
    """The guide's PDF. Read on every request rather than cached at import: it is 48 KB
    off local disk, and a module-level cache would keep a stale copy alive in a process
    that outlives a deploy of new content."""
    return GUIDE_PATH.read_bytes()
