#!/usr/bin/env python
import roslib; roslib.load_manifest('flytrax_ros')
import rospy
from flytrax_ros.msg import FlytraxInfo, TrackedObject, TrackerInfo, Detection
import numpy as np
import adskalman.adskalman as adskalman
import threading

FPS = 24.0
DEATH_THRESHOLD = 10.0
MAX_ACCEPT_DIST = 10.0
Qsigma = 0.1
Rsigma = 0.1

class KalmanObjectTracker(object):
    def __init__(self, observation, dt, obj_id):
        self.obj_id = obj_id

        # process model
        A = np.array([[1, 0, dt, 0],
                      [0, 1, 0, dt],
                      [0, 0, 1,  0],
                      [0, 0, 0,  1]],
                     dtype=np.float64)
        # observation model
        C = np.array([[1, 0, 0, 0],
                      [0, 1, 0, 0]],
                     dtype=np.float64)
        # process covariance
        Q = Qsigma*np.eye(4)
        # measurement covariance
        R = Rsigma*np.eye(2)

        initP = DEATH_THRESHOLD/4*0.9*np.eye(4) # initialize to 90% of the death threshold

        # initial state vector has zero velocity
        x = np.array([observation.x, observation.y, 0, 0])

        # initialize kalman filter
        self.kf = adskalman.KalmanFilter(A,C,Q,R,x,initP)
        self.kf.step(y=self._to_kf_observation(observation),isinitial=True)

    def close(self):
        # nothing to do for now...
        pass

    def _to_kf_observation(self,observation):
        if observation is None:
            return None
        return np.array( [observation.x, observation.y] )

    def to_ROS(self):
        result = TrackedObject()
        result.x, result.y, result.x_vel, result.y_vel = self.kf.xhat_k1
        result.obj_id = self.obj_id
        result.covariance_trace = self.calcuate_covariance_trace()
        return result

    def get_distance_vec(self, observations):
        xhatminus, Pminus = self.kf.step1__calculate_a_priori()

        # for now, just use Euclidean distance between 2D positions
        xys = np.array([(tobj.x,tobj.y) for tobj in observations])
        dists_2d = xys - xhatminus[:2]
        dists = np.sqrt(np.sum(dists_2d**2,axis=1))

        return dists

    def update(self,observation):
        y = self._to_kf_observation(observation)
        self.kf.step(y=y,isinitial=False)

    def calcuate_covariance_trace(self):
        trace = np.sum(np.diag(self.kf.P_k1))
        return trace

class Tracker(object):
    def __init__(self):
        self._flytrax_info_subscriber = None
        self._input_topic_prefix = ''
        self._input_topic_prefix_changed()
        self.publisher_lock = threading.Lock()
        self.publisher = None
        self._output_topic_prefix = ''
        self._output_topic_prefix_changed()
        self.tracked_objects = []
        self.next_id = 0

    def _input_topic_prefix_changed(self):
        if self._flytrax_info_subscriber is not None:
            # how to de-subscribe?
            raise NotImplementedError('')
        self._flytrax_info_subscriber = rospy.Subscriber('%s/flytrax_info'%self._input_topic_prefix,
                                                         FlytraxInfo,
                                                         self.flytrax_info_callback)

    def _output_topic_prefix_changed(self):
        with self.publisher_lock:
            # unregister old publisher
            if self.publisher is not None:
                self.publisher.unregister()

            # register a new publisher
            self.publisher = rospy.Publisher('%s/tracker_info'%self._output_topic_prefix,
                                             TrackerInfo,
                                             tcp_nodelay=True,
                                             )



    def flytrax_info_callback(self,flytrax_info):
        # We got position updates from flytrax.

        detections = flytrax_info.detections # shorthand

        unclaimed_objects = self._data_association( detections )
        self._do_object_births(unclaimed_objects)
        self._do_object_deaths()

        msg = TrackerInfo()
        msg.framenumber = flytrax_info.framenumber
        msg.stamp = flytrax_info.stamp
        msg.tracked_objects = [obj.to_ROS() for obj in self.tracked_objects]

        with self.publisher_lock:
            self.publisher.publish(msg)


    def _data_association(self, detections):
        # Do data association using "nearest-neighbor standard filter"
        # algorithm.
        distances = []
        for obj in self.tracked_objects:
            distances.append( obj.get_distance_vec( detections ) )

        if len(distances):
            distances = np.array(distances) # NxM array (N = number of objects, M = number of detections)

            closest_idxs = np.argmin(distances, axis=1)

            claimed_idxs = set()
            for i,obj in enumerate(self.tracked_objects):
                closest_idx = closest_idxs[i]
                closest_dist = distances[i, closest_idx]
                if closest_dist <= MAX_ACCEPT_DIST:
                    claimed_idxs.add( int(closest_idx) )
                    obj.update( detections[ closest_idx ] )
                else:
                    obj.update( None )

            all_idxs = set(range(len(detections)))
            unclaimed_idxs = all_idxs - claimed_idxs
            unclaimed_detections = [detections[i] for i in unclaimed_idxs]
        else:
            unclaimed_detections = detections
        return unclaimed_detections

    def _do_object_births(self,unclaimed_detections):
        for unclaimed_detection in unclaimed_detections:
            # birth of new tracked objects
            new_obj = KalmanObjectTracker( unclaimed_detection, 1.0/FPS, self.next_id )
            self.next_id += 1
            self.tracked_objects.append( new_obj )

    def _do_object_deaths(self):
        # death of old tracked objects
        remove_objects = []
        for i,obj in enumerate(self.tracked_objects):
            if obj.calcuate_covariance_trace() > DEATH_THRESHOLD:
                remove_objects.append(i)

        remove_objects.reverse() # go from end to start so we don't screw up order
        for i in remove_objects:
            self.tracked_objects[i].close()
            del self.tracked_objects[i]

if __name__ == '__main__':
    rospy.init_node('tracker', anonymous=True)
    tracker = Tracker()
    rospy.spin()

