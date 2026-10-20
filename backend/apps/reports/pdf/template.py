from __future__ import annotations

from datetime import date
from io import BytesIO
from typing import Any

from django.http import HttpResponse
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from apps.reports.pdf.utils import (
    COMPANY_ADDRESS,
    COMPANY_NAME,
    COMPANY_PHONE,
    format_datetime,
    format_period,
    get_logo_path,
)


class NumberedCanvas:
    pass


def _header_footer(canvas, doc):
    canvas.saveState()
    page_width, page_height = doc.pagesize
    footer = f"{COMPANY_NAME} | Page {doc.page} of {doc._pageNumber if hasattr(doc, '_pageNumber') else '?'}"
    # reportlab doesn't track total easily in simple flow; use canvas.getPageNumber() against page count tracked externally
    # We'll set total via doc attribute
    total = getattr(doc, '_total_pages', '?')
    footer_text = f"{COMPANY_NAME} | Page {canvas.getPageNumber()} of {total}"
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.grey)
    canvas.drawString(doc.leftMargin, 10 * mm, footer_text)
    canvas.restoreState()


class BarkotPDFReport:
    def __init__(
        self,
        title: str,
        description: str,
        report_type: str,
        start: date | None = None,
        end: date | None = None,
        as_of: date | None = None,
        period_label: str | None = None,
    ):
        self.title = title
        self.description = description
        self.report_type = report_type
        self.start = start
        self.end = end
        self.as_of = as_of
        self.period_label = period_label

    def render(self, summary_rows: list[tuple[str, str]] | None = None, table_data: list[list[Any]] | None = None, empty_message: str | None = None, landscape_layout: bool = False) -> HttpResponse:
        buffer = BytesIO()
        pagesize = landscape(A4) if landscape_layout else A4
        doc = SimpleDocTemplate(
            buffer,
            pagesize=pagesize,
            leftMargin=18 * mm,
            rightMargin=18 * mm,
            topMargin=18 * mm,
            bottomMargin=22 * mm,
            title=self.title,
        )
        story = []
        styles = getSampleStyleSheet()

        title_style = ParagraphStyle(
            "BarkotTitle",
            parent=styles["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=16,
            spaceAfter=2,
            textColor=colors.black,
        )
        subtitle_style = ParagraphStyle(
            "BarkotSubtitle",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=9,
            spaceAfter=1,
            textColor=colors.black,
        )
        small_style = ParagraphStyle(
            "BarkotSmall",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=8,
            spaceAfter=1,
            textColor=colors.black,
        )
        heading_style = ParagraphStyle(
            "BarkotHeading",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=12,
            spaceAfter=4,
            textColor=colors.black,
        )

        # Header with logo
        logo_path = get_logo_path()
        logo = None
        if logo_path and logo_path.exists():
            try:
                logo = Image(str(logo_path), width=32 * mm, height=18 * mm)
            except Exception:
                logo = None

        header_info = [
            Paragraph(f"<b>{COMPANY_NAME}</b>", subtitle_style),
            Paragraph(COMPANY_ADDRESS, small_style),
            Paragraph(COMPANY_PHONE, small_style),
        ]
        if logo:
            header_table = Table([[logo, header_info]], colWidths=[40 * mm, pagesize[0] - 76 * mm])
        else:
            header_table = Table([[header_info]], colWidths=[pagesize[0] - 36 * mm])
        header_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(header_table)
        story.append(Spacer(1, 3 * mm))
        story.append(Table([[""]], colWidths=[pagesize[0] - 36 * mm], style=[("LINEBELOW", (0, 0), (-1, -1), 0.5, colors.grey)]))
        story.append(Spacer(1, 6 * mm))

        # Report title and description
        story.append(Paragraph(self.title, title_style))
        story.append(Paragraph(self.description, subtitle_style))
        story.append(Paragraph(f"Report Type: {self.report_type}", small_style))
        story.append(Spacer(1, 4 * mm))

        # Metadata
        if self.period_label:
            period_text = self.period_label
        elif self.as_of:
            period_text = format_date(self.as_of)
        elif self.start and self.end:
            period_text = format_period(self.start, self.end)
        else:
            period_text = "Not specified"
        story.append(Paragraph(f"<b>Report Period:</b> {period_text}", small_style))
        story.append(Paragraph(f"<b>Generated On:</b> {format_datetime()}", small_style))
        story.append(Spacer(1, 6 * mm))

        # Summary
        if summary_rows:
            story.append(Paragraph("Summary", heading_style))
            summary_data = [[Paragraph(f"<b>{k}</b>", small_style), Paragraph(str(v), small_style)] for k, v in summary_rows]
            summary_table = Table(summary_data, colWidths=[60 * mm, pagesize[0] - 96 * mm])
            summary_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.whitesmoke),
                ("BOX", (0, 0), (-1, -1), 0.25, colors.grey),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]))
            story.append(summary_table)
            story.append(Spacer(1, 6 * mm))

        # Table
        if empty_message and (not table_data or len(table_data) == 0):
            story.append(Paragraph(empty_message, subtitle_style))
        elif table_data:
            story.append(Paragraph("Details", heading_style))
            t = Table(table_data, repeatRows=1)
            style_cmds = [
                ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 7.5),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 1), (-1, -1), 3),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
            # right align numeric-ish columns (monetary usually at end)
            t.setStyle(TableStyle(style_cmds))
            story.append(t)
        else:
            story.append(Paragraph(empty_message or "No records found for the selected period", subtitle_style))

        def _on_page(canvas, doc):
            canvas.saveState()
            total = getattr(doc, '_total_pages', canvas.getPageNumber())
            footer_text = f"{COMPANY_NAME} | Page {canvas.getPageNumber()} of {total}"
            canvas.setFont("Helvetica", 8)
            canvas.setFillColor(colors.grey)
            canvas.drawString(doc.leftMargin, 10 * mm, footer_text)
            canvas.restoreState()

        # Build to count pages
        doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
        buffer.seek(0)
        pdf_data = buffer.getvalue()
        # Count pages roughly by counting occurrences of %%EOF? easier: rebuild with total
        # For simplicity just use total pages from doc
        # reportlab stores page count differently; do a quick pass - use getPageNumber from canvas not directly available
        # We'll just set total to same as current page count by redoing footer after build? easier: regenerate footer text
        buffer2 = BytesIO()
        doc2 = SimpleDocTemplate(
            buffer2,
            pagesize=pagesize,
            leftMargin=18 * mm,
            rightMargin=18 * mm,
            topMargin=18 * mm,
            bottomMargin=22 * mm,
            title=self.title,
        )
        # rebuild story same content
        story2 = story
        total_pages = 1
        # rough estimate - build once to count
        temp = BytesIO()
        dtemp = SimpleDocTemplate(temp, pagesize=pagesize, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=18 * mm, bottomMargin=22 * mm)
        dtemp.build(story, onFirstPage=lambda c, d: None, onLaterPages=lambda c, d: None)
        total_pages = dtemp.page

        def _on_page2(canvas, doc):
            canvas.saveState()
            footer_text = f"{COMPANY_NAME} | Page {canvas.getPageNumber()} of {total_pages}"
            canvas.setFont("Helvetica", 8)
            canvas.setFillColor(colors.grey)
            canvas.drawString(doc.leftMargin, 10 * mm, footer_text)
            canvas.restoreState()
        buffer2 = BytesIO()
        doc3 = SimpleDocTemplate(buffer2, pagesize=pagesize, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=18 * mm, bottomMargin=22 * mm, title=self.title)
        doc3.build(story, onFirstPage=_on_page2, onLaterPages=_on_page2)
        pdf = buffer2.getvalue()
        return pdf
