"""Tests for label transition planning."""

from __future__ import annotations

from piqopiqo.label_transitions import plan_label_transition_changes
from piqopiqo.metadata.db_fields import DBFields
from piqopiqo.model import LabelTransitionRule


def test_plan_label_transition_changes_applies_rules_simultaneously():
    entries = [
        {"file_path": "/a.jpg", "db_metadata": {DBFields.LABEL: "Approved"}},
        {"file_path": "/b.jpg", "db_metadata": {DBFields.LABEL: "Uploaded"}},
        {"file_path": "/c.jpg", "db_metadata": {DBFields.LABEL: "Review"}},
        {"file_path": "/d.jpg", "db_metadata": {DBFields.LABEL: None}},
    ]
    rules = [
        LabelTransitionRule("Approved", "Uploaded"),
        LabelTransitionRule("Uploaded", "Rejected"),
        LabelTransitionRule("Review", "Rejected"),
        LabelTransitionRule("", "Approved"),
    ]

    plan = plan_label_transition_changes(entries, rules)

    assert [
        (change.file_path, change.from_label, change.to_label, change.rule_index)
        for change in plan.changes
    ] == [
        ("/a.jpg", "Approved", "Uploaded", 0),
        ("/b.jpg", "Uploaded", "Rejected", 1),
        ("/c.jpg", "Review", "Rejected", 2),
        ("/d.jpg", "", "Approved", 3),
    ]
    assert plan.per_rule_counts == [1, 1, 1, 1]
    assert plan.changed_count == 4


def test_plan_label_transition_changes_deduplicates_scope_paths():
    entries = [
        {"file_path": "/a.jpg", "db_metadata": {DBFields.LABEL: "Approved"}},
        {"file_path": "/a.jpg", "db_metadata": {DBFields.LABEL: "Approved"}},
    ]

    plan = plan_label_transition_changes(
        entries,
        [LabelTransitionRule("Approved", "Uploaded")],
    )

    assert [change.file_path for change in plan.changes] == ["/a.jpg"]
    assert plan.per_rule_counts == [1]
