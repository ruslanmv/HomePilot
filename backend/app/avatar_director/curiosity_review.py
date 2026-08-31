"""A twenty-minute session, printed — the half of B16's acceptance a test cannot do.

The batch is done when "a reviewer sits a 20-minute session and reports no moment felt
intrusive". A test can prove she was never *muted* when she spoke; it cannot tell you
whether the moment felt right, which is a judgement about tone and timing that belongs to a
person. So this exists to make that person's job cheap: it replays a scripted session and
prints every moment she would have spoken, with what was happening at the time, on one
screen.

    python -m app.avatar_director.curiosity_review

It is not a test and nothing imports it. A reviewer reads the output; their verdict goes in
``docs/AVATAR_DIRECTOR_BATCHES.md`` next to the rest of B16 — signed, or not yet.
"""

from __future__ import annotations

from .config import AvatarDirectorConfig, CuriosityConfig
from .curiosity import CuriosityEngine, InitiativeScheduler, InterestRecord, InterestStore


class _Memory(InterestStore):
    """The store in a dict, so a reviewer needs no database to read the timeline."""

    def __init__(self) -> None:
        super().__init__("review")
        self.records: dict = {}

    def all(self):
        return list(self.records.values())

    def get(self, topic):
        return self.records.get(topic)

    def save(self, record):
        self.records[record.topic] = record
        return record


#: What she is carrying into the evening. Realistic rather than flattering: at least one of
#: these would be actively unwelcome at the wrong moment, which is the point of reviewing.
TOPICS = [
    ("user.hobby.aquarium", "Planning a visit to the new aquarium", 0.72),
    ("user.work.thesis", "Chapter three has been stuck for a fortnight", 0.64),
    ("user.pet.cat", "The cat has been off her food", 0.58),
    ("user.family.mum", "Mum's scan results are due this week", 0.81),
]

#: Seconds from the start. The same transcript the etiquette tests replay.
SESSION = [
    (0, "ctx", {"activity": None, "attention": 0.2, "scene": None}, "settling in"),
    (15, "event", "user:silent", "a lull"),
    (30, "event", "user:silent", "still quiet"),
    (95, "event", "user:speaking", "telling a story"),
    (120, "event", "media:paused", "pauses the film mid-sentence"),
    (150, "event", "user:silent", "story over"),
    (185, "event", "media:cut", "scene change"),
    (240, "ctx", {"activity": "watch", "attention": 0.95, "scene": None}, "gripped by the film"),
    (300, "event", "media:cut", "scene change"),
    (360, "event", "media:cut", "scene change"),
    (420, "event", "media:paused", "pauses, still gripped"),
    (430, "ctx", {"activity": "watch", "attention": 0.4, "scene": None}, "looks up"),
    (600, "ctx", {"activity": None, "attention": 0.1, "scene": "meditation"}, "starts a meditation"),
    (620, "event", "user:silent", "quiet"),
    (700, "event", "media:paused", "quiet"),
    (800, "event", "user:silent", "quiet"),
    (900, "ctx", {"activity": None, "attention": 0.2, "scene": None}, "meditation ends"),
    (960, "event", "user:silent", "a lull"),
    (1020, "event", "user:speaking", "on the phone"),
    (1100, "event", "user:silent", "call over"),
    (1140, "event", "media:paused", "puts the kettle on"),
    (1200, "event", "user:silent", "a lull"),
]

OPENINGS = ["media:paused", "media:cut", "gaze:user-look-avatar>1500", "user:silent>12000"]


def build(budget: int = 4, min_gap_ms: int = 90000) -> InitiativeScheduler:
    clock = {"t": 0.0}
    store = _Memory()
    for topic, summary, curiosity in TOPICS:
        store.save(InterestRecord(topic=topic, summary=summary, curiosity=curiosity, openThread=True))

    config = AvatarDirectorConfig(
        enabled=True, curiosity=CuriosityConfig(session_budget=budget, min_gap_ms=min_gap_ms)
    )
    scheduler = InitiativeScheduler(CuriosityEngine(store, now=lambda: clock["t"]), config, now=lambda: clock["t"])
    scheduler.set_openings(OPENINGS)
    scheduler.clock = clock
    return scheduler


def run(seconds: int = 1200):
    """Replay, returning ``(scheduler, moments, narrative)``. ``main`` prints them."""
    scheduler = build()
    pending = list(SESSION)
    narrative = []
    moments = []
    note = "settling in"

    for second in range(seconds + 1):
        while pending and pending[0][0] <= second:
            _, kind, payload, description = pending.pop(0)
            note = description
            narrative.append((second, note))
            if kind == "ctx":
                scheduler.on_ctx(payload)
            else:
                scheduler.on_user_event(payload)
        scheduler.clock["t"] = float(second)
        chosen = scheduler.due()
        if chosen:
            moments.append((second, chosen, note))
    return scheduler, moments, narrative


def main() -> None:  # pragma: no cover - a reading aid, not a test
    scheduler, moments, narrative = run()
    spoke_at = {second for second, _, _ in moments}

    print("Twenty minutes, second by second. Every moment she chose to speak:\n")
    for second, chosen, note in moments:
        print(f"  {second // 60:>2}:{second % 60:02d}  “{chosen['summary']}”")
        print(f"         opening: {chosen['opening']}   ·   they were: {note}\n")
    if not moments:
        print("  (she said nothing — check the transcript offers an opening at all)\n")

    print(f"{len(moments)} initiative(s) in twenty minutes, from a budget of 4.\n")
    print("Why she stayed quiet the rest of the time:")
    for why, count in sorted(scheduler.refusals.items(), key=lambda kv: -kv[1]):
        print(f"  {count:>5} × {why}")

    print("\nThe transcript, for context:")
    for second, note in narrative:
        marker = "   ← she spoke" if second in spoke_at else ""
        print(f"  {second // 60:>2}:{second % 60:02d}  {note}{marker}")


if __name__ == "__main__":  # pragma: no cover
    main()
