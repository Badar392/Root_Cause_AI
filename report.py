"""
utils/report.py

Turns a completed root-cause analysis (the dict returned by
groq_client.analyze_root_cause) into a downloadable Markdown string or a
polished PDF, for the app's "Export Reports" tab.
"""

import io
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
)


# =============================================================================
# Markdown export
# =============================================================================

def generate_markdown_report(analysis: dict, filenames: list, generated_at: datetime = None) -> str:
    """Build a clean Markdown report string from the AI analysis dict."""
    generated_at = generated_at or datetime.now()
    lines = [
        "# Root Cause AI — Analysis Report",
        f"\n*Generated: {generated_at.strftime('%Y-%m-%d %H:%M')}*",
        f"\n**Source files:** {', '.join(filenames) if filenames else 'N/A'}\n",
    ]

    if not analysis or analysis.get("_parse_failed"):
        lines.append("## Note\n")
        lines.append("The AI analysis could not be generated or fully parsed for this run.\n")
        if analysis and analysis.get("_raw_text"):
            lines.append("### Raw model output\n")
            lines.append("```\n" + str(analysis["_raw_text"]) + "\n```")
        return "\n".join(lines)

    lines.append("## Summary\n")
    lines.append(str(analysis.get("summary", "")) + "\n")

    if analysis.get("anomalies"):
        lines.append("## Anomalies Detected\n")
        for a in analysis["anomalies"]:
            lines.append(f"- **[{a.get('severity', 'Unknown')}]** {a.get('description', '')}")
            if a.get("evidence"):
                lines.append(f"  - Evidence: {a['evidence']}")
        lines.append("")

    if analysis.get("trigger_events"):
        lines.append("## Trigger Events\n")
        for t in analysis["trigger_events"]:
            lines.append(
                f"- **{t.get('event', '')}** ({t.get('timestamp_or_period', 'unknown time')}) "
                f"— Confidence: {t.get('confidence', 'Unknown')}"
            )
            if t.get("evidence"):
                lines.append(f"  - Evidence: {t['evidence']}")
        lines.append("")

    if analysis.get("impact_assessment"):
        ia = analysis["impact_assessment"]
        lines.append("## Impact Assessment\n")
        lines.append(f"- **Category:** {ia.get('category', '')}")
        lines.append(f"- **Severity:** {ia.get('severity', '')}")
        lines.append(f"- **Justification:** {ia.get('justification', '')}\n")

    if analysis.get("recommended_actions"):
        lines.append("## Recommended Actions\n")
        for r in analysis["recommended_actions"]:
            lines.append(f"- **[{r.get('priority', 'Unknown')}]** {r.get('action', '')}")
            if r.get("rationale"):
                lines.append(f"  - Rationale: {r['rationale']}")
        lines.append("")

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
    return styles


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


def generate_pdf_report(analysis: dict, filenames: list, generated_at: datetime = None) -> bytes:
    """Build a polished PDF report and return it as raw bytes, ready for st.download_button."""
    generated_at = generated_at or datetime.now()
    styles = _report_styles()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter,
        topMargin=0.75 * inch, bottomMargin=0.75 * inch,
        leftMargin=0.75 * inch, rightMargin=0.75 * inch,
    )
    story = []

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
