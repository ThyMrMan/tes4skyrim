"""FO3's bhkConvexListShape, which Skyrim cannot construct, becomes a bhkListShape.

See: docs/commentary/asset_convert_collision.md#convex-list-shapes
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asset_convert.nif import nif_converter
from asset_convert.collision import collision
from pyffi.formats.nif import NifFormat

assert nif_converter


def test_a_convex_list_becomes_a_list_of_its_converted_pieces():
    """Two boxes keep their order and get the Havok rescale, under a bhkListShape."""
    cl = NifFormat.bhkConvexListShape()
    cl.num_sub_shapes = 2
    cl.sub_shapes.update_size()
    for i in range(2):
        box = NifFormat.bhkBoxShape()
        box.dimensions.x = box.dimensions.y = box.dimensions.z = 10.0 * (i + 1)
        cl.sub_shapes[i] = box
    out = collision._convert_shape(cl, NifFormat.NiNode())
    assert isinstance(out, NifFormat.bhkListShape)
    assert [round(s.dimensions.x, 3) for s in out.sub_shapes] == [1.0, 2.0]
    assert out.num_unknown_ints == 2
