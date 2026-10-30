"""PaperPilot configuration."""
import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

DATA_DIR = PROJECT_ROOT / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
CHROMA_DIR = DATA_DIR / "chroma"
DB_PATH = DATA_DIR / "papers.db"

# Set DB_BACKEND=mysql after filling MYSQL_* in .env.
DB_BACKEND = os.getenv("DB_BACKEND", "sqlite").lower()
MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "paperpilot")
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")

for directory in (DATA_DIR, UPLOAD_DIR, CHROMA_DIR):
    directory.mkdir(parents=True, exist_ok=True)

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

EMBEDDING_MODEL = os.getenv(
    "EMBEDDING_MODEL",
    r"E:\all-in-rag\models\bge-m3",
)
EMBEDDING_DEVICE = os.getenv("EMBEDDING_DEVICE", "")

RERANK_ENABLED = os.getenv("RERANK_ENABLED", "true").lower() == "true"
RERANK_MODEL = os.getenv(
    "RERANK_MODEL",
    r"E:\all-in-rag\models\bge-reranker-base",
)
RERANK_DEVICE = os.getenv("RERANK_DEVICE", "cpu")
RERANK_WINDOW_ENABLED = os.getenv("RERANK_WINDOW_ENABLED", "false").lower() == "true"
RERANK_SECTION_PREFIX = os.getenv("RERANK_SECTION_PREFIX", "false").lower() == "true"
RERANK_WINDOW_CHARS = int(os.getenv("RERANK_WINDOW_CHARS", "600"))
RERANK_WINDOW_OVERLAP = int(os.getenv("RERANK_WINDOW_OVERLAP", "80"))
RERANK_MAX_WINDOWS = int(os.getenv("RERANK_MAX_WINDOWS", "2"))
RRF_DENSE_WEIGHT = float(os.getenv("RRF_DENSE_WEIGHT", "0.5"))
RRF_LEXICAL_WEIGHT = float(os.getenv("RRF_LEXICAL_WEIGHT", "0.5"))

# If citation support falls below this, do not show the generated answer.
CITATION_SUPPORT_THRESHOLD = float(os.getenv("CITATION_SUPPORT_THRESHOLD", "0.35"))

OCR_ENABLED = os.getenv("OCR_ENABLED", "true").lower() == "true"
OCR_MIN_CHARS = int(os.getenv("OCR_MIN_CHARS", "40"))
OCR_DPI = int(os.getenv("OCR_DPI", "180"))

CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "800"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "100"))

# Rewrite is useful for future work, but keep section filtering opt-in:
# recall@18 showed section filtering dropped recall@5 from 1.00 to 0.78.
QUERY_REWRITE_ENABLED = os.getenv("QUERY_REWRITE_ENABLED", "false").lower() == "true"
SECTION_FILTER_ENABLED = os.getenv("SECTION_FILTER_ENABLED", "false").lower() == "true"

# pymupdf4llm gives better reading order/headings than plain text extraction.
# Set PDF_PARSER=pymupdf to force the lightweight fallback.
PDF_PARSER = os.getenv("PDF_PARSER", "pymupdf4llm").lower()
MAX_PAPERS = int(os.getenv("MAX_PAPERS", "30"))
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "50"))

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".md"}
