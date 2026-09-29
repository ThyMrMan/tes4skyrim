"""Phantom collision objects: a shape phantom is kept, a bare AABB phantom dropped.

See: docs/commentary/asset_convert_collision.md#phantom-collision-objects
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asset_convert.nif import nif_converter
from asset_convert.collision import collision
from pyffi.formats.nif import NifFormat

assert nif_converter


def _node_with(collision_type, body):
    """A root NiNode whose collision object of *collision_type* holds *body*."""
    node = NifFormat.NiNode()
    co = getattr(NifFormat, collision_type)()
    co.body = body
    co.target = node
    node.collision_object = co
    return node


def test_aabb_phantom_is_dropped():
    """bhkPCollisionObject + bhkAabbPhantom leaves no collision, not a crash."""
    node = _node_with('bhkPCollisionObject', NifFormat.bhkAabbPhantom())
    collision.convert_all_collisions(node)
    assert node.collision_object is None


def test_shape_phantom_under_p_collision_object_is_kept():
    """A bhkSimpleShapePhantom keeps its holder, flags 129, as under bhkSP."""
    phantom = NifFormat.bhkSimpleShapePhantom()
    phantom.shape = NifFormat.bhkSphereShape()
    phantom.shape.radius = 10.0
    node = _node_with('bhkPCollisionObject', phantom)
    collision.convert_all_collisions(node)
    assert node.collision_object is not None
    assert node.collision_object.flags == 129
