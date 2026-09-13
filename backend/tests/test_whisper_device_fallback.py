"""Loading Whisper when the GPU is present but unusable.

``WHISPER_DEVICE`` defaults to ``auto``, and CTranslate2 grants that request whenever it can
see a GPU — then raises at load time if the CUDA runtime is incomplete::

    RuntimeError: Library libcublas.so.12 is not found or cannot be loaded

The machine can still transcribe perfectly well on its CPU, so raising turned "slower" into
"speech-to-text is broken": every turn came back 502 while the status endpoint went on
reporting the provider as available.
"""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def providers():
    # Imported through the fixture rather than at module scope: several fixtures in this
    # suite purge and re-import `app.*`.
    return importlib.import_module("app.voice.providers")


class _FakeInner:
    def __init__(self, device):
        self.device = device


class _FakeModel:
    """Stands in for `faster_whisper.WhisperModel`, refusing whichever devices it is told to."""

    #: Devices whose *inference* raises, the way CTranslate2 does when it loads the CUDA
    #: libraries lazily: the constructor succeeds and the first transcribe blows up.
    lazy_failing_devices: tuple = ()

    def __init__(self, name, device="cpu", compute_type="default"):
        self.name = name
        self.device = device
        self.compute_type = compute_type
        self.model = _FakeInner(device)

    def transcribe(self, path):  # noqa: ARG002
        if self.device in type(self).lazy_failing_devices:
            raise RuntimeError("Library libcublas.so.12 is not found or cannot be loaded")
        seg = type("Seg", (), {"text": " hello there", "start": 0.0, "end": 1.0,
                               "avg_logprob": -0.1})()
        return [seg], None


def _install_fake(monkeypatch, providers, *, failing_devices=(), record=None):
    """Patch `faster_whisper.WhisperModel` with a stub that fails on the named devices."""

    def factory(name, device="cpu", compute_type="default"):
        if record is not None:
            record.append({"device": device, "compute_type": compute_type})
        if device in failing_devices:
            raise RuntimeError("Library libcublas.so.12 is not found or cannot be loaded")
        return _FakeModel(name, device=device, compute_type=compute_type)

    module = type(providers)("faster_whisper")
    module.WhisperModel = factory  # type: ignore[attr-defined]
    monkeypatch.setitem(importlib.sys.modules, "faster_whisper", module)


class TestCpuFallback:
    def test_an_unusable_cuda_install_loads_on_cpu_instead(self, providers, monkeypatch):
        monkeypatch.setenv("WHISPER_DEVICE", "auto")
        monkeypatch.setenv("WHISPER_COMPUTE", "default")
        calls: list = []
        _install_fake(monkeypatch, providers, failing_devices=("auto", "cuda"), record=calls)

        provider = providers.WhisperLocalSTTProvider()
        model = provider._ensure_model()

        assert model is not None
        assert [c["device"] for c in calls] == ["auto", "cpu"]
        assert provider.device == "cpu"

    def test_the_reason_is_kept_rather_than_swallowed(self, providers, monkeypatch):
        # "Why did this get ten times slower" needs an answer on screen, not only in the log.
        monkeypatch.setenv("WHISPER_DEVICE", "auto")
        _install_fake(monkeypatch, providers, failing_devices=("auto",))

        provider = providers.WhisperLocalSTTProvider()
        provider._ensure_model()

        assert provider.load_error
        assert "libcublas" in provider.load_error

    def test_a_gpu_compute_type_is_not_carried_onto_the_cpu_retry(self, providers, monkeypatch):
        # float16 does not exist on CPU, so reusing it would fail the retry for a second,
        # unrelated reason and hide the first.
        monkeypatch.setenv("WHISPER_DEVICE", "cuda")
        monkeypatch.setenv("WHISPER_COMPUTE", "float16")
        calls: list = []
        _install_fake(monkeypatch, providers, failing_devices=("cuda",), record=calls)

        providers.WhisperLocalSTTProvider()._ensure_model()

        assert calls[0] == {"device": "cuda", "compute_type": "float16"}
        assert calls[1] == {"device": "cpu", "compute_type": "default"}

    def test_a_cpu_compute_type_survives_the_retry(self, providers, monkeypatch):
        monkeypatch.setenv("WHISPER_DEVICE", "cuda")
        monkeypatch.setenv("WHISPER_COMPUTE", "int8")
        calls: list = []
        _install_fake(monkeypatch, providers, failing_devices=("cuda",), record=calls)

        providers.WhisperLocalSTTProvider()._ensure_model()

        assert calls[1] == {"device": "cpu", "compute_type": "int8"}

    def test_an_explicit_cpu_request_still_raises(self, providers, monkeypatch):
        # Nothing to fall back to, and swallowing it would hide a real failure behind a
        # retry that cannot help.
        monkeypatch.setenv("WHISPER_DEVICE", "cpu")
        _install_fake(monkeypatch, providers, failing_devices=("cpu",))

        with pytest.raises(RuntimeError):
            providers.WhisperLocalSTTProvider()._ensure_model()

    def test_a_working_gpu_is_left_alone(self, providers, monkeypatch):
        monkeypatch.setenv("WHISPER_DEVICE", "cuda")
        monkeypatch.setenv("WHISPER_COMPUTE", "float16")
        calls: list = []
        _install_fake(monkeypatch, providers, failing_devices=(), record=calls)

        provider = providers.WhisperLocalSTTProvider()
        provider._ensure_model()

        assert len(calls) == 1
        assert provider.device == "cuda"
        assert provider.load_error is None


