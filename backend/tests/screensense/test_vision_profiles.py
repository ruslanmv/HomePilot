"""Fitting a screen to a model, and tiling it when the model can take it (batch V5).

The claim this batch makes is narrow and checkable: **a downscale destroys small text, and an
overlapping crop of the original does not.** ``test_a_crop_keeps_text_the_overview_loses``
measures exactly that, on a stripe pattern fine enough to alias away in the overview — if that
test ever passes trivially, tiling has stopped being worth its cost and this file should say so.

Everything else here guards the ways a resize goes wrong in practice: enlarging a small image
and inventing detail, re-encoding a screen as JPEG and smearing the glyph strokes, cutting a
line of text down the middle between two crops, or quietly sending four images to a model that
cannot reason across them.
"""

from __future__ import annotations

import io

import pytest

from app import vision_adapter
from app.vision_adapter import adapter as ad
from app.vision_adapter import profiles as pf

ON = {"VISION_MULTI_IMAGE_MODELS": "testvlm"}


def image(width, height, mode="RGB", fmt="PNG", stripes=False, varied=False):
    from PIL import Image, ImageDraw

    picture = Image.new(mode, (width, height), (18, 22, 30) if mode != "L" else 30)
    if varied:
        # A flat colour encodes to identical bytes in every crop, which would let "all four
        # tiles were sent" pass while one tile was sent four times. Something different in
        # each quadrant is what makes that assertion mean anything.
        draw = ImageDraw.Draw(picture)
        for index, (x, y) in enumerate([(0, 0), (1, 0), (0, 1), (1, 1)]):
            left, top = x * width // 2, y * height // 2
            draw.rectangle(
                [left + 20, top + 20, left + 60 + index * 90, top + 60 + index * 40],
                fill=(200 - index * 40, 40 + index * 50, 90 + index * 30),
            )
    if stripes:
        # A 4px period: it survives a modest crop and aliases into flat grey under a hard
        # downscale, which is the whole argument for tiling in one pattern.
        pixels = picture.load()
        for x in range(width):
            if (x // 2) % 2:
                for y in range(height):
                    pixels[x, y] = (245, 245, 245) if mode != "L" else 245
    buffer = io.BytesIO()
    picture.save(buffer, format=fmt)
    return buffer.getvalue()


def spread(data, row_fraction=0.5):
    """Standard deviation along one row — how much detail is left after scaling."""
    from PIL import Image

    with Image.open(io.BytesIO(data)) as picture:
        grey = picture.convert("L")
        row = [grey.getpixel((x, int(grey.height * row_fraction))) for x in range(grey.width)]
    mean = sum(row) / len(row)
    return (sum((v - mean) ** 2 for v in row) / len(row)) ** 0.5


# ── the budget ──────────────────────────────────────────────────────────────


def test_a_small_image_is_never_enlarged():
    # The only thing extra pixels add to a 320×200 icon is detail nobody photographed.
    data = image(320, 200)
    out = vision_adapter.adapt(data, purpose="screen", mode="ocr")
    assert out.strategy == "passthrough"
    assert out.data == data
    assert (out.width, out.height) == (320, 200)


def test_a_screen_is_fitted_to_the_long_edge_with_its_shape_intact():
    out = vision_adapter.adapt(image(3840, 2160), purpose="screen", mode="caption")
    assert (out.width, out.height) == (1400, 788)
    assert abs(out.width / out.height - 3840 / 2160) < 0.01
    assert out.strategy == "resized"


def test_the_pixel_budget_catches_a_shape_the_long_edge_lets_past():
    # 2000×2000 is inside no long-edge cap that a 16:9 screen is comfortable with, and is
    # nearly two megapixels once it gets there. Both caps, or neither is a budget.
    width, height = pf.fit(2000, 2000, pf.SCREEN_OVERVIEW)
    assert max(width, height) < pf.SCREEN_OVERVIEW.max_long_edge
    assert width * height <= pf.SCREEN_OVERVIEW.max_megapixels * 1_000_000


def test_a_resized_screen_comes_back_as_png_even_from_a_jpeg():
    # JPEG ringing lands on high-contrast edges, and a glyph stroke at these sizes *is* a
    # high-contrast edge one or two pixels wide.
    out = vision_adapter.adapt(image(3000, 2000, fmt="JPEG"), mime_type="image/jpeg", purpose="screen")
    assert out.mime_type == "image/png"


def test_an_exif_rotated_photo_arrives_upright():
    from PIL import Image

    portrait = Image.new("RGB", (2400, 1200), (10, 10, 10))
    buffer = io.BytesIO()
    exif = portrait.getexif()
    exif[274] = 6  # rotate 90° clockwise on display
    portrait.save(buffer, format="JPEG", exif=exif)

    out = vision_adapter.adapt(buffer.getvalue(), mime_type="image/jpeg", purpose="photo")
    assert out.height > out.width, "the tag was ignored and the model gets a photo on its side"


# ── the gate ────────────────────────────────────────────────────────────────


def test_an_unknown_model_is_sent_exactly_one_image():
    out = vision_adapter.adapt(image(3840, 2160), purpose="screen", mode="ocr", model="something:7b")
    assert out.tiles == 1
    assert out.strategy == "resized"


def test_and_says_so_rather_than_just_answering_vaguely():
    # "the answer was thin" and "the detail crops were never sent" look identical from outside.
    out = vision_adapter.adapt(image(3840, 2160), purpose="screen", mode="ocr", model="something:7b")
    assert "tiling-unavailable:single-image-model" in out.warnings


def test_nothing_is_verified_in_this_repository_yet():
    # The gate is only honest while this holds. A family added here without a measurement to
    # point at is the failure this batch was written to avoid.
    assert pf.MULTI_IMAGE_VERIFIED == frozenset()
    assert not pf.supports_multiple_images("qwen2.5vl:7b", environ={})
    assert not pf.supports_multiple_images("", environ=ON)


def test_an_operator_can_switch_it_on_for_a_model_they_checked_themselves():
    assert pf.supports_multiple_images("testvlm:7b", environ=ON)
    out = vision_adapter.adapt(image(3840, 2160), purpose="screen", mode="ocr", model="testvlm:7b", environ=ON)
    assert out.strategy == "tiled"
    assert out.tiles > 1


def test_asking_for_a_caption_never_tiles_however_capable_the_model_is():
    # Tiling is for reading. A description of the screen does not need four passes of it.
    out = vision_adapter.adapt(image(3840, 2160), purpose="screen", mode="caption", model="testvlm:7b", environ=ON)
    assert out.profile == "screen_overview"
    assert out.tiles == 1


def test_a_photograph_is_fitted_and_never_tiled():
    out = vision_adapter.adapt(image(4000, 3000), purpose="photo", mode="ocr", model="testvlm:7b", environ=ON)
    assert out.profile == "photo"
    assert out.tiles == 1


# ── the tiles ───────────────────────────────────────────────────────────────


def tiled(width=3840, height=2160, **kwargs):
    return vision_adapter.adapt(
        image(width, height, **kwargs), purpose="screen", mode="ocr", model="testvlm:7b", environ=ON
    )


def test_the_overview_comes_first_and_is_labelled():
    out = tiled()
    assert out.parts[0].label == "overview"
    assert out.data == out.parts[0].data
    assert all(part.label != "overview" for part in out.parts[1:])


def test_a_widescreen_is_split_both_ways_and_an_ultrawide_only_across():
    # Halving a 16:9 screen top and bottom leaves every line of text as wide as it was.
    assert [p.label for p in tiled(3840, 2160).parts[1:]] == [
        "top-left", "top-right", "bottom-left", "bottom-right",
    ]
    assert [p.label for p in tiled(5120, 1440).parts[1:]] == ["left", "center", "right"]
    assert [p.label for p in tiled(1200, 3200).parts[1:]] == ["top", "middle", "bottom"]


def test_the_part_budget_is_never_exceeded():
    for size in [(3840, 2160), (5120, 1440), (1200, 3200), (1920, 1080), (7680, 4320)]:
        assert len(tiled(*size).parts) <= pf.SCREEN_TEXT.max_parts, size


def test_a_tighter_budget_gives_up_the_split_across_the_short_axis():
    # Today's shapes all fit inside today's budget, so this is the only thing holding the
    # reduction honest — and it is what a machine short of memory, or a smaller `max_parts`,
    # will hit first. A wide screen cut into a top half and a bottom half has thrown away the
    # split that was doing the work.
    assert pf.grid_for(3840, 2160, 2) == (2, 1)
    assert pf.grid_for(1200, 3200, 2) == (1, 2)
    assert pf.grid_for(3840, 2160, 1) == (1, 1)


def test_a_crop_keeps_text_the_overview_loses():
    """The batch, in one assertion.

    A 4-pixel stripe pattern across a 3840-wide screen: the overview scales it by ~0.36 and the
    stripes alias into flat grey; a crop scales the same stripes by ~0.53 and they are still
    there. That difference is the difference between a model that reads an error message and
    one that says it sees a code editor.
    """
    out = tiled(3840, 2160, stripes=True)
    assert out.strategy == "tiled"
    overview = spread(out.parts[0].data)
    best_crop = max(spread(part.data) for part in out.parts[1:])
    assert best_crop > overview * 1.3, (overview, best_crop)


def test_nothing_narrower_than_the_overlap_is_ever_split():
    """The geometric promise that makes tiling safe to read from.

    With tiles of width *w* stepping by ``w × (1 − overlap)``, any run shorter than
    ``w × overlap`` lies wholly inside at least one tile — so a line of text, a button label or
    an error string is never cut in half with neither crop showing all of it.
    """
    width, height, overlap = 3840, 2160, pf.SCREEN_TEXT.overlap
    boxes = [box for _, box in pf.tile_boxes(width, height, 2, 2, overlap)]
    tile_width = max(right - left for left, _, right, _ in boxes)
    run = int(tile_width * overlap) - 1

    # Without this the test is vacuous at zero overlap: a run of length -1 fits inside any tile,
    # so the assertion below would hold for a tiling that splits text down the middle.
    assert run >= 40, f"the overlap has to be worth something: {overlap} of {tile_width}px"

    for start in range(0, width - run, 37):
        span = (start, start + run)
        assert any(left <= span[0] and span[1] <= right for left, _, right, _ in boxes), span


def test_neighbouring_tiles_actually_share_a_strip():
    # The direct form of the same claim, so that setting `overlap` to zero fails here too
    # rather than only making the guarantee above trivially true.
    boxes = sorted(box for _, box in pf.tile_boxes(3840, 2160, 2, 2, pf.SCREEN_TEXT.overlap))
    left_tile, right_tile = boxes[0], boxes[2]
    shared = left_tile[2] - right_tile[0]
    assert shared > 0.1 * (left_tile[2] - left_tile[0]), shared


def test_the_tiles_cover_the_whole_screen():
    # An overlap that leaves a gap is worse than no tiling: the missing strip is invisible and
    # the answer is confident.
    boxes = [box for _, box in pf.tile_boxes(1911, 1077, 2, 2, pf.SCREEN_TEXT.overlap)]
    covered = set()
    for left, top, right, bottom in boxes:
        covered.update((x, y) for x in (left, right - 1) for y in (top, bottom - 1))
    assert min(x for x, _ in covered) == 0
    assert max(x for x, _ in covered) == 1910
    assert min(y for _, y in covered) == 0
    assert max(y for _, y in covered) == 1076


def test_crops_are_taken_from_the_original_not_from_the_overview():
    out = tiled(3840, 2160)
    # A crop of the 1400-wide overview could not be larger than the overview.
    assert max(part.width for part in out.parts[1:]) <= pf.SCREEN_TEXT.tile_long_edge
    source_width = max(right - left for _, (left, _, right, _) in pf.tile_boxes(3840, 2160, 2, 2, pf.SCREEN_TEXT.overlap))
    crop_scale = max(part.width for part in out.parts[1:]) / source_width
    assert crop_scale > out.scale


# ── degrading, rather than failing ──────────────────────────────────────────


def test_without_pillow_it_is_exactly_v4_again():
    # HomePilot runs on machines without Pillow. A vision request must not start failing there
    # because an optional resize could not be performed.
    data = image(3840, 2160)
    original = ad._pillow
    ad._pillow = lambda: None
    try:
        out = vision_adapter.adapt(data, purpose="screen", mode="ocr")
    finally:
        ad._pillow = original
    assert out.data == data
    assert out.strategy == "passthrough"
    assert "unmeasured" in out.warnings


def test_bytes_that_are_not_an_image_are_still_forwarded():
    out = vision_adapter.adapt(b"\x00\x01 not an image", purpose="screen", mode="ocr")
    assert out.data == b"\x00\x01 not an image"
    assert out.strategy == "passthrough"


def test_a_resize_that_throws_falls_back_to_the_original():
    data = image(3840, 2160)

    class Boom:
        LANCZOS = 1

        @staticmethod
        def open(*_args, **_kwargs):
            raise RuntimeError("decoder gave up")

    original = ad._pillow
    measured = ad._measure
    ad._measure = lambda _d: (3840, 2160, "image/png")
    ad._pillow = lambda: Boom
    try:
        out = vision_adapter.adapt(data, purpose="screen", mode="ocr")
    finally:
        ad._pillow, ad._measure = original, measured
    assert out.data == data
    assert "adapt-failed" in out.warnings


def test_a_purpose_nobody_has_heard_of_still_gets_a_profile_and_an_answer():
    out = vision_adapter.adapt(image(3840, 2160), purpose="interpretive-dance")
    assert out.profile
    assert out.data
    assert any(w.startswith("unknown-purpose") for w in out.warnings)


def test_a_small_rotated_photo_is_still_turned_upright():
    """The passthrough shortcut must not outrun the orientation fix.

    A 600×300 photo tagged "rotate 90°" is inside every budget, so nothing needs resizing — and
    handing back the bytes untouched sends the model the sideways picture the tag exists to
    correct. Small and rotated is the case where the two rules meet.
    """
    from PIL import Image

    picture = Image.new("RGB", (600, 300), (10, 10, 10))
    buffer = io.BytesIO()
    exif = picture.getexif()
    exif[274] = 6
    picture.save(buffer, format="JPEG", exif=exif)

    out = vision_adapter.adapt(buffer.getvalue(), mime_type="image/jpeg", purpose="photo")
    assert (out.width, out.height) == (300, 600)
    assert out.data != buffer.getvalue()

    with Image.open(io.BytesIO(out.data)) as sent:
        assert (sent.width, sent.height) == (300, 600)


# ── what reaches Ollama ─────────────────────────────────────────────────────


class _Response:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


def _ollama(monkeypatch, seen):
    from app import multimodal as mm

    class Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, **kwargs):
            seen.update(kwargs.get("json") or {})
            return _Response({"message": {"content": "A code editor showing a stack trace."}})

    monkeypatch.setattr(mm.httpx, "AsyncClient", Client)


