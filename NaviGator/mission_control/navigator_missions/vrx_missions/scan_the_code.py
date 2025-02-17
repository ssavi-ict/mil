#!/usr/bin/env python
from turtle import width
import txros
import numpy as np
from vrx import Vrx
from twisted.internet import defer
from sensor_msgs.msg import PointCloud2
from mil_tools import numpy_to_pointcloud2 as np2pc2, rosmsg_to_numpy
from mil_vision_tools.cv_tools import rect_from_roi, roi_enclosing_points, contour_mask
from image_geometry import PinholeCameraModel
from sensor_msgs.msg import Image, CameraInfo
from operator import attrgetter
from std_srvs.srv import SetBoolRequest
from navigator_vision import VrxStcColorClassifier
from cv_bridge import CvBridge
import cv2
from vrx_gazebo.srv import ColorSequenceRequest, ColorSequence
from mil_msgs.srv import ObjectDBQuery, ObjectDBQueryRequest
from dynamic_reconfigure.msg import DoubleParameter

LED_PANNEL_MAX  = 0.25
LED_PANNEL_MIN = 0.6

STC_HEIGHT = 2.3
STC_WIDTH = 2

CAMERA_LINK_OPTICAL = 'wamv/front_left_camera_link_optical'

COLOR_SEQUENCE_SERVICE = '/vrx/scan_dock_deliver/color_sequence'

TIMEOUT_SECONDS = 30

