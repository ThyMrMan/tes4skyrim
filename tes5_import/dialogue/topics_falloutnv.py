"""FO3/FNV topic flags and shown text.

A FO3/FNV DIAL carries a Top-level flag. A Top-level topic is listed
whenever its conditions pass; any other topic is reached as a reply (an
INFO's Choice list) or listed once something AddTopics it. Dialogue text
holds notes in braces that the Fallout engine never shows.

See: docs/commentary/tes5_import_dialogue.md#fallout-topic-links
See: docs/commentary/tes5_import_dialogue.md#fallout-brace-notes
"""

import re

from ..record_types.common import get_int
from ..record_types.world_falloutnv import is_fallout_source

#: FO3/FNV DIAL DATA.Flags bit: the topic is listed in the menu without a link to it.
_TOP_LEVEL = 0x02

#: A note in braces, with the spaces around it.
_BRACE_NOTE = re.compile(r'\s*\{[^{}]*\}\s*')

#: A space a removed note left before punctuation.
_SPACE_BEFORE_MARK = re.compile(r' +([.,!?;:])')


def has_topic_flags(dial_rec: dict) -> bool:
    """Whether a DIAL carries FO3/FNV topic flags (Oblivion's DATA has none)."""
    return 'DATA.Flags' in dial_rec


def is_top_level(dial_rec: dict) -> bool:
    """Whether a FO3/FNV topic has the Top-level flag."""
    return bool(get_int(dial_rec, 'DATA.Flags') & _TOP_LEVEL)


def shown_text(text: str) -> str:
    """Dialogue text as the player sees it: a Fallout source's `{notes}` removed."""
    if not text or '{' not in text or not is_fallout_source():
        return text
    return _SPACE_BEFORE_MARK.sub(r'\1', _BRACE_NOTE.sub(' ', text)).strip()


#: INFO DATA Flags 2 bit 0 (xEdit `wbDefinitionsFNV`): the line waits a day before it plays again.
_SAY_ONCE_A_DAY = 0x01

#: ENAM's reset for one day, in the engine's stored form trunc(days * 65535).
_ONE_DAY = 65535


def reset_ticks(info_rec: dict) -> int:
    """A Fallout INFO's re-play lockout: a day for Say Once a Day, else none."""
    return _ONE_DAY if get_int(info_rec, 'DATA.Flags2') & _SAY_ONCE_A_DAY else 0
