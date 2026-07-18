"""Pure title and tag replacement rules shared by local and Flickr tools."""

from __future__ import annotations

import re

from attrs import define

from piqopiqo.keyword_utils import normalize_keyword_list


@define(frozen=True)
class FindReplaceSpec:
    title_pattern: str = ""
    replace_title: bool = False
    title_replacement: str = ""
    remove_tags: tuple[str, ...] = ()
    add_tags: tuple[str, ...] = ()
    add_only_if_removed: bool = False

    def normalized(self) -> FindReplaceSpec:
        return FindReplaceSpec(
            title_pattern=str(self.title_pattern or ""),
            replace_title=bool(self.replace_title),
            title_replacement=str(self.title_replacement or ""),
            remove_tags=tuple(normalize_keyword_list(list(self.remove_tags))),
            add_tags=tuple(normalize_keyword_list(list(self.add_tags))),
            add_only_if_removed=bool(self.add_only_if_removed),
        )


@define(frozen=True)
class ReplacementOutcome:
    eligible: bool
    title: str
    tags: tuple[str, ...]
    title_changed: bool = False
    removed_tags: int = 0
    added_tags: int = 0

    @property
    def changed(self) -> bool:
        return self.title_changed or self.removed_tags > 0 or self.added_tags > 0


def validate_find_replace_spec(spec: FindReplaceSpec) -> str | None:
    """Return a user-facing validation error, or None when the spec is valid."""
    normalized = spec.normalized()
    if normalized.replace_title and not normalized.title_pattern:
        return "A title condition is required to replace title text."
    if not (normalized.replace_title or normalized.remove_tags or normalized.add_tags):
        return "Choose at least one title or tag change."
    if normalized.add_only_if_removed and not normalized.remove_tags:
        return "Conditional tag addition requires at least one tag to remove."
    if not normalized.title_pattern:
        return None
    try:
        pattern = re.compile(normalized.title_pattern)
        if normalized.replace_title:
            pattern.sub(normalized.title_replacement, "")
    except re.error as ex:
        return f"Invalid title regular expression or replacement: {ex}"
    return None


def apply_replacement(
    title: str | None,
    tags: list[str] | tuple[str, ...],
    spec: FindReplaceSpec,
) -> ReplacementOutcome:
    """Apply title/tag rules without performing any persistence."""
    normalized = spec.normalized()
    title_text = str(title or "")
    current_tags = list(tags)

    pattern = re.compile(normalized.title_pattern) if normalized.title_pattern else None
    if pattern is not None and pattern.search(title_text) is None:
        return ReplacementOutcome(
            eligible=False,
            title=title_text,
            tags=tuple(current_tags),
        )

    new_title = title_text
    title_changed = False
    if normalized.replace_title and pattern is not None:
        new_title, replacement_count = pattern.subn(
            normalized.title_replacement,
            title_text,
        )
        title_changed = replacement_count > 0 and new_title != title_text

    remove_set = set(normalized.remove_tags)
    kept_tags = [tag for tag in current_tags if tag not in remove_set]
    removed_count = len(current_tags) - len(kept_tags)

    added_count = 0
    should_add = bool(normalized.add_tags) and (
        not normalized.add_only_if_removed or removed_count > 0
    )
    if should_add:
        seen = {tag.casefold() for tag in kept_tags}
        for tag in normalized.add_tags:
            key = tag.casefold()
            if key in seen:
                continue
            seen.add(key)
            kept_tags.append(tag)
            added_count += 1

    return ReplacementOutcome(
        eligible=True,
        title=new_title,
        tags=tuple(kept_tags),
        title_changed=title_changed,
        removed_tags=removed_count,
        added_tags=added_count,
    )
