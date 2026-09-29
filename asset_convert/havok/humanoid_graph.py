"""Patch a vanilla SSE humanoid behavior/character packfile in place.

The humanoid project is ONE set of 64-bit graphs shared by every race, so a
new weapon type cannot ship as a standalone project the way a creature does:
its states are spliced into `0_master`, `1hm_behavior`, `weapequip` and
`1hm_locomotion`. hkxcmd cannot read those files, so they round-trip through
external/hkxconv (HKX2E): packfile -> XML -> ElementTree edits -> packfile.

What a patch may do: append events and variables to the graph tables, add
states/generators to a machine or selector, add conditioned transitions,
extend expression conditions, and splice whole node trees rendered by
behavior_nodes.GraphBuilder (its object ids start where the file's end, so
nothing is renumbered).
See: docs/commentary/asset_convert_falloutnv.md#gun-graph
"""

import copy
import os
import re
import struct
import subprocess
import xml.etree.ElementTree as ET

from asset_convert import paths
from core.subprocess_flags import POPEN_FLAGS

HKXCONV = str(paths.HKXCONV)

#: The engine-written hand type variables a weapon-type slot keys on; the Equipped pair holds the drawn type.
HAND_TYPE_VARS = ('iRightHandType', 'iLeftHandType', 'iRightHandEquipped',
                  'iLeftHandEquipped')
#: The last vanilla weapon type (Dawnguard crossbow); new types follow it.
LAST_VANILLA_TYPE = 12

_EXPR_SIG = '0x1c3c1045'
_TRANS_ARRAY_CLASS = 'hkbStateMachineTransitionInfoArray'


# ---------------------------------------------------------------------------
# The round trip and the XML helpers
# ---------------------------------------------------------------------------

def hkxconv(*args) -> None:
    """Run external/hkxconv (prebuilt; see external/hkxconv/README.md)."""
    r = subprocess.run([HKXCONV, *args], capture_output=True, text=True,
                       **POPEN_FLAGS)
    if r.returncode != 0:
        raise RuntimeError(f'hkxconv {" ".join(args)}: {r.stderr.strip()}')


def _sub(el, name):
    """The hkparam child of `el` called `name` (None when absent)."""
    for p in el.findall('hkparam'):
        if p.get('name') == name:
            return p
    return None


def param_text(el, name, default=''):
    """The text of the hkparam `name` under `el`, stripped."""
    p = _sub(el, name)
    return (p.text or '').strip() if p is not None else default


