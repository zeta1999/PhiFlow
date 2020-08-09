import itertools
from functools import wraps

import numpy as np
from phi import math
from phi.geom import AABox
from phi.field import StaggeredGrid, ConstantField, Grid, CenteredGrid
from ._field import Field, SampledField


def expose_tensors(field_function, *proto_fields):
    @wraps(field_function)
    def wrapper(*field_data):
        fields = [proto.with_data(data) for data, proto in zip(field_data, proto_fields)]
        return field_function(*fields).data
    return wrapper


def conjugate_gradient(function, y: Grid, x0: Grid, relative_tolerance: float = 1e-5, absolute_tolerance: float = 0.0, max_iterations: int = 1000, gradient: str = 'implicit', callback=None):
    if callback is not None:
        def field_callback(x):
            x = x0.with_data(x)
            callback(x)
    else:
        field_callback = None

    data_function = expose_tensors(function, y)
    converged, x, iterations = math.conjugate_gradient(data_function, y.data, x0.data, relative_tolerance, absolute_tolerance, max_iterations, gradient, field_callback)
    return converged, x0.with_data(x), iterations


def data_bounds(field: SampledField):
    data = field.points
    min_vec = math.min(data, axis=data.shape.spatial.names)
    max_vec = math.max(data, axis=data.shape.spatial.names)
    return AABox(min_vec, max_vec)


def extrapolate(input_field, valid_mask, voxel_distance=10):
    """
    Create a signed distance field for the grid, where negative signs are fluid cells and positive signs are empty cells. The fluid surface is located at the points where the interpolated value is zero. Then extrapolate the input field into the air cells.
        :param domain: Domain that can create new Fields
        :param input_field: Field to be extrapolated
        :param valid_mask: One dimensional binary mask indicating where fluid is present
        :param voxel_distance: Optional maximal distance (in number of grid cells) where signed distance should still be calculated / how far should be extrapolated.
        :return: ext_field: a new Field with extrapolated values, s_distance: tensor containing signed distance field, depending only on the valid_mask
    """
    ext_data = input_field.data
    dx = input_field.dx
    if isinstance(input_field, StaggeredGrid):
        ext_data = input_field.staggered_tensor()
        valid_mask = math.pad(valid_mask, [[0, 0]] + [[0, 1]] * input_field.rank + [[0, 0]], "constant")

    dims = range(input_field.rank)
    # Larger than voxel_distance to be safe. It could start extrapolating velocities from outside voxel_distance into the field.
    signs = -1 * (2 * valid_mask - 1)
    s_distance = 2.0 * (voxel_distance + 1) * signs
    surface_mask = create_surface_mask(valid_mask)

    # surface_mask == 1 doesn't output a tensor, just a scalar, but >= works.
    # Initialize the voxel_distance with 0 at the surface
    # Previously initialized with -0.5*dx, i.e. the cell is completely full (center is 0.5*dx inside the fluid surface). For stability and looks this was changed to 0 * dx, i.e. the cell is only half full. This way small changes to the SDF won't directly change neighbouring empty cells to fluid cells.
    s_distance = math.where((surface_mask >= 1), -0.0 * math.ones_like(s_distance), s_distance)

    directions = np.array(list(itertools.product(
        *np.tile((-1, 0, 1), (len(dims), 1))
    )))

    # First make a move in every positive direction (StaggeredGrid velocities there are correct, we want to extrapolate these)
    if isinstance(input_field, StaggeredGrid):
        for d in directions:
            if (d <= 0).all():
                continue

            # Shift the field in direction d, compare new distances to old ones.
            d_slice = tuple(
                [(slice(1, None) if d[i] == -1 else slice(0, -1) if d[i] == 1 else slice(None)) for i in dims])

            d_field = math.pad(ext_data,
                               [[0, 0]] + [([0, 1] if d[i] == -1 else [1, 0] if d[i] == 1 else [0, 0]) for i in
                                           dims] + [[0, 0]], "symmetric")
            d_field = d_field[(slice(None),) + d_slice + (slice(None),)]

            d_dist = math.pad(s_distance,
                              [[0, 0]] + [([0, 1] if d[i] == -1 else [1, 0] if d[i] == 1 else [0, 0]) for i in dims] + [
                                  [0, 0]], "symmetric")
            d_dist = d_dist[(slice(None),) + d_slice + (slice(None),)]
            d_dist += np.sqrt((dx * d).dot(dx * d)) * signs

            if (d.dot(d) == 1) and (d >= 0).all():
                # Pure axis direction (1,0,0), (0,1,0), (0,0,1)
                updates = (math.abs(d_dist) < math.abs(s_distance)) & (surface_mask <= 0)
                updates_velocity = updates & (signs > 0)
                ext_data = math.where(
                    math.concat([(math.zeros_like(updates_velocity) if d[i] == 1 else updates_velocity) for i in dims],
                                axis=-1), d_field, ext_data)
                s_distance = math.where(updates, d_dist, s_distance)
            else:
                # Mixed axis direction (1,1,0), (1,1,-1), etc.
                continue

    for _ in range(voxel_distance):
        buffered_distance = 1.0 * s_distance  # Create a copy of current voxel_distance. This should not be necessary...
        for d in directions:
            if (d == 0).all():
                continue

            # Shift the field in direction d, compare new distances to old ones.
            d_slice = tuple(
                [(slice(1, None) if d[i] == -1 else slice(0, -1) if d[i] == 1 else slice(None)) for i in dims])

            d_field = math.pad(ext_data,
                               [[0, 0]] + [([0, 1] if d[i] == -1 else [1, 0] if d[i] == 1 else [0, 0]) for i in
                                           dims] + [[0, 0]], "symmetric")
            d_field = d_field[(slice(None),) + d_slice + (slice(None),)]

            d_dist = math.pad(s_distance, [[0, 0]] + [([0, 1] if d[i] == -1 else [1, 0] if d[i] == 1 else [0, 0]) for i in dims] + [[0, 0]], "symmetric")
            d_dist = d_dist[(slice(None),) + d_slice + (slice(None),)]
            d_dist += np.sqrt((dx * d).dot(dx * d)) * signs

            # We only want to update velocity that is outside of fluid
            updates = (math.abs(d_dist) < math.abs(buffered_distance)) & (surface_mask <= 0)
            updates_velocity = updates & (signs > 0)
            ext_data = math.where(math.concat([updates_velocity] * math.spatial_rank(ext_data), axis=-1), d_field, ext_data)
            buffered_distance = math.where(updates, d_dist, buffered_distance)

        s_distance = buffered_distance

    # Cut off inaccurate values
    distance_limit = -voxel_distance * (2 * valid_mask - 1)
    s_distance = math.where(math.abs(s_distance) < voxel_distance, s_distance, distance_limit)

    if isinstance(input_field, StaggeredGrid):
        ext_field = input_field.with_data(ext_data)
        stagger_slice = tuple([slice(0, -1) for i in dims])
        s_distance = s_distance[(slice(None),) + stagger_slice + (slice(None),)]
    else:
        ext_field = input_field.copied_with(data=ext_data)

    return ext_field, s_distance


