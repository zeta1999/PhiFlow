from __future__ import annotations

from phi import math
from phi.math import AbstractTensor


class Geometry:
    """
    Abstract base class for N-dimensional shapes.

    Main implementing classes:

    * Sphere
    * box family: box (generator), AABox, Cuboid, AbstractBox

    All geometry objects support batching.
    Thereby any parameter defining the geometry can be varied along arbitrary batch dimensions.
    All batch dimensions are listed in Geometry.shape.
    """

    @property
    def center(self):
        """
        :return: center location in single channel dimension, ordered according to GLOBAL_AXIS_ORDER
        :rtype: AbstractTensor
        """
        raise NotImplementedError()

    @property
    def shape(self):
        raise NotImplementedError()

    @property
    def rank(self):
        return self.shape.spatial.rank

    def lies_inside(self, location) -> AbstractTensor:
        """
        Tests whether the given location lies inside or outside of the geometry. Locations on the surface count as inside.

        :param location: float tensor of shape (batch_size, ..., rank)
        :return: bool tensor of shape (*location.shape[:-1], 1).
        """
        raise NotImplementedError(self.__class__)

    def approximate_signed_distance(self, location) -> AbstractTensor:
        """
        Computes the approximate distance from location to the surface of the geometry.
        Locations outside return positive values, inside negative values and zero exactly at the boundary.

        The exact distance metric used depends on the geometry.
        The approximation holds close to the surface and the distance grows to infinity as the location is moved infinitely far from the geometry.
        The distance metric is differentiable and its gradients are bounded at every point in space.

        :param location: float tensor of shape (batch_size, ..., rank)
        :return: float tensor of shape (*location.shape[:-1], 1).
        """
        raise NotImplementedError(self.__class__)

    def approximate_fraction_inside(self, other_geometry) -> AbstractTensor:
        """
        Computes the approximate overlap between the geometry and a small other geometry.
        Returns 1.0 if `other_geometry` is fully enclosed in this geometry and 0.0 if there is no overlap.
        Close to the surface of this geometry, the fraction filled is differentiable w.r.t. the location and size of `other_geometry`.

        To call this method on batches of geometries of same shape, pass a batched Geometry instance.
        The result tensor will match the batch shape of `other_geometry`.

        The result may only be accurate in special cases.
        The given geometries may be approximated as spheres or boxes using `bounding_radius()` and `bounding_half_extent()`.

        The default implementation of this method approximates other_geometry as a Sphere and computes the fraction using `approximate_signed_distance()`.

        :param other_geometry: (batched) Geometry instance
        :return: fraction of cell volume lying inside the geometry. float tensor of shape (other_geometry.batch_shape, 1).
        """
        assert isinstance(other_geometry, Geometry)
        radius = other_geometry.bounding_radius()
        location = other_geometry.center
        distance = self.approximate_signed_distance(location)
        inside_fraction = 0.5 - distance / radius
        inside_fraction = math.clip(inside_fraction, 0, 1)
        return inside_fraction

    def bounding_radius(self) -> AbstractTensor:
        """
        Returns the radius of a Sphere object that fully encloses this geometry.
        The sphere is centered at the center of this geometry.

        :return: radius of type float
        """
        raise NotImplementedError(self.__class__)

    def bounding_half_extent(self) -> AbstractTensor:
        """
        The bounding half-extent sets a limit on the outer-most point for each coordinate axis.
        Each component is non-negative.

        Let the bounding half-extent have value `e` in dimension `d` (`extent[...,d] = e`).
        Then, no point of the geometry lies further away from its center point than `e` along `d` (in both axis directions).

        :return: float vector
        """
        raise NotImplementedError(self.__class__)

    def shifted(self, delta) -> Geometry:
        """
        Returns a translated version of this geometry.
        :param delta: direction vector
        :return: shifted geometry
        :rtype: Geometry
        """
        raise NotImplementedError(self.__class__)

    def rotated(self, angle) -> Geometry:
        """
        Returns a rotated version of this geometry.
        The geometry is rotated about its center point.

        :param angle: scalar (2d) or vector (3D+) representing delta angle
        :return: rotated geometry
        :rtype: Geometry
        """
        raise NotImplementedError(self.__class__)
