#!/usr/bin/env python
from __future__ import division
import txros
import numpy as np
from twisted.internet import defer
from vrx import Vrx
from mil_tools import rosmsg_to_numpy
from std_srvs.srv import SetBoolRequest
from mil_tools import quaternion_matrix

___author___ = "Kevin Allen and Alex Perez"


class VrxNavigation(Vrx):
    def __init__(self, *args, **kwargs):
        super(VrxNavigation, self).__init__(*args, **kwargs)

    @txros.util.cancellableInlineCallbacks
    def inspect_object(self, position):
        # Go in front of the object, looking directly at it
        yield self.move.look_at(position).set_position(position).backward(6.0).go()
        yield self.nh.sleep(5.)

    def get_index_of_type(self, objects, classifications):
        if type(classifications) == str:
            classifications = [classifications]
        return next(i for i, o in enumerate(objects) if o.labeled_classification in classifications and o.id not in self.objects_passed)

    @staticmethod
    def get_gate(one, two, position):
        one = one[:2]
        two = two[:2]
        position = position[:2]
        delta = (one - two)[:2]
        rot_right= np.array([[0, -1], [1, 0]], dtype=np.float)
        perp_vec = rot_right.dot(delta)
        perp_vec = perp_vec / np.linalg.norm(perp_vec)
        center = (one + two) / 2.0
        distances = np.array([
            np.linalg.norm((center + perp_vec) - position),
            np.linalg.norm((center - perp_vec) - position)
        ])
        if np.argmin(distances) == 0:
            perp_vec = -perp_vec
        return np.array([center[0], center[1], 0.]), np.array([perp_vec[0], perp_vec[1], 0.])

    @txros.util.cancellableInlineCallbacks
    def go_thru_gate(self, gate, BEFORE=5.0, AFTER=4.0):
        center, vec = gate
        before_position = center - (vec * BEFORE)
        after_position = center + (vec * AFTER)
        yield self.move.set_position(before_position).look_at(center).go()
        if AFTER > 0:
            yield self.move.look_at(after_position).set_position(after_position).go()

    @txros.util.cancellableInlineCallbacks
    def do_next_gate(self):
        pose = yield self.tx_pose
        p = pose[0]
        q_mat = quaternion_matrix(pose[1])

        def filter_and_sort(objects, positions):
            #filter out buoys more than filter_distance behind boat
            filter_distance = -5
            positions_local = np.array([(q_mat.T.dot(position - p)) for position in positions])
            positions_local_x = np.array(positions_local[:, 0])
            forward_indicies = np.argwhere(positions_local_x > filter_distance).flatten()
            forward_indicies = np.array([i for i in forward_indicies if objects[i].id not in self.objects_passed])
            distances = np.linalg.norm(positions_local[forward_indicies], axis=1)
            indicies =  forward_indicies[np.argsort(distances).flatten()].tolist()
            # ids = [objects[i].id for i in indicies]
            # self.send_feedback('Im attracted to {}'.format(ids))
            return indicies

        def is_done(objects, positions):
            try:
                left_index = self.get_index_of_type(objects, ('mb_marker_buoy_green', 'mb_marker_buoy_black'))
                right_index = self.get_index_of_type(objects, 'mb_marker_buoy_red')
            except StopIteration:
                return None

            end = objects[left_index].labeled_classification == 'mb_marker_buoy_black'
            return positions[left_index], objects[left_index], positions[right_index], objects[right_index], end

        left, left_obj, right, right_obj, end = yield self.explore_closest_until(is_done, filter_and_sort)
        self.send_feedback('Going through gate of objects {} and {}'.format(left_obj.labeled_classification, right_obj.labeled_classification))
        gate = self.get_gate(left, right, p)
        yield self.go_thru_gate(gate)
        self.objects_passed.add(left_obj.id)
        self.objects_passed.add(right_obj.id)
        defer.returnValue(end)

    @txros.util.cancellableInlineCallbacks
    def explore_closest_until(self, is_done, filter_and_sort):
        '''
        @conditon func taking in sorted objects, positions
        @object_filter func filters and sorts
        '''
        move_id_tuple = None
        previous_index = None
        previous_cone = None
        init_boat_pos = self.pose[0]
        cone_buoys_investigated = 0 # max will be 2
        service_req = None
        dl = None
        investigated = set()
        while True:
            if move_id_tuple is not None:
                if service_req is None:
                    service_req = self.database_query(name='all')
                dl = defer.DeferredList([service_req, move_id_tuple[0]], fireOnOneCallback=True)
                
                result, index = yield dl

                # Database query succeeded
                if index == 0:
                    service_req = None
                    objects_msg = result
                    classification_index = self.object_classified(objects_msg.objects, move_id_tuple[1])
                    if classification_index != -1:

                        self.send_feedback('{} identified. Canceling investigation'.format(move_id_tuple[1]))
                        yield dl.cancel()
                        yield move_id_tuple[0].cancel()
                        yield self.nh.sleep(1.)

                        if "marker" in objects_msg.objects[classification_index].labeled_classification:
                            previous_cone = previous_index
                            print("updating initial boat pos...")
                            init_boat_pos = rosmsg_to_numpy(objects_msg.objects[classification_index].pose.position)
                            print(init_boat_pos)
                            cone_buoys_investigated += 1

                            if "red" in objects_msg.objects[classification_index].labeled_classification and cone_buoys_investigated < 2:
                                yield self.move.left(3).yaw_left(30, "deg").go()
                            elif cone_buoys_investigated < 2:
                                yield self.move.right(3).yaw_right(30, "deg").go()

                        move_id_tuple = None

                # Move succeeded:
                else:
                    self.send_feedback('Investigated {}'.format(move_id_tuple[1]))
                    move_id_tuple = None
            else:
                objects_msg = yield self.database_query(name='all')
            objects = objects_msg.objects
            #print(len(objects))
            positions = np.array([rosmsg_to_numpy(obj.pose.position) for obj in objects])
            if len(objects) == 0:
                indicies = []
            else:
                indicies = filter_and_sort(objects, positions)
            if indicies is None or len(indicies) == 0:
                self.send_feedback('No objects')
                continue
            objects = [objects[i] for i in indicies]
            #print(len(objects))
            positions = positions[indicies]

            # Exit if done
            ret = is_done(objects, positions)
            if ret is not None:
                if move_id_tuple is not None:
                    self.send_feedback('Condition met. Canceling investigation')
                    yield dl.cancel()
                    yield move_id_tuple[0].cancel()
                    move_id_tuple = None

                defer.returnValue(ret)

            if move_id_tuple is not None:
                continue

            self.send_feedback('ALREADY INVEST {}'.format(investigated))
            
            #### The following is the logic for how we decide what buoy to investigate next ####
            potential_candidate = None
            shortest_distance = 1000

            #check if there are any buoys that have "marker" in the name that haven't been investigated
            #obtain the closest one to the previous gate and deem that the next buoy to investigate
            for i in xrange(len(objects)):
                
                if "marker" in objects[i].labeled_classification and objects[i].id not in investigated:
                    distance = np.linalg.norm(positions[i] - init_boat_pos)
                    if distance < shortest_distance:
                        shortest_distance = distance
                        print(shortest_distance)
                        print(positions[i])
                        print("POTENTIAL CANDIDATE: IDENTIFIED THROUGH MARKER THAT HAS NOT BEEN INVESTIGATED")
                        potential_candidate = i

            #if there no known cone buoys that haven't been investigated, check if we have already investigated one
            #and find closest one within 25 meters (max width of a gate).
            if cone_buoys_investigated > 0 and potential_candidate is None:
                for i in xrange(len(objects)):
                    print(positions[i])
                    if objects[i].id not in investigated and "round" not in objects[i].labeled_classification:
                        distance = np.linalg.norm(positions[i] - init_boat_pos)
                        if distance < shortest_distance and distance <= 25:
                            shortest_distance = distance
                            print(shortest_distance)
                            print(positions[i])
                            print("POTENTIAL CANDIDATE: IDENTIFIED BY FINDING CLOSEST CONE TO ALREADY INVESTIGATED CONE (<25m)")
                            potential_candidate = i

            #if that doesn't produce any results, literally just go to closest buoy
            if potential_candidate is None:
                for i in xrange(len(objects)):
            
                    if objects[i].id not in investigated and "round" not in objects[i].labeled_classification:
                        distance = np.linalg.norm(positions[i] - init_boat_pos)
                        if distance < shortest_distance:
                            shortest_distance = distance
                            print(shortest_distance)
                            print(positions[i])
                            print("POTENTIAL CANDIDATE: IDENTIFIED BY FINDING CLOSEST CONE TO INIT BOAT POS")
                            potential_candidate = i
                            print(positions[i])

            #explore the closest buoy to potential candidate
            if potential_candidate is not None:
                
                #if there exists a closest buoy, go to it
                self.send_feedback('Investigating {}'.format(objects[potential_candidate].id))
                investigated.add(objects[potential_candidate].id)
                move = self.inspect_object(positions[potential_candidate])
                move_id_tuple = (move, objects[potential_candidate].id)
                previous_index = potential_candidate
                print("USING POTENTIAL CANDIDATE")

            if move_id_tuple is None:
                self.send_feedback('!!!! NO MORE TO EXPLORE')
                raise Exception('no more to explore')

    def get_objects_indicies_for_start(self, objects):
        try:
            white_index = self.get_index_of_type(objects, 'mb_marker_buoy_white')
            red_index = self.get_index_of_type(objects, 'mb_marker_buoy_red')
        except StopIteration:
            return None
        return white_index, red_index

    @staticmethod
    def object_classified(objects, obj_id):
        '''
        @objects list of object messages
        @obj_id id of object
        @return True of object with obj_id is classified
        '''
        for i,obj in enumerate(objects):
            if obj.id == obj_id:
                if obj.labeled_classification != "UNKNOWN":
                    return i
        return -1

    @txros.util.cancellableInlineCallbacks
    def prepare_to_enter(self):
        closest = []
        robot_position = (yield self.tx_pose)[0]
        def filter_and_sort(objects, positions):
            distances = np.linalg.norm(positions - robot_position, axis=1)
            argsort = np.argsort(distances)
            return argsort

        def is_done(objects, positions):
            res = self.get_objects_indicies_for_start(objects)
            if res is None:
                return None
            white_index, red_index = res
            return objects[white_index], positions[white_index], objects[red_index], positions[red_index]

        white, white_position, red, red_position = yield self.explore_closest_until(is_done, filter_and_sort)
        self.objects_passed.add(white.id)
        self.objects_passed.add(red.id)
        gate = self.get_gate(white_position, red_position, robot_position)
        self.send_feedback('Going through start gate formed by {} and {}'.format(white.labeled_classification, red.labeled_classification))
        yield self.go_thru_gate(gate, AFTER=-2)

    @txros.util.cancellableInlineCallbacks
    def run(self, parameters):
        '''
        TODO: check for new objects in background, cancel move
              somefucking how handle case where gates litteraly loop back and head the other direction
        '''
        self.objects_passed = set()
        # Wait a bit for PCDAR to get setup
        yield self.nh.sleep(3.0)
        yield self.set_vrx_classifier_enabled(SetBoolRequest(data=True))
        yield self.prepare_to_enter()
        yield self.wait_for_task_such_that(lambda task: task.state =='running')
        yield self.move.forward(7.0).go()
        while not (yield self.do_next_gate()):
            pass
        self.send_feedback('Exiting last gate!! Go NaviGator')
        yield self.set_vrx_classifier_enabled(SetBoolRequest(data=False))

