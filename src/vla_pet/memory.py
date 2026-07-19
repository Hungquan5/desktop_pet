from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from vla_pet.persistence import StateRepository


class MemoryTier(str, Enum):
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROFILE = "profile"
    TASK = "task"
    RELATIONSHIP = "relationship"
    PROCEDURAL = "procedural"


@dataclass(frozen=True, slots=True)
class MemoryCandidate:
    tier: MemoryTier
    kind: str
    summary: str
    salience: float = 0.5
    tags: tuple[str, ...] = ()
    ttl_days: int | None = None


class MemoryManager:
    """Local deterministic memory policy with inspectable SQLite retrieval."""

    _EMAIL = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
    _SECRET = re.compile(
        r"(?i)\b(password|passwd|token|api[_ -]?key|secret)\s*[:=]\s*\S+"
    )
    _PREFERENCE = re.compile(
        r"(?i)\b(?:i\s+(?:really\s+)?(?:like|love|prefer)|my\s+favorite\s+\w+\s+is)\s+(.+)"
    )
    _PROFILE = re.compile(r"(?i)\b(?:call me|my name is)\s+([\w .'-]{1,80})")
    _TASK = re.compile(r"(?i)\b(?:remember to|todo:?|i need to)\s+(.+)")
    _FACT = re.compile(r"(?i)\bremember that\s+(.+)")

    def __init__(self, repository: StateRepository) -> None:
        self.repository = repository

    def remember(self, candidate: MemoryCandidate, *, details: dict[str, Any] | None = None) -> str:
        summary = self.sanitize(candidate.summary)
        if not summary:
            raise ValueError("Memory summary cannot be empty")
        expires_at = None
        if candidate.ttl_days is not None:
            expires_at = (
                datetime.now(timezone.utc) + timedelta(days=max(1, candidate.ttl_days))
            ).isoformat()
        dedupe_key = hashlib.sha256(
            f"{candidate.tier.value}:{candidate.kind}:{self._normalize(summary)}".encode()
        ).hexdigest()
        return self.repository.upsert_memory(
            tier=candidate.tier.value,
            kind=candidate.kind,
            summary=summary,
            dedupe_key=dedupe_key,
            salience=candidate.salience,
            tags=candidate.tags,
            details=details,
            expires_at=expires_at,
        )

    def extract_user_candidates(self, message: str) -> tuple[MemoryCandidate, ...]:
        """Store only explicit profile/preferences/tasks; never infer secrets."""
        text = " ".join(message.strip().split())[:1000]
        if not text or self._SECRET.search(text):
            return ()
        candidates: list[MemoryCandidate] = []
        if match := self._PREFERENCE.search(text):
            candidates.append(
                MemoryCandidate(
                    MemoryTier.PROFILE,
                    "explicit_preference",
                    f"User preference: {match.group(1).strip()}",
                    0.82,
                    ("preference",),
                )
            )
        if match := self._PROFILE.search(text):
            candidates.append(
                MemoryCandidate(
                    MemoryTier.PROFILE,
                    "preferred_name",
                    f"User prefers to be called {match.group(1).strip()}",
                    0.95,
                    ("profile", "name"),
                )
            )
        if match := self._TASK.search(text):
            task = match.group(1).strip().rstrip(".!?")
            candidates.append(
                MemoryCandidate(
                    MemoryTier.TASK,
                    "unfinished_task",
                    f"Unfinished task: {task}",
                    0.78,
                    ("task", "unfinished"),
                    90,
                )
            )
        if match := self._FACT.search(text):
            fact = match.group(1).strip().rstrip(".!?")
            candidates.append(
                MemoryCandidate(
                    MemoryTier.SEMANTIC,
                    "explicit_fact",
                    f"Explicit fact: {fact}",
                    0.72,
                    ("fact",),
                )
            )
        return tuple(candidates)

    def remember_from_user(self, message: str) -> tuple[str, ...]:
        return tuple(self.remember(candidate) for candidate in self.extract_user_candidates(message))

    def remember_shared_event(self, summary: str, *, salience: float = 0.65) -> str:
        return self.remember(
            MemoryCandidate(
                MemoryTier.EPISODIC,
                "shared_event",
                summary,
                salience,
                ("shared",),
                365,
            )
        )

    def remember_relationship(self, summary: str) -> str:
        return self.remember(
            MemoryCandidate(
                MemoryTier.RELATIONSHIP,
                "relationship_milestone",
                summary,
                0.85,
                ("relationship", "milestone"),
            )
        )

    def remember_procedure(self, summary: str) -> str:
        return self.remember(
            MemoryCandidate(
                MemoryTier.PROCEDURAL,
                "successful_workflow",
                summary,
                0.6,
                ("procedure",),
            )
        )

    def retrieve(
        self, query: str, *, tiers: tuple[MemoryTier, ...] = (), limit: int = 6
    ) -> tuple[dict[str, Any], ...]:
        return self.repository.search_memories(
            query,
            tiers=tuple(tier.value for tier in tiers),
            limit=limit,
        )

    def prompt_context(self, query: str, *, max_chars: int = 900) -> str:
        rows = self.retrieve(query, limit=8)
        lines: list[str] = []
        total = 0
        for row in rows:
            line = f"- [{row['tier']}] {row['summary']}"
            if total + len(line) + 1 > max_chars:
                break
            lines.append(line)
            total += len(line) + 1
        return "\n".join(lines)

    @classmethod
    def sanitize(cls, text: str) -> str:
        value = cls._EMAIL.sub("<email>", " ".join(text.strip().split()))
        value = cls._SECRET.sub(lambda match: f"{match.group(1)}=<redacted>", value)
        return value[:1000]

    @staticmethod
    def _normalize(text: str) -> str:
        return " ".join(re.findall(r"[\w-]+", text.casefold(), flags=re.UNICODE))