class TestCpuComputeType:
    @pytest.mark.parametrize("gpu_only", ["float16", "int8_float16", "bfloat16", "FLOAT16"])
    def test_gpu_only_types_become_default(self, providers, gpu_only):
        assert providers._cpu_compute_type(gpu_only) == "default"

    @pytest.mark.parametrize("portable", ["default", "int8", "float32", ""])
    def test_everything_else_is_kept(self, providers, portable):
        assert providers._cpu_compute_type(portable) == portable


class TestStatusReportsTheFallback:
    def test_the_note_names_the_device_and_the_reason(self, app, monkeypatch):
        transcribe = importlib.import_module("app.voice.transcribe")

        class _Fallen:
            name = "whisper-local"
            available = True
            device = "cpu"
            requested_device = "auto"
            load_error = "RuntimeError: Library libcublas.so.12 is not found or cannot be loaded"

        monkeypatch.setattr(
            "app.voice.providers.get_stt_provider", lambda: _Fallen(), raising=False
        )
        info = transcribe.stt_capability()

        assert info["available"] is True
        assert "libcublas" in info["device_note"]
        assert "running on cpu" in info["device_note"]

    def test_no_note_when_the_load_went_as_asked(self, app, monkeypatch):
        transcribe = importlib.import_module("app.voice.transcribe")

        class _Fine:
            name = "whisper-local"
            available = True
            device = "cpu"
            requested_device = "cpu"
            load_error = None

        monkeypatch.setattr(
            "app.voice.providers.get_stt_provider", lambda: _Fine(), raising=False
        )
        assert "device_note" not in transcribe.stt_capability()


class TestLazyCudaFailureAtInference:
    """The case that actually bit.

    CTranslate2 loads the CUDA libraries lazily, so on a machine with an incomplete runtime
    the constructor *succeeds* and the failure only appears at the first inference. A
    fallback that wrapped only the constructor therefore fixed nothing: every turn still came
    back 502 with `libcublas.so.12 is not found`.
    """

    @pytest.fixture(autouse=True)
    def _reset(self):
        _FakeModel.lazy_failing_devices = ()
        yield
        _FakeModel.lazy_failing_devices = ()

    @pytest.mark.anyio
    async def test_a_lazy_cuda_failure_is_retried_on_cpu(self, providers, monkeypatch):
        monkeypatch.setenv("WHISPER_DEVICE", "cuda")
        monkeypatch.setenv("WHISPER_COMPUTE", "float16")
        calls: list = []
        _install_fake(monkeypatch, providers, failing_devices=(), record=calls)
        _FakeModel.lazy_failing_devices = ("cuda",)

        provider = providers.WhisperLocalSTTProvider()
        text = await provider.transcribe(b"audio", fmt="webm")

        assert text == "hello there"
        # Constructed on cuda, then rebuilt on cpu with a CPU-safe compute type.
        assert [c["device"] for c in calls] == ["cuda", "cpu"]
        assert calls[1]["compute_type"] == "default"
        assert provider.device == "cpu"
        assert "libcublas" in provider.load_error

    @pytest.mark.anyio
    async def test_the_segments_path_recovers_too(self, providers, monkeypatch):
        # Meetings go through `transcribe_segments`; leaving it on the broken model would fix
        # chat and leave meetings 502ing.
        monkeypatch.setenv("WHISPER_DEVICE", "cuda")
        _install_fake(monkeypatch, providers, failing_devices=())
        _FakeModel.lazy_failing_devices = ("cuda",)

        spans = await providers.WhisperLocalSTTProvider().transcribe_segments(b"a", fmt="wav")

        assert [span["text"] for span in spans] == ["hello there"]

    @pytest.mark.anyio
    async def test_it_retries_once_and_then_gives_up(self, providers, monkeypatch):
        # A second retry could not help and would only hide the real error behind a
        # duplicate of itself.
        monkeypatch.setenv("WHISPER_DEVICE", "cuda")
        calls: list = []
        _install_fake(monkeypatch, providers, failing_devices=(), record=calls)
        _FakeModel.lazy_failing_devices = ("cuda", "cpu")

        with pytest.raises(RuntimeError):
            await providers.WhisperLocalSTTProvider().transcribe(b"a", fmt="wav")

        assert [c["device"] for c in calls] == ["cuda", "cpu"]

    @pytest.mark.anyio
    async def test_a_working_gpu_transcribes_without_a_rebuild(self, providers, monkeypatch):
        monkeypatch.setenv("WHISPER_DEVICE", "cuda")
        calls: list = []
        _install_fake(monkeypatch, providers, failing_devices=(), record=calls)

        provider = providers.WhisperLocalSTTProvider()
        assert await provider.transcribe(b"a", fmt="wav") == "hello there"

        assert [c["device"] for c in calls] == ["cuda"]
        assert provider.load_error is None
