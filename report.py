"""
utils/report.py

Turns a completed root-cause analysis (the dict returned by
groq_client.analyze_root_cause) into a downloadable Markdown string or a
polished PDF, for the app's "Export Reports" tab.

Supports two output modes:
  - "full":      the complete report (cover page + every section/table).
  - "executive": a condensed, best-effort one-page summary for stakeholders
                 who just need the headline finding and the recommended
                 next steps.

Both the Markdown and PDF builders also accept an optional company name and
(for PDF) a logo image, rendered on the cover page / summary header.
"""

import io
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
    Image, PageBreak,
)


_SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def _severity_sort_key(item: dict, field: str = "severity") -> int:
    return _SEVERITY_RANK.get(str(item.get(field, "")).strip().lower(), 4)


def _top_n(items: list, n: int, field: str = "severity") -> list:
    if not items:
        return []
    return sorted(items, key=lambda it: _severity_sort_key(it, field))[:n]


# =============================================================================
# Markdown export
# =============================================================================

def generate_markdown_report(
    analysis: dict,
    filenames: list,
    generated_at: datetime = None,
    company_name: str = None,
    mode: str = "full",
) -> str:
    """Build a clean Markdown report string from the AI analysis dict.

    mode="full": every section, in full.
    mode="executive": a condensed one-pager — summary, impact, the single
        highest-severity anomaly/trigger event, and the top 3 actions.
    """
    generated_at = generated_at or datetime.now()
    title = "# Root Cause AI — Executive Summary" if mode == "executive" else "# Root Cause AI — Analysis Report"
    lines = [title]
    if company_name:
        lines.append(f"\n**{company_name}**")
    lines.append(f"\n*Generated: {generated_at.strftime('%Y-%m-%d %H:%M')}*")
    lines.append(f"\n**Source files:** {', '.join(filenames) if filenames else 'N/A'}\n")

    if not analysis or analysis.get("_parse_failed"):
        lines.append("## Note\n")
        lines.append("The AI analysis could not be generated or fully parsed for this run.\n")
        if analysis and analysis.get("_raw_text") and mode == "full":
            lines.append("### Raw model output\n")
            lines.append("```\n" + str(analysis["_raw_text"]) + "\n```")
        return "\n".join(lines)

    lines.append("## Summary\n")
    lines.append(str(analysis.get("summary", "")) + "\n")

    if analysis.get("impact_assessment"):
        ia = analysis["impact_assessment"]
        lines.append("## Impact Assessment\n")
        lines.append(f"- **Category:** {ia.get('category', '')}")
        lines.append(f"- **Severity:** {ia.get('severity', '')}")
        lines.append(f"- **Justification:** {ia.get('justification', '')}\n")

    anomalies = analysis.get("anomalies") or []
    if mode == "executive":
        anomalies = _top_n(anomalies, 1)
    if anomalies:
        heading = "## Top Anomaly\n" if mode == "executive" else "## Anomalies Detected\n"
        lines.append(heading)
        for a in anomalies:
            lines.append(f"- **[{a.get('severity', 'Unknown')}]** {a.get('description', '')}")
            if a.get("evidence"):
                lines.append(f"  - Evidence: {a['evidence']}")
        lines.append("")

    trigger_events = analysis.get("trigger_events") or []
    if mode == "executive":
        trigger_events = _top_n(trigger_events, 1, field="confidence")
    if trigger_events:
        heading = "## Primary Trigger Event\n" if mode == "executive" else "## Trigger Events\n"
        lines.append(heading)
        for t in trigger_events:
            lines.append(
                f"- **{t.get('event', '')}** ({t.get('timestamp_or_period', 'unknown time')}) "
                f"— Confidence: {t.get('confidence', 'Unknown')}"
            )
            if t.get("evidence"):
                lines.append(f"  - Evidence: {t['evidence']}")
        lines.append("")

    actions = analysis.get("recommended_actions") or []
    if mode == "executive":
        actions = _top_n(actions, 3, field="priority")
    if actions:
        lines.append("## Recommended Actions\n")
        for r in actions:
            lines.append(f"- **[{r.get('priority', 'Unknown')}]** {r.get('action', '')}")
            if r.get("rationale") and mode == "full":
                lines.append(f"  - Rationale: {r['rationale']}")
        lines.append("")

    if mode == "executive":
        return "\n".join(lines)

    if analysis.get("counter_hypotheses"):
        lines.append("## Devil's Advocate — Counter-Hypothesis Verification\n")
        for c in analysis["counter_hypotheses"]:
            lines.append(
                f"- **Original hypothesis:** {c.get('original_hypothesis', '')}\n"
                f"  - **Alternative explanation:** {c.get('alternative_explanation', '')}\n"
                f"  - **Falsification risk:** {c.get('falsification_risk_score', '')}"
            )
        lines.append("")

    return "\n".join(lines)