class ScanTheCode(Vrx):

    def __init__(self, *args, **kwargs):
        super(ScanTheCode, self).__init__(*args, **kwargs)
        self.classifier = VrxStcColorClassifier()
        self.classifier.train_from_csv()
        self.camera_model = PinholeCameraModel()

    @txros.util.cancellableInlineCallbacks
    def run(self, args):
        self.debug_points_pub = self.nh.advertise('/stc_led_points', PointCloud2)
        self.bridge = CvBridge()
        self.image_debug_pub = self.nh.advertise('/stc_mask_debug', Image)
        self.sequence_report = self.nh.get_service_client(COLOR_SEQUENCE_SERVICE, ColorSequence)

        self.init_front_left_camera()
        self.init_front_right_camera()

        yield self.set_vrx_classifier_enabled(SetBoolRequest(data=False))
        info = yield self.front_left_camera_info_sub.get_next_message()
        self.camera_model.fromCameraInfo(info)

        pcodar_cluster_tol = DoubleParameter()
        pcodar_cluster_tol.name = 'cluster_tolerance_m'
        pcodar_cluster_tol.value = 6

        yield self.pcodar_set_params(doubles = [pcodar_cluster_tol])
        try:
            pose = yield self.find_stc2()
        except Exception as e:
            sequence = ['red', 'green', 'blue']
            yield self.report_sequence(sequence)
            defer.returnValue(sequence)

        yield self.move.look_at(pose).set_position(pose).backward(5).go()
        yield self.nh.sleep(5)
        
        try:
            sequence = yield txros.util.wrap_timeout(self.get_sequence(), TIMEOUT_SECONDS, 'Guessing RGB')
        except txros.util.TimeoutError:
            sequence = ['red', 'green', 'blue']
        print('Scan The Code Color Sequence', sequence)
        self.report_sequence(sequence)
        yield self.send_feedback('Done!')
        defer.returnValue(sequence)

    @txros.util.cancellableInlineCallbacks
    def get_sequence(self):
        sequence = []
        while len(sequence) < 3:

            img = yield self.front_left_camera_sub.get_next_message()
            bounding_box_msg = yield self.darknet_objects.get_next_message()

            img = self.bridge.imgmsg_to_cv2(img)
            img2 = img.copy()

            _,width,height = img.shape[::-1]
            xmin = bounding_box_msg.bounding_boxes[0].xmin
            xmax = bounding_box_msg.bounding_boxes[0].xmax
            ymin = bounding_box_msg.bounding_boxes[0].ymin
            ymax = bounding_box_msg.bounding_boxes[0].ymax

            cen_pixel_col = (xmin + xmax) / 2
            cen_pixel_row = (ymin + ymax) / 2
        
            if cen_pixel_col > 2*width/3 or cen_pixel_col < width/3:
                print("too far left or right")
                continue

            #general location that allows 
            bl_pixel_col = cen_pixel_col - 15
            bl_pixel_row = cen_pixel_row + 15
            tr_pixel_col = cen_pixel_col + 15
            tr_pixel_row = cen_pixel_row - 15

            #bl br tr tl cen
            b_comp = [0,0,0,0,0]
            g_comp = [0,0,0,0,0]
            r_comp = [0,0,0,0,0]

            b_comp[0] = int(img[bl_pixel_row][bl_pixel_col][2])
            g_comp[0] = int(img[bl_pixel_row][bl_pixel_col][1])
            r_comp[0] = int(img[bl_pixel_row][bl_pixel_col][0])
            b_comp[1] = int(img[bl_pixel_row][tr_pixel_col][2])
            g_comp[1] = int(img[bl_pixel_row][tr_pixel_col][1])
            r_comp[1] = int(img[bl_pixel_row][tr_pixel_col][0])
            b_comp[2] = int(img[tr_pixel_row][tr_pixel_col][2])
            g_comp[2] = int(img[tr_pixel_row][tr_pixel_col][1])
            r_comp[2] = int(img[tr_pixel_row][tr_pixel_col][0])
            b_comp[3] = int(img[tr_pixel_row][bl_pixel_col][2])
            g_comp[3] = int(img[tr_pixel_row][bl_pixel_col][1])
            r_comp[3] = int(img[tr_pixel_row][bl_pixel_col][0])
            b_comp[4] = int(img[cen_pixel_row][cen_pixel_col][2])
            g_comp[4] = int(img[cen_pixel_row][cen_pixel_col][1])
            r_comp[4] = int(img[cen_pixel_row][cen_pixel_col][0])

            #target cell for debugging purposes
            for i in range(len(img2)):
                img2[i][bl_pixel_col] = [255,255,255]
            for i in range(len(img2[0])):
                img2[bl_pixel_row][i] = [255,255,255]
            for i in range(len(img2)):
                img2[i][tr_pixel_col] = [255,255,255]
            for i in range(len(img2[0])):
                img2[tr_pixel_row][i] = [255,255,255]
            img2[cen_pixel_row][cen_pixel_col] = [255,255,255]
            mask_msg = self.bridge.cv2_to_imgmsg(img2, "rgb8")
            self.image_debug_pub.publish(mask_msg)

            most_likely_name = "none"

            for i in range(len(b_comp)):
                if r_comp[i] > 2*b_comp[i] and r_comp[i] > 2*g_comp[i]:
                    most_likely_name = "red"
                    break
                elif b_comp[i] > 2*r_comp[i] and b_comp[i] > 2*g_comp[i]:
                    most_likely_name = "blue"
                    break
                elif g_comp[i] > 2*r_comp[i] and g_comp[i] > 2*b_comp[i]:
                    most_likely_name = "green"
                    break
                elif r_comp[i] > 2*b_comp[i] and g_comp[i] > 2*b_comp[i]:
                    most_likely_name = "yellow"
                    break
                elif ( (abs(r_comp[i]-b_comp[i]) < 20) and (abs(r_comp[i]-g_comp[i]) < 20) and (abs(b_comp[i]-g_comp[i]) < 20) and (r_comp[i] < 125) ):
                    most_likely_name = "black"

            if most_likely_name == "none":
                continue
            if most_likely_name == "black":
                sequence = []
            elif sequence == [] or most_likely_name != sequence[-1]:
                sequence.append(most_likely_name)

            print(sequence)
        defer.returnValue(sequence)

    @txros.util.cancellableInlineCallbacks
    def report_sequence(self, sequence):
        color_sequence = ColorSequenceRequest()
        color_sequence.color1 = sequence[0]
        color_sequence.color2 = sequence[1]
        color_sequence.color3 = sequence[2]

        try:
            yield self.sequence_report(color_sequence)
        except Exception as e: #catch error incase vrx scroing isnt running
            print(e)


    @txros.util.cancellableInlineCallbacks
    def find_stc2(self):
        pose = None
        print("entering find_stc")
        # see if we already got scan the code tower
        try:
            _, poses = yield self.get_sorted_objects(name='stc_platform', n=1)
            pose = poses[0]
        # incase stc platform not already identified
        except Exception as e:
            print("could not find stc_platform")
            # get all pcodar objects
            try:
                print("check for any objects")
                msgs, poses = yield self.get_sorted_objects(name='UNKNOWN', n=-1)
            # if no pcodar objects, drive forward
            except Exception as e:
                print("literally no objects?")
                yield self.move.forward(25).go()
                # get first pcodar objects
                msgs, poses = yield self.get_sorted_objects(name='UNKNOWN', n=-1)
                # if still no pcodar objects, guess RGB and exit mission
            # go to nearest obj to get better data on that obj
            
            print('going to nearest small object')

            # determine the dock and stc_buoy based on cluster size
            dock_pose = None
            for i in range(len(msgs)):
                #Sometimes the dock is perceived as multiple objects
                #Ignore any objects that are the dock
                #I haven't found an overlap for a cluster tolerance that
                #keeps the entire dock together 100% of the time
                #while not including the stc buoy if it is too close
                #if dock_pose is not None and \
                #    np.linalg.norm(dock_pose[0] - poses[i][0]) < 10:
                #    continue

                if np.linalg.norm(rosmsg_to_numpy(msgs[i].scale)) > 4.0:
                    # much bigger than scale of stc
                    # then we found the dock
                    yield self.pcodar_label(msgs[i].id, 'dock')
                    dock_pose = poses[i]

                else: # if about same size as stc, lable it stc
                    yield self.pcodar_label(msgs[i].id, 'stc_platform')
                    pose = poses[i]
                    break

        print("leaving find_stc")
        defer.returnValue(pose)

    @txros.util.cancellableInlineCallbacks
    def find_stc(self):
        pose = None
        print("entering find_stc")
        # see if we already got scan the code tower
        try:
            _, poses = yield self.get_sorted_objects(name='stc_platform', n=1)
            pose = poses[0]
        # incase stc platform not already identified
        except Exception as e:
            print("could not find stc_platform")
            # get all pcodar objects
            try:
                print("check for any objects")
                _, poses = yield self.get_sorted_objects(name='UNKNOWN', n=-1)
            # if no pcodar objects, drive forward
            except Exception as e:
                print("literally no objects?")
                yield self.move.forward(50).go()
                # get all pcodar objects
                _, poses = yield self.get_sorted_objects(name='UNKNOWN', n=-1)
                # if still no pcodar objects, guess RGB and exit mission
            # go to nearest obj to get better data on that obj
            print('going to nearest object')
            yield self.move.set_position(poses[0]).go()
            # get data on closest obj
            msgs, poses = yield self.get_sorted_objects(name='UNKNOWN', n=1)
            if np.linalg.norm(rosmsg_to_numpy(msgs[0].scale)) > 6.64:
                # much bigger than scale of stc
                # then we found the dock
                yield self.pcodar_label(msgs[0].id, 'dock')
                # get other things
                msgs, poses = yield self.get_sorted_objects(name='UNKNOWN', n=1)
                # if no other things, throw error and exit mission
                yield self.pcodar_label(msgs[0].id, 'stc_platform')
                pose = poses[0]
            else: # if about same size as stc, lable it stc
                yield self.pcodar_label(msgs[0].id, 'stc_platform')
                pose = poses[0]

        print("leaving find_stc")
        defer.returnValue(pose)

def z_filter(db_obj_msg):
    # do a z filter for the led points
    top = max(db_obj_msg.points, key=attrgetter('z')).z
    points = np.array([[i.x, i.y, i.z] for i in db_obj_msg.points 
                        if i.z < top-LED_PANNEL_MAX and i.z > top-LED_PANNEL_MIN])
    return points

def bbox_from_rect(rect):
    bbox = np.array([[rect[0][0], rect[0][1]],
                     [rect[1][0], rect[0][1]],
                     [rect[1][0], rect[1][1]],
                     [rect[0][0], rect[1][1]]])
    return bbox
