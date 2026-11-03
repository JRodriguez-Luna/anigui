"""Which shows are 18+, and what's in them, from AniList's genres and community tags.

The rule was tuned on real AniList data (Nov 2026). Nudity is the clearest signal:
fan-service shows score 70+ (I'm Dating a Dark Summoner 93, High School DxD 93, Prison
School 88, Food Wars 80, Goblin Slayer 75), while shows with a scene or two stay below
(Chainsaw Man 48, KonoSuba 45, Rent-a-Girlfriend 20). AniList's own adult-tag flags are
too noisy to decide on their own (KonoSuba is tagged Masochism, Rent-a-Girlfriend
Prostitution), so they only feed the "Sexual themes" note. Shows AniList marks adult
are 18+ outright.

Violence and gore never make a show 18+ on their own (Attack on Titan, Chainsaw Man),
they're listed as notes. Spoiler tags are never shown, though they still count.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

NUDITY_18 = 70            # Nudity tag rank that makes a show 18+
SEXUAL_VIOLENCE_18 = 60   # same for the Rape tag
NOTE_RANK = 60            # a tag must be rated this central to the show to be listed
# "Nudity" is only listed when it's also enough for 18+, so the Content line and the badge agree
SEXUAL_VIOLENCE_NOTE = 40
DISTURBING = ("Torture", "Suicide", "Cannibalism", "Self-Harm", "Child Abuse", "Slavery")


@dataclass(frozen=True)
class Tag:
    name: str
    rank: int
    adult: bool = False
    spoiler: bool = False

    @classmethod
    def from_json(cls, d: dict) -> "Tag":
        return cls(str(d.get("name") or ""), int(d.get("rank") or 0), bool(d.get("isAdult")),
                   bool(d.get("isMediaSpoiler") or d.get("isGeneralSpoiler")))


@dataclass(frozen=True)
class Maturity:
    mature: bool = False
    notes: tuple[str, ...] = ()       # e.g. ("Nudity", "Sexual themes", "Gore")
    # What each note came from, for the tooltips: (note, ((tag, rank), ...)). An empty
    # tuple of tags means the Ecchi genre.
    sources: tuple[tuple[str, tuple[tuple[str, int], ...]], ...] = ()

    def source(self, note: str) -> tuple[tuple[str, int], ...]:
        return next((tags for name, tags in self.sources if name == note), ())


def level(rank: int) -> str:
    """AniList's 0-100 tag rating in words."""
    if rank >= 80:
        return "What the show is known for"
    if rank >= 60:
        return "A regular part of the show"
    if rank >= 40:
        return "Noticeable, but not the focus"
    return "Minor"


def assess(is_adult: bool, genres: Iterable[str], tags: Iterable[Tag]) -> Maturity:
    tags = list(tags)
    by_name = {t.name: t for t in tags}

    def rank(name: str) -> int:
        t = by_name.get(name)
        return t.rank if t else 0

    def shown(name: str, minimum: int = NOTE_RANK) -> bool:
        t = by_name.get(name)
        return bool(t and t.rank >= minimum and not t.spoiler)

    mature = bool(is_adult) or rank("Nudity") >= NUDITY_18 or rank("Rape") >= SEXUAL_VIOLENCE_18

    sources: list[tuple[str, tuple[tuple[str, int], ...]]] = []

    def note(name: str, found: list[tuple[str, int]], always: bool = False) -> None:
        if found or always:
            sources.append((name, tuple(sorted(found, key=lambda f: -f[1]))))

    def ranked(names: Iterable[str], minimum: int = NOTE_RANK) -> list[tuple[str, int]]:
        return [(n, rank(n)) for n in names if shown(n, minimum)]

    note("Nudity", ranked(["Nudity"], NUDITY_18))
    adult = [(t.name, t.rank) for t in tags if t.adult and t.name != "Rape" and t.rank >= NOTE_RANK and not t.spoiler]
    note("Sexual themes", adult, always="Ecchi" in set(genres))
    note("Sexual violence", ranked(["Rape"], SEXUAL_VIOLENCE_NOTE))
    note("Gore", ranked(["Gore", "Body Horror"]))
    note("Disturbing themes", ranked(DISTURBING, 50))
    return Maturity(mature, tuple(n for n, _ in sources), tuple(sources))
