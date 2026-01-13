import io

def test_upload_returns_url(client, mock_outbound):
    fake_png = b"\x89PNG\r\n\x1a\n" + b"0" * 64
    files = {"file": ("test.png", io.BytesIO(fake_png), "image/png")}
    r = client.post("/upload", files=files)
    assert r.status_code in (200, 201), r.text
    data = r.json()
    assert "url" in data
    assert isinstance(data["url"], str)
