from commands.metadata import brainstem_recording_command as module


class _MetadataDao:
    def query_view(self, design, view, group=False):
        assert (design, view, group) == ("brainstem", "recording-statistics", True)
        return {
            "rows": [{
                "value": {
                    "total_count": 2,
                    "total_length": 900,
                    "last_24h_count": 1,
                    "type_counts": {"sleep": 2},
                    "user_counts": {"participant-a": 2},
                }
            }]
        }


class _RewardsDao:
    def query_view(self, design, view):
        return {"rows": [{"value": 3}]}


def test_statistics_uses_the_installed_brainstem_view(monkeypatch):
    monkeypatch.setattr(module, "image_metadata_dao", _MetadataDao())
    monkeypatch.setattr(module, "rewards_dao", _RewardsDao())

    assert module.BrainstemRecordingStatisticsCommand().execute() == {
        "total_count": 2,
        "total_length": 900,
        "type_counts": {"sleep": 2},
        "last_24h_count": 1,
        "users": 1,
        "total_rewards": 3,
    }
