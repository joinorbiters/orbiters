"""Imports every SQLAlchemy model so that `Base.metadata` is complete.

Each task that adds a model appends its import here.
"""

from pigrocrm.core.activities.models import Activity  # noqa: F401
from pigrocrm.core.auth.models import User  # noqa: F401
from pigrocrm.core.auth.pat_models import PersonalAccessToken  # noqa: F401
from pigrocrm.core.auth.refresh_models import RefreshToken  # noqa: F401
from pigrocrm.core.customers.models import Customer  # noqa: F401
from pigrocrm.core.deals.models import Deal  # noqa: F401
from pigrocrm.core.fields.models import FieldDefinition  # noqa: F401
from pigrocrm.core.people.models import Person  # noqa: F401
from pigrocrm.core.pipeline.models import PipelineStage  # noqa: F401
