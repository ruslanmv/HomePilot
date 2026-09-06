"""The bench set, and the six failure modes it keeps apart (batch V8).

Two things are under test, and the second is the plan's stated acceptance.

**The corpus measures something.** `metrics.stroke_survival` turns "the resize destroyed the
text" into a number — the narrowest source stroke still legible after the adapter — and that
number is what tunes the caps in `profiles.py`. A metric that always returns the same answer, or
that answers from arithmetic rather than from the pixels, would be worse than no metric, so it is
held to both ends: it must notice a hard downscale, and it must *not* cry damage on an image
nothing was done to.

**Six failure modes stay distinguishable.** Before this series they all arrived as an empty
`analysis_text`, and the product answered every one of them by suggesting a larger model — though
two are not the model's fault, and one of those two is the most common. `failures.classify` is a
pure function of what a request already reports, so each mode is exercised here with the response
that produces it, and no two are allowed to collapse.
"""

from __future__ import annotations

import warnings

import pytest

from app import vision_adapter
from app.vision_bench import corpus, failures, metrics, runner

# The decompression-bomb case is supposed to be a decompression bomb.
warnings.filterwarnings("ignore", message=".*decompression bomb.*")


# ── the corpus ──────────────────────────────────────────────────────────────


def test_every_case_the_plan_named_is_here():
    names = {case.name for case in corpus.cases()}
    for wanted in [
        "desktop-1920", "desktop-2560", "desktop-3840", "code-error", "browser-page",
        "settings-window", "terminal", "terminal-dense", "svg-diagram", "ultrawide",
        "very-tall-page", "multi-monitor", "tiny-icon", "transparent-png", "exif-rotated",
        "animated-gif", "animated-webp", "corrupt-bytes", "empty-bytes", "decompression-bomb",
    ]:
        assert wanted in names, wanted


def test_every_case_says_what_it_is_for():
    # A case whose purpose is not written down becomes a case nobody dares delete.
    for case in corpus.cases():
        assert case.asks and len(case.asks) > 20, case.name


def test_the_corpus_is_generated_not_committed():
    # Two builds of the same case are byte-identical, which is what makes a measured number
    # comparable across runs and across machines.
    case = corpus.by_name()["terminal"]
    assert case.bytes() == case.bytes()
    assert len(case.bytes()) > 1000


# ── the measurement ─────────────────────────────────────────────────────────


def survival_of(name):
    case = corpus.by_name()[name]
    adapted = vision_adapter.adapt(case.bytes(), mime_type=case.mime, purpose=case.purpose, mode=case.mode)
    return metrics.stroke_survival(adapted.data, source_widths=case.strokes, scale=adapted.scale)


def test_an_image_nothing_was_done_to_keeps_its_finest_stroke():
    # 96×64 is under every budget, so it comes back byte-for-byte and a one-pixel bar is still a
    # one-pixel bar. If this ever fails, the metric is measuring the resize's arithmetic rather
    # than the pixels in front of it.
    assert survival_of("tiny-icon").finest == 1


def test_a_hard_downscale_is_noticed():
    # 3840 → 1400 is a scale of 0.365: a one- and a two-pixel stroke both land under one output
    # pixel and go. This is the number the whole vision series exists because of.
    assert survival_of("desktop-3840").finest == 3


def test_the_worse_the_downscale_the_worse_the_loss():
    # Ordering, not exact values — the values are corpus-specific and will move when the caps are
    # tuned. The ordering is a property of what a downscale does and must not move.
    hd = survival_of("desktop-1920").finest
    fourk = survival_of("desktop-3840").finest
    ultrawide = survival_of("ultrawide").finest
    assert hd < fourk <= ultrawide


def test_a_rotated_picture_is_measured_the_right_way_up():
    # The bars become horizontal the moment EXIF turns the picture upright, and a scan that only
    # reads rows then measures the gaps between bars instead of the bars. It read 6px before the
    # metric learned to look both ways, on an image that keeps 2px.
    assert survival_of("exif-rotated").finest == 2


def test_a_crop_recovers_what_the_overview_lost():
    # V5's claim and V6's whole argument, in the only unit that settles it. The crop comes from
    # the original at close to native resolution; the overview does not.
    case = corpus.by_name()["ultrawide"]
    overview = survival_of("ultrawide").finest
    best = min(
        reading.finest
        for reading in (
            metrics.stroke_survival(part.data, source_widths=case.strokes, scale=part.scale)
            for part in vision_adapter.crops(case.bytes(), purpose="screen", mode="ocr")
        )
        if reading.finest is not None
    )
    assert best < overview


def test_nothing_decodable_is_reported_as_such_rather_than_as_damage():
    assert metrics.stroke_survival(b"not an image", source_widths=(1, 2), scale=1.0).note == "not decodable"
    assert metrics.stroke_survival(b"", source_widths=(1, 2), scale=1.0).note == "no image"


# ── what the bench found ────────────────────────────────────────────────────


