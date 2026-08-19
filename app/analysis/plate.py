import re
import logging

from app.config import PLATE_REGEX

logger = logging.getLogger("media_pipeline")


def _normalize_ocr_text(text: str) -> str:
    """
    Normalize OCR text for plate matching.
    Keeps only alphanumeric characters.
    """
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def _looks_like_date(text: str) -> bool:
    """
    Reject OCR candidates that look like dates.

    Example:
        AY17FEB2026
    should not be interpreted as a vehicle number.
    """
    date_pattern = re.compile(
        r"^(?:[A-Z]{1,3})?\d{1,2}"
        r"(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)"
        r"\d{2,4}$"
    )

    return bool(date_pattern.fullmatch(text))


def _find_plate(text: str):
    """
    Search OCR output for an Indian vehicle registration number.
    """

    normalized = re.sub(
        r"[^A-Z0-9]",
        "",
        text.upper(),
    )

    # Normalized Indian registration format.
    pattern = r"[A-Z]{2}[0-9]{1,2}[A-Z]{1,3}[0-9]{4}"

    for match in re.finditer(pattern, normalized):

        candidate = match.group(0)

        if _looks_like_date(candidate):
            logger.debug(
                "Rejected date-like OCR candidate: %s",
                candidate,
            )
            continue

        return candidate

    return None

    for match in pattern.finditer(text.upper()):
        candidate = "".join(match.groups())

        if _looks_like_date(candidate):
            logger.debug("Rejected date-like OCR candidate: %s", candidate)
            continue

        # Validate against configured format as an additional safety check.
        if re.fullmatch(
            PLATE_REGEX.replace("^", "").replace("$", ""),
            candidate,
        ):
            return candidate

    return None


def _find_plate_regions(image_bgr):
    """
    Find rectangular regions that could contain a vehicle number plate.

    Uses edge detection + contours and filters candidates based on:
    - size
    - aspect ratio
    - rectangularity
    - location in the lower part of the image
    """

    import cv2

    image_height, image_width = image_bgr.shape[:2]

    gray = cv2.cvtColor(
        image_bgr,
        cv2.COLOR_BGR2GRAY,
    )

    # Reduce small image noise.
    blurred = cv2.GaussianBlur(
        gray,
        (5, 5),
        0,
    )

    # Find strong edges.
    edges = cv2.Canny(
        blurred,
        50,
        150,
    )

    # Connect nearby horizontal/vertical edges.
    kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT,
        (7, 3),
    )

    edges = cv2.morphologyEx(
        edges,
        cv2.MORPH_CLOSE,
        kernel,
        iterations=2,
    )

    contours, _ = cv2.findContours(
        edges,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )

    candidates = []

    for contour in contours:

        x, y, w, h = cv2.boundingRect(contour)

        area = w * h

        # ---------------------------------------------------------
        # Basic size filtering
        # ---------------------------------------------------------

        if area < 500:
            continue

        if w < image_width * 0.08:
            continue

        if h < image_height * 0.015:
            continue

        # Don't accept enormous parts of the vehicle.
        if area > image_width * image_height * 0.05:
            continue

        # ---------------------------------------------------------
        # Plate aspect ratio
        # ---------------------------------------------------------

        aspect_ratio = w / float(h)

        # Typical plate-like rectangles are wider than tall.
        if aspect_ratio < 1.8 or aspect_ratio > 6.5:
            continue

        # ---------------------------------------------------------
        # Location
        # ---------------------------------------------------------

        # Ignore text/posters near the top of the image.
        if y < image_height * 0.40:
            continue

        # ---------------------------------------------------------
        # Rectangularity
        # ---------------------------------------------------------

        contour_area = cv2.contourArea(contour)

        if contour_area <= 0:
            continue

        rectangularity = contour_area / float(area)

        # Reject very irregular shapes.
        if rectangularity < 0.25:
            continue

        candidates.append({
            "x": x,
            "y": y,
            "w": w,
            "h": h,
            "source": "contour_plate",
            "score": (
                rectangularity
                * min(aspect_ratio, 6.0)
                * w
            ),
        })

    # Best candidates first.
    candidates.sort(
        key=lambda candidate: candidate["score"],
        reverse=True,
    )

    return candidates[:10]


