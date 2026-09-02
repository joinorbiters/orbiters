from pigrocrm.core.automations.config_service import AutomationConfigService
from pigrocrm.core.automations.models import AutomationConfig
from pigrocrm.core.automations.runner import AutomationOutcome, AutomationRunner
from pigrocrm.core.automations.schemas import (
    AUTOMATION_KINDS,
    KIND_CONFIG_CHANGED,
    KIND_NOT_EXECUTED,
    KIND_STAGE_MOVED,
    AutomationConfigRead,
    AutomationConfigUpdate,
    AutomationRule,
    AutomationRuleDescription,
    AutomationRun,
    AutomationsDescription,
    AutomationSkipReason,
)

__all__ = [
    "AUTOMATION_KINDS",
    "KIND_CONFIG_CHANGED",
    "KIND_NOT_EXECUTED",
    "KIND_STAGE_MOVED",
    "AutomationConfig",
    "AutomationConfigRead",
    "AutomationConfigService",
    "AutomationConfigUpdate",
    "AutomationOutcome",
    "AutomationRule",
    "AutomationRuleDescription",
    "AutomationRun",
    "AutomationRunner",
    "AutomationSkipReason",
    "AutomationsDescription",
]
