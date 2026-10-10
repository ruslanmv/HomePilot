# backend/tests/test_avatar_crop.py
"""
Edit profile picture: the user frames the persona's picture, and that framing —
cut from the original at full resolution — becomes the thumbnail every round
avatar shows. The original is never changed, and the framing is kept so the
crop can be refined later.

CI-friendly: synthetic pictures drawn with Pillow; no network.
"""
import hashlib
import io
import json
from pathlib import Path

import pytest
from PIL import Image

RED, BLUE, GREEN, WHITE = (220, 30, 30), (30, 60, 220), (30, 180, 60), (240, 240, 240)


def quadrants(path: Path, size=(800, 1200)) -> Path:
    """Top-left red, top-right blue, bottom-left green, bottom-right white."""
    w, h = size
    im = Image.new("RGB", size, WHITE)
    im.paste(RED, (0, 0, w // 2, h // 2))
    im.paste(BLUE, (w // 2, 0, w, h // 2))
    im.paste(GREEN, (0, h // 2, w // 2, h))
    im.save(path)
    return path


def centre_colour(path: Path):
    with Image.open(path) as im:
        im = im.convert("RGB")
        return im.getpixel((im.width // 2, im.height // 2))


def close(a, b, tol=12):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


@pytest.fixture()
def ac():
    from app.personas import avatar_crop
    return avatar_crop


# ── the pure part ───────────────────────────────────────────────────────────


def test_an_area_must_be_four_positive_finite_percentages(ac):
    assert ac.parse_area({"x": 10, "y": 5, "width": 40, "height": 40}) == {"x": 10.0, "y": 5.0, "width": 40.0, "height": 40.0}
    for bad in [None, [], {"x": 1}, {"x": "a", "y": 0, "width": 1, "height": 1},
                {"x": 0, "y": 0, "width": 0, "height": 10}, {"x": 0, "y": 0, "width": 150, "height": 10},
                {"x": float("nan"), "y": 0, "width": 10, "height": 10}]:
        with pytest.raises(ac.CropError):
            ac.parse_area(bad)


def test_the_box_is_a_square_inside_the_picture_and_never_stretched(ac):
    # A square area on a portrait picture: 50% of the width = 25% of the height.
    box = ac.square_box({"x": 25, "y": 10, "width": 50, "height": 25}, 800, 1600)
    assert box == (200, 160, 600, 560)
    # Slightly out-of-bounds input is moved back inside, keeping the side.
    x0, y0, x1, y1 = ac.square_box({"x": 80, "y": 90, "width": 40, "height": 40}, 1000, 1000)
    assert x1 - x0 == y1 - y0 == 400
    assert x1 <= 1000 and y1 <= 1000 and x0 >= 0 and y0 >= 0


def test_the_crop_is_cut_from_the_original_at_512_px(ac, tmp_path):
    rel = "projects/p/persona/appearance/avatar_a.png"
    (tmp_path / rel).parent.mkdir(parents=True)
    quadrants(tmp_path / rel)
    # The blue quadrant: x 50..100%, y 0..50% of an 800x1200 picture is 400x600; a square
    # inside it is 400x400 = 50% of the width, 33.3% of the height.
    res = ac.crop_to_thumb(tmp_path, rel, {"x": 50, "y": 8.33, "width": 50, "height": 33.33})
    out = tmp_path / res.thumb_rel
    assert out.parent == (tmp_path / rel).parent
    assert out.name.startswith("thumb_avatar_a_crop_") and out.suffix == ".webp"
    with Image.open(out) as im:
        assert im.size == (512, 512)
    assert close(centre_colour(out), BLUE)
    assert res.box[2] - res.box[0] == res.box[3] - res.box[1] == 400


def test_exif_orientation_is_applied_so_the_crop_matches_what_the_browser_showed(ac, tmp_path):
    # Stored 400x200, left half red; EXIF 6 = shown rotated 90° clockwise, so the
    # browser shows 200x400 with red on top.
    stored = Image.new("RGB", (400, 200), BLUE)
    stored.paste(RED, (0, 0, 200, 200))
    exif = Image.Exif()
    exif[0x0112] = 6
    rel = "avatar_rot.jpg"
    stored.save(tmp_path / rel, format="JPEG", exif=exif, quality=95)
    res = ac.crop_to_thumb(tmp_path, rel, {"x": 0, "y": 0, "width": 100, "height": 50})
    assert res.source_size == (200, 400)
    assert close(centre_colour(tmp_path / res.thumb_rel), RED, tol=30)


def test_unreadable_unsupported_or_escaping_sources_are_refused(ac, tmp_path):
    (tmp_path / "not.png").write_bytes(b"hello")
    with pytest.raises(ac.CropError):
        ac.crop_to_thumb(tmp_path, "not.png", {"x": 0, "y": 0, "width": 10, "height": 10})
    Image.new("RGB", (20, 20)).save(tmp_path / "pic.gif")
    with pytest.raises(ac.CropError):
        ac.crop_to_thumb(tmp_path, "pic.gif", {"x": 0, "y": 0, "width": 10, "height": 10})
    with pytest.raises(FileNotFoundError):
        ac.crop_to_thumb(tmp_path, "../../etc/passwd", {"x": 0, "y": 0, "width": 10, "height": 10})


def test_a_crop_stops_being_active_when_another_picture_is_chosen(ac):
    app = {"selected_filename": "a.png", "selected_thumb_filename": "t_crop.webp",
           "avatar_crop": {"output": "t_crop.webp", "source": "a.png"}}
    assert ac.active_crop(app)["output"] == "t_crop.webp"
    app["selected_thumb_filename"] = "thumb_avatar_b.webp"   # e.g. a new look committed elsewhere
    assert ac.active_crop(app) is None
    assert ac.active_crop({}) is None


# ── the endpoints ───────────────────────────────────────────────────────────


@pytest.fixture()
def persona(client, monkeypatch, tmp_path):
    import app.main as main

    rel = "projects/p1/persona/appearance/avatar_orig.png"
    (tmp_path / rel).parent.mkdir(parents=True)
    quadrants(tmp_path / rel)
    auto = "projects/p1/persona/appearance/thumb_avatar_orig.webp"
    Image.new("RGB", (256, 256), RED).save(tmp_path / auto)
    db = {
        "p1": {"id": "p1", "project_type": "persona",
               "persona_appearance": {"selected_filename": rel, "selected_thumb_filename": auto}},
        "p-empty": {"id": "p-empty", "project_type": "persona", "persona_appearance": {}},
        "chat": {"id": "chat", "project_type": "chat"},
    }

    def update(pid, patch):
        db[pid] = {**db[pid], **patch, "updated_at": 1700000000.0}
        return db[pid]

    monkeypatch.setattr(main, "UPLOAD_PATH", tmp_path)
    monkeypatch.setattr(main.projects, "get_project_by_id", lambda pid: db.get(pid))
    monkeypatch.setattr(main.projects, "update_project", update)
    return {"root": tmp_path, "db": db, "original": rel, "auto": auto}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def post_crop(client, pid, area, zoom=None, file=None):
    data = {"area": json.dumps(area)}
    if zoom is not None:
        data["zoom"] = str(zoom)
    files = {"file": file} if file else None
    return client.post(f"/projects/{pid}/persona/avatar/crop", data=data, files=files)


def test_saving_a_crop_makes_it_the_thumbnail_and_keeps_the_original(client, persona):
    before = digest(persona["root"] / persona["original"])
    r = post_crop(client, "p1", {"x": 0, "y": 0, "width": 50, "height": 33.33}, zoom=1.8)
    assert r.status_code == 200, r.text
    body = r.json()
    pa = body["persona_appearance"]
    crop = pa["avatar_crop"]
    assert pa["selected_thumb_filename"] == crop["output"] != persona["auto"]
    assert pa["selected_filename"] == persona["original"]            # original untouched
    assert digest(persona["root"] / persona["original"]) == before
    assert crop["source"] == persona["original"] and crop["auto_thumb"] == persona["auto"]
    assert crop["zoom"] == 1.8 and crop["area"]["width"] == 50 and crop["size"] == 512
    assert close(centre_colour(persona["root"] / crop["output"]), RED)
    assert persona["db"]["p1"]["persona_appearance"]["avatar_crop"]["output"] == crop["output"]  # persisted


def test_recropping_refines_and_still_remembers_the_automatic_thumbnail(client, persona):
    first = post_crop(client, "p1", {"x": 0, "y": 0, "width": 50, "height": 33.33}).json()["avatar_crop"]
    second = post_crop(client, "p1", {"x": 50, "y": 0, "width": 50, "height": 33.33}).json()["avatar_crop"]
    assert second["output"] != first["output"]
    assert second["auto_thumb"] == persona["auto"]
    assert close(centre_colour(persona["root"] / second["output"]), BLUE)


def test_going_back_to_the_automatic_thumbnail(client, persona):
    post_crop(client, "p1", {"x": 0, "y": 0, "width": 50, "height": 33.33})
    r = client.delete("/projects/p1/persona/avatar/crop")
    assert r.status_code == 200 and r.json()["changed"] is True
    pa = persona["db"]["p1"]["persona_appearance"]
    assert pa["selected_thumb_filename"] == persona["auto"]
    assert pa["avatar_crop"]["area"]["width"] == 50          # the framing is kept for later
    assert client.delete("/projects/p1/persona/avatar/crop").json()["changed"] is False


def test_a_replacement_photo_becomes_the_new_original_and_the_old_one_goes_to_history(client, persona):
    buf = io.BytesIO()
    Image.new("RGB", (600, 600), GREEN).save(buf, format="PNG")
    r = post_crop(client, "p1", {"x": 10, "y": 10, "width": 80, "height": 80},
                  file=("new.png", buf.getvalue(), "image/png"))
    assert r.status_code == 200, r.text
    pa = r.json()["persona_appearance"]
    assert pa["selected_filename"] != persona["original"]
    assert pa["avatar_crop"]["source"] == pa["selected_filename"]
    assert any(h.get("selected_filename") == persona["original"] for h in pa.get("avatar_history", []))
    assert (persona["root"] / persona["original"]).is_file()              # nothing deleted
    assert close(centre_colour(persona["root"] / pa["avatar_crop"]["output"]), GREEN)
    assert not list(persona["root"].glob("crop_upload_*"))                 # temp upload cleaned up


@pytest.mark.parametrize("area,status", [
    ("not json", 400),
    ({"x": 0, "y": 0, "width": 0, "height": 10}, 400),
])
def test_bad_areas_are_refused(client, persona, area, status):
    data = {"area": area if isinstance(area, str) else json.dumps(area)}
    assert client.post("/projects/p1/persona/avatar/crop", data=data).status_code == status


def test_bad_uploads_and_wrong_projects_are_refused_without_changes(client, persona):
    area = {"x": 0, "y": 0, "width": 50, "height": 50}
    assert post_crop(client, "p1", area, file=("x.gif", b"GIF89a", "image/gif")).status_code == 400
    assert post_crop(client, "p1", area, file=("x.png", b"not an image", "image/png")).status_code == 400
    assert "avatar_crop" not in persona["db"]["p1"]["persona_appearance"]
    assert post_crop(client, "p-empty", area).status_code == 400
    assert post_crop(client, "chat", area).status_code == 400
    assert post_crop(client, "missing", area).status_code == 404
