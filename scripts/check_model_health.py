#!/usr/bin/env python3
"""
HomePilot Model Health Checker

Verifies the health and availability of all model download URLs in the catalog.
Run this before deploying or when download errors occur.

Usage:
    # Check all models
    python scripts/check_model_health.py

    # Check only edit models
    python scripts/check_model_health.py --type edit

    # Output JSON for API consumption
    python scripts/check_model_health.py --json

    # Verbose output with response details
    python scripts/check_model_health.py --verbose
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

try:
    import requests
except ImportError:
    print("ERROR: Missing required package. Install with:")
    print("  pip install requests")
    sys.exit(1)

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
CATALOG_PATH = PROJECT_ROOT / "backend" / "app" / "model_catalog_data.json"

# Timeout for health checks (seconds)
CHECK_TIMEOUT = 15

# Number of concurrent checks
MAX_WORKERS = 5

# User agent for requests
USER_AGENT = "HomePilot-HealthCheck/1.0"


class HealthStatus(Enum):
    """Health check status."""
    HEALTHY = "healthy"      # URL is accessible (2xx or 3xx)
    UNHEALTHY = "unhealthy"  # URL returns error (4xx, 5xx)
    TIMEOUT = "timeout"      # Request timed out
    ERROR = "error"          # Network or other error
    NO_URL = "no_url"        # No download URL defined


@dataclass
class HealthResult:
    """Result of a health check."""
    model_id: str
    model_label: str
    provider: str
    model_type: str
    download_url: Optional[str]
    status: HealthStatus
    http_status: Optional[int]
    response_time_ms: Optional[int]
    error_message: Optional[str]
    content_length: Optional[int]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "model_id": self.model_id,
            "model_label": self.model_label,
            "provider": self.provider,
            "model_type": self.model_type,
            "download_url": self.download_url,
            "status": self.status.value,
            "http_status": self.http_status,
            "response_time_ms": self.response_time_ms,
            "error_message": self.error_message,
            "content_length_bytes": self.content_length,
        }


# -----------------------------------------------------------------------------
# Health Check Functions
# -----------------------------------------------------------------------------

def load_catalog() -> Dict[str, Any]:
    """Load the model catalog JSON."""
    if not CATALOG_PATH.exists():
        print(f"ERROR: Catalog not found at {CATALOG_PATH}")
        sys.exit(1)

    with open(CATALOG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def check_url_health(
    url: str,
    timeout: int = CHECK_TIMEOUT,
) -> tuple[HealthStatus, Optional[int], Optional[int], Optional[str], Optional[int]]:
    """
    Check if a URL is healthy using a HEAD request.

    Returns: (status, http_status, response_time_ms, error_message, content_length)
    """
    if not url:
        return HealthStatus.NO_URL, None, None, "No download URL", None

    headers = {"User-Agent": USER_AGENT}

    start_time = time.time()

    try:
        # Use HEAD request first (faster, less bandwidth)
        response = requests.head(
            url,
            headers=headers,
            timeout=timeout,
            allow_redirects=True,
        )

        elapsed_ms = int((time.time() - start_time) * 1000)
        content_length = response.headers.get("content-length")
        content_length = int(content_length) if content_length else None

        # Check status code
        if response.status_code < 400:
            return HealthStatus.HEALTHY, response.status_code, elapsed_ms, None, content_length
        else:
            error_msg = f"HTTP {response.status_code}"
            # Try to get error message from HuggingFace headers
            if "x-error-message" in response.headers:
                error_msg += f": {response.headers['x-error-message']}"
            return HealthStatus.UNHEALTHY, response.status_code, elapsed_ms, error_msg, content_length

    except requests.exceptions.Timeout:
        elapsed_ms = int((time.time() - start_time) * 1000)
        return HealthStatus.TIMEOUT, None, elapsed_ms, f"Request timed out after {timeout}s", None

    except requests.exceptions.RequestException as e:
        elapsed_ms = int((time.time() - start_time) * 1000)
        return HealthStatus.ERROR, None, elapsed_ms, str(e), None


def check_model_health(
    model_id: str,
    model_data: Dict[str, Any],
    provider: str,
    model_type: str,
) -> HealthResult:
    """Check health of a single model."""
    download_url = model_data.get("download_url")
    label = model_data.get("label", model_id)

    status, http_status, response_time, error_msg, content_length = check_url_health(download_url)

    return HealthResult(
        model_id=model_id,
        model_label=label,
        provider=provider,
        model_type=model_type,
        download_url=download_url,
        status=status,
        http_status=http_status,
        response_time_ms=response_time,
        error_message=error_msg,
        content_length=content_length,
    )


def get_models_to_check(
    catalog: Dict[str, Any],
    filter_type: Optional[str] = None,
    filter_provider: Optional[str] = None,
) -> List[tuple[str, Dict[str, Any], str, str]]:
    """
    Get list of models to check from catalog.

    Returns: List of (model_id, model_data, provider, model_type)
    """
    models = []
    providers = catalog.get("providers", {})

    for provider_name, provider_data in providers.items():
        if filter_provider and provider_name != filter_provider:
            continue

        # Skip non-downloadable providers
        if provider_name in ("ollama", "openai", "claude", "openai_compat", "watsonx"):
            continue

        for type_name, model_list in provider_data.items():
            if filter_type and type_name != filter_type:
                continue

            if not isinstance(model_list, list):
                continue

            for model in model_list:
                model_id = model.get("id")
                if model_id and model.get("download_url"):
                    models.append((model_id, model, provider_name, type_name))

    return models


def run_health_checks(
    models: List[tuple[str, Dict[str, Any], str, str]],
    max_workers: int = MAX_WORKERS,
    verbose: bool = False,
) -> List[HealthResult]:
    """Run health checks on all models concurrently."""
    results = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_model = {
            executor.submit(check_model_health, model_id, model_data, provider, model_type): model_id
            for model_id, model_data, provider, model_type in models
        }

        for future in as_completed(future_to_model):
            model_id = future_to_model[future]
            try:
                result = future.result()
                results.append(result)

                if verbose:
                    status_icon = get_status_icon(result.status)
                    print(f"  {status_icon} {result.model_id}: {result.status.value} ({result.response_time_ms}ms)")

            except Exception as e:
                print(f"  ✗ Error checking {model_id}: {e}")

    return results


def get_status_icon(status: HealthStatus) -> str:
    """Get icon for status."""
    icons = {
        HealthStatus.HEALTHY: "✅",
        HealthStatus.UNHEALTHY: "❌",
        HealthStatus.TIMEOUT: "⏱️",
        HealthStatus.ERROR: "⚠️",
        HealthStatus.NO_URL: "➖",
    }
    return icons.get(status, "?")


def get_status_color(status: HealthStatus) -> str:
    """Get ANSI color code for status."""
    colors = {
        HealthStatus.HEALTHY: "\033[92m",     # Green
        HealthStatus.UNHEALTHY: "\033[91m",   # Red
        HealthStatus.TIMEOUT: "\033[93m",     # Yellow
        HealthStatus.ERROR: "\033[93m",       # Yellow
        HealthStatus.NO_URL: "\033[90m",      # Gray
    }
    return colors.get(status, "")


RESET_COLOR = "\033[0m"


# -----------------------------------------------------------------------------
# Output Functions
# -----------------------------------------------------------------------------

def print_results(results: List[HealthResult], verbose: bool = False) -> None:
    """Print health check results in a formatted table."""
    # Group by status
    healthy = [r for r in results if r.status == HealthStatus.HEALTHY]
    unhealthy = [r for r in results if r.status == HealthStatus.UNHEALTHY]
    timeout = [r for r in results if r.status == HealthStatus.TIMEOUT]
    errors = [r for r in results if r.status == HealthStatus.ERROR]

    print("\n" + "="*80)
    print("MODEL HEALTH CHECK REPORT")
    print("="*80 + "\n")

    # Summary
    total = len(results)
    print(f"📊 Summary: {len(healthy)}/{total} healthy")
    print(f"   ✅ Healthy:   {len(healthy)}")
    print(f"   ❌ Unhealthy: {len(unhealthy)}")
    print(f"   ⏱️  Timeout:   {len(timeout)}")
    print(f"   ⚠️  Error:     {len(errors)}")
    print()

    # Unhealthy models (most important)
    if unhealthy:
        print("-"*80)
        print("❌ UNHEALTHY MODELS (Broken URLs)")
        print("-"*80)
        for r in unhealthy:
            print(f"\n  Model: {r.model_label}")
            print(f"  ID: {r.model_id}")
            print(f"  Type: {r.provider}/{r.model_type}")
            print(f"  URL: {r.download_url}")
            print(f"  Error: {r.error_message}")
        print()

    # Timeout models
    if timeout:
        print("-"*80)
        print("⏱️  TIMEOUT MODELS (Slow or unreachable)")
        print("-"*80)
        for r in timeout:
            print(f"\n  Model: {r.model_label}")
            print(f"  ID: {r.model_id}")
            print(f"  URL: {r.download_url}")
        print()

    # Errors
    if errors:
        print("-"*80)
        print("⚠️  ERROR MODELS (Network issues)")
        print("-"*80)
        for r in errors:
            print(f"\n  Model: {r.model_label}")
            print(f"  ID: {r.model_id}")
            print(f"  Error: {r.error_message}")
        print()

    # Healthy models (brief)
    if healthy and verbose:
        print("-"*80)
        print("✅ HEALTHY MODELS")
        print("-"*80)
        for r in healthy:
            size_mb = r.content_length / (1024*1024) if r.content_length else 0
            size_str = f"{size_mb:.1f}MB" if size_mb > 0 else "?"
            print(f"  ✅ {r.model_label} ({r.model_type}) - {r.response_time_ms}ms - {size_str}")
        print()

    print("="*80)

    # Return code hint
    if unhealthy or errors:
        print("\n⚠️  Some models have broken or unreachable URLs.")
        print("   Consider updating the catalog or checking network connectivity.")
    else:
        print("\n✅ All models are healthy and accessible!")


def output_json(results: List[HealthResult]) -> None:
    """Output results as JSON."""
    output = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "summary": {
            "total": len(results),
            "healthy": len([r for r in results if r.status == HealthStatus.HEALTHY]),
            "unhealthy": len([r for r in results if r.status == HealthStatus.UNHEALTHY]),
            "timeout": len([r for r in results if r.status == HealthStatus.TIMEOUT]),
            "error": len([r for r in results if r.status == HealthStatus.ERROR]),
        },
        "results": [r.to_dict() for r in results],
    }
    print(json.dumps(output, indent=2))


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="HomePilot Model Health Checker",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--type", "-t",
        choices=["chat", "image", "video", "edit", "enhance"],
        help="Filter by model type",
    )
    parser.add_argument(
        "--provider", "-p",
        help="Filter by provider (comfyui, civitai)",
    )
    parser.add_argument(
        "--json", "-j",
        action="store_true",
        help="Output results as JSON",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show verbose output including healthy models",
    )
    parser.add_argument(
        "--workers", "-w",
        type=int,
        default=MAX_WORKERS,
        help=f"Number of concurrent checks (default: {MAX_WORKERS})",
    )

    args = parser.parse_args()

    # Load catalog
    catalog = load_catalog()

    # Get models to check
    models = get_models_to_check(
        catalog,
        filter_type=args.type,
        filter_provider=args.provider,
    )

    if not models:
        print("No downloadable models found matching criteria.")
        return 1

    if not args.json:
        print(f"\n🔍 Checking {len(models)} models...")
        if args.verbose:
            print()

    # Run health checks
    results = run_health_checks(
        models,
        max_workers=args.workers,
        verbose=args.verbose and not args.json,
    )

    # Output results
    if args.json:
        output_json(results)
    else:
        print_results(results, verbose=args.verbose)

    # Return code based on health
    unhealthy = [r for r in results if r.status in (HealthStatus.UNHEALTHY, HealthStatus.ERROR)]
    return 1 if unhealthy else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(130)
