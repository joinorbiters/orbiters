"""Imports every SQLAlchemy model so that `Base.metadata` is complete.

Each task that adds a model appends its import here.
"""

from pigrocrm.core.auth.models import User  # noqa: F401
from pigrocrm.core.auth.pat_models import PersonalAccessToken  # noqa: F401
