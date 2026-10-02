"""Derived FormIDs that keep their slot when a newer generator's key hashes onto it.

`derive_formid` gives a contested slot to whichever key asks first, so a record
added by a newer generator that runs early can take an older record's FormID
and move it, breaking saves. Each key here derives before anything else, so the
older record keeps its FormID and the newcomer rehashes. Every machine reads the
same list, so ids stay identical everywhere.

See: docs/commentary/tes5_import_pipeline.md#formid-claims
"""

import os

#: Plugin file name (lowercase) -> [(site, key)] derived before any generator runs.
CLAIMS = {
    'falloutnv.esm': [('MGEF_DELIVERY', (0x1015170, 0, 0, 0)),
                      ('FOLLOWUP_RESUME_DLBR', 'TES4FollowUpResume_000F43F2')],
}


def claim_existing(writer, export_dir: str) -> int:
    """Derive the plugin's claimed keys first; how many."""
    pairs = CLAIMS.get(os.path.basename(os.path.normpath(export_dir)).lower(), ())
    for site, key in pairs:
        writer.derive_formid(site, key)
    return len(pairs)
