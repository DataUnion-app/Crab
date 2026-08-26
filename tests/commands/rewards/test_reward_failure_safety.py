from commands.rewards.scrub_failure_reasons import scrub_failure_reasons
from models.rewards.rewards_model import RewardStatus, safe_reward_failure_message


SECRET_URL = "https://rpc.example/v2/provider-secret-value"


class FakeRewards:
    def __init__(self):
        self.documents = [{
            "_id": "failed-claim",
            "status": RewardStatus.FAILED,
            "reason": "403 Client Error for url: " + SECRET_URL,
        }]

    def iter_query(self, _query):
        yield from (dict(document) for document in self.documents)

    def mutate_doc(self, document_id, mutator):
        document = next(
            document for document in self.documents if document["_id"] == document_id
        )
        mutator(document)

    def get_rewards_list(self, *_args):
        return [dict(document) for document in self.documents]


def test_reward_failure_message_redacts_endpoints_and_named_secrets():
    message = safe_reward_failure_message(
        "request failed at " + SECRET_URL + " api_key=another-secret"
    )
    assert "provider-secret-value" not in message
    assert "another-secret" not in message
    assert "[redacted endpoint]" in message
    assert "api_key=[redacted]" in message


def test_scrubber_is_dry_run_by_default_and_applies_only_when_requested():
    rewards = FakeRewards()
    preview = scrub_failure_reasons(rewards)
    assert preview == {"examined": 1, "changed": 1, "applied": False}
    assert "provider-secret-value" in rewards.documents[0]["reason"]

    applied = scrub_failure_reasons(rewards, apply=True)
    assert applied == {"examined": 1, "changed": 1, "applied": True}
    assert "provider-secret-value" not in rewards.documents[0]["reason"]
