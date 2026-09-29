"""The gun entries of the jump and sprint selectors, after the vanilla
crossbow's shape: the plain move with the class' held pose overlaid on the
`Arms` character property, and the class' run clip for sprint.
See: docs/commentary/asset_convert_falloutnv.md#jump-and-sprint
"""

from asset_convert.havok.gun_graph_falloutnv import (GunGraphBuilder,
                                                     class_selector,
                                                     pose_gen)
from asset_convert.havok.humanoid_graph import (LAST_VANILLA_TYPE,
                                                HumanoidGraph, param_text)

#: The character property (a bone-weight array) the held pose overlays.
OVERLAY_PROPERTY = 'Arms'
#: The sprint selectors, one per hand, both keyed on the equipped type.
SPRINT_SELECTORS = ('SprintRightSideManualSelectorGenerator',
                    'SprintLeftSideManualSelectorGenerator')

_PROPERTY_BINDING = '''<hkobject>
\t<hkparam name="memberPath">spBoneWeight</hkparam>
\t<hkparam name="variableIndex">{prop}</hkparam>
\t<hkparam name="bitIndex">-1</hkparam>
\t<hkparam name="bindingType">BINDING_TYPE_CHARACTER_PROPERTY</hkparam>
</hkobject>'''


def bone_switch(gb: GunGraphBuilder, name, default_ref, overlay_ref,
                prop_index: int, weight_ref: str):
    """BSBoneSwitchGenerator: `default_ref` with `overlay_ref` on the bones
    of character property `prop_index` (`weight_ref` is the placeholder
    array the binding replaces, as vanilla's)."""
    bind = gb.add('hkbVariableBindingSet')
    bind.param_raw('bindings', _PROPERTY_BINDING.format(prop=prop_index),
                   numelements=1)
    bind.param('indexOfBindingToEnable', -1)
    child = gb.add('BSBoneSwitchGeneratorBoneData')
    child.param('variableBindingSet', bind.ref)
    child.param('pGenerator', overlay_ref)
    child.param('spBoneWeight', weight_ref)
    sw = gb.add('BSBoneSwitchGenerator')
    sw.param('variableBindingSet', 'null')
    sw.param('userData', 1)
    sw.param('name', name)
    sw.param('pDefaultGenerator', default_ref)
    sw.param_array('ChildrenA', [child.ref])
    return sw


def jump_replacements(g: HumanoidGraph, gb: GunGraphBuilder) -> dict:
    """{Jump*_MSG name: gun entry ref}: the last vanilla type's plain move
    under the held-pose overlay, on every jump selector."""
    prop = g.character_property_index(OVERLAY_PROPERTY)
    held = class_selector(gb, 'TES4Gun_Held_MSG',
                          lambda c: pose_gen(gb, c, f'TES4Gun_{c}_Held'))
    out = {}
    for el, kind in g.hand_type_slots():
        name = param_text(el, 'name')
        if kind != 'msg' or not name.startswith('Jump'):
            continue
        vanilla = g.obj(g.ref_list(el, 'generators')[LAST_VANILLA_TYPE])
        child = g.obj(g.ref_list(vanilla, 'ChildrenA')[0])
        sw = bone_switch(gb, f'TES4Gun_{name}_BoneSwitch',
                         param_text(vanilla, 'pDefaultGenerator'), held.ref,
                         prop, param_text(child, 'spBoneWeight'))
        out[name] = sw.ref
    return out


def _run_clip(gb: GunGraphBuilder, cls):
    """The class' run (else walk) clip, looping, for sprint; None without one."""
    stem = gb.clips.find(cls, 'fastforward') or gb.clips.find(cls, 'forward')
    return gb.clip(f'TES4Gun_{cls}_Sprint', stem, True) if stem else None


def sprint_selector(gb: GunGraphBuilder, fallback):
    """The class selector of run clips both sprint sides play; a class
    without one plays `fallback`, the vanilla sprint."""
    return class_selector(gb, 'TES4Gun_Sprint_MSG', lambda c: _run_clip(gb, c),
                          fallback)
