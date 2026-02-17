"""Fast keyword/regex prompt classifier for context retrieval.

No LLM calls — must complete classification in <500ms total.
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.storage.models import Person, Project

logger = logging.getLogger(__name__)

# Query type detection patterns
_CODE_PATTERNS = re.compile(
    r'\b(bug|fix|error|refactor|test|function|class|module|import|file|code|implement|build|compile|lint|deploy)\b',
    re.IGNORECASE,
)
_EMAIL_PATTERNS = re.compile(
    r'\b(email|reply|send|draft|inbox|gmail|message|forward)\b',
    re.IGNORECASE,
)
_TASK_PATTERNS = re.compile(
    r'\b(task|todo|priority|deadline|sprint|kanban|backlog|assign|commit|milestone)\b',
    re.IGNORECASE,
)
_META_PATTERNS = re.compile(
    r'\b(focus|vault|sync|config|setup|hook|daemon|worker)\b',
    re.IGNORECASE,
)


@dataclass
class PromptClassification:
    """Result of classifying a user prompt for context retrieval."""

    project_slugs: list[str] = field(default_factory=list)
    person_names: list[str] = field(default_factory=list)
    query_type: str = "general"
    workspace_project: Optional[str] = None
    explicit_project: Optional[str] = None
    file_paths: list[str] = field(default_factory=list)
    confidence: float = 0.0


class PromptClassifier:
    """Fast keyword/regex classifier for prompt context retrieval.

    Pre-loads known entities from the database on init, then classifies
    via pure regex/string matching — no LLM calls.
    """

    def __init__(self) -> None:
        self._projects: list[tuple[str, str]] = []  # (slug, name)
        self._people: list[tuple[str, Optional[str]]] = []  # (name, email)
        self._loaded = False

    async def load_entities(self, session: AsyncSession) -> None:
        """Load known projects and people from the database.

        Should complete in <100ms for typical dataset sizes.

        Args:
            session: Database session.
        """
        result = await session.execute(
            select(Project.slug, Project.name).where(Project.status == "active")
        )
        self._projects = [(row[0], row[1]) for row in result.all()]

        result = await session.execute(
            select(Person.name, Person.email)
        )
        self._people = [(row[0], row[1]) for row in result.all() if row[0]]

        self._loaded = True
        logger.debug(
            "Classifier loaded %d projects, %d people",
            len(self._projects), len(self._people),
        )

    def classify(
        self,
        prompt: str,
        cwd: Optional[str] = None,
    ) -> PromptClassification:
        """Classify a prompt using keyword matching.

        All regex/string ops, no LLM calls. Completes in <10ms.

        Args:
            prompt: The user's prompt text.
            cwd: Current working directory (for workspace matching).

        Returns:
            PromptClassification with matched entities and confidence.
        """
        result = PromptClassification()

        if not prompt or len(prompt.strip()) < 3:
            return result

        prompt_lower = prompt.lower()

        # 0. Explicit project from project state
        from src.context.project_state import get_active_project

        explicit = get_active_project(workspace=cwd)
        if explicit:
            result.explicit_project = explicit
            if explicit not in result.project_slugs:
                result.project_slugs.append(explicit)

        # 1. Workspace matching — set from cwd regardless of project match
        if cwd:
            dir_name = Path(cwd).name.lower()
            result.workspace_project = dir_name
            # Boost if it matches a known project slug
            for slug, name in self._projects:
                if slug == dir_name:
                    break

        # 2. Project matching
        for slug, name in self._projects:
            if _word_match(slug, prompt_lower):
                if slug not in result.project_slugs:
                    result.project_slugs.append(slug)
            elif name and _word_match(name.lower(), prompt_lower):
                if slug not in result.project_slugs:
                    result.project_slugs.append(slug)

        # 3. Person matching
        for name, email in self._people:
            if len(name) > 2 and _word_match(name.lower(), prompt_lower):
                if name not in result.person_names:
                    result.person_names.append(name)

        # 4. Query type detection
        result.query_type = _detect_query_type(prompt)

        # 5. File path extraction
        from src.context.artifact_extractor import extract_file_paths_from_text

        result.file_paths = extract_file_paths_from_text(prompt)

        # 6. Confidence scoring
        result.confidence = _compute_confidence(result)

        return result


def _word_match(pattern: str, text: str) -> bool:
    """Check if pattern appears as a word boundary match in text.

    Uses word boundaries when the pattern starts/ends with word chars,
    falls back to substring search for patterns with special chars.

    Args:
        pattern: The pattern to search for (lowercase).
        text: The text to search in (lowercase).

    Returns:
        True if pattern matches at word boundaries.
    """
    escaped = re.escape(pattern)

    # Use word boundaries only if pattern starts/ends with word chars
    prefix = r'\b' if pattern and pattern[0].isalnum() else ''
    suffix = r'\b' if pattern and pattern[-1].isalnum() else ''

    try:
        return bool(re.search(prefix + escaped + suffix, text))
    except re.error:
        return pattern in text


def _detect_query_type(prompt: str) -> str:
    """Detect the type of query from the prompt text.

    Args:
        prompt: The user's prompt.

    Returns:
        One of: "code", "email", "task", "meta", "general".
    """
    if _CODE_PATTERNS.search(prompt):
        return "code"
    if _EMAIL_PATTERNS.search(prompt):
        return "email"
    if _TASK_PATTERNS.search(prompt):
        return "task"
    if _META_PATTERNS.search(prompt):
        return "meta"
    return "general"


def _compute_confidence(classification: PromptClassification) -> float:
    """Compute confidence score based on what was matched.

    Args:
        classification: The classification result so far.

    Returns:
        Confidence score from 0.0 to 1.0.
    """
    score = 0.0

    # Explicit project selection is highest confidence
    if classification.explicit_project:
        score = max(score, 0.9)

    # Explicit entity mentions are high confidence
    if classification.project_slugs:
        score = max(score, 0.8)
    if classification.person_names:
        score = max(score, 0.7)

    # Workspace match alone is medium confidence
    if classification.workspace_project and score < 0.5:
        score = 0.5

    # Query type adds a small boost
    if classification.query_type != "general" and score < 0.3:
        score = 0.3

    # No matches at all
    if score == 0.0:
        score = 0.1

    return score
