"""Generate human-readable changelog/commit messages from diffs."""

from .diff import TimelineDiff, changelog_line


def generate_commit_message(diff: TimelineDiff, user_message: str = "") -> str:
    headline = changelog_line(diff)
    if user_message:
        # User message is primary; auto changelog is appended
        return f"{user_message}\n\nAuto: {headline}"
    return headline


def generate_extended_message(diff: TimelineDiff, user_message: str = "") -> str:
    from .diff import format_text

    headline = generate_commit_message(diff, user_message)
    details = format_text(diff)
    # Don't duplicate headline if already there
    return f"{headline}\n\n{details}"
