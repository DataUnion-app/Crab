from models.GuidelinesAcceptanceFlag import GuidelinesAcceptanceFlag
from models.UsageFlag import UsageFlag


def has_brainstem_data_consent(user):
    return bool(user) and (
        user.get("usage_flag") == UsageFlag.ACCEPTED.name
        and user.get("guidelines_acceptance_flag")
        == GuidelinesAcceptanceFlag.ACCEPTED.name
    )


def has_legacy_mobile_consent(user):
    """Keep pre-migration apps working without weakening research consent."""
    allowed_usage = {UsageFlag.UNKNOWN.name, UsageFlag.ACCEPTED.name}
    allowed_guidelines = {
        GuidelinesAcceptanceFlag.UNKNOWN.name,
        GuidelinesAcceptanceFlag.ACCEPTED.name,
    }
    return bool(user) and user.get("is_access_blocked") is not True and (
        user.get("usage_flag") in allowed_usage
        and user.get("guidelines_acceptance_flag") in allowed_guidelines
    )
