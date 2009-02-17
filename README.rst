**************************************************************************
:mod:`flytrax` - fview plugin for tracking 2D points in realtime
**************************************************************************

.. module:: flytrax
  :synopsis: fview plugin for tracking 2D points in realtime
.. index::
  module: flytrax
  single: flytrax

Flytrax is a plugin for :mod:`fview` to track a single point in
realtime. It saves (X,Y) position, orientation, and small
(spatially-cropped) movies that follow the tracked point. It uses
background subtraction with optional online updating to deal with
slowly changing lighting conditions.

See also :ref:`flytrax-screenshot`.