def create_surface_mask(liquid_mask):
    """
Computes inner contours of the liquid_mask.
A cell i is flagged 1 if liquid_mask[i] = 1 and it has a non-liquid neighbour.
    :param liquid_mask: binary tensor
    :return: tensor
    """
    # When we create inner contour, we don't want the fluid-wall boundaries to show up as surface, so we should pad with symmetric edge values.
    mask = math.pad(liquid_mask, [[0, 0]] + [[1, 1]] * math.spatial_rank(liquid_mask) + [[0, 0]], "constant")
    dims = range(math.spatial_rank(mask))
    bcs = math.zeros_like(liquid_mask)

    # Move in every possible direction to assure corners are properly set.
    directions = np.array(list(itertools.product(
        *np.tile((-1, 0, 1), (len(dims), 1))
    )))

    for d in directions:
        d_slice = tuple([(slice(2, None) if d[i] == -1 else slice(0, -2) if d[i] == 1 else slice(1, -1)) for i in dims])
        center_slice = tuple([slice(1, -1) for _ in dims])

        # Create inner contour of particles
        bc_d = math.maximum(mask[(slice(None),) + d_slice + (slice(None),)],
                            mask[(slice(None),) + center_slice + (slice(None),)]) - \
               mask[(slice(None),) + d_slice + (slice(None),)]
        bcs = math.maximum(bcs, bc_d)
    return bcs