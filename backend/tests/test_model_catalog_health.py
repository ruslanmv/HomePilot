"""
Model Catalog Health Check

Validates that every Ollama chat model in model_catalog_data.json actually exists
in the Ollama registry (ollama.com). Does NOT download models — only checks availability.

Usage:
  # Run as pytest (marks missing models as warnings, always passes)
  cd backend && python -m pytest tests/test_model_catalog_health.py -v

  # Run standalone to auto-clean missing models from catalog
  cd backend && python tests/test_model_catalog_health.py --clean
"""

import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CATALOG_PATH = Path(__file__).resolve().parent.parent / "app" / "model_catalog_data.json"


def load_ollama_chat_models() -> list[dict]:
    """Load Ollama chat models from the JSON catalog."""
    with open(CATALOG_PATH) as f:
        data = json.load(f)
    return data["providers"]["ollama"]["chat"]


def ollama_registry_url(model_id: str) -> str:
    """Build the Ollama registry URL for a model.

    Standard models  → https://ollama.com/library/<name>
    Namespaced models → https://ollama.com/<namespace>/<name>
    Tags (e.g. :8b) are stripped because the registry page is per-model, not per-tag.
    """
    # Strip tag (e.g. ":8b", ":latest", ":3b")
    base = model_id.split(":")[0]

    if "/" in base:
        # Namespaced: huihui_ai/qwen3-abliterated → https://ollama.com/huihui_ai/qwen3-abliterated
        return f"https://ollama.com/{base}"
    else:
        # Standard: llama3 → https://ollama.com/library/llama3
        return f"https://ollama.com/library/{base}"


def check_model_exists(model_id: str, timeout: float = 10.0) -> tuple[bool, str]:
    """Check if a model exists on the Ollama registry.

    Returns (exists: bool, detail: str).
    """
    url = ollama_registry_url(model_id)
    req = urllib.request.Request(url, method="GET")
    req.add_header("User-Agent", "HomePilot-HealthCheck/1.0")

    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        # Read a small amount to complete the request, then discard
        resp.read(1024)
        resp.close()
        if resp.status == 200:
            return True, f"OK ({url})"
        return False, f"HTTP {resp.status} ({url})"
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False, f"NOT FOUND ({url})"
        return False, f"HTTP {e.code} ({url})"
    except urllib.error.URLError as e:
        return False, f"Network error: {e.reason} ({url})"
    except Exception as e:
        return False, f"Error: {e} ({url})"


# ---------------------------------------------------------------------------
# Pytest tests
# ---------------------------------------------------------------------------

class TestModelCatalogHealth:
    """Validate Ollama model catalog entries exist in the registry."""

    def test_catalog_json_is_valid(self):
        """Catalog JSON should parse without errors."""
        models = load_ollama_chat_models()
        assert len(models) > 0, "Catalog should have at least one Ollama chat model"

    def test_all_models_have_required_fields(self):
        """Every model entry must have at least 'id' and 'label'."""
        models = load_ollama_chat_models()
        for m in models:
            assert "id" in m, f"Model missing 'id': {m}"
            assert "label" in m, f"Model {m['id']} missing 'label'"

    def test_no_duplicate_model_ids(self):
        """No duplicate model IDs in the catalog."""
        models = load_ollama_chat_models()
        ids = [m["id"] for m in models]
        dupes = [mid for mid in ids if ids.count(mid) > 1]
        assert len(dupes) == 0, f"Duplicate model IDs: {set(dupes)}"

    def test_nsfw_models_have_uncensored_flag(self):
        """Models with nsfw:true should also have uncensored:true."""
        models = load_ollama_chat_models()
        for m in models:
            if m.get("nsfw"):
                assert m.get("uncensored", False), (
                    f"Model {m['id']} has nsfw:true but missing uncensored:true"
                )

    @pytest.mark.skipif(
        os.environ.get("SKIP_NETWORK_TESTS", "0") == "1",
        reason="SKIP_NETWORK_TESTS=1",
    )
    def test_ollama_models_exist_in_registry(self):
        """Check that all models exist on ollama.com (network test).

        This test checks unique model base names (without tags) to avoid
        redundant requests for the same model with different tags.
        """
        models = load_ollama_chat_models()

        # Deduplicate by base name (strip tag)
        seen_bases = set()
        unique_models = []
        for m in models:
            base = m["id"].split(":")[0]
            if base not in seen_bases:
                seen_bases.add(base)
                unique_models.append(m)

        missing = []
        for m in unique_models:
            exists, detail = check_model_exists(m["id"])
            if not exists:
                missing.append((m["id"], m["label"], detail))

        if missing:
            msg_lines = [f"\n{len(missing)} model(s) not found on Ollama registry:"]
            for mid, label, detail in missing:
                msg_lines.append(f"  - {mid} ({label}): {detail}")
            # Use warnings instead of failing — models may be temporarily unavailable
            import warnings
            warnings.warn("\n".join(msg_lines))


# ---------------------------------------------------------------------------
# Standalone mode: check + optional cleanup
# ---------------------------------------------------------------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Check Ollama model catalog health")
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove models that don't exist from the JSON catalog",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="HTTP timeout per model check (default: 10s)",
    )
    args = parser.parse_args()

    print(f"Loading catalog from {CATALOG_PATH}")
    models = load_ollama_chat_models()
    print(f"Found {len(models)} Ollama chat models\n")

    # Deduplicate checks by base name
    seen_bases: dict[str, bool] = {}
    results: list[tuple[dict, bool, str]] = []

    for m in models:
        base = m["id"].split(":")[0]
        if base in seen_bases:
            # Reuse result from same base model
            exists = seen_bases[base]
            detail = "(same base model)"
        else:
            exists, detail = check_model_exists(m["id"], timeout=args.timeout)
            seen_bases[base] = exists

        status = "OK" if exists else "MISSING"
        nsfw_tag = " [NSFW]" if m.get("nsfw") else ""
        print(f"  [{status:>7}] {m['id']:<50} {m['label']}{nsfw_tag}")
        results.append((m, exists, detail))

    # Summary
    ok_count = sum(1 for _, exists, _ in results if exists)
    missing_count = sum(1 for _, exists, _ in results if not exists)
    print(f"\nResults: {ok_count} OK, {missing_count} missing out of {len(results)} total")

    if missing_count > 0:
        print("\nMissing models:")
        for m, exists, detail in results:
            if not exists:
                print(f"  - {m['id']} ({m['label']}): {detail}")

    # Auto-clean if requested
    if args.clean and missing_count > 0:
        print(f"\n--clean: Removing {missing_count} missing model(s) from catalog...")
        missing_ids = {m["id"] for m, exists, _ in results if not exists}

        with open(CATALOG_PATH) as f:
            catalog = json.load(f)

        original_count = len(catalog["providers"]["ollama"]["chat"])
        catalog["providers"]["ollama"]["chat"] = [
            m for m in catalog["providers"]["ollama"]["chat"]
            if m["id"] not in missing_ids
        ]
        new_count = len(catalog["providers"]["ollama"]["chat"])

        with open(CATALOG_PATH, "w") as f:
            json.dump(catalog, f, indent=2)
            f.write("\n")

        print(f"Catalog updated: {original_count} -> {new_count} models")
        print("NOTE: You also need to update the TSX fallback in frontend/src/ui/Models.tsx manually.")
    elif args.clean and missing_count == 0:
        print("\n--clean: Nothing to remove, all models exist!")

    sys.exit(1 if missing_count > 0 and not args.clean else 0)


if __name__ == "__main__":
    main()
