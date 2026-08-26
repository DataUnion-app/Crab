from enum import Enum
import re


_URL = re.compile(r"https?://[^\s'\"}\]]+", re.IGNORECASE)
_NAMED_SECRET = re.compile(
    r"(?i)\b(api[_-]?key|authorization|bearer|private[_-]?key|secret|token)\b"
    r"\s*[:=]\s*[^\s,;}]+"
)
_KNOWN_TOKEN = re.compile(
    r"\b(?:ghp_|github_pat_|sk-|pk_)[A-Za-z0-9_-]{12,}\b"
)


def safe_reward_failure_message(reason, maximum_length=500):
    """Keep payout failures useful without persisting provider credentials."""
    message = str(reason or "Reward transfer failed")
    message = _URL.sub("[redacted endpoint]", message)
    message = _NAMED_SECRET.sub(r"\1=[redacted]", message)
    message = _KNOWN_TOKEN.sub("[redacted credential]", message)
    return message[:maximum_length]


class RewardStatus(str, Enum):
    TRANSFERRING = "transferring"
    CALCULATING = "calculating"
    TRANSFER_FAILED = "transfer_failed"
    CREATED = "created"
    TRANSFER_SUCCEEDED = "transfer_succeeded"
    FAILED = 'failed'
    PAID = 'paid'
    VOIDED = 'voided'


class ClaimRewardErrorMessages(str, Enum):
    ALREADY_IN_PROGRESS = "Another claim in progress"
    AMOUNT_TOO_SMALL = "Amount too small"
    ZERO_AMOUNT = "Reward amount is 0"
    EXCEEDS_DAILY_LIMIT = "Max daily claim limit reached"
    REWARD_CLAIMED = "Reward already claimed"
    RECONCILIATION_REQUIRED = "Previous reward claim requires reconciliation"
    AMOUNT_CHANGED = "Reward amount changed; refresh before claiming"
    ELIGIBILITY_CHANGED = "Reward eligibility changed; refresh before claiming"


class TaskType(str, Enum):
    BRA_USER_SIGNUP = "BRA_USER_SIGNUP"
    BRA_COMP_REST = "BRA_COMP_REST"
    BRA_COMP_SLEEP = "BRA_COMP_SLEEP"
    BRA_COMP_BREATH_S = "BRA_COMP_BREATH_S"
    BRA_COMP_BREATH_L = "BRA_COMP_BREATH_L"
    BRA_COMP_REST_SEQ = "BRA_COMP_REST_SEQ"
    BRA_COMP_SLEEP_SEQ = "BRA_COMP_SLEEP_SEQ"
    BRA_COMP_BREATH_SEQ = "BRA_COMP_BREATH_SEQ"
    BRA_COMP_BREATH_L_SEQ = "BRA_COMP_BREATH_L_SEQ"
    BRA_COMP_ALL_SEQ = "BRA_COMP_ALL_SEQ"
