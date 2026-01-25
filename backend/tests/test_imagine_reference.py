# Tests for Upload Reference feature (img2img similar image generation)


def test_imagine_with_reference_accepts_params(client, mock_outbound):
    """Test that /chat endpoint accepts imgReference and imgRefStrength parameters."""
    payload = {
        "message": "imagine a beautiful sunset",
        "conversation_id": "test-ref-conv",
        "mode": "imagine",
        # Reference image parameters
        "imgReference": "http://localhost:8000/files/test-reference.png",
        "imgRefStrength": 0.35,
    }
    r = client.post("/chat", json=payload)
    assert r.status_code == 200, r.text
    data = r.json()

    assert "text" in data
    assert isinstance(data["text"], str)
    assert "conversation_id" in data


def test_imagine_without_reference_still_works(client, mock_outbound):
    """Test that /chat endpoint works without reference (backward compatible)."""
    payload = {
        "message": "imagine a robot",
        "conversation_id": "test-no-ref-conv",
        "mode": "imagine",
        # No reference parameters
    }
    r = client.post("/chat", json=payload)
    assert r.status_code == 200, r.text
    data = r.json()

    assert "text" in data
    assert isinstance(data["text"], str)


def test_imagine_reference_strength_bounds(client, mock_outbound):
    """Test that reference strength values at bounds are accepted."""
    # Test minimum strength (very similar)
    payload_min = {
        "message": "imagine a cat",
        "conversation_id": "test-ref-min",
        "mode": "imagine",
        "imgReference": "http://localhost:8000/files/cat.png",
        "imgRefStrength": 0.0,  # Maximum similarity
    }
    r = client.post("/chat", json=payload_min)
    assert r.status_code == 200, r.text

    # Test maximum strength (more creative)
    payload_max = {
        "message": "imagine a dog",
        "conversation_id": "test-ref-max",
        "mode": "imagine",
        "imgReference": "http://localhost:8000/files/dog.png",
        "imgRefStrength": 1.0,  # Maximum creativity
    }
    r = client.post("/chat", json=payload_max)
    assert r.status_code == 200, r.text


def test_ref_strength_to_denoise_mapping():
    """Test the reference strength to denoise mapping function."""
    # Import the mapping function
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

    from app.orchestrator import _map_ref_strength_to_denoise

    # Test None returns default
    assert _map_ref_strength_to_denoise(None) == 0.35

    # Test boundaries
    # 0.0 strength -> 0.15 denoise (very similar)
    assert abs(_map_ref_strength_to_denoise(0.0) - 0.15) < 0.01

    # 1.0 strength -> 0.85 denoise (more creative)
    assert abs(_map_ref_strength_to_denoise(1.0) - 0.85) < 0.01

    # 0.5 strength -> ~0.50 denoise (balanced)
    assert abs(_map_ref_strength_to_denoise(0.5) - 0.50) < 0.01

    # Test clamping for out-of-range values
    assert _map_ref_strength_to_denoise(-1.0) == 0.15  # Clamped to 0
    assert _map_ref_strength_to_denoise(2.0) == 0.85   # Clamped to 1

    # Test invalid input
    assert _map_ref_strength_to_denoise("invalid") == 0.35  # Returns default


def test_aspect_ratio_preserved_in_refined():
    """Test that aspect ratio from frontend is preserved in refined dict."""
    # This tests the bug fix where aspect_ratio wasn't written back to refined
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

    # The fix ensures refined["aspect_ratio"] = aspect_ratio is called
    # We verify by checking the orchestrator code contains this line
    orchestrator_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "app",
        "orchestrator.py"
    )

    with open(orchestrator_path, "r") as f:
        content = f.read()

    # Verify the fix is in place
    assert 'refined["aspect_ratio"] = aspect_ratio' in content, \
        "Bug fix missing: aspect_ratio should be written back to refined dict"
