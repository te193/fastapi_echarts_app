from etl import label_local_generation, label_rule_evidence_snapshot_update
from app.services.label_hub_change_data import LabelHubChangeDataService


def test_default_entry_uses_local_generation_and_never_opens_legacy_remote_results(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("legacy remote label path was used")

    monkeypatch.setattr(label_rule_evidence_snapshot_update, "connect_source", forbidden)
    monkeypatch.setattr(label_rule_evidence_snapshot_update, "latest_label_dates", forbidden)
    monkeypatch.setattr(label_rule_evidence_snapshot_update, "sync_label_snapshots", forbidden)
    expected = {"source_mode": "local_generated", "periods": ["7d", "14d", "30d", "90d"]}
    monkeypatch.setattr(label_local_generation, "run_generation", lambda **kwargs: dict(expected))
    assert label_rule_evidence_snapshot_update.run_update() == expected


def test_generated_evidence_uses_generated_role_even_when_old_python_threshold_disagrees():
    old = {"evidence_status": "generated", "computed_sub_label_id": 101, "daily_sales": 2, "tag_gross_margin": 0.2}
    new = {"evidence_status": "generated", "computed_sub_label_id": 102, "daily_sales": 2, "tag_gross_margin": 0.2}
    code, _ = LabelHubChangeDataService._reason_for_pair(old, new)
    assert code not in {"evidence_mismatch", "evidence_missing"}