def _contour_candidates(mask, width, height, source):
    """
    Convert contours into plate-like bounding boxes.
    """

    import cv2

    contours, _ = cv2.findContours(
        mask,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )

    candidates = []

    image_area = width * height

    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)

        area = w * h

        if area < image_area * 0.0005:
            continue

        if area > image_area * 0.25:
            continue

        if h == 0:
            continue

        aspect_ratio = w / h

        # Typical plate-like rectangles are wider than tall.
        if aspect_ratio < 2.0 or aspect_ratio > 7.0:
            continue

        candidates.append(
            {
                "x": x,
                "y": y,
                "w": w,
                "h": h,
                "area": area,
                "aspect_ratio": round(aspect_ratio, 2),
                "source": source,
            }
        )

    return candidates


def _deduplicate_candidates(candidates):
    """
    Remove candidates that overlap heavily.
    """

    result = []

    for candidate in candidates:

        duplicate = False

        cx = candidate["x"] + candidate["w"] / 2
        cy = candidate["y"] + candidate["h"] / 2

        for existing in result:

            ex = existing["x"] + existing["w"] / 2
            ey = existing["y"] + existing["h"] / 2

            distance_x = abs(cx - ex)
            distance_y = abs(cy - ey)

            overlap_x = distance_x < (
                candidate["w"] + existing["w"]
            ) / 2

            overlap_y = distance_y < (
                candidate["h"] + existing["h"]
            ) / 2

            if overlap_x and overlap_y:
                duplicate = True
                break

        if not duplicate:
            result.append(candidate)

    return result


def _prepare_plate_crop(crop):
    """
    Prepare a detected plate crop for OCR.
    """

    import cv2

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)

    # Upscale small plate regions.
    enlarged = cv2.resize(
        gray,
        None,
        fx=5,
        fy=5,
        interpolation=cv2.INTER_CUBIC,
    )

    # Improve local contrast.
    clahe = cv2.createCLAHE(
        clipLimit=2.0,
        tileGridSize=(8, 8),
    )

    enhanced = clahe.apply(enlarged)

    # Light denoising.
    enhanced = cv2.GaussianBlur(
        enhanced,
        (3, 3),
        0,
    )

    # Otsu threshold.
    thresholded = cv2.threshold(
        enhanced,
        0,
        255,
        cv2.THRESH_BINARY + cv2.THRESH_OTSU,
    )[1]

    # Also create an inverted version.
    inverted = cv2.bitwise_not(thresholded)

    return enhanced, thresholded, inverted

def _find_yellow_plate_regions(image_bgr):
    """
    Detect likely yellow Indian vehicle plates using HSV color segmentation.
    Returns candidate rectangular regions.
    """
    import cv2

    hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)

    # Yellow range.
    lower_yellow = (15, 70, 70)
    upper_yellow = (40, 255, 255)

    mask = cv2.inRange(
        hsv,
        lower_yellow,
        upper_yellow,
    )

    # Clean up small gaps/noise.
    kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT,
        (5, 5),
    )

    mask = cv2.morphologyEx(
        mask,
        cv2.MORPH_CLOSE,
        kernel,
        iterations=2,
    )

    mask = cv2.morphologyEx(
        mask,
        cv2.MORPH_OPEN,
        kernel,
        iterations=1,
    )

    contours, _ = cv2.findContours(
        mask,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )

    image_height, image_width = image_bgr.shape[:2]

    candidates = []

    for contour in contours:

        x, y, w, h = cv2.boundingRect(contour)

        area = w * h

        if area < 300:
            continue

        if w < 30 or h < 10:
            continue

        aspect_ratio = w / float(h)

        # Number plates are generally wider than tall.
        if aspect_ratio < 1.5:
            continue

        if aspect_ratio > 8.0:
            continue

        # Reject regions that occupy almost the entire image.
        if w > image_width * 0.8:
            continue

        if h > image_height * 0.3:
            continue

        candidates.append({
            "x": x,
            "y": y,
            "w": w,
            "h": h,
            "source": "yellow",
        })

    # Larger / more plate-like candidates first.
    candidates.sort(
        key=lambda c: c["w"] * c["h"],
        reverse=True,
    )

    return candidates[:20]


