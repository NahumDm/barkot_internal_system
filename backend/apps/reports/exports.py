"""Report exports (PDF preferred; CSV retained for backward compatibility).

Reports generate professional, branded PDF documents. CSV export is still
supported if explicitly requested, but new implementations default to PDF.
"""

from __future__ import annotations

import csv
import io

from django.http import HttpResponse

_LINE_TERMINATOR = "\r\n"


def csv_download(
    *,
    filename: str,
    columns: list[tuple[str, str]],
    rows: list[dict[str, object]],
) -> HttpResponse:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator=_LINE_TERMINATOR)
    writer.writerow([header for header, _ in columns])
    for row in rows:
        writer.writerow([_cell(row.get(key)) for _, key in columns])

    payload = "\ufeff" + buffer.getvalue()
    response = HttpResponse(payload, content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}.csv"'
    return response


def _cell(value: object) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return str(value)


__all__ = ["csv_download"]