class HumanoidGraph:
    """One packfile's XML, with the edits a weapon-type patch needs."""

    def __init__(self, xml_path: str):
        """Parse the XML hkxconv wrote."""
        self.xml_path = xml_path
        self.tree = ET.parse(xml_path)
        self.section = self.tree.getroot().find('hksection')
        self.objs = {o.get('name'): o for o in self.section.findall('hkobject')}
        self._next = max((int(n[1:]) for n in self.objs), default=0) + 1

    @classmethod
    def from_hkx(cls, hkx_bytes: bytes, work_dir: str, stem: str):
        """Decompile a packfile's bytes into a HumanoidGraph."""
        os.makedirs(work_dir, exist_ok=True)
        hkx = os.path.join(work_dir, stem + '.hkx')
        xml = os.path.join(work_dir, stem + '.xml')
        with open(hkx, 'wb') as f:
            f.write(hkx_bytes)
        hkxconv('toxml', hkx, xml)
        return cls(xml)

    def write(self, out_hkx: str) -> None:
        """Serialize the XML and compile it to a 64-bit packfile."""
        os.makedirs(os.path.dirname(os.path.abspath(out_hkx)), exist_ok=True)
        self.tree.write(self.xml_path, encoding='us-ascii',
                        xml_declaration=True)
        hkxconv('tohkx', self.xml_path, out_hkx)

    # -----------------------------------------------------------------------
    # Lookups
    # -----------------------------------------------------------------------

    def of_class(self, klass: str) -> list:
        """Every object of one class."""
        return [o for o in self.objs.values() if o.get('class') == klass]

    def find(self, name: str, klass: str = None):
        """The first object named `name` (optionally of `klass`)."""
        for o in self.objs.values():
            if param_text(o, 'name') == name and (klass is None
                                              or o.get('class') == klass):
                return o
        return None

    def ref(self, el) -> str:
        """An object's `#NNNN` reference."""
        return el.get('name')

    def obj(self, ref: str):
        """The object a `#NNNN` reference names (None when absent)."""
        return self.objs.get(ref)

    def next_id(self) -> int:
        """The first object id no object in the file uses."""
        return self._next

    @property
    def string_data(self):
        """The graph's hkbBehaviorGraphStringData object."""
        return self.of_class('hkbBehaviorGraphStringData')[0]

    @property
    def events(self) -> list:
        """The event names, in id order."""
        return [s.text or '' for s in
                _sub(self.string_data, 'eventNames').findall('hkcstring')]

    @property
    def variables(self) -> list:
        """The variable names, in index order."""
        return [s.text or '' for s in
                _sub(self.string_data, 'variableNames').findall('hkcstring')]

    def character_property_index(self, name: str) -> int:
        """The index of character property `name` (a bone set); KeyError if absent."""
        names = [s.text or '' for s in
                 _sub(self.string_data, 'characterPropertyNames').findall('hkcstring')]
        return names.index(name)

    def bound_variable(self, el, member: str):
        """The variable name bound to `member` of `el`, or None."""
        bind = self.obj(param_text(el, 'variableBindingSet'))
        if bind is None:
            return None
        names = self.variables
        for b in _sub(bind, 'bindings').findall('hkobject'):
            if param_text(b, 'memberPath') == member:
                i = int(param_text(b, 'variableIndex') or -1)
                return names[i] if 0 <= i < len(names) else None
        return None

    # -----------------------------------------------------------------------
    # Tables
    # -----------------------------------------------------------------------

    def add_event(self, name: str) -> int:
        """Append an event name (idempotent); its id."""
        names = self.events
        if name in names:
            return names.index(name)
        self._append_string(_sub(self.string_data, 'eventNames'), name)
        infos = _sub(self.of_class('hkbBehaviorGraphData')[0], 'eventInfos')
        self._append_struct(infos, [('flags', '0')])
        return len(names)

    def add_variable(self, name: str, init: float = 0, real=False) -> int:
        """Append an INT32 (or REAL) variable (idempotent); its index.
        A REAL's initial value is stored as its float bit pattern."""
        names = self.variables
        if name in names:
            return names.index(name)
        self._append_string(_sub(self.string_data, 'variableNames'), name)
        gdata = self.of_class('hkbBehaviorGraphData')[0]
        info = ET.SubElement(_sub(gdata, 'variableInfos'), 'hkobject')
        role = ET.SubElement(info, 'hkparam', name='role')
        ro = ET.SubElement(role, 'hkobject')
        ET.SubElement(ro, 'hkparam', name='role').text = 'ROLE_DEFAULT'
        ET.SubElement(ro, 'hkparam', name='flags').text = '0'
        ET.SubElement(info, 'hkparam', name='type').text = (
            'VARIABLE_TYPE_REAL' if real else 'VARIABLE_TYPE_INT32')
        self._bump(_sub(gdata, 'variableInfos'))
        values = self.obj(param_text(gdata, 'variableInitialValues'))
        word = (struct.unpack('<i', struct.pack('<f', init))[0] if real
                else int(init))
        self._append_struct(_sub(values, 'wordVariableValues'),
                            [('value', str(word))])
        return len(names)

    def _append_string(self, arr, text):
        """Append an hkcstring to a string array and recount it."""
        ET.SubElement(arr, 'hkcstring').text = text
        self._bump(arr)

    def _append_struct(self, arr, fields):
        """Append an anonymous hkobject of (param, text) to an array."""
        o = ET.SubElement(arr, 'hkobject')
        for k, v in fields:
            ET.SubElement(o, 'hkparam', name=k).text = v
        self._bump(arr)

    @staticmethod
    def _bump(arr):
        """Rewrite an array param's numelements from its children."""
        arr.set('numelements', str(len(list(arr))))

    # -----------------------------------------------------------------------
    # Objects
    # -----------------------------------------------------------------------

    def new_object(self, klass: str, signature: str = None):
        """Append an empty object of `klass`; the element."""
        attrs = {'name': f'#{self._next:04d}', 'class': klass}
        if signature:
            attrs['signature'] = signature
        el = ET.SubElement(self.section, 'hkobject', attrs)
        self.objs[attrs['name']] = el
        self._next += 1
        return el

    def expression_condition(self, expr: str) -> str:
        """A new hkbExpressionCondition; its ref."""
        el = self.new_object('hkbExpressionCondition', _EXPR_SIG)
        ET.SubElement(el, 'hkparam', name='expression').text = expr
        return self.ref(el)

    def splice(self, packfile_xml: str) -> None:
        """Append every object of a GraphBuilder-rendered packfile.

        The builder must have been created with `first_id=self.next_id()`
        so its refs are already unique here.
        """
        root = ET.fromstring(packfile_xml)
        for o in root.find('hksection').findall('hkobject'):
            n = int(o.get('name')[1:])
            if o.get('name') in self.objs:
                raise ValueError(f'object id collision {o.get("name")}')
            self.section.append(o)
            self.objs[o.get('name')] = o
            self._next = max(self._next, n + 1)

    # -----------------------------------------------------------------------
    # Edits
    # -----------------------------------------------------------------------

    def ref_list(self, el, param: str) -> list:
        """The `#NNNN` references an array param holds."""
        return param_text(el, param).split()

    def set_ref_list(self, el, param: str, refs: list) -> None:
        """Replace an array param's references and recount it."""
        p = _sub(el, param)
        p.text = ' '.join(refs)
        p.set('numelements', str(len(refs)))

    def add_state(self, machine, state_id: int, name: str, generator_ref: str,
                  transitions_ref: str = 'null') -> str:
        """A new stateInfo on `machine`; the state's ref."""
        st = self.new_object('hkbStateMachineStateInfo', '0x0ed7f9d0')
        for k, v in (('variableBindingSet', 'null'), ):
            ET.SubElement(st, 'hkparam', name=k).text = v
        ET.SubElement(st, 'hkparam', name='listeners', numelements='0')
        for k, v in (('enterNotifyEvents', 'null'), ('exitNotifyEvents', 'null'),
                     ('transitions', transitions_ref),
                     ('generator', generator_ref), ('name', name),
                     ('stateId', str(state_id)), ('probability', '1.000000'),
                     ('enable', 'true')):
            ET.SubElement(st, 'hkparam', name=k).text = v
        self.set_ref_list(machine, 'states',
                          self.ref_list(machine, 'states') + [self.ref(st)])
        return self.ref(st)

    def state_of(self, machine, state_id: int):
        """The stateInfo of `machine` with `state_id`, or None."""
        for r in self.ref_list(machine, 'states'):
            s = self.obj(r)
            if s is not None and int(param_text(s, 'stateId') or -1) == state_id:
                return s
        return None

    def add_generator(self, selector, generator_ref: str) -> None:
        """Append a child to an hkbManualSelectorGenerator."""
        self.set_ref_list(selector, 'generators',
                          self.ref_list(selector, 'generators')
                          + [generator_ref])

    def _template_transition(self, array):
        """A deep copy of the array's first transition, or a fresh one."""
        if array is not None:
            first = _sub(array, 'transitions').find('hkobject')
            if first is not None:
                return copy.deepcopy(first)
        for arr in self.of_class(_TRANS_ARRAY_CLASS):
            first = _sub(arr, 'transitions').find('hkobject')
            if first is not None:
                return copy.deepcopy(first)
        raise ValueError('no transition to copy the layout from')

    def add_transition(self, holder, event: str, to_state: int,
                       condition: str = None, priority: int = 0,
                       flags: str = None, first: bool = False,
                       wildcard: bool = False) -> None:
        """Add `on event -> to_state [if condition]` to a state or machine.

        `holder` is a stateInfo (its `transitions`) or, with `wildcard`, a
        state machine (its `wildcardTransitions`). A conditioned transition
        placed `first` with a higher `priority` beats the vanilla one on the
        same event.
        """
        param = 'wildcardTransitions' if wildcard else 'transitions'
        array = self.obj(param_text(holder, param))
        t = self._template_transition(array)
        if array is None:
            array = self.new_object(_TRANS_ARRAY_CLASS, '0xe397b11e')
            ET.SubElement(array, 'hkparam', name='transitions',
                          numelements='0')
            _sub(holder, param).text = self.ref(array)
        events = self.events
        if event not in events:
            raise KeyError(f'unknown event {event}')
        _sub(t, 'eventId').text = str(events.index(event))
        _sub(t, 'toStateId').text = str(to_state)
        _sub(t, 'fromNestedStateId').text = '0'
        _sub(t, 'toNestedStateId').text = '0'
        _sub(t, 'priority').text = str(priority)
        _sub(t, 'condition').text = (self.expression_condition(condition)
                                     if condition else 'null')
        _sub(t, 'flags').text = flags or ('0' if condition
                                          else 'FLAG_DISABLE_CONDITION')
        arr = _sub(array, 'transitions')
        arr.insert(0, t) if first else arr.append(t)
        self._bump(arr)

    # -----------------------------------------------------------------------
    # The weapon-type slot rule
    # -----------------------------------------------------------------------

    def hand_type_slots(self) -> list:
        """(element, kind) for every selector/machine keyed on a hand type.

        kind is 'msg' (selectedGeneratorIndex) or 'sm' (startStateId).
        """
        out = []
        for el in self.of_class('hkbManualSelectorGenerator'):
            if self.bound_variable(el, 'selectedGeneratorIndex') in HAND_TYPE_VARS:
                out.append((el, 'msg'))
        for el in self.of_class('hkbStateMachine'):
            if self.bound_variable(el, 'startStateId') in HAND_TYPE_VARS:
                out.append((el, 'sm'))
        return out

    def vanilla_slot(self, name: str):
        """The generator ref the last vanilla hand type plays in slot `name`;
        None when the slot has no entry for it."""
        for el, kind in self.hand_type_slots():
            if param_text(el, 'name') != name:
                continue
            if kind == 'msg':
                gens = self.ref_list(el, 'generators')
                return gens[LAST_VANILLA_TYPE] if len(gens) > LAST_VANILLA_TYPE else None
            state = self.state_of(el, LAST_VANILLA_TYPE)
            return None if state is None else param_text(state, 'generator')
        return None

    def extend_type_slots(self, new_type: int, replacements: dict) -> list:
        """Give every hand-type slot an entry for `new_type`.

        `replacements` maps an object NAME to the generator ref to use;
        anything else that already spans the vanilla types gets the last
        vanilla type's generator again, so no slot can be left short. An
        entry the vanilla file already holds at `new_type` is overwritten:
        it is a leftover the vanilla types never reach. The names patched
        are returned.
        See: docs/commentary/asset_convert_falloutnv.md#stale-slot-13
        """
        done = []
        for el, kind in self.hand_type_slots():
            name = param_text(el, 'name')
            if kind == 'msg':
                gens = self.ref_list(el, 'generators')
                if name not in replacements and not (
                        LAST_VANILLA_TYPE < len(gens) <= new_type):
                    continue
                while len(gens) <= new_type:
                    gens.append(gens[-1])
                gens[new_type] = replacements.get(name, gens[LAST_VANILLA_TYPE])
                self.set_ref_list(el, 'generators', gens)
            else:
                last = self.state_of(el, LAST_VANILLA_TYPE)
                if name not in replacements and last is None:
                    continue
                gen = (replacements[name] if name in replacements
                       else param_text(last, 'generator'))
                ours = f'TES4Type{new_type}_{name}'
                stale = self.state_of(el, new_type)
                if stale is None:
                    self.add_state(el, new_type, ours, gen)
                elif name in replacements or param_text(stale, 'name') != ours:
                    _sub(stale, 'generator').text = gen
                    _sub(stale, 'name').text = ours
                else:
                    continue
            done.append(name)
        return done

    def conditions_of_events(self, events) -> set:
        """The condition refs of every transition on one of `events`."""
        ids = {str(self.events.index(e)) for e in events if e in self.events}
        out = set()
        for arr in self.of_class(_TRANS_ARRAY_CLASS):
            for t in _sub(arr, 'transitions').findall('hkobject'):
                if param_text(t, 'eventId') in ids:
                    out.add(param_text(t, 'condition'))
        return out

    def gate_transitions(self, event: str, condition: str) -> int:
        """Give every unconditioned transition on `event` the condition.
        Returns the number gated.
        See: docs/commentary/tes_runtime_guns.md#bash-and-reload-events
        """
        n = 0
        eid = str(self.events.index(event))
        for arr in self.of_class(_TRANS_ARRAY_CLASS):
            for t in _sub(arr, 'transitions').findall('hkobject'):
                cond = _sub(t, 'condition')
                if param_text(t, 'eventId') != eid or cond.text != 'null':
                    continue
                cond.text = self.expression_condition(condition)
                flags = _sub(t, 'flags')
                kept = [f for f in (flags.text or '').split('|')
                        if f and f not in ('0', 'FLAG_DISABLE_CONDITION')]
                flags.text = '|'.join(kept) or '0'
                n += 1
        return n

    def widen_type_conditions(self, old_type: int, new_type: int,
                              skip_events=()) -> int:
        """Make every `== old` / `!= old` hand-type test also cover `new`.
        In the conditions of transitions on `skip_events` only the `!= old`
        tests are widened, so those transitions exclude `new` as they
        exclude `old`. Returns the number of conditions rewritten.
        See: docs/commentary/tes_runtime_guns.md#bash-and-reload-events
        """
        n = 0
        skip = self.conditions_of_events(skip_events)
        for el in self.of_class('hkbExpressionCondition'):
            equal = '#' + el.get('name', '').lstrip('#') not in skip
            p = _sub(el, 'expression')
            expr = p.text or ''
            new = re.sub(rf'\((i(?:Right|Left)HandType) != {old_type}\)',
                         rf'((\1 != {old_type}) && (\1 != {new_type}))', expr)
            if equal:
                new = re.sub(rf'\((i(?:Right|Left)HandType) == {old_type}\)',
                             rf'((\1 == {old_type}) || (\1 == {new_type}))', new)
                new = re.sub(rf'^(i(?:Right|Left)HandType) == {old_type}$',
                             rf'(\1 == {old_type}) || (\1 == {new_type})', new)
            if new != expr:
                p.text = new
                n += 1
        return n