def check_plate(image_bgr) -> dict:
    """
    Detect likely Indian vehicle number plates and OCR them.

    Strategy:
    1. Detect yellow plate-like regions using HSV.
    2. Detect rectangular plate-like regions using contours.
    3. Rank candidates by plate geometry and location.
    4. OCR only the best candidates.
    5. Validate OCR output against the Indian registration format.

    OCR is treated as a best-effort signal, not ground truth.
    """

    try:
        import cv2
        import pytesseract

        image_height, image_width = image_bgr.shape[:2]

        # =========================================================
        # Helper: normalize OCR text
        # =========================================================

        def normalize_text(text):
            text = text.upper()

            # Remove spaces, punctuation and OCR noise.
            text = re.sub(r"[^A-Z0-9]", "", text)

            # Common OCR substitutions.
            replacements = {
                "O": "0",
                "I": "1",
                "L": "1",
            }

            # Don't blindly replace letters globally because
            # plate state codes contain letters.
            return text

        # =========================================================
        # Helper: OCR a crop
        # =========================================================

        def run_ocr(crop):
            results = []

            if crop is None or crop.size == 0:
                return results

            # Number plates are usually small, so upscale.
            enlarged = cv2.resize(
                crop,
                None,
                fx=4,
                fy=4,
                interpolation=cv2.INTER_CUBIC,
            )

            gray = cv2.cvtColor(
                enlarged,
                cv2.COLOR_BGR2GRAY,
            )

            # Slight denoising.
            gray = cv2.GaussianBlur(
                gray,
                (3, 3),
                0,
            )

            # Multiple preprocessing approaches.
            variants = [
                ("gray", gray),

                (
                    "otsu",
                    cv2.threshold(
                        gray,
                        0,
                        255,
                        cv2.THRESH_BINARY + cv2.THRESH_OTSU,
                    )[1],
                ),

                (
                    "adaptive",
                    cv2.adaptiveThreshold(
                        gray,
                        255,
                        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                        cv2.THRESH_BINARY,
                        31,
                        9,
                    ),
                ),
            ]

            for variant_name, processed in variants:

                for psm in [7, 8, 13]:

                    text = pytesseract.image_to_string(
                        processed,
                        config=(
                            f"--psm {psm} "
                            "-c "
                            "tessedit_char_whitelist="
                            "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
                        ),
                    ).strip()

                    if text:
                        results.append({
                            "text": text,
                            "source": f"{variant_name}_psm{psm}",
                        })

            return results

        # =========================================================
        # 1. Detect yellow regions
        # =========================================================

        hsv = cv2.cvtColor(
            image_bgr,
            cv2.COLOR_BGR2HSV,
        )

        # Yellow number plates.
        lower_yellow = (15, 80, 80)
        upper_yellow = (40, 255, 255)

        yellow_mask = cv2.inRange(
            hsv,
            lower_yellow,
            upper_yellow,
        )

        # Close small gaps.
        kernel = cv2.getStructuringElement(
            cv2.MORPH_RECT,
            (7, 5),
        )

        yellow_mask = cv2.morphologyEx(
            yellow_mask,
            cv2.MORPH_CLOSE,
            kernel,
            iterations=2,
        )

        contours, _ = cv2.findContours(
            yellow_mask,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE,
        )

        yellow_candidates = []

        for contour in contours:

            x, y, w, h = cv2.boundingRect(contour)

            area = w * h

            if area < 300:
                continue

            if w < 50 or h < 12:
                continue

            aspect_ratio = w / float(h)

            # Indian plates are generally rectangular.
            if aspect_ratio < 2.0 or aspect_ratio > 7.0:
                continue

            # Reject enormous yellow regions.
            if area > image_width * image_height * 0.03:
                continue

            # Prefer lower portion of vehicle images.
            relative_y = y / float(image_height)

            if relative_y < 0.35:
                continue

            # Score candidate.
            score = 0

            # Wider plates are better.
            if 2.5 <= aspect_ratio <= 6.0:
                score += 3

            # Lower part gets higher priority.
            if relative_y > 0.55:
                score += 3
            elif relative_y > 0.45:
                score += 2

            yellow_candidates.append({
                "x": x,
                "y": y,
                "w": w,
                "h": h,
                "source": "yellow",
                "score": score,
            })

        # =========================================================
        # 2. Generic rectangular contour detection
        # =========================================================

        gray = cv2.cvtColor(
            image_bgr,
            cv2.COLOR_BGR2GRAY,
        )

        edges = cv2.Canny(
            gray,
            50,
            150,
        )

        contour_kernel = cv2.getStructuringElement(
            cv2.MORPH_RECT,
            (5, 3),
        )

        edges = cv2.morphologyEx(
            edges,
            cv2.MORPH_CLOSE,
            contour_kernel,
            iterations=2,
        )

        contours, _ = cv2.findContours(
            edges,
            cv2.RETR_LIST,
            cv2.CHAIN_APPROX_SIMPLE,
        )

        contour_candidates = []

        for contour in contours:

            x, y, w, h = cv2.boundingRect(contour)

            area = w * h

            if area < 500:
                continue

            if w < 60 or h < 15:
                continue

            aspect_ratio = w / float(h)

            if aspect_ratio < 2.0 or aspect_ratio > 6.5:
                continue

            relative_y = y / float(image_height)

            if relative_y < 0.35:
                continue

            # Don't accept giant rectangles such as the whole vehicle.
            if area > image_width * image_height * 0.08:
                continue

            score = 0

            if 2.5 <= aspect_ratio <= 6.0:
                score += 3

            if relative_y > 0.55:
                score += 3
            elif relative_y > 0.45:
                score += 2

            contour_candidates.append({
                "x": x,
                "y": y,
                "w": w,
                "h": h,
                "source": "contour",
                "score": score,
            })

        # =========================================================
        # 3. Combine and rank candidates
        # =========================================================

        candidates = (
            yellow_candidates +
            contour_candidates
        )

        # Highest scoring candidates first.
        candidates.sort(
            key=lambda candidate: (
                candidate["score"],
                candidate["w"] * candidate["h"],
            ),
            reverse=True,
        )

        # Avoid spending 40+ seconds OCR'ing dozens of regions.
        candidates = candidates[:12]

        logger.info(
            "Plate detection: yellow=%d contour=%d total=%d",
            len(yellow_candidates),
            len(contour_candidates),
            len(candidates),
        )

        # =========================================================
        # 4. OCR candidate regions
        # =========================================================

        all_ocr_text = []

        for candidate in candidates:

            x = candidate["x"]
            y = candidate["y"]
            w = candidate["w"]
            h = candidate["h"]

            # Add small padding around plate.
            padding_x = int(w * 0.12)
            padding_y = int(h * 0.20)

            x1 = max(
                0,
                x - padding_x,
            )

            y1 = max(
                0,
                y - padding_y,
            )

            x2 = min(
                image_width,
                x + w + padding_x,
            )

            y2 = min(
                image_height,
                y + h + padding_y,
            )

            crop = image_bgr[
                y1:y2,
                x1:x2
            ]

            if crop.size == 0:
                continue

            ocr_results = run_ocr(crop)

            for result in ocr_results:

                text = result["text"]

                all_ocr_text.append(text)

                plate = _find_plate(text)

                if plate:

                    logger.info(
                        "Plate detected: %s source=%s",
                        plate,
                        candidate["source"],
                    )

                    return {
                        "check": "plate_format",
                        "ocr_available": True,
                        "plate_detected": True,
                        "extracted_text": plate,
                        "is_valid_format": True,
                        "candidate_regions": len(candidates),
                        "detection_source": candidate["source"],
                        "raw_text": text[:500],
                    }

        # =========================================================
        # 5. OCR found text but no valid plate
        # =========================================================

        combined_text = "\n".join(
            all_ocr_text
        )

        return {
            "check": "plate_format",
            "ocr_available": True,
            "plate_detected": False,
            "extracted_text": None,
            "is_valid_format": None,
            "candidate_regions": len(candidates),
            "raw_text": combined_text[:1000],
        }

    except Exception as e:

        logger.exception(
            "OCR unavailable or failed: %s",
            e,
        )

        return {
            "check": "plate_format",
            "ocr_available": False,
            "plate_detected": False,
            "extracted_text": None,
            "is_valid_format": None,
            "candidate_regions": 0,
            "raw_text": None,
            "note": (
                "OCR engine unavailable/failed on this host; "
                "format could not be verified."
            ),
        }