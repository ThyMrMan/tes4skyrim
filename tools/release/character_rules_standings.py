"""The karma and infamy half of a Fallout game's character rules plugin.

Karma and each reputation are globals of the converted plugin
(tes5_import.record_types.reputation_falloutnv); this builds the lists the
rules' Papyrus reads when the player kills, steals or is caught at a crime:
the actors of each alignment, the evil and crime-tracking factions, and each
reputation's crime-tracking factions, with the amounts from the game's settings.

See: docs/commentary/character_rules.md#fallout-karma-and-infamy
"""
from tools.release.character_rules_records import Obj, build_flst

#: Each alignment list's property and the character data's name for it, in the order first shipped.
ALIGNMENT_LISTS = (('VeryEvilActors', 'very_evil'), ('EvilActors', 'evil'),
                   ('GoodActors', 'good'), ('VeryGoodActors', 'very_good'))

#: A kill-karma entry meaning the creature or person murder setting.
MURDER = 'murder'

#: Kill karma by alignment (neutral, evil, very evil, good, very good): claimed by a crime faction, then not.
KILL_KARMA = {'falloutnv': ((MURDER, 'fKarmaModKillingEvilActor', 'fKarmaModKillingVeryEvilActor',
                             'fKarmaModMurderingGoodNPC', 'fKarmaModMurderingVeryGoodNPC'),
                            (None, None, None, None, None)),
              'fallout3': ((MURDER, None, 'fKarmaModKillingEvilActor', MURDER, MURDER),
                           (None, None, 'fKarmaModKillingEvilActor', None, None))}

#: Each other karma or infamy property and its setting.
AMOUNTS = (('KarmaMurderNPC', 'fKarmaModMurderingNonEvilNPC'),
           ('KarmaMurderCreature', 'fKarmaModMurderingNonEvilCreature'),
           ('KarmaTheft', 'fKarmaModStealing'),
           ('KarmaMin', 'fAlignMinKarma'), ('KarmaMax', 'fAlignMaxKarma'),
           ('InfamyMajor', 'fReputationMajorCrimeNeg'), ('InfamyMinor', 'fReputationMinorCrimeNeg'))


def amount_table(settings: dict, game: str) -> dict:
    """Each amount, 0 where the game has no setting, and the kill karma by alignment."""
    out = {prop: float(settings.get(name, 0.0)) for prop, name in AMOUNTS}
    claimed, unclaimed = KILL_KARMA[game]
    out['KillMurders'] = [int(name == MURDER) for name in claimed]
    out['KillKarmaClaimed'] = [float(settings.get(name, 0.0)) if name else 0.0 for name in claimed]
    out['KillKarmaUnclaimed'] = [float(settings.get(name, 0.0)) if name else 0.0 for name in unclaimed]
    return out


def _reputation_factions(doc: dict) -> dict:
    """Each reputation form (as a tuple) -> the forms of the crime-tracking factions that name it."""
    out = {}
    for row in doc.get('factions', []):
        if row['reputation'] and row['crime']:
            out.setdefault(tuple(row['reputation']), []).append(row['form'])
    return out


def build_standings(forms, doc: dict, prefix: str, karma: int) -> tuple:
    """(properties, FLST bytes): the karma global, the alignment and faction lists, and the amounts."""
    lists, props = b'', {'Karma': Obj(karma), **amount_table(doc['settings'], doc['game'])}
    alignments, factions = doc.get('alignments', {}), doc.get('factions', [])
    named = [(prop, alignments.get(name, [])) for prop, name in ALIGNMENT_LISTS]
    named.append(('CrimeFactions', [row['form'] for row in factions if row['crime']]))
    reputations, members = [], []
    for i, (rep, members_of) in enumerate(sorted(_reputation_factions(doc).items())):
        named.append((f'ReputationFactions{i}', members_of))
        reputations.append(Obj(forms.of(list(rep))))
    named.append(('EvilFactions', [row['form'] for row in factions if row.get('evil')]))
    for prop, entries in named:
        fid = forms.new()
        lists += build_flst(fid, f'{prefix}{prop}', [forms.of(form) for form in entries])
        if prop.startswith('ReputationFactions'):
            members.append(Obj(fid))
        else:
            props[prop] = Obj(fid)
    props.update(Reputations=reputations, ReputationFactions=members)
    return props, lists
