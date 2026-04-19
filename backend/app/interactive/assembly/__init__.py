"""
Assembly subsystem — turn DB rows into a publishable manifest.

Two things live here:

  manifest.py   build_manifest(experience) → dict — a complete,
                self-describing snapshot of an experience: nodes,
                edges, actions, rules, asset references. The
                publish flow stores a copy on ix_publications.
  packager.py   package_experience — light wrapper that pairs a
                manifest with a deterministic content hash so the
                publish step can detect "nothing changed since
                last publish" and skip re-emitting.

Nothing here writes back to ix_experiences — assembly is
read-only. Status changes happen one layer up in publish/.
"""
from .manifest import build_manifest
from .packager import PackagedExperience, package_experience

__all__ = [
    "build_manifest",
    "PackagedExperience",
    "package_experience",
]