# =============================================================================
# PDF export
# =============================================================================

def _report_styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="RCTitle", fontSize=22, leading=26, spaceAfter=6,
        textColor=colors.HexColor("#1a1a2e"), fontName="Helvetica-Bold",
    ))
    styles.add(ParagraphStyle(
        name="RCMeta", fontSize=9.5, leading=13, textColor=colors.HexColor("#555555"),
    ))
    styles.add(ParagraphStyle(
        name="RCHeading", fontSize=14, leading=18, spaceBefore=16, spaceAfter=8,
        textColor=colors.HexColor("#0f3460"), fontName="Helvetica-Bold",
    ))
    styles.add(ParagraphStyle(
        name="RCBody", fontSize=10, leading=14.5, textColor=colors.HexColor("#222222"),
    ))
    styles.add(ParagraphStyle(
        name="RCCell", fontSize=9, leading=12.5, textColor=colors.HexColor("#222222"),
    ))
    styles.add(ParagraphStyle(
        name="RCCompany", fontSize=13, leading=17, textColor=colors.HexColor("#0f3460"),
        fontName="Helvetica-Bold",
    ))
    styles.add(ParagraphStyle(
        name="RCCoverTitle", fontSize=30, leading=34, textColor=colors.HexColor("#1a1a2e"),
        fontName="Helvetica-Bold",
    ))
    styles.add(ParagraphStyle(
        name="RCCoverSubtitle", fontSize=15, leading=19, textColor=colors.HexColor("#555555"),
    ))
    styles.add(ParagraphStyle(
        name="RCExecTitle", fontSize=18, leading=22, spaceAfter=4,
        textColor=colors.HexColor("#1a1a2e"), fontName="Helvetica-Bold",
    ))
    return styles


def _scaled_logo(logo_bytes, max_width=2.2 * inch, max_height=1.3 * inch):
    """Load logo bytes into a size-capped ReportLab Image flowable, or None."""
    if not logo_bytes:
        return None
    try:
        img = Image(io.BytesIO(logo_bytes))
        iw, ih = img.imageWidth, img.imageHeight
        if not iw or not ih:
            return None
        scale = min(max_width / iw, max_height / ih, 1.0)
        img.drawWidth = iw * scale
        img.drawHeight = ih * scale
        return img
    except Exception:
        # A corrupt/unsupported image should never break report generation.
        return None


def _make_table(data, col_widths=None):
    styles = _report_styles()
    wrapped = [[Paragraph(str(cell), styles["RCCell"]) for cell in row] for row in data]
    table = Table(wrapped, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f3460")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f6fb")]),
    ]))
    return table


def _build_cover_page(story, styles, generated_at, filenames, logo_bytes, company_name):
    """Prepend a dedicated cover page (logo + company + title + metadata)."""
    logo_img = _scaled_logo(logo_bytes)
    if logo_img:
        story.append(logo_img)
        story.append(Spacer(1, 16))
    if company_name:
        story.append(Paragraph(company_name, styles["RCCompany"]))
    story.append(Spacer(1, 70))
    story.append(Paragraph("Root Cause AI", styles["RCCoverTitle"]))
    story.append(Paragraph("Root Cause Analysis Report", styles["RCCoverSubtitle"]))
    story.append(Spacer(1, 50))
    story.append(HRFlowable(width="40%", color=colors.HexColor("#0f3460"), thickness=1.2))
    story.append(Spacer(1, 14))
    story.append(Paragraph(f"Generated: {generated_at.strftime('%B %d, %Y at %H:%M')}", styles["RCMeta"]))
    story.append(Paragraph(
        f"Source files analyzed: {len(filenames)} "
        f"({', '.join(filenames)})" if filenames else "Source files analyzed: 0",
        styles["RCMeta"],
    ))
    story.append(PageBreak())