class CharacterFile:
    """The hkbCharacterStringData half of characters\\default*.hkx."""

    def __init__(self, xml_path: str):
        """Parse the XML hkxconv wrote and find the string data."""
        self.xml_path = xml_path
        self.tree = ET.parse(xml_path)
        section = self.tree.getroot().find('hksection')
        self.strings = next(o for o in section.findall('hkobject')
                            if o.get('class') == 'hkbCharacterStringData')

    @classmethod
    def from_hkx(cls, hkx_bytes: bytes, work_dir: str, stem: str):
        """Decompile a character packfile's bytes into a CharacterFile."""
        os.makedirs(work_dir, exist_ok=True)
        hkx = os.path.join(work_dir, stem + '.hkx')
        xml = os.path.join(work_dir, stem + '.xml')
        with open(hkx, 'wb') as f:
            f.write(hkx_bytes)
        hkxconv('toxml', hkx, xml)
        return cls(xml)

    @property
    def animation_names(self) -> list:
        """The registered animation files, in index order."""
        return [s.text or '' for s in
                _sub(self.strings, 'animationNames').findall('hkcstring')]

    def append_animations(self, names: list) -> dict:
        """Register animation files (idempotent); {name: index}."""
        arr = _sub(self.strings, 'animationNames')
        have = {n.lower(): i for i, n in enumerate(self.animation_names)}
        for n in names:
            if n.lower() not in have:
                have[n.lower()] = len(have)
                ET.SubElement(arr, 'hkcstring').text = n
        arr.set('numelements', str(len(have)))
        return {n: have[n.lower()] for n in names}

    def write(self, out_hkx: str) -> None:
        """Serialize the XML and compile it to a 64-bit packfile."""
        os.makedirs(os.path.dirname(os.path.abspath(out_hkx)), exist_ok=True)
        self.tree.write(self.xml_path, encoding='us-ascii',
                        xml_declaration=True)
        hkxconv('tohkx', self.xml_path, out_hkx)
