import os


class Config:
    # Flask configuration
    SECRET_KEY = os.environ.get(
        "SECRET_KEY",
        "lms_secret_key_2026"
    )

    # MySQL Database configuration
    DB_HOST = os.environ.get("DB_HOST", "localhost")
    DB_USER = os.environ.get("DB_USER", "root")
    DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
    DB_NAME = os.environ.get("DB_NAME", "lms_db")

    # Upload configuration
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))

    UPLOAD_FOLDER = os.path.join(
        BASE_DIR,
        "static",
        "uploads"
    )

    MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10 MB

    # Allowed file extensions
    ALLOWED_EXTENSIONS = {
        "pdf",
        "docx",
        "doc",
        "png",
        "jpg",
        "jpeg",
        "zip",
        "pptx"
    }


def allowed_file(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower()
        in Config.ALLOWED_EXTENSIONS
    )