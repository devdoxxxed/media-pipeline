import cv2
from app.config import BLUR_THRESHOLD


def check_blur(gray_image) -> dict:
    """Laplacian variance: sharp edges -> high variance. Low variance -> blurry."""
    variance = cv2.Laplacian(gray_image, cv2.CV_64F).var()
    return {
        "check": "blur",
        "score": round(float(variance), 2),
        "threshold": BLUR_THRESHOLD,
        "is_blurry": bool(variance < BLUR_THRESHOLD),
    }
