"""CSV export for report endpoints (spec §15.3).

Reports are the only place Barkot ships files, and for the MVP every report fits
comfortably on a spreadsheet, so CSV is the export format for all four. The BOM
in front of the payload is not decoration: without it, Excel opens the file as
mojibake because the CSV arrives without a declared encoding. Each endpoint
streams the same quantised strings it returns as JSON (§10.3), so a reader
comparing the screen to the downloaded file sees identical numbers.
"""

from __future__ import annotations

import csv
import io

from django.http import HttpResponse

#: One row per line; ``\r\n`` is the line-ending every spreadsheet import expects.
_LINE_TERMINATOR = "\r\n"


def csv_download(
    *,
    filename: str,
    columns: list[tuple[str, str]],
    rows: list[dict[str, object]],
) -> HttpResponse:
    """Return an attachment response with the given rows as CSV.

    Args:
        filename: The ``Content-Disposition`` filename; ``.csv`` is appended.
        columns: ``(header, key)`` pairs in display order; unknown keys render
            empty so a new service field cannot silently reorder a spreadsheet.
        rows: Row dictionaries; values are ``str``/``None``/``int``/``date``.
    """
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
    """Render one report cell for a spreadsheet.

    ``str(None)`` is not what a spreadsheet should see; an empty cell is.
    """
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return str(value)


__all__ = ["csv_download"]
