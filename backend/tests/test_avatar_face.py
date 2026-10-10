# backend/tests/test_avatar_face.py
"""
Face-centred avatar thumbnails: a full-body persona picture shown in a 32 px
circle must show the face, not a head-to-waist square.

CI-friendly: synthetic pictures drawn with Pillow; no InsightFace, no network.
"""
import os
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

SKIN = (224, 172, 140)
FACE_CENTER = (300, 100)


def full_body(path: Path, background=(70, 90, 120)) -> Path:
    """512x768 standing figure: face (with eyes and mouth) up top, bare arms and legs below."""
    im = Image.new("RGB", (512, 768), background)
    d = ImageDraw.Draw(im)
    cx, cy = FACE_CENTER
    d.ellipse([cx - 44, cy - 62, cx + 44, cy + 20], fill=(60, 40, 30))           # hair
    d.ellipse([cx - 36, cy - 46, cx + 36, cy + 46], fill=SKIN)                   # face
    d.ellipse([cx - 20, cy - 12, cx - 8, cy - 4], fill=(40, 30, 30))             # eyes
    d.ellipse([cx + 8, cy - 12, cx + 20, cy - 4], fill=(40, 30, 30))
    d.rectangle([cx - 12, cy + 20, cx + 12, cy + 25], fill=(120, 40, 50))       # mouth
    d.rectangle([cx - 13, cy + 46, cx + 13, cy + 64], fill=SKIN)                 # neck
    d.rectangle([cx - 70, cy + 64, cx + 70, cy + 400], fill=(30, 30, 40))       # clothes
    d.rectangle([cx - 100, cy + 75, cx - 76, cy + 330], fill=SKIN)               # arms
    d.rectangle([cx + 76, cy + 75, cx + 100, cy + 330], fill=SKIN)
    d.rectangle([cx - 50, cy + 400, cx - 15, cy + 650], fill=SKIN)               # legs
    d.rectangle([cx + 15, cy + 400, cx + 50, cy + 650], fill=SKIN)
    im.save(path)
    return path


@pytest.fixture()
def af():
    from app.personas import avatar_face
    return avatar_face


def test_the_face_is_found_above_the_arms_and_legs(af, tmp_path):
    with Image.open(full_body(tmp_path / "avatar_p.png")) as im:
        box = af.find_face_box(im)
    assert box is not None
    x0, y0, x1, y1 = box
    assert abs((x0 + x1) / 2 - FACE_CENTER[0]) < 20
    assert abs((y0 + y1) / 2 - FACE_CENTER[1]) < 25
    assert 40 < x1 - x0 < 110


def test_the_crop_is_a_square_around_the_face_and_much_tighter_than_the_top_square(af):
    face = (264.0, 54.0, 336.0, 146.0)
    left, top, right, bottom = af.face_crop_box((512, 768), face)
    assert right - left == bottom - top
    assert left <= face[0] and right >= face[2] and top <= face[1] and bottom >= face[3]
    assert right - left < 512 * 0.5  # the face fills the circle, not 15% of it


def test_the_crop_never_leaves_the_picture(af):
    for face in [(0.0, 0.0, 60.0, 70.0), (460.0, 700.0, 512.0, 768.0), (0.0, 0.0, 512.0, 768.0)]:
        left, top, right, bottom = af.face_crop_box((512, 768), face)
        assert 0 <= left and 0 <= top and right <= 512 and bottom <= 768
        assert right - left == bottom - top


def test_no_face_keeps_the_regular_top_square(af):
    assert af.face_crop_box((512, 768), None) == (0, 0, 512, 512)
    assert af.face_crop_box((768, 512), None) == (128, 0, 640, 512)


def test_a_skin_toned_backdrop_is_not_mistaken_for_a_face(af, tmp_path):
    # The whole frame is "skin": nothing face-shaped stands out, so no box,
    # and the picture falls back to the regular square rather than a wall.
    with Image.open(full_body(tmp_path / "avatar_w.png", background=SKIN)) as im:
        box = af.find_face_box(im)
        crop = af.face_crop_box(im.size, box)
    if box is not None:
        assert abs((box[0] + box[2]) / 2 - FACE_CENTER[0]) < 40
    assert crop[2] - crop[0] <= 512


def test_the_crop_is_written_once_and_redone_when_the_picture_changes(af, tmp_path):
    src = full_body(tmp_path / "avatar_p.png")
    out = af.ensure_face_thumb(src)
    assert out.name == "thumb_face_avatar_p.webp"
    with Image.open(out) as im:
        assert im.size == (af.FACE_THUMB_SIZE, af.FACE_THUMB_SIZE)
    first = out.stat().st_mtime
    assert af.ensure_face_thumb(src).stat().st_mtime == first

    # A re-committed picture overwrites the same file name: the crop is now
    # older than its picture and is written again.
    past = first - 100
    os.utime(out, (past, past))
    assert af.ensure_face_thumb(src).stat().st_mtime > past + 50


def test_the_thumb_name_is_public_to_the_files_route(af, tmp_path):
    # files.py serves names starting with "thumb_" without a session.
    assert af.face_thumb_path(tmp_path / "avatar_x.png").name.startswith("thumb_")
    assert af.face_thumb_path(tmp_path / "thumb_avatar_x.webp").name == "thumb_face_avatar_x.webp"


# ── the endpoint ────────────────────────────────────────────────────────────


@pytest.fixture()
def picture_project(client, monkeypatch, tmp_path):
    import app.main as main

    rel = "projects/p-face/persona/appearance/avatar_p.png"
    (tmp_path / rel).parent.mkdir(parents=True)
    full_body(tmp_path / rel)
    db = {
        "p-face": {"id": "p-face", "project_type": "persona", "persona_appearance": {"selected_filename": rel}},
        "p-none": {"id": "p-none", "project_type": "persona", "persona_appearance": {}},
        "p-escape": {"id": "p-escape", "project_type": "persona", "persona_appearance": {"selected_filename": "../../etc/passwd"}},
    }
    monkeypatch.setattr(main, "UPLOAD_PATH", tmp_path)
    monkeypatch.setattr(main.projects, "get_project_by_id", lambda pid: db.get(pid))
    return tmp_path


def test_the_endpoint_serves_the_face_crop(client, picture_project):
    r = client.get("/projects/p-face/persona/avatar/face?v=1")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/webp"
    assert "max-age" in r.headers.get("cache-control", "")
    assert (picture_project / "projects/p-face/persona/appearance/thumb_face_avatar_p.webp").is_file()


def test_the_endpoint_404s_without_a_picture_or_outside_the_uploads(client, picture_project):
    assert client.get("/projects/p-none/persona/avatar/face").status_code == 404
    assert client.get("/projects/p-escape/persona/avatar/face").status_code == 404
    assert client.get("/projects/missing/persona/avatar/face").status_code == 404
