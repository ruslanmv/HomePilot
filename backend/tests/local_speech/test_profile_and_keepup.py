"""The hardware chooses itself, keeps up or says so, and reports it (batches LS5–LS8).

Three acceptances, one file, because they are three views of the same question — *is this machine
actually doing the job* — and testing them apart is how they drift apart.

**LS5.** *CUDA present but unusable → the profile records CPU and the UI says CPU.* A
configuration that silently fell back to CPU while still displaying "GPU" is precisely the failure
this batch exists to prevent, and it is invisible without this test.

**LS6.** *A deliberately slow runtime drives the degrade path, and no remote call happens at any
point in it.* The default answer to "your computer is slow" must never be "so let us send your
meeting somewhere else".

**LS7.** *Six failure modes are distinguishable from the status payload alone.* A status endpoint
that collapses any two of them has failed at the one job it has.

**LS8.** No default changes without data from this repository — expressed as a function that
refuses to rank runs measured differently.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.local_speech import bench, benchmark, keepup, manifest, status
from app.local_speech.hardware import Hardware
from app.local_speech.provider import HomePilotLocalSTTProvider

from .test_local_pack import FakeEngine, eight_second_wav, make_pack


def provider_on(tmp_path, *, engine_factory=FakeEngine, hardware=None, environ=None):
    make_pack(tmp_path)
    return HomePilotLocalSTTProvider(
        environ=environ if environ is not None else {"HOMEPILOT_SPEECH_DIR": str(tmp_path)},
        engine_factory=engine_factory,
        hardware=hardware,
    )


# ── LS5: the hardware chooses itself ────────────────────────────────────────


def test_cuda_present_but_unusable_records_cpu(tmp_path):
    """The batch's stated acceptance.

    The machine has CUDA. The engine loaded on CPU anyway — a mismatched ctranslate2 wheel, a
    missing cuDNN, the reasons are many and all of them are silent. Everything works and runs ten
    times slower than the budget assumed. The profile must say cpu, because the profile is the
    only place anybody would ever find out.
    """
    has_cuda = Hardware(system="Linux", machine="x86_64", cpu_count=8, cuda=True,
                        cuda_devices=["cuda:0"])

    class FallsBackSilently(FakeEngine):
        def __init__(self, directory, device="auto", compute_type="default", **kwargs):
            super().__init__(directory, device=device, compute_type=compute_type, **kwargs)
            self.device = "cpu"  # what ctranslate2 reports back after the fallback

    stt = provider_on(tmp_path, engine_factory=FallsBackSilently, hardware=has_cuda)
    audio = eight_second_wav(tmp_path / "s.wav")
    profile = benchmark.measure(stt, audio, sample_s=8.0)

    assert profile.device == "cpu"
    assert profile.hardware["cuda"] is True, "the detection was right; the load was not"

    # And the interface says so too, by name rather than by inference.
    body = status.payload(provider=stt, profile=profile)
    assert body["device"] == "cpu"
    assert status.WRONG_DEVICE in body["modes"]


def test_a_working_gpu_is_not_flagged(tmp_path):
    has_cuda = Hardware(system="Linux", machine="x86_64", cpu_count=8, cuda=True, cuda_devices=["cuda:0"])

    class RealGpu(FakeEngine):
        def __init__(self, directory, **kwargs):
            super().__init__(directory, **kwargs)
            self.device = "cuda"

    stt = provider_on(tmp_path, engine_factory=RealGpu, hardware=has_cuda)
    profile = benchmark.measure(stt, eight_second_wav(tmp_path / "s.wav"), sample_s=8.0)
    body = status.payload(provider=stt, profile=profile)
    assert status.WRONG_DEVICE not in body["modes"]


def test_the_real_time_factor_is_measured_not_guessed(tmp_path):
    stt = provider_on(tmp_path)
    clock = {"t": 0.0}

    def now():
        clock["t"] += 0.4  # a few ticks across load and transcribe
        return clock["t"]

    profile = benchmark.measure(stt, eight_second_wav(tmp_path / "s.wav"), sample_s=8.0, now=now)
    assert profile.elapsed_s > 0
    assert profile.rtf == round(profile.elapsed_s / 8.0, 4)


def test_a_machine_that_cannot_keep_up_is_not_certified():
    slow = benchmark.Profile(model="whisper-large-v3-turbo", device="cpu", rtf=1.4, sample_s=8.0)
    fast = benchmark.Profile(model="whisper-small", device="cpu", rtf=0.2, sample_s=8.0)
    assert keepup.certify(slow)["certified"] is False
    assert keepup.certify(fast)["certified"] is True
    # Certified because it keeps up with a meeting, not because the model loaded.
    assert keepup.certify(slow)["reason"] == "too-slow"


def test_a_benchmark_that_failed_is_still_a_profile(tmp_path):
    stt = HomePilotLocalSTTProvider(environ={"HOMEPILOT_SPEECH_DIR": str(tmp_path / "none")},
                                    engine_factory=FakeEngine)
    profile = benchmark.measure(stt, b"", sample_s=8.0)
    assert profile.error == "pack-not-installed"
    assert profile.rtf == 0.0
    assert keepup.certify(profile)["certified"] is False


def test_the_profile_is_measured_once_and_kept(tmp_path):
    # A benchmark that re-runs at every startup is a delay somebody pays for repeatedly and
    # learns nothing new from.
    environ = {"HOMEPILOT_SPEECH_DIR": str(tmp_path)}
    stt = provider_on(tmp_path, environ=environ)
    audio = eight_second_wav(tmp_path / "s.wav")

    first = benchmark.ensure(stt, audio, sample_s=8.0, environ=environ)
    marker = benchmark.path_for(environ)
    assert marker.is_file()

    stored = json.loads(marker.read_text())
    stored["rtf"] = 9.99
    marker.write_text(json.dumps(stored))

    second = benchmark.ensure(stt, audio, sample_s=8.0, environ=environ)
    assert second.rtf == 9.99, "it re-measured instead of reading what it had"
    third = benchmark.ensure(stt, audio, sample_s=8.0, environ=environ, force=True)
    assert third.rtf != 9.99


def test_a_corrupt_profile_file_is_not_a_crash(tmp_path):
    environ = {"HOMEPILOT_SPEECH_DIR": str(tmp_path)}
    benchmark.path_for(environ).parent.mkdir(parents=True, exist_ok=True)
    benchmark.path_for(environ).write_text("{not json")
    assert benchmark.load(environ) is None


def test_nothing_here_decides_which_runtime_is_fastest():
    # The plan forbids it explicitly, and a search order is not a verdict: the benchmark is.
    cuda_box = Hardware(system="Linux", machine="x86_64", cpu_count=8, cuda=True, cuda_devices=["cuda:0"])
    options = benchmark.candidates(cuda_box)
    assert {option["device"] for option in options} == {"cuda", "cpu"}
    assert options[-1]["device"] == "cpu", "cpu always stays reachable as a candidate"
    cpu_box = Hardware(system="Linux", machine="x86_64", cpu_count=8, cuda=False)
    assert [option["device"] for option in benchmark.candidates(cpu_box)] == ["cpu"]


# ── LS6: keep up, or say so ─────────────────────────────────────────────────


def test_one_slow_utterance_is_not_a_verdict():
    watch = keepup.KeepUp()
    watch.record(audio_s=4.0, latency_s=6.0)
    assert watch.behind is False


def test_a_run_of_late_lines_is():
    watch = keepup.KeepUp()
    for _ in range(keepup.BEHIND_AT):
        watch.record(audio_s=4.0, latency_s=6.0)
    assert watch.behind is True
    assert watch.stats()["p95_latency_s"] == 6.0


def test_a_fast_machine_stays_out_of_the_degrade_path():
    watch = keepup.KeepUp()
    for _ in range(keepup.WINDOW):
        watch.record(audio_s=4.0, latency_s=0.5)
    assert watch.behind is False


def test_a_lighter_local_model_is_offered_first():
    # The default answer to "your computer is slow" is never "so let us send your meeting
    # somewhere else". That is the one thing the person chose this feature to avoid.
    offer = keepup.offer(
        current_pack="whisper-large-v3-turbo",
        installed=["whisper-large-v3-turbo", "whisper-small"],
        remote_enabled=True,
    )
    assert offer.kind == "lighter-local"
    assert offer.pack == "whisper-small"
    assert "this computer" in offer.label


def test_remote_is_only_offered_to_somebody_who_already_enabled_it():
    installed = ["whisper-base"]
    assert keepup.offer(current_pack="whisper-base", installed=installed, remote_enabled=False).kind == "none"
    assert keepup.offer(current_pack="whisper-base", installed=installed, remote_enabled=True).kind == "ask-remote"


def test_and_always_as_a_question():
    offer = keepup.offer(current_pack="whisper-base", installed=["whisper-base"], remote_enabled=True)
    assert offer.asks is True, "a fallback that happens to somebody is not a choice"


def test_a_lighter_model_that_is_not_installed_is_not_offered():
    # Offering it would be offering a download in the middle of a meeting, which is the thing
    # LS3 removed.
    assert keepup.lighter_than("whisper-large-v3-turbo", installed=[]) is None
    assert keepup.lighter_than("whisper-large-v3-turbo", installed=["whisper-base"]) == "whisper-base"


def test_the_forbidden_warm_moments_are_written_down():
    # Never on the first spoken word — a cold load in front of people — and never during
    # application startup, which spends a first impression on a feature nobody has opened.
    assert "first-utterance" in keepup.NEVER_WARM_ON
    assert "app-startup" in keepup.NEVER_WARM_ON
    assert "meeting-panel-opened" in keepup.WARM_ON


def test_no_remote_call_happens_anywhere_in_the_degrade_path(tmp_path):
    from app.local_speech import netguard

    stt = provider_on(tmp_path)
    audio = eight_second_wav(tmp_path / "s.wav")
    with netguard.no_outbound() as attempts:
        watch = keepup.KeepUp()
        for _ in range(keepup.WINDOW):
            watch.record(audio_s=4.0, latency_s=9.0)
        assert watch.behind
        offer = keepup.offer(current_pack="whisper-large-v3-turbo",
                             installed=["whisper-large-v3-turbo", "whisper-small"],
                             remote_enabled=True)
        assert offer.kind == "lighter-local"
        benchmark.measure(stt, audio, sample_s=8.0)
    assert attempts.clean, attempts.outbound


# ── LS7: status worth reading ───────────────────────────────────────────────


def base_status(**overrides):
    body = {
        "available": True, "warm": True, "remote": False, "requested_device": "auto",
        "device": "cpu", "last_error": "", "last_result_empty": False, "benchmark": {},
    }
    body.update(overrides)
    return body


MODE_CASES = {
    status.MODEL_NOT_FOUND: base_status(available=False, warm=False),
    status.COLD_LOAD: base_status(warm=False),
    status.WRONG_DEVICE: base_status(requested_device="cuda", device="cpu"),
    status.DECODE_FAILURE: base_status(last_error="transcribe-failed: RuntimeError"),
    status.EMPTY_MODEL_RESPONSE: base_status(last_result_empty=True),
    status.REMOTE_IN_USE: base_status(remote=True, available=True, warm=True),
}


@pytest.mark.parametrize("mode", status.MODES)
def test_each_status_failure_mode_stands_alone(mode):
    assert status.classify(MODE_CASES[mode]) == [mode]


def test_no_two_status_modes_have_collapsed():
    # The batch's acceptance, as a property: every mode is observed on its own somewhere. A
    # payload where two always travel together cannot tell them apart.
    observed = {mode: status.classify(body) for mode, body in MODE_CASES.items()}
    assert status.distinguishable(observed) == []


def test_not_installed_and_not_loaded_are_different_sentences():
    # One is a button; the other is a wait. Collapsing them sends somebody to install what they
    # already have.
    assert status.classify(base_status(available=False, warm=False)) == [status.MODEL_NOT_FOUND]
    assert status.classify(base_status(available=True, warm=False)) == [status.COLD_LOAD]


def test_auto_that_landed_on_cpu_with_cuda_present_is_flagged():
    # `auto` is not an error anywhere in the stack, which is exactly why it needs naming here.
    body = base_status(requested_device="auto", device="cpu",
                       benchmark={"hardware": {"cuda": True}})
    assert status.WRONG_DEVICE in status.classify(body)


def test_local_is_a_field_not_an_inference():
    # Somebody who chose this feature for privacy needs that sentence to be load-bearing.
    assert status.payload(remote_in_use=True)["local"] is False
    assert status.payload(remote_in_use=False)["local"] is True


def test_the_pill_says_local_and_names_the_model(tmp_path):
    stt = provider_on(tmp_path)
    body = status.payload(provider=stt)
    assert body["label"] == "Transcription — Local · Whisper Small"
    assert status.payload(remote_in_use=True)["label"] == "Transcription — Remote"


def test_the_payload_is_json_and_recomputable(tmp_path):
    stt = provider_on(tmp_path)
    stt.load()
    body = status.payload(provider=stt, profile=benchmark.Profile(rtf=0.2))
    json.dumps(body)
    # A consumer holding only the JSON reaches the same conclusion the server did.
    assert status.classify(body) == body["modes"]


# ── LS8: no default changes without data from here ──────────────────────────


def complete_run(family="faster-whisper", model="large-v3-turbo", **metric_overrides):
    metrics = {metric: 0.5 for metric in bench.METRICS}
    metrics.update(metric_overrides)
    return bench.Run(
        family=family, model=model, device="cuda", corpus="meetings-v1",
        parameters={name: 1 for name in bench.PARAMETERS},
        metrics=metrics,
    )


def test_this_repository_has_measured_nothing_yet():
    # No licensed corpus and no GPU here. An empty result set is the honest state, and a
    # populated one that nobody measured would be worse than none.
    assert bench.RESULTS == ()
    assert bench.INCUMBENT == ("faster-whisper", "large-v3-turbo")


def test_a_comparison_without_decoding_parameters_is_refused():
    # The same model is two different products at beam 1 and beam 5, and one of those two is
    # being quoted.
    undocumented = complete_run()
    undocumented.parameters = {"beam_size": 5}
    with pytest.raises(bench.NotComparable, match="undocumented parameters"):
        bench.compare([complete_run(), undocumented])


def test_runs_on_different_corpora_are_refused():
    other = complete_run(family="whisper.cpp")
    other.corpus = "librispeech"
    with pytest.raises(bench.NotComparable, match="different corpora"):
        bench.compare([complete_run(), other])


def test_runs_on_different_devices_are_refused():
    other = complete_run(family="whisper.cpp")
    other.device = "cpu"
    with pytest.raises(bench.NotComparable, match="different devices"):
        bench.compare([complete_run(), other])


def test_a_complete_comparison_ranks_every_metric():
    incumbent = complete_run()
    challenger = complete_run(family="whisper.cpp", wer=0.2)
    report = bench.compare([incumbent, challenger])
    assert report["metrics"] == len(bench.METRICS)
    assert report["table"]["wer"][0][0] == "whisper.cpp/large-v3-turbo"


def test_a_challenger_must_beat_the_incumbent_on_every_metric():
    incumbent = complete_run()
    mixed = complete_run(family="whisper.cpp", wer=0.2, drift_s_per_hour=0.9)
    ok, why = bench.may_replace_default(mixed, incumbent)
    assert ok is False
    assert "drift_s_per_hour" in why


def test_and_a_clean_sweep_earns_it():
    incumbent = complete_run()
    better = complete_run(family="whisper.cpp", **{metric: 0.1 for metric in bench.METRICS})
    ok, why = bench.may_replace_default(better, incumbent)
    assert ok is True, why


def test_an_english_only_model_never_becomes_the_default_however_well_it_scores():
    # The people it stops working for are exactly the people who will not be running the
    # benchmark, so this gate is not a preference — it is the whole reason the flag exists.
    incumbent = complete_run()
    distil = complete_run(family="faster-whisper", model="distil-large-v3",
                          **{metric: 0.01 for metric in bench.METRICS})
    ok, why = bench.may_replace_default(distil, incumbent)
    assert ok is False
    assert "English-only" in why


def test_nothing_can_be_promoted_without_measuring_the_incumbent_first():
    ok, why = bench.may_replace_default(complete_run(family="whisper.cpp"), None)
    assert ok is False
    assert "measure the current default first" in why


def test_every_metric_the_plan_named_is_carried():
    for metric in ("wer", "p95_latency_s", "rtf", "cold_load_s", "peak_ram_mb", "peak_vram_mb",
                   "timestamp_error_s", "proper_noun_error_rate", "number_error_rate",
                   "silence_hallucination_rate", "noisy_wer", "drift_s_per_hour"):
        assert metric in bench.METRICS
