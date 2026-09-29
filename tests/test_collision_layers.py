"""_body_tris: which collision layers the navmesh extractor keeps.

See: docs/commentary/asset_convert_collision.md#transparent-layer
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asset_convert.collision import collision_extract as ce


class _Vec(object):
    """A havok vector triple."""

    def __init__(self, x, y, z):
        """Hold the three components."""
        self.x, self.y, self.z = x, y, z


class bhkBoxShape(object):
    """Stand-in box shape; `_primitive_tris` dispatches on the class name."""

    def __init__(self):
        """A 1x1x1 havok half-extent box."""
        self.dimensions = _Vec(1.0, 1.0, 1.0)


class _Filter(object):
    """The body's havok collision filter."""

    def __init__(self, layer):
        """Hold the layer number."""
        self.layer = layer


class _Body(object):
    """Stand-in bhkRigidBody holding a box on one layer."""

    def __init__(self, layer):
        """Build a box body on `layer`."""
        self.havok_col_filter = _Filter(layer)
        self.shape = bhkBoxShape()


def test_transparent_layer_invisible_box_is_kept():
    """Layer 3 is invisible collision (CollisionBox01): all 12 box faces extract."""
    assert len(ce._body_tris(_Body(ce.OL_TRANSPARENT))) == 12


def test_clutter_and_trigger_layers_are_dropped():
    """Clutter (4) and trigger (12) never shape the navmesh."""
    assert ce._body_tris(_Body(4)) == []
    assert ce._body_tris(_Body(12)) == []
