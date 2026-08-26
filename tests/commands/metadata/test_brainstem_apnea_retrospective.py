import hashlib
import json
from pathlib import Path

from commands.dataunions.brainstem.apnea_retrospective import (
    candidate_protocol,
    protocol_sha256,
)
from commands.dataunions.brainstem.record_export import full_night_rr_record


def test_full_night_contract_and_protocol_are_aggregate_only(tmp_path: Path):
    owner = "generated-owner"
    path = tmp_path / owner / "night.json"
    path.parent.mkdir()
    rows = ";".join(
        f"{minute * 60},60," + ",".join(["1000"] * 60)
        for minute in range(301)
    )
    record = {
        "schemaVersion": "1.0",
        "type": "sleep",
        "timestamp": "2026-08-04_000000",
        "datasource": {
            "sensor": {
                "name": "generated",
                "id": "not-exported",
                "payloads": {
                    "hbr_rr": {
                        "dataType": "hbr_rr",
                        "format": "csv",
                        "data": rows,
                    }
                },
            }
        },
    }
    path.write_text(json.dumps(record), encoding="utf-8")
    digest = hashlib.sha256(
        json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    result = full_night_rr_record(
        tmp_path,
        owner,
        {"_id": "generated-record", "file_path": str(path), "content_hash": digest},
    )
    assert result is not None
    assert set(result.recording) == {
        "recordingType",
        "durationSeconds",
        "intervalSemantics",
        "allowedUse",
        "quality",
        "rrIntervalsMs",
    }
    assert len(result.recording["rrIntervalsMs"]) == 18060
    assert result.recording["quality"] == {
        "observedIntervalCount": 18060,
        "acceptedIntervalCount": 18060,
        "acceptedFraction": 1.0,
        "durationCoverageRatio": round(18060 / 18001, 6),
        "normalToNormalProvenance": "unverified",
        "officialMethodInputCompatible": False,
    }

    record["datasource"]["sensor"]["payloads"]["hbr_rr"]["data"] = (
        record["datasource"]["sensor"]["payloads"]["hbr_rr"]["data"].replace(
            ",1000", ",invalid", 1000
        )
    )
    path.write_text(json.dumps(record), encoding="utf-8")
    rejected_digest = hashlib.sha256(
        json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert (
        full_night_rr_record(
            tmp_path,
            owner,
            {
                "_id": "generated-record",
                "file_path": str(path),
                "content_hash": rejected_digest,
            },
        )
        is None
    )

    protocol = candidate_protocol()
    assert protocol["status"] == "candidate_generated_only"
    assert protocol["privacy"]["minimumDistinctParticipants"] == 20
    assert protocol["analysis"]["personalResult"] is False
    assert protocol["method"]["executionStatus"].startswith("blocked_")
    assert protocol["activation"]["generatedDataOnly"] is True
    assert not any(
        value
        for key, value in protocol["activation"].items()
        if key != "generatedDataOnly"
    )
    assert protocol_sha256() == hashlib.sha256(
        json.dumps(protocol, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
