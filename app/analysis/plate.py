import os
import re
import logging

from app.config import PLATE_REGEX

logger = logging.getLogger("media_pipeline")

# Set this to True (or export PLATE_DEBUG=1) to dump every candidate crop
# to ./debug_crops/ so you can SEE what the pipeline is selecting instead
# of only seeing the final OCR text. Safe to leave on during development.
PLATE_DEBUG = os.environ.get("PLATE_DEBUG", "0") == "1"


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
    Tries an exact match first, then falls back to correcting common
    OCR character confusions (0/O, 1/I, 2/Z, 5/S, 8/B, H/N, etc.)
    before giving up.
    """

    normalized = re.sub(
        r"[^A-Z0-9]",
        "",
        text.upper(),
    )

    exact = _find_plate_exact(normalized)

    if exact:
        return exact

    return _find_plate_fuzzy(normalized)


# Characters that Tesseract commonly confuses with each other on
# stylized/embossed plate fonts. Each entry maps a character to the
# other characters it might actually be.
_CONFUSABLES = {
    "0": "OQ", "O": "0Q", "Q": "0O",
    "1": "IL", "I": "1L", "L": "1I",
    "2": "Z", "Z": "2",
    "5": "S", "S": "5",
    "8": "B", "B": "8",
    "6": "G", "G": "6",
    "7": "T", "T": "7",
    # Observed in real testing: two-line auto-rickshaw plates
    # under glare confuse H and N surprisingly often.
    "H": "N", "N": "H",
}


def _find_plate_exact(normalized: str):
    """
    Original exact-match search - no character correction.
    """

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


def _find_plate_fuzzy(normalized: str, max_substitutions: int = 2):
    """
    Retry plate matching after correcting a small number of
    commonly-confused characters. Bounded to max_substitutions
    changes so this stays cheap and doesn't just brute-force
    everything into matching.

    Only runs on text that's already plate-length-ish, to avoid
    wasting time generating variants of long noisy OCR strings that
    were never going to match anyway.
    """

    import itertools

    # Only attempt fuzzy correction on segments plausibly the right
    # length for a plate (8-11 chars covers all valid formats).
    candidates_to_try = []

    for length in range(8, 12):
        for start in range(0, max(1, len(normalized) - length + 1)):
            candidates_to_try.append(normalized[start:start + length])

    pattern = re.compile(r"^[A-Z]{2}[0-9]{1,2}[A-Z]{1,3}[0-9]{4}$")

    for segment in candidates_to_try:

        # Positions where a confusable substitution might help.
        ambiguous_positions = [
            i for i, ch in enumerate(segment) if ch in _CONFUSABLES
        ]

        if len(ambiguous_positions) > 6:
            # Too many ambiguous chars - combinatorics would explode
            # and it's unlikely to be a real plate anyway.
            continue

        # Try 0 substitutions (exact), then 1, then up to
        # max_substitutions - preferring the fewest possible changes.
        for num_subs in range(0, max_substitutions + 1):

            for positions in itertools.combinations(
                ambiguous_positions, num_subs
            ):

                chars = list(segment)

                option_lists = [
                    [chars[p]] + list(_CONFUSABLES[chars[p]])
                    for p in positions
                ]

                for replacement_combo in itertools.product(*option_lists):

                    for p, new_char in zip(positions, replacement_combo):
                        chars[p] = new_char

                    variant = "".join(chars)

                    if pattern.fullmatch(variant) and not _looks_like_date(
                        variant
                    ):
                        logger.info(
                            "Fuzzy-matched plate: %s (from %s, "
                            "%d substitution(s))",
                            variant, segment, num_subs,
                        )
                        return variant

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


def _save_debug_crop(image_bgr, candidate, index, image_tag="image"):
    """
    Dump a candidate crop to disk so it can be visually inspected.
    Only runs when PLATE_DEBUG is enabled. Never raises - debug helpers
    should never be able to break the real pipeline.
    """

    if not PLATE_DEBUG:
        return

    try:
        import cv2

        x, y, w, h = (
            candidate["x"],
            candidate["y"],
            candidate["w"],
            candidate["h"],
        )

        crop = image_bgr[y:y + h, x:x + w]

        if crop.size == 0:
            return

        out_dir = os.path.join("debug_crops", image_tag)
        os.makedirs(out_dir, exist_ok=True)

        aspect = round(w / h, 2) if h else 0
        source = candidate.get("source", "unknown")
        score = candidate.get("score", 0)

        fname = (
            f"candidate_{index:02d}_{source}_"
            f"ar{aspect}_score{score}.png"
        )

        cv2.imwrite(os.path.join(out_dir, fname), crop)

    except Exception:
        logger.debug("Debug crop save failed", exc_info=True)


def check_plate(image_bgr, image_tag="image") -> dict:
    """
    Detect likely Indian vehicle number plates and OCR them.

    Strategy:
    1. Detect yellow plate-like regions using HSV.
    2. Detect rectangular plate-like regions using contours.
    3. Rank candidates by plate geometry and location.
    4. OCR only the best candidates.
    5. Validate OCR output against the Indian registration format.

    OCR is treated as a best-effort signal, not ground truth.

    `image_tag` is only used to namespace debug crop dumps (e.g. the
    filename or job id) when PLATE_DEBUG is enabled - it has no effect
    on detection itself.
    """

    try:
        import cv2
        import pytesseract

        image_height, image_width = image_bgr.shape[:2]

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

                # psm 6 = "uniform block of text" - handles two-line
                # stacked plates properly. psm 7/8/13 all assume a
                # single line, which mangles stacked text.
                for psm in [6, 7, 8, 13]:

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
        #
        # FIX: kernel height increased from 5 to 15. Two-line
        # stacked plates (common on autos/two-wheelers) have a gap
        # between the two rows of text that was splitting the
        # yellow mask into two separate blobs instead of one - each
        # too small individually to survive area/size filters.
        # Taller closing bridges that gap.
        kernel = cv2.getStructuringElement(
            cv2.MORPH_RECT,
            (7, 15),
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

            # ---------------------------------------------------
            # FIX: Indian auto-rickshaw / two-wheeler plates are
            # often TWO-LINE stacked plates (e.g. "MH12N" over
            # "W8556"), which are much closer to square than the
            # elongated single-line car plates this filter used to
            # assume. The old floor of 2.0 rejected these outright
            # before color/shape scoring even ran. Lowered to 1.1
            # to admit them - the edge-density check below is what
            # keeps this from letting solid yellow trim panels back
            # in.
            # ---------------------------------------------------

            if aspect_ratio < 1.1 or aspect_ratio > 7.0:
                continue

            # Reject enormous yellow regions.
            if area > image_width * image_height * 0.03:
                continue

            # Prefer lower portion of vehicle images.
            relative_y = y / float(image_height)

            # ---------------------------------------------------
            # FIX: raised from 0.35 to 0.55.
            #
            # Real-world test images show ad banners/wraps on
            # vehicles (autos, trucks) occupying roughly the top
            # half of the frame, with the actual plate sitting much
            # lower, near the grille/bumper. 0.35 let banner text
            # lines through. Tune this if your fleet's plates ever
            # sit higher in frame than this assumes.
            # ---------------------------------------------------

            if relative_y < 0.55:
                continue

            # ---------------------------------------------------
            # FIX: fill-ratio / solidity check.
            #
            # A real plate is a near-solid rectangle - the yellow
            # mask fills almost the entire bounding box. Signage,
            # posters, and printed text on a yellow background
            # (e.g. "RECRUITERS", "ANIMATIONS") have much lower
            # fill density because of letter spacing and gaps.
            # Without this check, those pass through as valid
            # "plate-shaped" candidates.
            # ---------------------------------------------------

            contour_area = cv2.contourArea(contour)

            if contour_area <= 0:
                continue

            fill_ratio = contour_area / float(area)

            # FIX: lowered from 0.55 to 0.35. Two-line plates have
            # two rows of text (more gaps/holes in the yellow mask)
            # than a single-line plate, so their natural fill ratio
            # is lower even when they ARE the real plate. 0.55 was
            # likely rejecting the actual plate outright.
            if fill_ratio < 0.35:
                logger.debug(
                    "Rejected yellow candidate: low fill_ratio=%.2f "
                    "bbox=(%d,%d,%d,%d)",
                    fill_ratio, x, y, w, h,
                )
                continue

            # ---------------------------------------------------
            # FIX: edge-density check.
            #
            # Loosening the aspect ratio above would otherwise let
            # solid yellow trim panels (mudguards, bumpers) back in,
            # since they're also solid, near-square-ish chunks of
            # yellow. The key difference: a real plate has visible
            # black character strokes inside it, so it has SOME
            # internal edges. A blank painted panel has almost none.
            # An overly busy region (ad wrap, textured background)
            # has too many. This band excludes both extremes.
            # ---------------------------------------------------

            roi_gray = cv2.cvtColor(
                image_bgr[y:y + h, x:x + w],
                cv2.COLOR_BGR2GRAY,
            )

            roi_edges = cv2.Canny(roi_gray, 50, 150)

            edge_density = cv2.countNonZero(roi_edges) / float(w * h)

            # FIX: upper bound raised from 0.35 to 0.5. Two rows of
            # characters produce more edge pixels than one row, so
            # a real two-line plate can legitimately have higher
            # edge density than the original single-line assumption.
            if edge_density < 0.02 or edge_density > 0.5:
                logger.debug(
                    "Rejected yellow candidate: edge_density=%.3f "
                    "bbox=(%d,%d,%d,%d)",
                    edge_density, x, y, w, h,
                )
                continue

            logger.info(
                "Yellow candidate survived: bbox=(%d,%d,%d,%d) "
                "aspect=%.2f fill_ratio=%.2f edge_density=%.3f",
                x, y, w, h, aspect_ratio, fill_ratio, edge_density,
            )

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

            # Reward higher fill ratio (more plate-like solidity).
            score += round(fill_ratio * 2, 2)

            yellow_candidates.append({
                "x": x,
                "y": y,
                "w": w,
                "h": h,
                "source": "yellow",
                "score": score,
                "fill_ratio": round(fill_ratio, 2),
                "edge_density": round(edge_density, 3),
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

            # FIX: raised from 0.35 to 0.55 - see matching comment
            # in the yellow-candidate loop above. This is what was
            # letting ad-banner text lines (e.g. "CREATIVITY") in as
            # plate-shaped candidates.
            if relative_y < 0.55:
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

        # Log every surviving candidate's geometry so we can see WHERE
        # the pipeline is looking without needing DEBUG-level logs.
        for i, c in enumerate(candidates):
            logger.info(
                "Candidate %d: source=%s bbox=(x=%d,y=%d,w=%d,h=%d) "
                "aspect=%.2f score=%s",
                i, c["source"], c["x"], c["y"], c["w"], c["h"],
                c["w"] / float(c["h"]) if c["h"] else 0,
                c.get("score"),
            )

        # Dump every surviving candidate crop for visual inspection
        # when PLATE_DEBUG=1. No-op otherwise.
        for i, candidate in enumerate(candidates):
            _save_debug_crop(image_bgr, candidate, i, image_tag)

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
            padding_y = int(h * 0.35)

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

                logger.info(
                    "OCR text: candidate=%d source=%s variant=%s -> %r",
                    candidates.index(candidate),
                    candidate["source"],
                    result["source"],
                    text,
                )

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
        # 5. OCR found text but no valid plate via candidates.
        #    Fallback: just OCR the bottom third of the whole image
        #    directly. No color/contour tuning - brute force, but
        #    the regex is specific enough to filter noise out of it.
        # =========================================================

        combined_text = "\n".join(
            all_ocr_text
        )

        fallback_y = int(image_height * 0.65)
        fallback_crop = image_bgr[fallback_y:image_height, 0:image_width]

        if fallback_crop.size != 0:

            fallback_ocr = run_ocr(fallback_crop)

            for result in fallback_ocr:

                text = result["text"]
                combined_text += "\n" + text

                logger.info(
                    "OCR text: candidate=fallback_bottom_strip "
                    "variant=%s -> %r",
                    result["source"],
                    text,
                )

                plate = _find_plate(text)

                if plate:

                    logger.info(
                        "Plate detected: %s source=fallback_bottom_strip",
                        plate,
                    )

                    return {
                        "check": "plate_format",
                        "ocr_available": True,
                        "plate_detected": True,
                        "extracted_text": plate,
                        "is_valid_format": True,
                        "candidate_regions": len(candidates),
                        "detection_source": "fallback_bottom_strip",
                        "raw_text": text[:500],
                    }

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