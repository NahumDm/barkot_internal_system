from __future__ import annotations

from datetime import date
from io import BytesIO

from django.http import HttpResponse
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from apps.reports.pdf.utils import (
    COMPANY_ADDRESS,
    COMPANY_NAME,
    COMPANY_PHONE,
    format_date,
    format_datetime,
    format_period,
    get_logo_path,
)


def _build_pdf(
    *,
    title: str,
    description: str,
    report_type: str,
    period_label: str | None = None,
    start: date | None = None,
    end: date | None = None,
    as_of: date | None = None,
    summary_rows: list[tuple[str, str]] | None = None,
    headers: list[str] | None = None,
    rows: list[list[str]] | None = None,
    empty_message: str | None = None,
    landscape_layout: bool = False,
    filename: str,
) -> HttpResponse:
    pagesize = landscape(A4) if landscape_layout else A4
    buffer = BytesIO()

    styles = getSampleStyleSheet()
    subtitle_style = ParagraphStyle("Subtitle", parent=styles["Normal"], fontSize=9)
    small_style = ParagraphStyle("Small", parent=styles["Normal"], fontSize=8)
    heading_style = ParagraphStyle("Heading", parent=styles["Heading2"], fontSize=12)
    title_style = ParagraphStyle("Title", parent=styles["Heading1"], fontSize=16)

    story = []

    # Header
    logo_path = get_logo_path()
    header_right = [
        Paragraph(f"<b>{COMPANY_NAME}</b>", subtitle_style),
        Paragraph(COMPANY_ADDRESS, small_style),
        Paragraph(COMPANY_PHONE, small_style),
    ]
    if logo_path and logo_path.exists():
        try:
            logo = Image(str(logo_path), width=28 * mm, height=16 * mm)
            header_table = Table([[logo, header_right]], colWidths=[36 * mm, pagesize[0] - 72 * mm])
        except Exception:
            header_table = Table([[header_right]], colWidths=[pagesize[0] - 36 * mm])
    else:
        header_table = Table([[header_right]], colWidths=[pagesize[0] - 36 * mm])
    header_table.setStyle(
        TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ])
    )
    story.append(header_table)
    story.append(Spacer(1, 3 * mm))
    story.append(
        Table(
            [[""]],
            colWidths=[pagesize[0] - 36 * mm],
            style=[("LINEBELOW", (0, 0), (-1, -1), 0.5, colors.grey)],
        )
    )
    story.append(Spacer(1, 6 * mm))

    story.append(Paragraph(title, title_style))
    story.append(Paragraph(description, subtitle_style))
    story.append(Paragraph(f"Report Type: {report_type}", small_style))
    story.append(Spacer(1, 4 * mm))

    if period_label:
        p = period_label
    elif as_of:
        p = format_date(as_of)
    elif start and end:
        p = format_period(start, end)
    else:
        p = "Not specified"
    story.append(Paragraph(f"<b>Report Period:</b> {p}", small_style))
    story.append(Paragraph(f"<b>Generated On:</b> {format_datetime()}", small_style))
    story.append(Spacer(1, 6 * mm))

    if summary_rows:
        story.append(Paragraph("Summary", heading_style))
        sdata = [
            [Paragraph(f"<b>{k}</b>", small_style), Paragraph(str(v), small_style)]
            for k, v in summary_rows
        ]
        stable = Table(sdata, colWidths=[70 * mm, pagesize[0] - 106 * mm])
        stable.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.whitesmoke),
                ("BOX", (0, 0), (-1, -1), 0.25, colors.grey),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ])
        )
        story.append(stable)
        story.append(Spacer(1, 6 * mm))

    if empty_message and (not rows or len(rows) == 0):
        story.append(Paragraph(empty_message, subtitle_style))
    elif headers and rows:
        story.append(Paragraph("Details", heading_style))
        table_data = [[Paragraph(str(h), small_style) for h in headers]] + [
            [Paragraph(str(c), small_style) for c in row] for row in rows
        ]
        t = Table(table_data, repeatRows=1)
        t.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 7.5),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ])
        )
        story.append(t)
    else:
        story.append(
            Paragraph(empty_message or "No records found for the selected period", subtitle_style)
        )

    # Count pages
    def _noop(canvas, doc):
        pass

    temp_buffer = BytesIO()
    doc_temp = SimpleDocTemplate(
        temp_buffer,
        pagesize=pagesize,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=22 * mm,
    )
    doc_temp.build(story, onFirstPage=_noop, onLaterPages=_noop)
    total_pages = doc_temp.page

    def _on_page(canvas, doc):
        canvas.saveState()
        footer_text = f"{COMPANY_NAME} | Page {canvas.getPageNumber()} of {total_pages}"
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.grey)
        canvas.drawString(doc.leftMargin, 10 * mm, footer_text)
        canvas.restoreState()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=pagesize,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=22 * mm,
        title=title,
    )
    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
    pdf = buffer.getvalue()
    response = HttpResponse(pdf, content_type="application/pdf")
    safe_name = filename.replace('"', "").replace(";", "")
    response["Content-Disposition"] = f'attachment; filename="{safe_name}.pdf"'
    return response
