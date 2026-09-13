"""
utils/parsers.py

Safe, dependency-light parsing for every file type Root Cause AI accepts:
CSV, PDF, DOCX (Word), plain-text logs, freeform text (complaint logs), and
.eml email files.

Every public parser raises ValueError with a human-readable message on
failure rather than letting a raw exception/stack trace bubble up to the UI.
"""

import io
import re
import email
from email import policy

import pandas as pd

try:
    import pdfplumber
except ImportError:  # pragma: no cover
    pdfplumber = None

try:
    import docx  # python-docx
except ImportError:  # pragma: no cover
    docx = None


# =============================================================================
# Regex patterns
# =============================================================================

# Matches lines like: [2024-03-15 09:12:03] ERROR - message text
#                      2024-03-15T09:12:03,451 WARN: message text
LOG_LINE_PATTERN = re.compile(
    r"^\[?(?P<timestamp>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?)\]?\s*"
    r"[-\s]*\[?(?P<level>DEBUG|INFO|WARN(?:ING)?|ERROR|CRITICAL|FATAL)\]?[:\s-]*"
    r"(?P<message>.*)$",
    re.IGNORECASE,
)

DATE_PREFIX_PATTERN = re.compile(r"^\[?(\d{4}-\d{2}-\d{2})\]?", re.MULTILINE)


# =============================================================================
# Individual format parsers
# =============================================================================

def parse_csv(buffer) -> pd.DataFrame:
    """Parse a CSV from a file-like object or bytes buffer into a DataFrame."""
    try:
        return pd.read_csv(buffer)
    except UnicodeDecodeError:
        buffer.seek(0)
        return pd.read_csv(buffer, encoding="latin-1")
    except Exception as e:
        raise ValueError(f"Could not parse this file as CSV: {e}")


def parse_pdf(file_bytes: bytes) -> str:
    """Extract plain text from a PDF, page by page, using pdfplumber."""
    if pdfplumber is None:
        raise ValueError(
            "pdfplumber is not installed. Add it to requirements.txt to enable PDF parsing."
        )
    try:
        chunks = []
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for i, page in enumerate(pdf.pages):
                page_text = page.extract_text() or ""
                chunks.append(f"--- Page {i + 1} ---\n{page_text}".strip())
        text = "\n\n".join(chunks).strip()
        if not text:
            raise ValueError("No extractable text was found (this may be a scanned/image-only PDF).")
        return text
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"Could not extract text from this PDF: {e}")


def parse_docx(file_bytes: bytes) -> str:
    """Extract paragraph and table text from a Word (.docx) document."""
    if docx is None:
        raise ValueError(
            "python-docx is not installed. Add it to requirements.txt to enable Word file parsing."
        )
    try:
        document = docx.Document(io.BytesIO(file_bytes))
        paragraphs = [p.text for p in document.paragraphs if p.text.strip()]
        table_lines = []
        for table in document.tables:
            for row in table.rows:
                row_text = " | ".join(cell.text.strip() for cell in row.cells)
                if row_text.strip(" |"):
                    table_lines.append(row_text)
        text = "\n".join(paragraphs + table_lines).strip()
        if not text:
            raise ValueError("No readable text was found in this Word document.")
        return text
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"Could not extract text from this Word document: {e}")


def parse_txt(file_bytes: bytes) -> str:
    """Decode raw bytes to text, tolerating non-UTF-8 encodings."""
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return file_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    return file_bytes.decode("utf-8", errors="replace")


def parse_email_eml(file_bytes: bytes) -> dict:
    """Parse an .eml file into a structured dict with headers + plain-text body."""
    try:
        msg = email.message_from_bytes(file_bytes, policy=policy.default)
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    body += part.get_content()
        else:
            body = msg.get_content()
        return {
            "from": msg.get("From", "Unknown"),
            "to": msg.get("To", "Unknown"),
            "subject": msg.get("Subject", "(no subject)"),
            "date": msg.get("Date", "Unknown"),
            "body": (body or "").strip(),
        }
    except Exception as e:
        raise ValueError(f"Could not parse this .eml file: {e}")


