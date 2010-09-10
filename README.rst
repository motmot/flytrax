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

Flytrax broadcasts its tracking information over the `Robot Operating
System (ROS) <http://ros.org/>`__. To enable this, do the following:

  1. Make sure the directory with setup.py is called ``flytrax_ros``
  2. Make sure this ``flytrax_ros`` directory is on your ROS_PACKAGE_PATH
  3. Run ``rosmake flytrax_ros``.

See also :ref:`flytrax-screenshot`.