def test_a_hundred_megapixels_is_refused_before_it_is_decoded():
    # 315 KB on disk and ~300 MB in memory. The adapter used to decode it without comment,
    # because "the image exceeded a safety limit" was a failure mode with nothing behind it.
    case = corpus.by_name()["decompression-bomb"]
    adapted = vision_adapter.adapt(case.bytes(), purpose="screen", mode="ocr")
    assert any(w.startswith("over-limit") for w in adapted.warnings)
    assert adapted.data == b"", "refusing has to mean not sending it, or nothing was refused"
    assert adapted.original_width == 10000


def test_and_the_ceiling_is_checked_against_the_header_not_the_byte_count():
    # A few kilobytes that decode to a hundred megapixels is the entire trick. Deciding on
    # `len(payload)` would let every one of them through.
    case = corpus.by_name()["decompression-bomb"]
    assert len(case.bytes()) < 1_000_000
    assert vision_adapter.adapter.MAX_PIXELS < 10000 * 10000


def test_a_real_multi_monitor_capture_is_still_under_the_ceiling():
    # The ceiling must be past anything real, or it is a bug that only shows up on good hardware.
    assert 7680 * 4320 * 2 < vision_adapter.adapter.MAX_PIXELS


def test_an_over_limit_image_becomes_its_own_typed_failure():
    import asyncio
    import base64
    from pathlib import Path

    from app import multimodal as mm

    case = corpus.by_name()["decompression-bomb"]
    result = asyncio.new_event_loop().run_until_complete(
        mm.analyze_image_ollama("", Path("/tmp"), image_b64=base64.b64encode(case.bytes()).decode(), model="x")
    )
    # Not "the model returned nothing": the model was never asked, and the person can act on the
    # size in a way they cannot act on a shrug.
    assert result["error_code"] == "image_too_large"
    assert "10000x10000" in result["error"]


def test_an_animated_file_is_recorded_rather_than_refused():
    # The model is handed one frame of several and has no way to say so, which made "she
    # described the wrong moment" indistinguishable from "she misread it". The first frame of a
    # screen recording is still an answer, so it is a note, not a refusal.
    case = corpus.by_name()["animated-gif"]
    adapted = vision_adapter.adapt(case.bytes(), mime_type="image/gif", purpose="screen", mode="ocr")
    assert "animated:4" in adapted.warnings
    assert adapted.data


def test_alpha_survives_the_re_encode():
    import io

    from PIL import Image

    case = corpus.by_name()["transparent-png"]
    adapted = vision_adapter.adapt(case.bytes(), purpose="screen", mode="ocr")
    # The case is deliberately over the caps: an alpha image *under* them is passed through
    # untouched and proves nothing about the encoder, which is the only place alpha is at risk.
    assert adapted.strategy == "resized"
    assert adapted.mime_type == "image/png"
    with Image.open(io.BytesIO(adapted.data)) as sent:
        assert sent.mode in ("RGBA", "LA", "P"), "a JPEG re-encode would have flattened it to black"


# ── the metric measures pixels, not arithmetic ──────────────────────────────


def bars(width_px, *, contrast=(20, 240), size=(900, 200), count=6, gap=40):
    """An image of `count` bars `width_px` wide, at a chosen ink/ground contrast."""
    import io

    from PIL import Image, ImageDraw

    ground, ink = contrast
    picture = Image.new("L", size, ground)
    draw = ImageDraw.Draw(picture)
    cursor = gap
    for _ in range(count):
        draw.rectangle([cursor, 20, cursor + width_px - 1, size[1] - 20], fill=ink)
        cursor += width_px + gap
    buffer = io.BytesIO()
    picture.save(buffer, format="PNG")
    return buffer.getvalue()


def test_a_faint_stroke_is_not_a_legible_one():
    """Contrast has to decide something, or the metric is arithmetic wearing a measurement's hat.

    These bars are six pixels wide at full scale, so every width test based on `w × scale` says
    they are fine. They are grey on grey. A model cannot read them and neither can a person, and
    the metric has to agree — otherwise "the resize damaged OCR resolution" is being answered
    without looking at the image.
    """
    strong = metrics.stroke_survival(bars(6), source_widths=(6,), scale=1.0)
    faint = metrics.stroke_survival(bars(6, contrast=(120, 132)), source_widths=(6,), scale=1.0)

    assert strong.readings[0].contrast > metrics.LEGIBLE
    assert strong.finest == 6
    assert faint.readings[0].contrast < metrics.LEGIBLE
    assert faint.finest is None


def test_a_stroke_that_is_not_there_is_reported_as_gone():
    # Nothing in this image is one pixel wide. A metric that matched the nearest run whatever its
    # width would find a six-pixel bar and call the one-pixel stroke legible.
    reading = metrics.stroke_survival(bars(6), source_widths=(1,), scale=1.0)
    assert reading.readings[0].contrast == 0.0
    assert reading.finest is None


