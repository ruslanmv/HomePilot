# HomePilot Avatar Service

Optional microservice for **random face generation** using StyleGAN2.

## Why a separate service?

- Completely isolates `torch`/`torchvision` from the backend and ComfyUI venvs
- Allows pinning GPU library versions independently
- Clean licensing toggle: if this service isn't running, the feature is simply absent
- Enterprise-friendly: the backend just makes HTTP calls

## Quick start (dev)

```bash
cd avatar-service
pip install -e .
bash scripts/run_dev.sh
```

The service starts on port `8020` by default.

## Placeholder mode

The skeleton ships with a **placeholder** generator that produces labelled PNG
images so you can test the end-to-end flow without GPU weights. Replace the
placeholder logic in `app/storage/local_store.py` with real StyleGAN2
inference when ready.

## API

- `POST /v1/avatars/generate` — generate random face images
  - Body: `{ "count": 4, "seeds": [1,2,3,4], "truncation": 0.7 }`
  - Response: `{ "results": [...], "warnings": [...] }`
