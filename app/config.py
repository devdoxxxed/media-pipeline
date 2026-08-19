import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR}/media_pipeline.db")
UPLOAD_DIR = os.getenv("UPLOAD_DIR", os.path.join(BASE_DIR, "uploads"))
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "10"))
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

BLUR_THRESHOLD = float(os.getenv("BLUR_THRESHOLD", "100.0"))       # Laplacian variance below this = blurry
LOW_LIGHT_THRESHOLD = float(os.getenv("LOW_LIGHT_THRESHOLD", "60.0"))  # mean brightness below this = low light
DUPLICATE_HASH_DISTANCE = int(os.getenv("DUPLICATE_HASH_DISTANCE", "5"))  # hamming distance <= this = duplicate

# Indian vehicle plate: e.g. KA01AB1234 / KA 01 AB 1234
PLATE_REGEX = r"^[A-Z]{2}[\s-]?[0-9]{1,2}[\s-]?[A-Z]{1,3}[\s-]?[0-9]{4}$"

os.makedirs(UPLOAD_DIR, exist_ok=True)
