"""The installation's own settings, kept in its own database.

An environment variable is the operator's decision for a process; a space (spec
2026-09-08) has no operator and no process of its own, so the settings that make sense
per space live in that space's database and are read on every request. The root can
use them too: a row here wins over the environment for the keys this package knows.
"""

from pigrocrm.core.space_settings.models import SpaceSetting
from pigrocrm.core.space_settings.schemas import (
    OVERRIDABLE_KEYS,
    SpaceSettingsRead,
    SpaceSettingsUpdate,
)
from pigrocrm.core.space_settings.service import SpaceSettingsService, apply_overrides

__all__ = [
    "OVERRIDABLE_KEYS",
    "SpaceSetting",
    "SpaceSettingsRead",
    "SpaceSettingsService",
    "SpaceSettingsUpdate",
    "apply_overrides",
]
