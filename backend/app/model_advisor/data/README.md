# Bundled FitLab data

Snapshots of [FitLab](https://github.com/ruslanmv/fitlab)'s published data, trimmed to what the
Model Advisor reads. They are the offline fallback: used until definitions are fetched, and
whenever FitLab cannot be reached.

| File | From | Kept |
|---|---|---|
| `fitlab_registry.snapshot.json` | `data/registry.json` (`registry-latest`) | Chat and vision models with an Ollama tag: sizing fields, 30-day downloads, measured benchmarks, calibration |
| `fitlab_media.snapshot.json` | `data/media_registry.json` | The media lane as published (image + video, scoring weights and components) |
| `fitlab_gpus.json` | `data/gpu_catalog.json` (`master`) | Name, aliases, VRAM and memory bandwidth per GPU profile |

Do not edit by hand. Refresh with:

```bash
python backend/scripts/update_fitlab_snapshot.py            # from GitHub
python backend/scripts/update_fitlab_snapshot.py --from-dir ../fitlab
```

Run it before a release so the release ships current suggestions. Users get newer definitions with
**Fetch definitions** (or the optional daily automatic check); this snapshot is only the fallback.

Data © FitLab contributors, licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
