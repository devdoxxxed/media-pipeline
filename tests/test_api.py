"""
Lightweight end-to-end smoke test (not a unit test suite).
Requires the server to be running: uvicorn app.main:app --reload
Usage: python tests/test_api.py
"""
import io
import sys
import time
import numpy as np
import cv2
import requests

BASE_URL = "http://localhost:8000"


def make_test_image() -> bytes:
    img = np.random.randint(80, 200, (300, 400, 3), dtype="uint8")
    cv2.rectangle(img, (20, 20), (380, 100), (255, 255, 255), -1)
    cv2.putText(img, "KA05MZ4521", (30, 80), cv2.FONT_HERSHEY_SIMPLEX, 1.3, (0, 0, 0), 3)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return buf.tobytes()


def main():
    print("1. Health check")
    r = requests.get(f"{BASE_URL}/health")
    assert r.status_code == 200, r.text
    print("   OK")

    print("2. Upload image")
    files = {"file": ("test_vehicle.jpg", make_test_image(), "image/jpeg")}
    r = requests.post(f"{BASE_URL}/upload", files=files)
    assert r.status_code == 202, r.text
    job_id = r.json()["id"]
    print(f"   OK - job_id={job_id}")

    print("3. Poll status until completed (max 10s)")
    for _ in range(20):
        r = requests.get(f"{BASE_URL}/status/{job_id}")
        assert r.status_code == 200, r.text
        status = r.json()["status"]
        if status in ("completed", "failed"):
            break
        time.sleep(0.5)
    print(f"   Final status: {status}")
    assert status == "completed", f"Job did not complete: {status}"

    print("4. Fetch results")
    r = requests.get(f"{BASE_URL}/results/{job_id}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "checks" in body["results"] or set(body["results"].keys()) >= {
        "blur", "brightness", "duplicate", "plate_format"
    }
    print(f"   OK - verdict={body['verdict']}")

    print("5. Non-existent job -> 404")
    r = requests.get(f"{BASE_URL}/status/does-not-exist")
    assert r.status_code == 404, r.text
    print("   OK")

    print("\nAll smoke tests passed.")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        print(f"\nFAILED: {e}", file=sys.stderr)
        sys.exit(1)
