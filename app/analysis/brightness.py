import numpy as np
from app.config import LOW_LIGHT_THRESHOLD


def check_brightness(gray_image) -> dict:
    """Mean pixel intensity (0-255). Low mean -> underexposed / low-light image."""
    mean_val = float(np.mean(gray_image))
    return {
        "check": "brightness",
        "score": round(mean_val, 2),
        "threshold": LOW_LIGHT_THRESHOLD,
        "is_low_light": bool(mean_val < LOW_LIGHT_THRESHOLD),
    }
