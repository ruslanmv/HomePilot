"""
Publish subsystem — promotes a draft experience to a channel.

  publisher.py  publish(experience, channel) → Publication

Publishing flow:

  1. Run QA. Refuse to publish if verdict == 'fail'.
  2. Build packaged experience (manifest + digest).
  3. Compare digest against the most recent publication on the
     same channel — if identical, return the existing record
     (idempotent re-publish).
  4. Insert ix_publications row with the new manifest + version
     bumped from the previous one.
  5. Update ix_experiences.status = 'published'.

Channels supported in v1: 'web_embed', 'studio_preview', 'export'.
The channel string lives on the publication row so future channels
need no schema change.
"""
from .publisher import PublishResult, publish

__all__ = ["PublishResult", "publish"]
