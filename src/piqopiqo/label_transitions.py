"""Helpers for configurable label transition rules."""

from __future__ import annotations

from attrs import define, field

from piqopiqo.metadata.db_fields import DBFields
from piqopiqo.model import LabelTransitionRule, StatusLabel


@define(frozen=True)
class LabelTransitionChange:
    file_path: str
    from_label: str
    to_label: str
    rule_index: int


@define(frozen=True)
class LabelTransitionPlan:
    changes: list[LabelTransitionChange] = field(factory=list)
    per_rule_counts: list[int] = field(factory=list)

    @property
    def changed_count(self) -> int:
        return len(self.changes)


def normalize_label_value(value: object) -> str:
    return str(value or "").strip()


def known_label_values(status_labels: list[StatusLabel]) -> set[str]:
    return {
        "",
        *(
            normalize_label_value(label.name)
            for label in status_labels
            if normalize_label_value(label.name)
        ),
    }


def is_valid_label_transition_rules(
    rules: list[LabelTransitionRule] | None,
    *,
    status_labels: list[StatusLabel],
) -> bool:
    known_values = known_label_values(status_labels)
    seen_from: set[str] = set()
    for rule in rules or []:
        from_label = normalize_label_value(rule.from_label)
        to_label = normalize_label_value(rule.to_label)
        if from_label not in known_values or to_label not in known_values:
            return False
        if from_label == to_label:
            return False
        if from_label in seen_from:
            return False
        seen_from.add(from_label)
    return True


def filter_valid_label_transition_rules(
    rules: list[LabelTransitionRule] | None,
    *,
    status_labels: list[StatusLabel],
) -> list[LabelTransitionRule]:
    known_values = known_label_values(status_labels)
    out: list[LabelTransitionRule] = []
    seen_from: set[str] = set()
    for rule in rules or []:
        from_label = normalize_label_value(rule.from_label)
        to_label = normalize_label_value(rule.to_label)
        if from_label not in known_values or to_label not in known_values:
            continue
        if from_label == to_label:
            continue
        if from_label in seen_from:
            continue
        seen_from.add(from_label)
        out.append(LabelTransitionRule(from_label=from_label, to_label=to_label))
    return out


def _entry_file_path(entry: object) -> str:
    if isinstance(entry, dict):
        return str(entry.get("file_path") or "").strip()
    return str(getattr(entry, "path", "") or "").strip()


def _entry_metadata(entry: object) -> dict | None:
    if isinstance(entry, dict):
        metadata = entry.get("db_metadata")
    else:
        metadata = getattr(entry, "db_metadata", None)
    return metadata if isinstance(metadata, dict) else None


def plan_label_transition_changes(
    entries: list[object],
    rules: list[LabelTransitionRule],
) -> LabelTransitionPlan:
    per_rule_counts = [0 for _rule in rules]
    rule_by_from: dict[str, tuple[int, str]] = {}
    for index, rule in enumerate(rules):
        from_label = normalize_label_value(rule.from_label)
        if from_label in rule_by_from:
            continue
        rule_by_from[from_label] = (index, normalize_label_value(rule.to_label))

    changes: list[LabelTransitionChange] = []
    seen_paths: set[str] = set()
    for entry in entries:
        file_path = _entry_file_path(entry)
        if not file_path or file_path in seen_paths:
            continue
        seen_paths.add(file_path)

        metadata = _entry_metadata(entry)
        current_label = normalize_label_value(
            metadata.get(DBFields.LABEL) if metadata is not None else None
        )
        match = rule_by_from.get(current_label)
        if match is None:
            continue

        rule_index, to_label = match
        changes.append(
            LabelTransitionChange(
                file_path=file_path,
                from_label=current_label,
                to_label=to_label,
                rule_index=rule_index,
            )
        )
        per_rule_counts[rule_index] += 1

    return LabelTransitionPlan(
        changes=changes,
        per_rule_counts=per_rule_counts,
    )