def test_contrast_falls_as_a_stroke_is_scaled_away():
    # The ordering the whole batch rests on: the harder the downscale, the less is left. Measured
    # on the same source bars at three scales, so nothing but the resize differs.
    import io

    from PIL import Image

    source = bars(2, size=(1200, 200), gap=30)
    contrasts = []
    for scale in (1.0, 0.5, 0.2):
        with Image.open(io.BytesIO(source)) as picture:
            target = (max(1, int(picture.width * scale)), max(1, int(picture.height * scale)))
            resized = picture.resize(target, Image.LANCZOS)
            buffer = io.BytesIO()
            resized.save(buffer, format="PNG")
        contrasts.append(
            metrics.stroke_survival(buffer.getvalue(), source_widths=(2,), scale=scale).readings[0].contrast
        )
    assert contrasts[0] > contrasts[-1], contrasts


# ── the six modes ───────────────────────────────────────────────────────────


def response(**kwargs):
    base = {"ok": True, "analysis_text": "A code editor.", "error_code": "",
            "meta": {"model": "chosen:7b", "adapter": {"warnings": []}}}
    meta = kwargs.pop("meta", None)
    base.update(kwargs)
    if meta:
        base["meta"] = meta
    return base


MODE_CASES = {
    failures.EMPTY_MODEL_RESPONSE: dict(
        result=response(ok=False, error_code="empty_model_response", analysis_text=""),
        requested_model="chosen:7b", finest_stroke=2, strokes_offered=(1, 2)),
    failures.DECODE_FAILED: dict(
        result=response(meta={"model": "chosen:7b", "adapter": {"warnings": ["unmeasured"]}}),
        requested_model="chosen:7b", finest_stroke=None, strokes_offered=(1, 2)),
    failures.OVER_LIMIT: dict(
        result=response(ok=False, error_code="image_too_large", analysis_text="",
                        meta={"model": "chosen:7b", "adapter": {"warnings": ["over-limit:10000x10000"]}}),
        requested_model="chosen:7b", finest_stroke=None, strokes_offered=(1, 2)),
    failures.OCR_DAMAGED: dict(
        result=response(), requested_model="chosen:7b", finest_stroke=None, strokes_offered=(1, 2)),
    failures.SELECTION_IGNORED: dict(
        result=response(meta={"model": "moondream", "adapter": {"warnings": []}}),
        requested_model="chosen:7b", finest_stroke=2, strokes_offered=(1, 2)),
    failures.PROVIDER_REJECTED: dict(
        result=response(ok=False, error_code="model_not_found", analysis_text=""),
        requested_model="chosen:7b", finest_stroke=2, strokes_offered=(1, 2)),
}


@pytest.mark.parametrize("mode", failures.MODES)
def test_each_failure_mode_is_reachable_on_its_own(mode):
    assert failures.classify(**MODE_CASES[mode]) == [mode]


def test_no_two_modes_have_collapsed_into_one():
    # The plan's acceptance, stated as a property rather than as six assertions: every mode is
    # observed alone somewhere. A report where two always travel together cannot tell them apart,
    # and telling them apart is the only job it has.
    observed = {mode: failures.classify(**arguments) for mode, arguments in MODE_CASES.items()}
    assert failures.distinguishable(observed) == []


def test_a_request_can_have_more_than_one_and_reports_both():
    # Picking a winner is how a report loses the interesting half: an over-limit image on the
    # wrong model is two problems, and fixing one leaves the other.
    modes = failures.classify(
        result=response(ok=False, error_code="image_too_large", analysis_text="",
                        meta={"model": "moondream", "adapter": {"warnings": ["over-limit:9999x9999"]}}),
        requested_model="chosen:7b", finest_stroke=None, strokes_offered=(1, 2),
    )
    assert failures.OVER_LIMIT in modes
    assert failures.SELECTION_IGNORED in modes


def test_a_clean_request_reports_nothing():
    assert failures.classify(result=response(), requested_model="chosen:7b",
                             finest_stroke=2, strokes_offered=(1, 2)) == []


def test_every_mode_has_a_sentence():
    for mode in failures.MODES:
        assert failures.EXPLAIN[mode]


# ── the runner ──────────────────────────────────────────────────────────────


def test_the_whole_corpus_runs_without_a_model():
    # No Ollama, no GPU, no download. That is what makes this the file that tunes the caps.
    rows = runner.run()
    assert len(rows) == len(corpus.cases())
    assert all(row.strategy for row in rows)


def test_the_report_names_the_two_cases_that_should_not_be_clean():
    rows = {row.case: row for row in runner.run()}
    assert failures.OVER_LIMIT in rows["decompression-bomb"].modes
    assert failures.DECODE_FAILED in rows["corrupt-bytes"].modes
    assert failures.DECODE_FAILED in rows["empty-bytes"].modes


def test_the_summary_carries_the_number_that_tunes_the_caps():
    summary = runner.summary(runner.run())
    assert summary["worst_stroke"] >= 3, "a corpus where nothing is hard is not a bench"
    assert summary["cases_a_crop_helps"] > 0, "if a crop never helps, V6's ladder is not worth its calls"


def test_a_harness_that_throws_on_one_case_still_reports_the_rest():
    def explode(**_kwargs):
        raise RuntimeError("no model here")

    rows = runner.run(analyze=explode, only=["terminal", "tiny-icon"])
    assert len(rows) == 2
    assert all(failures.PROVIDER_REJECTED in row.modes for row in rows)
