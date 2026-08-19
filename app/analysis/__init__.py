import logging
import cv2
from sqlalchemy.orm import Session

from app.analysis.blur import check_blur
from app.analysis.brightness import check_brightness
from app.analysis.duplicate import check_duplicate, compute_phash
from app.analysis.plate import check_plate

logger = logging.getLogger("media_pipeline")


def run_all_checks(image_path: str, job_id: str, db: Session) -> dict:
    """
    Runs all 4 checks. Each is isolated in its own try/except so one bad
    check doesn't fail the whole job - it just gets recorded as errored.
    """
    image_bgr = cv2.imread(image_path)
    if image_bgr is None:
        raise ValueError(f"Could not decode image at {image_path} (corrupt or unsupported format)")

    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)

    checks = {}
    issues = []

    def run(name, fn):
        try:
            result = fn()
            checks[name] = result
            return result
        except Exception as e:
            logger.exception("Check '%s' failed for job %s", name, job_id)
            checks[name] = {"check": name, "error": str(e)}
            return None

    blur_result = run("blur", lambda: check_blur(gray))
    if blur_result and blur_result.get("is_blurry"):
        issues.append("blurry_image")

    brightness_result = run("brightness", lambda: check_brightness(gray))
    if brightness_result and brightness_result.get("is_low_light"):
        issues.append("low_light")

    dup_result = run("duplicate", lambda: check_duplicate(image_path, job_id, db))
    if dup_result and dup_result.get("is_duplicate"):
        issues.append("duplicate_image")

    plate_result = run("plate_format", lambda: check_plate(image_bgr))

    if (
    plate_result
    and plate_result.get("is_valid_format") is False
    and plate_result.get("ocr_available")
    and plate_result.get("plate_detected")
    ):
        issues.append("invalid_plate_format")
        

    perceptual_hash = None
    if dup_result and "hash" in dup_result:
        perceptual_hash = dup_result["hash"]
    else:
        try:
            perceptual_hash = compute_phash(image_path)
        except Exception:
            logger.warning("Could not compute perceptual hash for job %s", job_id)

    verdict = "flagged" if issues else "clean"

    return {
        "checks": checks,
        "issues": issues,
        "verdict": verdict,
        "perceptual_hash": perceptual_hash,
    }
