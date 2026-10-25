"""The production gate: deploy the same commit the Space can serve, and never an older one."""
from __future__ import annotations

import unittest
from pathlib import Path

from resolve_deploy import (
    APP_IMAGE_FILES, APP_IMAGE_PREFIXES, decide, needs_image_wait, touches_app_image,
)
from verify_production import version_matches

OWNER = "ruslanmv"
HEAD = "b317a51fded1cf965e7f95fb8cb38d00b1ee462e"
OLDER = "8bf8936f02700ce7fbc48e9e2b49490c6b9aafdf"
LATEST = HEAD


def _present(tag: str) -> bool:
    return tag in {HEAD[:7], LATEST[:7]}


class DecideTests(unittest.TestCase):
    def test_a_failed_publish_does_not_deploy(self):
        for conclusion in ("failure", "cancelled", ""):
            decision = decide(
                event="workflow_run", conclusion=conclusion, branch="master",
                head_sha=HEAD, changed=None, image_tag_exists=_present,
                latest_sha=LATEST, master_sha=HEAD, is_ancestor=lambda _a, _b: False,
                owner=OWNER,
            )
            self.assertTrue(decision.skip, conclusion)

    def test_a_successful_publish_wraps_that_commits_tag(self):
        decision = decide(
            event="workflow_run", conclusion="success", branch="master",
            head_sha=HEAD, changed=None, image_tag_exists=_present,
            latest_sha="", master_sha=HEAD, is_ancestor=lambda _a, _b: False,
            owner=OWNER,
        )
        self.assertFalse(decision.skip)
        self.assertEqual(decision.sha, HEAD)
        self.assertEqual(decision.base_image, f"ghcr.io/{OWNER}/homepilot:{HEAD[:7]}")

    def test_a_publish_without_its_image_fails_closed(self):
        with self.assertRaises(SystemExit):
            decide(
                event="workflow_run", conclusion="success", branch="master",
                head_sha=HEAD, changed=None, image_tag_exists=lambda _tag: False,
                latest_sha=LATEST, master_sha=HEAD, is_ancestor=lambda _a, _b: False,
                owner=OWNER,
            )

    def test_an_app_push_deploys_that_commits_image_once_it_exists(self):
        self.assertTrue(needs_image_wait("push", ["backend/app/main.py"], False))
        self.assertFalse(needs_image_wait("push", ["backend/app/main.py"], True))
        self.assertFalse(needs_image_wait("push", ["oracle/Dockerfile"], False))
        decision = decide(
            event="push", conclusion="", branch="master", head_sha=HEAD,
            changed=["backend/app/main.py", "oracle/Dockerfile"],
            image_tag_exists=_present, latest_sha=LATEST, master_sha=HEAD,
            is_ancestor=lambda _a, _b: False, owner=OWNER,
        )
        self.assertFalse(decision.skip)
        self.assertEqual(decision.sha, HEAD)
        self.assertEqual(decision.base_image, f"ghcr.io/{OWNER}/homepilot:{HEAD[:7]}")

    def test_a_push_publish_does_not_deploy_twice(self):
        decision = decide(
            event="workflow_run", conclusion="success", branch="master",
            head_sha=HEAD, changed=None, image_tag_exists=_present,
            latest_sha="", master_sha=HEAD, is_ancestor=lambda _a, _b: False,
            owner=OWNER, upstream_event="push",
        )
        self.assertTrue(decision.skip)

    def test_a_manual_container_publish_still_deploys(self):
        decision = decide(
            event="workflow_run", conclusion="success", branch="master",
            head_sha=HEAD, changed=None, image_tag_exists=_present,
            latest_sha="", master_sha=HEAD, is_ancestor=lambda _a, _b: False,
            owner=OWNER, upstream_event="workflow_dispatch",
        )
        self.assertFalse(decision.skip)
        self.assertEqual(decision.base_image, f"ghcr.io/{OWNER}/homepilot:{HEAD[:7]}")

    def test_a_wrapper_only_push_uses_latest_when_this_commit_has_no_image(self):
        decision = decide(
            event="push", conclusion="", branch="master", head_sha=OLDER,
            changed=["oracle/Dockerfile", "notifications/content-notice.js"],
            image_tag_exists=lambda tag: tag == LATEST[:7],
            latest_sha=LATEST, master_sha=LATEST,
            is_ancestor=lambda older, newer: older == OLDER and newer == LATEST,
            owner=OWNER,
        )
        # There is no app image for the wrapper commit. Production keeps the
        # published app commit (the same one :latest and the Space are on).
        self.assertFalse(decision.skip)
        self.assertEqual(decision.sha, LATEST)
        self.assertTrue(decision.base_image.endswith(":latest"))

    def test_a_wrapper_push_of_master_wraps_latest(self):
        decision = decide(
            event="push", conclusion="", branch="master", head_sha=HEAD,
            changed=["oracle/README.md"],
            image_tag_exists=lambda tag: tag == "other00",
            latest_sha=LATEST, master_sha=HEAD,
            is_ancestor=lambda _a, _b: False, owner=OWNER,
        )
        self.assertFalse(decision.skip)
        self.assertEqual(decision.sha, LATEST)
        self.assertTrue(decision.base_image.endswith(":latest"))

    def test_an_older_publish_does_not_roll_back(self):
        decision = decide(
            event="workflow_run", conclusion="success", branch="master",
            head_sha=OLDER, changed=None,
            image_tag_exists=lambda tag: tag in {OLDER[:7], HEAD[:7]},
            latest_sha=LATEST, master_sha=HEAD,
            is_ancestor=lambda older, newer: older == OLDER and newer == HEAD,
            owner=OWNER,
        )
        self.assertTrue(decision.skip)

    def test_version_match_accepts_the_full_or_short_commit(self):
        self.assertTrue(version_matches({"sha": HEAD}, HEAD))
        self.assertTrue(version_matches({"sha": HEAD}, HEAD[:7]))
        self.assertFalse(version_matches({"sha": "unknown"}, HEAD))
        self.assertFalse(version_matches({"sha": OLDER}, HEAD))

    def test_container_workflow_watches_every_app_path(self):
        text = Path(__file__).resolve().parents[1].joinpath(".github/workflows/container.yml").read_text()
        for prefix in APP_IMAGE_PREFIXES:
            self.assertIn(prefix + "**", text, prefix)
        for filename in APP_IMAGE_FILES:
            self.assertIn(filename, text, filename)
        self.assertTrue(touches_app_image(["expert/backend/app/expert/x.py"]))
        self.assertTrue(touches_app_image(["scripts/download.py"]))
        self.assertFalse(touches_app_image(["oracle/Dockerfile", "notifications/content-notice.js"]))


if __name__ == "__main__":
    unittest.main()
