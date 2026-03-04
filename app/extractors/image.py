import base64


def prepare_image(image_bytes: bytes) -> str:
    """Return base64-encoded image string for Gemini Vision."""
    return base64.b64encode(image_bytes).decode()
