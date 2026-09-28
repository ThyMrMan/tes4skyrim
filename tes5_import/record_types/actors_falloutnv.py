"""FO3/FNV actor templates: resolving TPLT so a spawn stub knows what it is.

FO3/FNV actors inherit by category. A spawn stub owns nothing but a TPLT and
the ACBS Template Flags naming the categories it takes from that template, so
its model, name, AI data and stats all live one or more links away. Nothing
here writes TPLT into the output, so an unflattened category is lost outright.

Also holds the AIDT combat tiers, which FO3/FNV stores in the same enums TES5
uses and Oblivion stores as 0-100 scalars.

See: docs/commentary/tes5_import_falloutnv_actors.md
"""

from ..base.text_reader import get_formid, get_int, get_str

#: Template Flags bits, and the field each hides (wbDefinitionsFNV.pas:6830).
_USE_TRAITS = 1 << 0
_USE_STATS = 1 << 1
_USE_FACTIONS = 1 << 2
_USE_EFFECTS = 1 << 3
_USE_AI_DATA = 1 << 4
_USE_PACKAGES = 1 << 5
_USE_MODEL = 1 << 6
_USE_BASE_DATA = 1 << 7
_USE_INVENTORY = 1 << 8
_USE_SCRIPT = 1 << 9

#: A template chain longer than this is a cycle; FNV's deepest is 3.
_MAX_DEPTH = 8

#: Inherited with Model/Animation, and read by the creature race builder.
_MODEL_KEYS = ('Model.MODL', 'Model.MODB', 'Model.MODT', 'HNAM.Hair',
               'LNAM.HairLength', 'ENAM.Eyes', 'HCLR.R', 'HCLR.G', 'HCLR.B',
               'FGGS', 'FGGA', 'FGTS', 'NIFT.Size')

#: Inherited with AI Data; Aggression and Confidence drive the combat tiers.
_AIDT_KEYS = ('AIDT.Aggression', 'AIDT.Confidence', 'AIDT.EnergyLevel',
              'AIDT.Responsibility', 'AIDT.Mood', 'AIDT.Services',
              'AIDT.Teaches', 'AIDT.MaxTraining', 'AIDT.Assistance',
              'AIDT.AggroRadiusBehavior', 'AIDT.AggroRadius',
              'ACBS.BarterGold')

#: Inherited with Traits: race, voice, class and the rest of an actor's identity.
_TRAIT_KEYS = ('RNAM.Race', 'VTCK.Voice', 'CNAM.Class', 'ZNAM.CombatStyle',
               'INAM.DeathItem', 'ACBS.Karma', 'ACBS.Disposition',
               'BNAM.BaseScale', 'TNAM.TurningSpeed', 'WNAM.FootWeight',
               'RNAM.AttackReach', 'CSCR.InheritSound')

#: Inherited with Stats: level, the ACBS scaling band and the DATA attributes.
_STAT_KEYS = ('ACBS.Level', 'ACBS.CalcMin', 'ACBS.CalcMax', 'ACBS.Fatigue',
              'ACBS.SpeedMultiplier', 'DATA.Health', 'DATA.AttackDamage',
              'DATA.Strength', 'DATA.Perception', 'DATA.Endurance',
              'DATA.Charisma', 'DATA.Intelligence', 'DATA.Agility',
              'DATA.Luck')

#: Scalar categories: a Template Flags bit and the keys it carries verbatim.
_CATEGORIES = ((_USE_MODEL, _MODEL_KEYS),
               (_USE_AI_DATA, _AIDT_KEYS),
               (_USE_TRAITS, _TRAIT_KEYS),
               (_USE_STATS, _STAT_KEYS),
               (_USE_BASE_DATA, ('FULL',)),
               (_USE_SCRIPT, ('SCRI',)))

#: Counted-array categories: bit, count key, and its per-entry key templates.
_ARRAY_CATEGORIES = (
    (_USE_INVENTORY, 'ItemCount', ('Item[%d].FormID', 'Item[%d].Count')),
    (_USE_FACTIONS, 'FactionCount', ('Faction[%d].FormID', 'Faction[%d].Rank')),
    (_USE_PACKAGES, 'AIPackageCount', ('AIPackage[%d]',)),
    (_USE_EFFECTS, 'SpellCount', ('Spell[%d]',)),
    (_USE_MODEL, 'KFFZCount', ('KFFZ[%d]',)),
    (_USE_TRAITS, 'SoundTypeCount', ('SoundType[%d].Type',
                                     'SoundType[%d].Sound',
                                     'SoundType[%d].Sound.Chance')),
)


#: Highest legal TES5 tier: wbAggressionEnum is 0-3, wbConfidenceEnum 0-4.
_MAX_AGGRESSION, _MAX_CONFIDENCE = 3, 4


def aidt_tiers(rec: dict) -> tuple:
    """FO3/FNV (Aggression, Confidence) as TES5 tiers, clamped to their enums.

    See: docs/commentary/tes5_import_falloutnv_actors.md#aggression-is-already-a-tier
    """
    return (min(get_int(rec, 'AIDT.Aggression'), _MAX_AGGRESSION),
            min(get_int(rec, 'AIDT.Confidence'), _MAX_CONFIDENCE))


#: Types a TPLT chain can pass through. FO3/FNV has LVLN as well as LVLC.
_TEMPLATE_SIGS = ('CREA', 'NPC_', 'LVLC', 'LVLN')

