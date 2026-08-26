from dataclasses import dataclass
from datetime import datetime, timezone
import re

from commands.dataunions.brainstem.consent import has_brainstem_data_consent
from commands.dataunions.brainstem.limits import MINIMUM_DISCLOSURE_PARTICIPANTS


TOTAL_SORT_FIELDS = {"total_amount", "total_rows", "total_durations"}
NESTED_SORT_PATTERN = re.compile(r"^(counts|durations|rows)\.[A-Za-z0-9_-]+$")


@dataclass(frozen=True)
class BrainstemFilterSpec:
    recording_type: str = ""
    min_age: int = 0
    max_age: int = 120
    gender: str = ""
    ethnicity: str = ""
    min_amount: int = 0
    max_amount: int = 1_000_000
    page: int = 0
    per_page: int = 5
    sort_by: str = "total_amount"
    sort_direction: str = "descending"

    def __post_init__(self):
        if self.page < 0:
            raise ValueError("page must be zero or greater")
        if not 1 <= self.per_page <= 100:
            raise ValueError("per_page must be between 1 and 100")
        if self.min_age < 0 or self.max_age < self.min_age or self.max_age > 200:
            raise ValueError("age range is invalid")
        if self.min_amount < 0 or self.max_amount < self.min_amount:
            raise ValueError("amount range is invalid")
        if self.sort_direction not in {"ascending", "descending"}:
            raise ValueError("sort_direction must be ascending or descending")
        if (
            self.sort_by not in TOTAL_SORT_FIELDS
            and not NESTED_SORT_PATTERN.fullmatch(self.sort_by)
        ):
            raise ValueError("sort_by is not supported")


def _metric(recording_data, path):
    value = recording_data
    for part in path.split("."):
        if not isinstance(value, dict):
            return 0
        value = value.get(part, 0)
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def _safe_metric_map(value):
    if not isinstance(value, dict):
        return {}
    return {
        str(key): metric
        for key, metric in value.items()
        if isinstance(metric, (int, float)) and not isinstance(metric, bool)
    }


def sanitized_recording_data(value):
    value = value if isinstance(value, dict) else {}
    return {
        "total_amount": _metric(value, "total_amount"),
        "total_rows": _metric(value, "total_rows"),
        "total_durations": _metric(value, "total_durations"),
        "counts": _safe_metric_map(value.get("counts")),
        "durations": _safe_metric_map(value.get("durations")),
        "rows": _safe_metric_map(value.get("rows")),
    }


def _matches(user, spec, current_year):
    if not has_brainstem_data_consent(user):
        return False
    recording_data = sanitized_recording_data(user.get("recording_data"))
    metadata = user.get("metadata") if isinstance(user.get("metadata"), dict) else {}
    if spec.gender and metadata.get("gender") != spec.gender:
        return False
    if spec.ethnicity and metadata.get("region") != spec.ethnicity:
        return False
    year = metadata.get("year")
    if not isinstance(year, (int, float)) or isinstance(year, bool):
        return False
    age = current_year - int(year)
    if not spec.min_age <= age <= spec.max_age:
        return False
    if spec.recording_type and spec.recording_type not in recording_data["counts"]:
        return False
    amount_path = f"counts.{spec.recording_type}" if spec.recording_type else "total_amount"
    amount = _metric(recording_data, amount_path)
    return spec.min_amount <= amount <= spec.max_amount


def participant_selector(spec, current_year=None):
    """Build the server-side half of the participant filter contract."""
    current_year = current_year or datetime.now(timezone.utc).year
    amount_path = (
        f"recording_data.counts.{spec.recording_type}"
        if spec.recording_type else "recording_data.total_amount"
    )
    selector = {
        "recording_data": {"$exists": True},
        "usage_flag": "ACCEPTED",
        "guidelines_acceptance_flag": "ACCEPTED",
        "metadata.year": {
            "$gte": current_year - spec.max_age,
            "$lte": current_year - spec.min_age,
        },
        amount_path: {"$gte": spec.min_amount, "$lte": spec.max_amount},
    }
    if spec.gender:
        selector["metadata.gender"] = spec.gender
    if spec.ethnicity:
        selector["metadata.region"] = spec.ethnicity
    return selector


def project_participants(users, spec):
    current_year = datetime.now(timezone.utc).year
    total_count = 0

    for user in users:
        if _matches(user, spec, current_year):
            total_count += 1
    return {
        "rows": [],
        "participantCount": (
            "20_or_more"
            if total_count >= MINIMUM_DISCLOSURE_PARTICIPANTS
            else "fewer_than_20"
        ),
        "participantRowsExposed": False,
    }
