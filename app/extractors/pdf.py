import fitz  # pymupdf
import logging

logger = logging.getLogger(__name__)


def extract_pdf(pdf_bytes: bytes) -> str:
    """Extract text from a PDF. Returns empty string on any failure."""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        if doc.is_encrypted:
            logger.warning("PDF is encrypted/password-protected — cannot extract text")
            return "[PDF is password-protected — text extraction not possible]"
        pages = [page.get_text() for page in doc]
        return "\n\n".join(pages)
    except Exception as e:
        logger.exception("PDF extraction failed: %s", e)
        return ""