#: The actor types in a chain; a leveled list only points onward.
_ACTOR_SIGS = ('CREA', 'NPC_')


def _index_actors(by_type: dict, master_export: dict) -> dict:
    """FormID -> record for every actor and leveled actor list in scope."""
    index = {}
    sources = [master_export.values()] if master_export else []
    sources.extend(by_type.get(sig, []) for sig in _TEMPLATE_SIGS)
    for group in sources:
        for rec in group:
            if get_str(rec, 'Signature') in _TEMPLATE_SIGS:
                index[get_formid(rec, 'FormID')] = rec
    return index


def actor_index(by_type: dict, master_export: dict = None) -> dict:
    """FormID -> record for every actor and leveled actor list, for template walks."""
    return _index_actors(by_type, master_export)


def inherited_voice(rec: dict, index: dict) -> int:
    """A Use Traits stub's voice type, from the nearest template naming one, or 0.

    `_flatten_one` keys the Traits category on `RNAM.Race`, which no CREA
    owns, so a creature stub's voice is resolved here instead.
    See: docs/commentary/tes5_import_conditions.md#authored-voice-types
    """
    if not get_int(rec, 'ACBS.TemplateFlags') & _USE_TRAITS:
        return 0
    donor = _first_owning(rec, index, 'VTCK.Voice')
    return get_formid(donor, 'VTCK.Voice') if donor is not None else 0


def _chain(rec: dict, index: dict):
    """Every actor down this record's template chain, nearest first.

    A leveled-list link resolves through its entries, which is how FNV points
    a stub at an actor: stub -> LVLC/LVLN -> CREA/NPC_. ``rec`` is not yielded.
    """
    seen = set()
    queue = [(rec, 0)]
    while queue:
        node, depth = queue.pop(0)
        fid = get_formid(node, 'FormID')
        if depth > _MAX_DEPTH or fid in seen:
            continue
        seen.add(fid)
        if node is not rec:
            yield node
        nxt = [get_formid(node, 'TPLT.Template')]
        nxt += [get_formid(node, f'Entry[{i}].FormID')
                for i in range(get_int(node, 'EntryCount', 0))]
        queue += [(index[f], depth + 1) for f in nxt if f and f in index]


def _first_owning(rec: dict, index: dict, key: str) -> dict:
    """The nearest actor down the chain that owns ``key``, or None."""
    for node in _chain(rec, index):
        if get_str(node, key):
            return node
    return None


def _defines(node: dict, bit: int) -> bool:
    """Whether an actor holds category ``bit`` itself, not from a template."""
    inherits = get_int(node, 'ACBS.TemplateFlags') & bit and get_formid(node, 'TPLT.Template')
    return get_str(node, 'Signature') in _ACTOR_SIGS and not inherits


def _defining(rec: dict, index: dict, bit: int) -> dict:
    """The nearest actor down the chain that defines category ``bit`` itself, or None."""
    return next((node for node in _chain(rec, index) if _defines(node, bit)), None)


def _copy_array(rec: dict, donor: dict, count_key: str, templates) -> bool:
    """Copy one counted array down from ``donor``, entry by entry.

    Every entry is taken: a partial list is worse than none, since the engine
    reads the count and would index past what was copied.
    """
    count = get_int(donor, count_key, 0)
    if not count:
        return False
    for i in range(count):
        for tmpl in templates:
            key = tmpl % i
            if key in donor:
                rec[key] = donor[key]
    rec[count_key] = str(count)
    return True


def _flatten_one(rec: dict, index: dict) -> bool:
    """Copy every category ``rec``'s flags claim down from its template.

    A claimed category comes whole from the nearest actor down the chain that
    defines it: the engine ignores the stub's own values there, which it still
    carries (ACBS.Level and AIDT are always written). Counted arrays
    (inventory, factions, packages, spells) are carried whole.

    See: docs/commentary/tes5_import_falloutnv_actors.md#every-category-flattens
    """
    flags = get_int(rec, 'ACBS.TemplateFlags') if get_formid(rec, 'TPLT.Template') else 0
    filled = False
    for bit, keys in _CATEGORIES:
        donor = _defining(rec, index, bit) if flags & bit else None
        if donor is None:
            continue
        for key in keys:
            if get_str(donor, key):
                rec[key] = donor[key]
        if bit == _USE_MODEL:
            _copy_nifz(rec, donor)
        filled = True

    for bit, count_key, templates in _ARRAY_CATEGORIES:
        donor = _defining(rec, index, bit) if flags & bit else None
        if donor is not None and _copy_array(rec, donor, count_key, templates):
            filled = True
    return filled


def _copy_nifz(rec: dict, donor: dict) -> None:
    """Carry the donor's NIFZ model list across; the body-set lookup keys off it."""
    count = get_int(donor, 'NIFZCount', 0)
    if not count:
        return
    rec['NIFZCount'] = str(count)
    for i in range(count):
        rec[f'NIFZ[{i}]'] = donor[f'NIFZ[{i}]']


def flatten_actor_templates(by_type: dict, master_export: dict = None) -> int:
    """Copy each FO3/FNV stub's inherited categories down from its template.

    Mutates the record dicts in ``by_type``, so it must run before the creature
    race builder and any actor conversion. Returns the number flattened.
    """
    index = _index_actors(by_type, master_export)
    flattened = 0
    for sig in ('CREA', 'NPC_'):
        for rec in by_type.get(sig, []):
            flattened += _flatten_one(rec, index)
    return flattened