def _build_header_block(story, styles, generated_at, filenames, logo_bytes, company_name, heading_text):
    """Compact inline header used for the one-page executive summary (no page break)."""
    if logo_bytes or company_name:
        logo_img = _scaled_logo(logo_bytes, max_width=1.1 * inch, max_height=0.6 * inch)
        header_cells = [[
            logo_img if logo_img else "",
            Paragraph(company_name or "", styles["RCCompany"]),
        ]]
        header_table = Table(header_cells, colWidths=[1.3 * inch, 4.7 * inch])
        header_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(header_table)
    story.append(Paragraph(heading_text, styles["RCExecTitle"]))
    story.append(Paragraph(f"Generated: {generated_at.strftime('%Y-%m-%d %H:%M')}", styles["RCMeta"]))
    story.append(Paragraph(f"Source files: {', '.join(filenames) if filenames else 'N/A'}", styles["RCMeta"]))
    story.append(Spacer(1, 8))
    story.append(HRFlowable(width="100%", color=colors.HexColor("#0f3460"), thickness=1.2))
    story.append(Spacer(1, 8))


def _build_executive_pdf(analysis, filenames, generated_at, logo_bytes, company_name, styles) -> bytes:
    """Best-effort single-page PDF: summary, impact, top anomaly/trigger, top 3 actions."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter,
        topMargin=0.6 * inch, bottomMargin=0.6 * inch,
        leftMargin=0.7 * inch, rightMargin=0.7 * inch,
    )
    story = []
    _build_header_block(story, styles, generated_at, filenames, logo_bytes, company_name,
                         "Executive Summary")

    if not analysis or analysis.get("_parse_failed"):
        story.append(Paragraph(
            "The AI analysis could not be generated or fully parsed for this report.",
            styles["RCBody"],
        ))
        doc.build(story)
        buffer.seek(0)
        return buffer.getvalue()

    story.append(Paragraph("Summary", styles["RCHeading"]))
    story.append(Paragraph(str(analysis.get("summary", "")), styles["RCBody"]))

    ia = analysis.get("impact_assessment") or {}
    if ia:
        story.append(Paragraph("Impact Assessment", styles["RCHeading"]))
        story.append(Paragraph(
            f"<b>{ia.get('category', '')}</b> — Severity: <b>{ia.get('severity', '')}</b>. "
            f"{ia.get('justification', '')}",
            styles["RCBody"],
        ))

    top_anomaly = _top_n(analysis.get("anomalies") or [], 1)
    if top_anomaly:
        a = top_anomaly[0]
        story.append(Paragraph("Top Anomaly", styles["RCHeading"]))
        story.append(Paragraph(
            f"[{a.get('severity', 'Unknown')}] {a.get('description', '')}", styles["RCBody"],
        ))

    top_trigger = _top_n(analysis.get("trigger_events") or [], 1, field="confidence")
    if top_trigger:
        t = top_trigger[0]
        story.append(Paragraph("Primary Trigger Event", styles["RCHeading"]))
        story.append(Paragraph(
            f"{t.get('event', '')} ({t.get('timestamp_or_period', 'unknown time')}) "
            f"— Confidence: {t.get('confidence', 'Unknown')}",
            styles["RCBody"],
        ))

    top_actions = _top_n(analysis.get("recommended_actions") or [], 3, field="priority")
    if top_actions:
        story.append(Paragraph("Top Recommended Actions", styles["RCHeading"]))
        data = [["Priority", "Action"]]
        for r in top_actions:
            data.append([r.get("priority", ""), r.get("action", "")])
        story.append(_make_table(data, col_widths=[1.0 * inch, 4.9 * inch]))

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()


def generate_pdf_report(
    analysis: dict,
    filenames: list,
    generated_at: datetime = None,
    logo_bytes: bytes = None,
    company_name: str = None,
    mode: str = "full",
) -> bytes:
    """Build a polished PDF report and return it as raw bytes, ready for st.download_button.

    mode="full": cover page (logo/company/title/date) followed by every section.
    mode="executive": a best-effort single-page summary — no cover page, just a
        compact header, so the whole thing fits on one page.
    """
    generated_at = generated_at or datetime.now()
    styles = _report_styles()

    if mode == "executive":
        return _build_executive_pdf(analysis, filenames, generated_at, logo_bytes, company_name, styles)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter,
        topMargin=0.75 * inch, bottomMargin=0.75 * inch,
        leftMargin=0.75 * inch, rightMargin=0.75 * inch,
    )
    story = []
    _build_cover_page(story, styles, generated_at, filenames, logo_bytes, company_name)

    story.append(Paragraph("Root Cause AI — Analysis Report", styles["RCTitle"]))
    story.append(Paragraph(f"Generated: {generated_at.strftime('%Y-%m-%d %H:%M')}", styles["RCMeta"]))
    story.append(Paragraph(f"Source files: {', '.join(filenames) if filenames else 'N/A'}", styles["RCMeta"]))
    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", color=colors.HexColor("#0f3460"), thickness=1.2))
    story.append(Spacer(1, 10))

    if not analysis or analysis.get("_parse_failed"):
        story.append(Paragraph("Note", styles["RCHeading"]))
        story.append(Paragraph(
            "The AI analysis could not be generated or fully parsed for this report.",
            styles["RCBody"],
        ))
        doc.build(story)
        buffer.seek(0)
        return buffer.getvalue()

    story.append(Paragraph("Summary", styles["RCHeading"]))
    story.append(Paragraph(str(analysis.get("summary", "")), styles["RCBody"]))

    if analysis.get("anomalies"):
        story.append(Paragraph("Anomalies Detected", styles["RCHeading"]))
        data = [["Severity", "Description", "Evidence"]]
        for a in analysis["anomalies"]:
            data.append([a.get("severity", ""), a.get("description", ""), a.get("evidence", "")])
        story.append(_make_table(data, col_widths=[0.9 * inch, 2.4 * inch, 3.1 * inch]))

    if analysis.get("trigger_events"):
        story.append(Paragraph("Trigger Events", styles["RCHeading"]))
        data = [["Event", "Time", "Confidence", "Evidence"]]
        for t in analysis["trigger_events"]:
            data.append([t.get("event", ""), t.get("timestamp_or_period", ""),
                        t.get("confidence", ""), t.get("evidence", "")])
        story.append(_make_table(data, col_widths=[1.6 * inch, 1.1 * inch, 0.9 * inch, 2.8 * inch]))

    if analysis.get("impact_assessment"):
        ia = analysis["impact_assessment"]
        story.append(Paragraph("Impact Assessment", styles["RCHeading"]))
        story.append(Paragraph(f"<b>Category:</b> {ia.get('category', '')}", styles["RCBody"]))
        story.append(Paragraph(f"<b>Severity:</b> {ia.get('severity', '')}", styles["RCBody"]))
        story.append(Paragraph(f"<b>Justification:</b> {ia.get('justification', '')}", styles["RCBody"]))
        story.append(Spacer(1, 6))

    if analysis.get("recommended_actions"):
        story.append(Paragraph("Recommended Actions", styles["RCHeading"]))
        data = [["Priority", "Action", "Rationale"]]
        for r in analysis["recommended_actions"]:
            data.append([r.get("priority", ""), r.get("action", ""), r.get("rationale", "")])
        story.append(_make_table(data, col_widths=[0.9 * inch, 2.4 * inch, 3.1 * inch]))

    if analysis.get("counter_hypotheses"):
        story.append(Paragraph("Devil's Advocate — Counter-Hypothesis Verification", styles["RCHeading"]))
        data = [["Original Hypothesis", "Alternative Explanation", "Falsification Risk"]]
        for c in analysis["counter_hypotheses"]:
            data.append([c.get("original_hypothesis", ""), c.get("alternative_explanation", ""), c.get("falsification_risk_score", "")])
        story.append(_make_table(data, col_widths=[2.1 * inch, 3.4 * inch, 1.1 * inch]))

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()
