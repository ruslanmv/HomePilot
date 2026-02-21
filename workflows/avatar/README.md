# Avatar Workflow Templates

ComfyUI prompt templates for the Avatar Studio feature.

## How It Works

The backend loads these JSON templates, injects runtime values, and submits
them to ComfyUI via `/prompt`.

### Injected values

| Target node class_type | Input key     | Source                      |
| ---------------------- | ------------- | --------------------------- |
| `CLIPTextEncode`       | `text`        | User prompt                 |
| `KSampler`             | `seed`        | Deterministic seed          |
| `EmptyLatentImage`     | `batch_size`  | Requested count (1-8)       |
| `LoadImage`            | `image`       | Reference image path or URL |

### Replacing templates

Export your working graph from the ComfyUI web UI (Save as API format)
and drop it here, keeping the same filename. The backend matches by
filename, not by node IDs, so any valid ComfyUI API-format JSON will work
as long as it includes the node class_types above.

## Templates

- **avatar_instantid.json** — Reference image + prompt → identity-consistent headshots
- **avatar_photomaker.json** — 1-4 refs + prompt → consistent portraits
- **avatar_faceswap.json** — Body prompt → swap face → GFPGAN restore