def parse_log_lines(raw_text: str) -> list:
    """Split a raw log dump into structured {timestamp, level, message} events."""
    events = []
    for i, line in enumerate(raw_text.splitlines()):
        line = line.strip()
        if not line:
            continue
        match = LOG_LINE_PATTERN.match(line)
        if match:
            events.append({
                "line_number": i + 1,
                "timestamp": match.group("timestamp"),
                "level": match.group("level").upper().replace("WARNING", "WARN"),
                "message": match.group("message").strip(),
            })
        else:
            events.append({
                "line_number": i + 1,
                "timestamp": None,
                "level": "UNKNOWN",
                "message": line,
            })
    return events


def parse_complaints_text(raw_text: str) -> list:
    """
    Split a freeform grievance/complaint log into individual entries.
    Prefers date-prefixed entries (e.g. "[2024-03-15] ..."); falls back to
    blank-line-separated blocks when no dates are detectable.
    """
    matches = list(DATE_PREFIX_PATTERN.finditer(raw_text))
    entries = []
    if len(matches) >= 2:
        for idx, m in enumerate(matches):
            start = m.start()
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(raw_text)
            block = raw_text[start:end].strip()
            entries.append({"date": m.group(1), "text": block})
    else:
        blocks = [b.strip() for b in raw_text.split("\n\n") if b.strip()]
        entries = [{"date": None, "text": b} for b in blocks]
    return entries


# =============================================================================
# Dispatcher
# =============================================================================

def detect_file_kind(filename: str) -> str:
    name = filename.lower()
    if name.endswith(".csv"):
        return "csv"
    if name.endswith(".pdf"):
        return "pdf"
    if name.endswith(".docx"):
        return "docx"
    if name.endswith(".eml"):
        return "eml"
    if name.endswith(".txt") and ("log" in name or "error" in name):
        return "log"
    if name.endswith(".txt"):
        return "txt"
    return "unknown"


def parse_uploaded_file(uploaded_file) -> dict:
    """
    Master dispatcher for any file the UI accepts.

    `uploaded_file` only needs a `.name` attribute and a `.read()` method
    returning bytes — this matches both Streamlit's UploadedFile and a
    plain local-file wrapper (see app.py's sample-data loader).

    Returns:
        {
          "kind": "csv"|"pdf"|"docx"|"eml"|"log"|"txt",
          "filename": str,
          "dataframe": pd.DataFrame | None,
          "raw_text": str | None,
          "structured": list | dict | None,
        }

    Raises:
        ValueError with a user-facing message on any failure.
    """
    filename = getattr(uploaded_file, "name", "uploaded_file")
    kind = detect_file_kind(filename)
    raw_bytes = uploaded_file.read()

    if not raw_bytes:
        raise ValueError(f"'{filename}' is empty.")

    result = {"kind": kind, "filename": filename, "dataframe": None, "raw_text": None, "structured": None}

    if kind == "csv":
        result["dataframe"] = parse_csv(io.BytesIO(raw_bytes))
        result["raw_text"] = result["dataframe"].head(50).to_csv(index=False)

    elif kind == "pdf":
        result["raw_text"] = parse_pdf(raw_bytes)

    elif kind == "docx":
        result["raw_text"] = parse_docx(raw_bytes)

    elif kind == "eml":
        structured = parse_email_eml(raw_bytes)
        result["structured"] = structured
        result["raw_text"] = (
            f"From: {structured['from']}\nTo: {structured['to']}\n"
            f"Subject: {structured['subject']}\nDate: {structured['date']}\n\n{structured['body']}"
        )

    elif kind == "log":
        text = parse_txt(raw_bytes)
        result["raw_text"] = text
        result["structured"] = parse_log_lines(text)

    elif kind == "txt":
        text = parse_txt(raw_bytes)
        result["raw_text"] = text
        result["structured"] = parse_complaints_text(text)

    else:
        raise ValueError(
            f"'{filename}' has an unsupported file type. Root Cause AI accepts "
            f"CSV, PDF, DOCX, .eml, and .txt files."
        )

    return result
