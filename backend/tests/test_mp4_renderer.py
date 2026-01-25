"""
Tests for MP4 renderer pipeline.
Uses mocks to verify the pipeline logic without requiring FFmpeg.
"""
import os
import shutil
import tempfile
from unittest.mock import patch, MagicMock

import pytest

from app.studio.models import ProjectScene, CaptionSegment, AudioTrack


class TestMP4RendererHelpers:
    """Test helper functions in mp4_renderer."""

    def test_safe_filename(self):
        """Test _safe_filename sanitizes filenames correctly."""
        from app.studio.mp4_renderer import _safe_filename

        assert _safe_filename("hello world.png") == "hello_world.png"
        assert _safe_filename("file@#$%.txt") == "file_.txt"
        assert _safe_filename("valid-name_123.mp4") == "valid-name_123.mp4"
        assert _safe_filename("   ") == "file"
        assert _safe_filename("") == "file"

    def test_url_to_local_path(self):
        """Test _url_to_local_path maps URLs to local paths."""
        from app.studio.mp4_renderer import _url_to_local_path

        upload_dir = "/tmp/uploads"

        # Valid /files/ URL
        result = _url_to_local_path("/files/images/test.png", upload_dir)
        assert result == "/tmp/uploads/images/test.png"

        # Non-files URL returns None
        result = _url_to_local_path("http://example.com/image.png", upload_dir)
        assert result is None

        # Empty URL returns None
        result = _url_to_local_path("", upload_dir)
        assert result is None

        # None URL returns None
        result = _url_to_local_path(None, upload_dir)
        assert result is None

    def test_ensure_dir(self):
        """Test ensure_dir creates directories."""
        from app.studio.mp4_renderer import ensure_dir

        with tempfile.TemporaryDirectory() as tmp:
            new_dir = os.path.join(tmp, "a", "b", "c")
            ensure_dir(new_dir)
            assert os.path.isdir(new_dir)


