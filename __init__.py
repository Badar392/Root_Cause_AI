"""
Root Cause AI — utility package.

Modules:
    parsers      — file parsing for CSV, PDF, DOCX, TXT, logs, and .eml emails
    groq_client  — Groq API wrapper and root-cause analysis prompts
    timeline     — event/incident timeline construction and Plotly rendering
    report       — Markdown and PDF report export
"""

from . import parsers, groq_client, timeline, report

__all__ = ["parsers", "groq_client", "timeline", "report"]
