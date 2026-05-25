import os
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

from settings import settings

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUTS_DIR = Path(settings.output_dir) if settings.output_dir else (BASE_DIR / "outputs")


def ensure_outputs_dir():
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)


def generate_job_id() -> str:
    return datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")


def create_job_dir(job_id: str) -> Path:
    job_dir = OUTPUTS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    return job_dir


def get_job_dir(job_id: str) -> Path:
    return OUTPUTS_DIR / job_id


def get_index_html_path(job_id: str) -> Path:
    return OUTPUTS_DIR / job_id / "index.html"


def get_logs_path(job_id: str) -> Path:
    return OUTPUTS_DIR / job_id / "logs.txt"


def check_index_html_exists(job_id: str) -> bool:
    return get_index_html_path(job_id).is_file()


def get_standalone_html_path(job_id: str) -> Path:
    return OUTPUTS_DIR / job_id / "standalone.html"


def check_standalone_exists(job_id: str) -> bool:
    return get_standalone_html_path(job_id).is_file()


def create_zip(job_id: str) -> Path:
    job_dir = get_job_dir(job_id)
    zip_path = OUTPUTS_DIR / f"{job_id}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(job_dir):
            for file in files:
                file_path = Path(root) / file
                arcname = file_path.relative_to(job_dir)
                zf.write(file_path, arcname)
    return zip_path


def zip_exists(job_id: str) -> bool:
    return (OUTPUTS_DIR / f"{job_id}.zip").is_file()


def get_zip_path(job_id: str) -> Path:
    return OUTPUTS_DIR / f"{job_id}.zip"
