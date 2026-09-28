"""FO3/FNV `begin SayToDone <topic>`: the speaker's script runs a block as its line ends.

Skyrim has no such event. The block becomes a function on its own script, and
every INFO End fragment of the topic calls it on the speaker, through a cast
that is None for any speaker without that script. A block naming no topic runs
after any line, so it is hooked to every topic its script names.

See: docs/commentary/script_convert.md#saytodone
"""

import re

from script_convert.constants import papyrus_script_name, sanitize_name

#: `begin SayToDone [topic]`, the topic group empty when the block names none.
_BEGIN_RE = re.compile(r'(?im)^[ \t]*begin[ \t]+saytodone\b[ \t]*(\w*)')

#: Any identifier, for the topics a topic-less block's script names.
_WORD_RE = re.compile(r'\w+')

#: The block type as the parser lowercases it.
BLOCK_TYPE = 'saytodone'


def function_name(topic: str) -> str:
    """The Papyrus function a SayToDone block on `topic` ('' for none) becomes."""
    return f'TES4_SayToDone_{topic.lower()}' if topic else 'TES4_SayToDone'


def block_header(block) -> tuple:
    """(opener, closer) of the function a SayToDone block becomes."""
    match = _WORD_RE.match(block.filter or '')
    return f'Function {function_name(match.group(0) if match else "")}()', 'EndFunction'


def _hooked_topics(text: str, dial_edids: set) -> dict:
    """{topic EditorID (lower): function} for one script's SayToDone blocks."""
    out = {}
    for topic in _BEGIN_RE.findall(text):
        if topic:
            out[topic.lower()] = function_name(topic)
            continue
        for word in _WORD_RE.findall(text):
            if word.lower() in dial_edids:
                out.setdefault(word.lower(), function_name(''))
    return out


def say_to_done_topics(scpt_records: list, dial_edids: set) -> set:
    """Topic EditorIDs (lower) some script's SayToDone waits on."""
    return {topic for rec in scpt_records
            for topic in _hooked_topics(rec.get('SCTX') or '', dial_edids)
            if topic in dial_edids}


def say_to_done_hooks(by_type: dict) -> dict:
    """{DIAL FormID (upper hex, as INFO.ParentDIAL): [(script name, function)]}."""
    dial_fid = {(r.get('EditorID') or '').strip().lower(): (r.get('FormID') or '').upper()
                for r in by_type.get('DIAL', ())}
    dial_fid.pop('', None)
    dial_edids = set(dial_fid)
    hooks = {}
    for rec in by_type.get('SCPT', ()):
        name = papyrus_script_name(sanitize_name(
            rec.get('EditorID') or f'Script_{rec.get("FormID", "")}'))
        for topic, func in _hooked_topics(rec.get('SCTX') or '', dial_edids).items():
            if topic in dial_fid:
                hooks.setdefault(dial_fid[topic], []).append((name, func))
    return hooks


def fragment_calls(hooks) -> list:
    """INFO End fragment lines running each hooked script's SayToDone on the speaker."""
    out = []
    for i, (script, func) in enumerate(hooks):
        out += [f'  {script} TES4_Done{i} = akSpeakerRef as {script}',
                f'  If TES4_Done{i}', f'    TES4_Done{i}.{func}()', '  EndIf']
    return out
