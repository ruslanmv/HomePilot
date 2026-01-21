#!/usr/bin/env python3
"""
HomePilot Model Management Utility
Provides advanced model management: list, verify, update, clean
"""

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime

# Color codes for terminal output
class Colors:
    BLUE = '\033[0;34m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    RED = '\033[0;31m'
    NC = '\033[0m'  # No Color
    BOLD = '\033[1m'

@dataclass
class ModelInfo:
    """Information about a model file"""
    name: str
    path: Path
    size_bytes: int
    model_type: str  # checkpoint, unet, clip, vae
    exists: bool
    last_modified: Optional[datetime] = None

    @property
    def size_human(self) -> str:
        """Human-readable file size"""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if self.size_bytes < 1024.0:
                return f"{self.size_bytes:.1f} {unit}"
            self.size_bytes /= 1024.0
        return f"{self.size_bytes:.1f} PB"

# Model registry with expected models and their metadata
MODEL_REGISTRY = {
    "flux1-schnell": {
        "path": "unet/flux1-schnell.safetensors",
        "type": "unet",
        "size_gb": 23.8,
        "url": "https://huggingface.co/black-forest-labs/FLUX.1-schnell/resolve/main/flux1-schnell.safetensors",
        "preset": ["minimal", "recommended", "full"],
        "description": "FLUX Schnell - Fast image generation (4 steps)"
    },
    "flux1-dev": {
        "path": "unet/flux1-dev.safetensors",
        "type": "unet",
        "size_gb": 23.8,
        "url": "https://huggingface.co/black-forest-labs/FLUX.1-dev/resolve/main/flux1-dev.safetensors",
        "preset": ["full"],
        "description": "FLUX Dev - High quality image generation (20 steps)"
    },
    "t5xxl_fp16": {
        "path": "clip/t5xxl_fp16.safetensors",
        "type": "clip",
        "size_gb": 9.5,
        "url": "https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/t5xxl_fp16.safetensors",
        "preset": ["minimal", "recommended", "full"],
        "description": "T5-XXL Text Encoder (fp16)"
    },
    "clip_l": {
        "path": "clip/clip_l.safetensors",
        "type": "clip",
        "size_gb": 0.2,
        "url": "https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/clip_l.safetensors",
        "preset": ["minimal", "recommended", "full"],
        "description": "CLIP-L Text Encoder"
    },
    "ae": {
        "path": "vae/ae.safetensors",
        "type": "vae",
        "size_gb": 0.3,
        "url": "https://huggingface.co/black-forest-labs/FLUX.1-schnell/resolve/main/ae.safetensors",
        "preset": ["minimal", "recommended", "full"],
        "description": "FLUX VAE Encoder"
    },
    "sd_xl_base_1.0": {
        "path": "checkpoints/sd_xl_base_1.0.safetensors",
        "type": "checkpoint",
        "size_gb": 6.9,
        "url": "https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_base_1.0.safetensors",
        "preset": ["recommended", "full"],
        "description": "SDXL Base 1.0 - High quality image generation"
    },
    "dreamshaper_8": {
        "path": "checkpoints/dreamshaper_8.safetensors",
        "type": "checkpoint",
        "size_gb": 2.0,
        "url": "https://civitai.com/api/download/models/128713",
        "preset": ["full"],
        "description": "Dreamshaper 8 - SD 1.5 uncensored"
    },
    "svd": {
        "path": "checkpoints/svd.safetensors",
        "type": "checkpoint",
        "size_gb": 25.0,
        "url": "https://huggingface.co/stabilityai/stable-video-diffusion-img2vid-xt/resolve/main/svd_xt.safetensors",
        "preset": ["full"],
        "description": "Stable Video Diffusion - Video generation"
    }
}

class ModelManager:
    """Manages AI model files for HomePilot"""

    def __init__(self, models_dir: Optional[Path] = None):
        if models_dir is None:
            # Default to ../models from script location
            script_dir = Path(__file__).parent
            self.models_dir = (script_dir / ".." / "models").resolve()
        else:
            self.models_dir = Path(models_dir)

        self.comfy_dir = self.models_dir / "comfy"
        self.llm_dir = self.models_dir / "llm"

    def scan_models(self) -> List[ModelInfo]:
        """Scan the models directory and return list of found models"""
        models = []

        if not self.comfy_dir.exists():
            return models

        # Scan each model type directory
        for model_type in ['checkpoints', 'unet', 'clip', 'vae']:
            type_dir = self.comfy_dir / model_type
            if not type_dir.exists():
                continue

            for model_file in type_dir.glob('*.safetensors'):
                stat = model_file.stat()
                models.append(ModelInfo(
                    name=model_file.name,
                    path=model_file,
                    size_bytes=stat.st_size,
                    model_type=model_type,
                    exists=True,
                    last_modified=datetime.fromtimestamp(stat.st_mtime)
                ))

        return sorted(models, key=lambda m: m.model_type)

    def verify_preset(self, preset: str) -> Tuple[List[str], List[str]]:
        """
        Verify models for a preset
        Returns: (found_models, missing_models)
        """
        found = []
        missing = []

        for model_id, model_data in MODEL_REGISTRY.items():
            if preset not in model_data["preset"]:
                continue

            model_path = self.comfy_dir / model_data["path"]
            if model_path.exists() and model_path.stat().st_size > 0:
                found.append(model_id)
            else:
                missing.append(model_id)

        return found, missing

    def list_models(self, verbose: bool = False):
        """List all downloaded models"""
        print(f"\n{Colors.BOLD}╔══════════════════════════════════════════════════════════════╗{Colors.NC}")
        print(f"{Colors.BOLD}║                    Installed Models                          ║{Colors.NC}")
        print(f"{Colors.BOLD}╚══════════════════════════════════════════════════════════════╝{Colors.NC}\n")

        models = self.scan_models()

        if not models:
            print(f"{Colors.YELLOW}No models found in {self.comfy_dir}{Colors.NC}")
            print(f"\nRun: {Colors.BLUE}make download-recommended{Colors.NC} to download models\n")
            return

        # Group by type
        by_type = {}
        for model in models:
            if model.model_type not in by_type:
                by_type[model.model_type] = []
            by_type[model.model_type].append(model)

        total_size = 0

        for model_type in sorted(by_type.keys()):
            print(f"{Colors.BOLD}{model_type.upper()}:{Colors.NC}")
            for model in by_type[model_type]:
                size_str = self._format_size(model.size_bytes)
                total_size += model.size_bytes

                if verbose and model.last_modified:
                    date_str = model.last_modified.strftime('%Y-%m-%d %H:%M')
                    print(f"  {Colors.GREEN}✓{Colors.NC} {model.name:<45} {size_str:>10}  {date_str}")
                else:
                    print(f"  {Colors.GREEN}✓{Colors.NC} {model.name:<45} {size_str:>10}")
            print()

        print(f"{Colors.BOLD}Total:{Colors.NC} {len(models)} models, {self._format_size(total_size)}\n")

    def verify_models(self, preset: str = "recommended"):
        """Verify models for a specific preset"""
        print(f"\n{Colors.BOLD}Verifying {preset} preset models...{Colors.NC}\n")

        found, missing = self.verify_preset(preset)

        if found:
            print(f"{Colors.GREEN}Found models:{Colors.NC}")
            for model_id in found:
                model_data = MODEL_REGISTRY[model_id]
                print(f"  {Colors.GREEN}✓{Colors.NC} {model_data['description']}")
            print()

        if missing:
            print(f"{Colors.YELLOW}Missing models:{Colors.NC}")
            for model_id in missing:
                model_data = MODEL_REGISTRY[model_id]
                print(f"  {Colors.RED}✗{Colors.NC} {model_data['description']}")
                print(f"    Path: {model_data['path']}")
                print(f"    Size: ~{model_data['size_gb']:.1f} GB")
            print()
            print(f"Run: {Colors.BLUE}make download-{preset}{Colors.NC} to download missing models\n")
        else:
            print(f"{Colors.GREEN}✓ All {preset} preset models are installed!{Colors.NC}\n")

    def show_presets(self):
        """Show available presets and their models"""
        print(f"\n{Colors.BOLD}Available Presets:{Colors.NC}\n")

        presets = {
            "minimal": {
                "desc": "Fast setup with essential models",
                "size": 0,
                "vram": "12-16GB"
            },
            "recommended": {
                "desc": "Balanced quality and performance",
                "size": 0,
                "vram": "12-16GB"
            },
            "full": {
                "desc": "All models for maximum flexibility",
                "size": 0,
                "vram": "16-24GB"
            }
        }

        # Calculate sizes
        for model_id, model_data in MODEL_REGISTRY.items():
            for preset in model_data["preset"]:
                presets[preset]["size"] += model_data["size_gb"]

        for preset_name, preset_info in presets.items():
            print(f"{Colors.BLUE}{Colors.BOLD}{preset_name.upper()}{Colors.NC} - {preset_info['desc']}")
            print(f"  Total: ~{preset_info['size']:.1f} GB")
            print(f"  VRAM Required: {preset_info['vram']}")
            print(f"  Models:")

            for model_id, model_data in MODEL_REGISTRY.items():
                if preset_name in model_data["preset"]:
                    print(f"    • {model_data['description']} (~{model_data['size_gb']:.1f} GB)")
            print()

        print(f"Usage: {Colors.BLUE}make download-<preset>{Colors.NC}\n")

    def clean_orphaned(self, dry_run: bool = True):
        """Remove model files not in registry"""
        print(f"\n{Colors.BOLD}Scanning for orphaned models...{Colors.NC}\n")

        models = self.scan_models()
        registry_files = {MODEL_REGISTRY[m]["path"] for m in MODEL_REGISTRY}

        orphaned = []
        for model in models:
            rel_path = model.path.relative_to(self.comfy_dir)
            if str(rel_path) not in registry_files:
                orphaned.append(model)

        if not orphaned:
            print(f"{Colors.GREEN}No orphaned models found{Colors.NC}\n")
            return

        print(f"Found {len(orphaned)} orphaned model(s):")
        total_size = 0
        for model in orphaned:
            print(f"  {Colors.YELLOW}•{Colors.NC} {model.path.relative_to(self.comfy_dir)} ({self._format_size(model.size_bytes)})")
            total_size += model.size_bytes

        print(f"\nTotal space to reclaim: {self._format_size(total_size)}")

        if dry_run:
            print(f"\n{Colors.YELLOW}DRY RUN - no files deleted{Colors.NC}")
            print(f"To actually delete, run: {Colors.BLUE}python scripts/manage_models.py clean --no-dry-run{Colors.NC}\n")
        else:
            response = input(f"\n{Colors.RED}Delete these files? [y/N]{Colors.NC} ")
            if response.lower() == 'y':
                for model in orphaned:
                    model.path.unlink()
                    print(f"  {Colors.GREEN}✓{Colors.NC} Deleted {model.name}")
                print(f"\n{Colors.GREEN}Cleanup complete{Colors.NC}\n")
            else:
                print(f"{Colors.YELLOW}Cancelled{Colors.NC}\n")

    @staticmethod
    def _format_size(bytes_size: int) -> str:
        """Format bytes as human-readable size"""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if bytes_size < 1024.0:
                return f"{bytes_size:.1f} {unit}"
            bytes_size /= 1024.0
        return f"{bytes_size:.1f} PB"

def main():
    parser = argparse.ArgumentParser(
        description='HomePilot Model Management Utility',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s list                    # List all installed models
  %(prog)s list -v                 # List with timestamps
  %(prog)s verify                  # Verify recommended preset
  %(prog)s verify --preset full    # Verify full preset
  %(prog)s presets                 # Show available presets
  %(prog)s clean                   # Show orphaned models (dry run)
  %(prog)s clean --no-dry-run      # Delete orphaned models
        """
    )

    parser.add_argument(
        'command',
        choices=['list', 'verify', 'presets', 'clean'],
        help='Command to execute'
    )

    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Show detailed information'
    )

    parser.add_argument(
        '--preset',
        choices=['minimal', 'recommended', 'full'],
        default='recommended',
        help='Preset to verify (default: recommended)'
    )

    parser.add_argument(
        '--no-dry-run',
        action='store_true',
        help='Actually delete files (for clean command)'
    )

    parser.add_argument(
        '--models-dir',
        type=Path,
        help='Override models directory path'
    )

    args = parser.parse_args()

    manager = ModelManager(models_dir=args.models_dir)

    try:
        if args.command == 'list':
            manager.list_models(verbose=args.verbose)
        elif args.command == 'verify':
            manager.verify_models(preset=args.preset)
        elif args.command == 'presets':
            manager.show_presets()
        elif args.command == 'clean':
            manager.clean_orphaned(dry_run=not args.no_dry_run)
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Cancelled{Colors.NC}")
        sys.exit(1)
    except Exception as e:
        print(f"\n{Colors.RED}Error: {e}{Colors.NC}\n")
        sys.exit(1)

if __name__ == '__main__':
    main()
