# Community Addons

External persona packs that get published to the HomePilot Community Gallery.

## Structure

```
addons/
├── README.md          ← this file
├── <pack_id>/         ← one folder per pack
│   ├── pack.json      ← pack metadata
│   ├── packs.json     ← sub-pack groupings (optional)
│   └── *.hpersona     ← persona packages
```

## Adding a new pack

1. Create a folder: `addons/<your_pack_id>/`
2. Add a `pack.json` with: id, name, author, content_rating, default_tags, personas[]
3. Drop `.hpersona` files in the folder
4. Run `python community/scripts/sync-addons.py` to rebuild the registry
5. Push to main — the `sync-addons.yml` workflow uploads to R2

## pack.json schema

```json
{
  "id": "my_pack",
  "name": "Display Name",
  "version": "1.0.0",
  "author": "Author Name",
  "content_rating": "sfw|nsfw",
  "default_class_id": "assistant|companion|secretary",
  "default_tags": ["tag1", "tag2"],
  "personas": ["persona_id_1", "persona_id_2"]
}
```

## Security

Only personas in `addons/` folders are published. Core and system personas
from source repos are never copied here.