def analyse(monkeypatch, tmp_path, data, **kwargs):
    import asyncio
    import base64

    from app import multimodal as mm

    seen: dict = {}
    _ollama(monkeypatch, seen)
    result = asyncio.new_event_loop().run_until_complete(
        mm.analyze_image_ollama(
            "", tmp_path, image_b64=base64.b64encode(data).decode(), **kwargs
        )
    )
    return result, seen


def test_every_crop_reaches_the_model(monkeypatch, tmp_path):
    monkeypatch.setenv(pf.MULTI_IMAGE_ENV, "testvlm")
    result, seen = analyse(
        monkeypatch, tmp_path, image(3840, 2160, varied=True), model="testvlm:7b", mode="ocr"
    )
    images = seen["messages"][1]["images"]
    assert len(images) == result["meta"]["adapter"]["tiles"] > 1
    assert len(set(images)) == len(images), "the same crop was sent more than once"


def test_the_prompt_says_the_crops_are_one_screen(monkeypatch, tmp_path):
    # Five images with no account of how they relate are five separate pictures to a model,
    # which is exactly the failure the gate exists to keep away from unverified models.
    monkeypatch.setenv(pf.MULTI_IMAGE_ENV, "testvlm")
    _result, seen = analyse(monkeypatch, tmp_path, image(3840, 2160), model="testvlm:7b", mode="ocr")
    prompt = seen["messages"][1]["content"]
    assert "one screen, not several" in prompt
    assert "top-left" in prompt


def test_a_single_image_request_says_nothing_about_crops(monkeypatch, tmp_path):
    _result, seen = analyse(monkeypatch, tmp_path, image(3840, 2160), model="plain:7b", mode="ocr")
    assert len(seen["messages"][1]["images"]) == 1
    assert "crops" not in seen["messages"][1]["content"]


def test_the_response_reports_the_profile_and_the_parts(monkeypatch, tmp_path):
    monkeypatch.setenv(pf.MULTI_IMAGE_ENV, "testvlm")
    result, _seen = analyse(monkeypatch, tmp_path, image(3840, 2160), model="testvlm:7b", mode="ocr")
    meta = result["meta"]["adapter"]
    assert meta["profile"] == "screen_text"
    assert meta["strategy"] == "tiled"
    assert [p["label"] for p in meta["parts"]][0] == "overview"


def test_asking_about_a_photo_gets_the_photo_profile(monkeypatch, tmp_path):
    result, seen = analyse(
        monkeypatch, tmp_path, image(4000, 3000), model="plain:7b", mode="both", purpose="photo"
    )
    assert result["meta"]["adapter"]["profile"] == "photo"
    assert len(seen["messages"][1]["images"]) == 1