class TestSRTWriter:
    """Test SRT subtitle file generation."""

    def test_write_srt_basic(self):
        """Test _write_srt creates valid SRT file."""
        from app.studio.mp4_renderer import _write_srt

        captions = [
            CaptionSegment(id="c1", projectId="p1", startSec=0.0, endSec=2.5, text="Hello world"),
            CaptionSegment(id="c2", projectId="p1", startSec=2.5, endSec=5.0, text="This is a test"),
            CaptionSegment(id="c3", projectId="p1", startSec=5.0, endSec=7.5, text="Goodbye"),
        ]

        with tempfile.TemporaryDirectory() as tmp:
            srt_path = os.path.join(tmp, "test.srt")
            _write_srt(captions, srt_path)

            assert os.path.exists(srt_path)

            with open(srt_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Verify SRT format
            assert "1\n" in content
            assert "00:00:00,000 --> 00:00:02,500" in content
            assert "Hello world" in content
            assert "2\n" in content
            assert "00:00:02,500 --> 00:00:05,000" in content
            assert "This is a test" in content
            assert "3\n" in content
            assert "Goodbye" in content

    def test_write_srt_empty(self):
        """Test _write_srt handles empty captions list."""
        from app.studio.mp4_renderer import _write_srt

        with tempfile.TemporaryDirectory() as tmp:
            srt_path = os.path.join(tmp, "empty.srt")
            _write_srt([], srt_path)

            assert os.path.exists(srt_path)
            with open(srt_path, "r", encoding="utf-8") as f:
                content = f.read()
            assert content == ""


class TestMP4RendererPipeline:
    """Test the main render_project_to_mp4 function with mocks."""

    @patch("app.studio.mp4_renderer._which")
    @patch("app.studio.mp4_renderer._ffmpeg_run")
    @patch("app.studio.mp4_renderer._resolve_image")
    def test_render_basic_pipeline(self, mock_resolve, mock_ffmpeg, mock_which):
        """Test basic pipeline flow with mocked FFmpeg."""
        from app.studio.mp4_renderer import render_project_to_mp4

        # Setup mocks
        mock_which.return_value = "/usr/bin/ffmpeg"

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = os.path.join(tmp, "output")
            upload_dir = os.path.join(tmp, "uploads")
            os.makedirs(upload_dir)

            # Mock image resolution to return a dummy PNG path
            mock_resolve.side_effect = lambda scene, tmp_dir, upload_dir: os.path.join(tmp_dir, f"scene_{scene.idx:04d}.png")

            # Create test scenes
            scenes = [
                ProjectScene(
                    id="s1", projectId="p1", idx=0,
                    narration="Scene one narration",
                    durationSec=3.0, createdAt=0.0, updatedAt=0.0
                ),
                ProjectScene(
                    id="s2", projectId="p1", idx=1,
                    narration="Scene two narration",
                    durationSec=4.0, createdAt=0.0, updatedAt=0.0
                ),
            ]

            # Mock FFmpeg to create the expected output files
            def mock_ffmpeg_side_effect(args, log_path):
                # Create output file based on last argument (output path)
                out_file = args[-1]
                if out_file.endswith(".mp4"):
                    os.makedirs(os.path.dirname(out_file), exist_ok=True)
                    with open(out_file, "wb") as f:
                        f.write(b"MOCK_MP4_DATA")
                elif out_file.endswith(".jpg"):
                    os.makedirs(os.path.dirname(out_file), exist_ok=True)
                    with open(out_file, "wb") as f:
                        f.write(b"MOCK_JPG_DATA")

            mock_ffmpeg.side_effect = mock_ffmpeg_side_effect

            # Run the renderer
            result = render_project_to_mp4(
                project_id="p1",
                scenes=scenes,
                captions=[],
                audio_tracks=[],
                out_dir=out_dir,
                upload_dir=upload_dir,
                width=1280,
                height=720,
                fps=30,
                burn_in_captions=False,
            )

            # Verify result structure
            assert "mp4_path" in result
            assert "log_path" in result
            assert result["mp4_path"].endswith("output.mp4")

            # Verify FFmpeg was called
            assert mock_ffmpeg.called

            # Verify log file was created
            assert os.path.exists(result["log_path"])

    @patch("app.studio.mp4_renderer._which")
    def test_render_fails_without_ffmpeg(self, mock_which):
        """Test that render fails gracefully when FFmpeg is not installed."""
        from app.studio.mp4_renderer import render_project_to_mp4

        mock_which.return_value = None

        with tempfile.TemporaryDirectory() as tmp:
            with pytest.raises(RuntimeError, match="ffmpeg not found"):
                render_project_to_mp4(
                    project_id="p1",
                    scenes=[],
                    captions=[],
                    audio_tracks=[],
                    out_dir=tmp,
                    upload_dir=tmp,
                    width=1280,
                    height=720,
                    fps=30,
                )

    @patch("app.studio.mp4_renderer._which")
    @patch("app.studio.mp4_renderer._ffmpeg_run")
    @patch("app.studio.mp4_renderer._resolve_image")
    def test_render_with_captions(self, mock_resolve, mock_ffmpeg, mock_which):
        """Test pipeline with captions generates SRT file."""
        from app.studio.mp4_renderer import render_project_to_mp4

        mock_which.return_value = "/usr/bin/ffmpeg"

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = os.path.join(tmp, "output")
            upload_dir = os.path.join(tmp, "uploads")
            os.makedirs(upload_dir)

            mock_resolve.side_effect = lambda scene, tmp_dir, upload_dir: os.path.join(tmp_dir, f"scene_{scene.idx:04d}.png")

            def mock_ffmpeg_side_effect(args, log_path):
                out_file = args[-1]
                if out_file.endswith(".mp4") or out_file.endswith(".jpg"):
                    os.makedirs(os.path.dirname(out_file), exist_ok=True)
                    with open(out_file, "wb") as f:
                        f.write(b"MOCK_DATA")

            mock_ffmpeg.side_effect = mock_ffmpeg_side_effect

            scenes = [
                ProjectScene(
                    id="s1", projectId="p1", idx=0,
                    narration="Hello", durationSec=2.0,
                    createdAt=0.0, updatedAt=0.0
                ),
            ]

            captions = [
                CaptionSegment(id="c1", projectId="p1", startSec=0.0, endSec=2.0, text="Hello caption"),
            ]

            result = render_project_to_mp4(
                project_id="p1",
                scenes=scenes,
                captions=captions,
                audio_tracks=[],
                out_dir=out_dir,
                upload_dir=upload_dir,
                width=1280,
                height=720,
                fps=30,
                burn_in_captions=True,
            )

            # Verify SRT was created
            assert result["srt_path"]
            assert os.path.exists(result["srt_path"])

            with open(result["srt_path"], "r") as f:
                content = f.read()
            assert "Hello caption" in content


class TestImageResolver:
    """Test image resolution logic."""

    def test_resolve_placeholder_image(self):
        """Test that placeholder image is generated when no imageUrl."""
        from app.studio.mp4_renderer import _resolve_image
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = os.path.join(tmp, "tmp")
            upload_dir = os.path.join(tmp, "uploads")
            os.makedirs(tmp_dir)
            os.makedirs(upload_dir)

            scene = ProjectScene(
                id="s1", projectId="p1", idx=0,
                narration="Test narration",
                imageUrl=None,
                durationSec=5.0, createdAt=0.0, updatedAt=0.0
            )

            png_path = _resolve_image(scene, tmp_dir, upload_dir)

            # Verify PNG was created
            assert os.path.exists(png_path)
            assert png_path.endswith(".png")

            # Verify it's a valid image
            img = Image.open(png_path)
            assert img.size == (1280, 720)
            assert img.mode == "RGB"

    def test_resolve_local_image(self):
        """Test resolving a local image from /files/ URL."""
        from app.studio.mp4_renderer import _resolve_image
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = os.path.join(tmp, "tmp")
            upload_dir = os.path.join(tmp, "uploads")
            os.makedirs(tmp_dir)
            os.makedirs(upload_dir)

            # Create a test image
            test_img_path = os.path.join(upload_dir, "test.png")
            img = Image.new("RGB", (100, 100), color="red")
            img.save(test_img_path)

            scene = ProjectScene(
                id="s1", projectId="p1", idx=0,
                narration="Test",
                imageUrl="/files/test.png",
                durationSec=5.0, createdAt=0.0, updatedAt=0.0
            )

            png_path = _resolve_image(scene, tmp_dir, upload_dir)

            # Verify PNG was created
            assert os.path.exists(png_path)

            # Verify it's the converted image
            result_img = Image.open(png_path)
            assert result_img.mode == "RGB"


class TestRenderJobModels:
    """Test render job models."""

    def test_render_job_model(self):
        """Test RenderJob model creation."""
        from app.studio.models import RenderJob

        job = RenderJob(
            id="job-123",
            projectId="proj-456",
            kind="mp4",
            status="queued",
            progress=0.0,
            stage="queued",
            createdAt=1234567890.0,
            updatedAt=1234567890.0,
        )

        assert job.id == "job-123"
        assert job.projectId == "proj-456"
        assert job.kind == "mp4"
        assert job.status == "queued"
        assert job.progress == 0.0

    def test_export_artifact_model(self):
        """Test ExportArtifact model creation."""
        from app.studio.models import ExportArtifact

        artifact = ExportArtifact(
            id="art-123",
            projectId="proj-456",
            kind="mp4",
            url="/files/exports/output.mp4",
            filename="output.mp4",
            bytes=1024000,
            createdAt=1234567890.0,
        )

        assert artifact.id == "art-123"
        assert artifact.kind == "mp4"
        assert artifact.bytes == 1024000


class TestRenderJobs:
    """Test render_jobs module."""

    def test_create_and_get_job(self):
        """Test creating and retrieving a render job."""
        from app.studio import render_jobs

        # Clear any existing jobs for clean test
        render_jobs._JOBS.clear()

        job = render_jobs.create_job("proj-test")

        assert job.id is not None
        assert job.projectId == "proj-test"
        assert job.status == "queued"

        # Retrieve the job
        retrieved = render_jobs.get_job(job.id)
        assert retrieved is not None
        assert retrieved.id == job.id

        # Non-existent job returns None
        assert render_jobs.get_job("non-existent") is None

    def test_update_job(self):
        """Test updating a render job."""
        from app.studio import render_jobs

        render_jobs._JOBS.clear()

        job = render_jobs.create_job("proj-test")

        # Update the job
        updated = render_jobs.update_job(
            job.id,
            status="running",
            progress=50.0,
            stage="rendering"
        )

        assert updated is not None
        assert updated.status == "running"
        assert updated.progress == 50.0
        assert updated.stage == "rendering"

    def test_list_jobs(self):
        """Test listing render jobs for a project."""
        from app.studio import render_jobs
        import time

        render_jobs._JOBS.clear()

        # Create jobs for different projects with small delays to get unique IDs
        job1 = render_jobs.create_job("proj-a")
        time.sleep(0.002)
        job2 = render_jobs.create_job("proj-a")
        time.sleep(0.002)
        job3 = render_jobs.create_job("proj-b")

        # Verify jobs were created
        assert job1.projectId == "proj-a"
        assert job2.projectId == "proj-a"
        assert job3.projectId == "proj-b"

        # List jobs for proj-a
        jobs_a = render_jobs.list_jobs("proj-a")
        assert len(jobs_a) == 2
        assert all(j.projectId == "proj-a" for j in jobs_a)

        # List jobs for proj-b
        jobs_b = render_jobs.list_jobs("proj-b")
        assert len(jobs_b) == 1
        assert jobs_b[0].projectId == "proj-b"


class TestExportsRepo:
    """Test exports_repo module."""

    def test_add_and_list_exports(self):
        """Test adding and listing export artifacts."""
        from app.studio import exports_repo

        # Clear existing exports
        exports_repo._EXPORTS.clear()

        # Use the actual function signature
        artifact = exports_repo.add_export(
            project_id="proj-test",
            kind="mp4",
            url="/files/output.mp4",
            filename="output.mp4",
            bytes_=1000,
        )

        exports = exports_repo.list_exports("proj-test")
        assert len(exports) == 1
        assert exports[0].projectId == "proj-test"
        assert exports[0].kind == "mp4"

    def test_latest_export(self):
        """Test getting the latest export."""
        from app.studio import exports_repo
        import time

        exports_repo._EXPORTS.clear()

        # Add first artifact
        exports_repo.add_export(
            project_id="proj-test",
            kind="mp4",
            url="/files/old.mp4",
            filename="old.mp4",
        )

        # Small delay to ensure different timestamp
        time.sleep(0.01)

        # Add second artifact
        exports_repo.add_export(
            project_id="proj-test",
            kind="mp4",
            url="/files/new.mp4",
            filename="new.mp4",
        )

        latest = exports_repo.latest_export("proj-test", "mp4")
        assert latest is not None
        assert latest.url == "/files/new.mp4"
