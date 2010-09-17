from __future__ import division

# FlyTrax is multi-camera aware. That's why there is so much cam_id
# stuff in here. When/if fview gets re-written to do multiple cameras,
# FlyTrax should be ready to go.

# XXX ROI isn't implemented as fast as could be. First, a full frame
# is sent to do_work() for analysis. Second, a new full-frame buffer
# is allocated for each incoming frame. That could be cached and
# recycled.

# There are 3 levels of ROIs implemented:

#  1) At the hardware (camera) level. This is handled transparently by
#  fview.

#  2) At the software level. This is handled mostly transparently by
#  the use_roi2 parameter passed to realtime_analyzer.do_work(). This
#  gets called "software ROI" in GUI.

#  3) Display/Save/Send ROIs. These are collected by
#  _process_frame_extract_roi() during the process_frame() call.

import sys, threading, Queue, time, socket, math, struct, os, warnings, re
import pkg_resources
import traxio

import motmot.wxvideo.wxvideo as wxvideo
import motmot.imops.imops as imops
import motmot.FastImage.FastImage as FastImage

import motmot.realtime_image_analysis.realtime_image_analysis as realtime_image_analysis

import numpy

import motmot.wxvalidatedtext.wxvalidatedtext as wxvt

import wx
from wx import xrc
import scipy.io

try:
    import roslib
    have_ROS = True
except ImportError, err:
    have_ROS = False

if have_ROS:
    roslib.load_manifest('flytrax_ros')
    import flytrax_ros
    from flytrax_ros.msg import FlytraxInfo, Detection
    from sensor_msgs.msg import Image
    import rospy
    import rospy.core

RESFILE = pkg_resources.resource_filename(__name__,"flytrax.xrc") # trigger extraction
RES = xrc.EmptyXmlResource()
RES.LoadFromString(open(RESFILE).read())
BGROI_IM=True

class BufferAllocator:
    def __call__(self, w, h):
        return FastImage.FastImage8u(FastImage.Size(w,h))

class SharedValue:
    def __init__(self):
        self.evt = threading.Event()
        self._val = None
    def set(self,value):
        # called from producer thread
        self._val = value
        self.evt.set()
    def is_new_value_waiting(self):
        return self.evt.isSet()
    def get(self,*args,**kwargs):
        # called from consumer thread
        self.evt.wait(*args,**kwargs)
        val = self._val
        self.evt.clear()
        return val
    def get_nowait(self):
        val = self._val
        self.evt.clear()
        return val

class LockedValue:
    def __init__(self,initial_value=None):
        self._val = initial_value
        self._q = Queue.Queue()
    def set(self,value):
        self._q.put( value )
    def get(self):
        try:
            while 1:
                self._val = self._q.get_nowait()
        except Queue.Empty:
            pass
        return self._val

def topic_prefix_validator(test_string):
    matchobj = re.match(r'^\w*$',test_string)
    if matchobj is not None:
        return True
    else:
        return False

class Tracker(object):
    def __init__(self,wx_parent):
        self.wx_parent = wx_parent
        self.frame = RES.LoadFrame(self.wx_parent,"FLYTRAX_FRAME") # make frame main panel

        self.frame_nb = xrc.XRCCTRL(self.frame,"FLYTRAX_NOTEBOOK")
        self.status_message = xrc.XRCCTRL(self.frame,"STATUS_MESSAGE")
        self.status_message2 = xrc.XRCCTRL(self.frame,"STATUS_MESSAGE2")
        self.new_image = False

        if have_ROS:
            self.publisher_lock = threading.Lock()
            self.publisher = None
            rospy.init_node('flytrax',
                            anonymous=True, # allow multiple instances to run
                            disable_signals=True, # let WX intercept them
                            )

        self.cam_ids = []
        self.pixel_format = {}

        self.use_roi2 = {}

        self.view_mask_mode = {}
        self.newmask = {}

        self.topic_prefix = ''

        self.wxmessage_queues = {}

        self.clear_and_take_bg_image = {}
        self.load_bg_image = {}
        self.enable_ongoing_bg_image = {}

        self.ongoing_bg_image_num_images = {}
        self.ongoing_bg_image_update_interval = {}

        self.tracking_enabled = {}
        self.realtime_analyzer = {}
        self.max_frame_size = {}
        self.full_frame_live = {}
        self.running_mean_im = {}

        self.clear_threshold_value = {}
        self.new_clear_threshold = {}
        self.diff_threshold_value = {}
        self.new_diff_threshold = {}
        self.history_buflen_value = {}
        self.display_active = {}

        self.mask_x_center = {}
        self.mask_y_center = {}
        self.mask_radius = {}

        self.realtime_mask_x_center = {} # only touch in RT thread
        self.realtime_mask_y_center = {} # only touch in RT thread
        self.realtime_mask_radius = {} # only touch in RT thread

        self.new_mask_x_center = {}
        self.new_mask_y_center = {}
        self.new_mask_radius = {}

        self.save_status_widget = {}
        self.save_data_prefix_widget = {}

        self.widget2cam_id = {}
        self.edit_mask_dlg = {}

        self.image_update_lock = threading.Lock()

        self.last_detection_list = [] # only used in realtime thread

        self.bg_update_lock = threading.Lock()

        self.minimum_eccentricity = 1.5

        self.per_cam_panel = {}

        self.ticks_since_last_update = {}

        if 1:
            # live view
            live_roi_view_panel = xrc.XRCCTRL(self.frame,"LIVE_ROI_VIEW_PANEL")
            box = wx.BoxSizer(wx.VERTICAL)
            live_roi_view_panel.SetSizer(box)

            self.live_canvas = wxvideo.DynamicImageCanvas(live_roi_view_panel,-1)
            #self.live_canvas.set_clipping( False ) # faster without clipping

            box.Add(self.live_canvas,1,wx.EXPAND)
            live_roi_view_panel.SetAutoLayout(True)
            live_roi_view_panel.Layout()

        if 1:
            # bgroi view
            bgroi_view_panel = xrc.XRCCTRL(self.frame,"BGROI_VIEW_PANEL")
            box = wx.BoxSizer(wx.VERTICAL)
            bgroi_view_panel.SetSizer(box)

            self.bgroi_canvas = wxvideo.DynamicImageCanvas(bgroi_view_panel,-1)

            box.Add(self.bgroi_canvas,1,wx.EXPAND)
            bgroi_view_panel.SetAutoLayout(True)
            bgroi_view_panel.Layout()

        self.roi_sz_lock = threading.Lock()
        self.roi_display_sz = FastImage.Size( 100, 100 ) # width, height
        self.roi_save_fmf_sz = FastImage.Size( 100, 100 ) # width, height
        self.ros_send_sz = FastImage.Size( 20, 20 ) # width, height

        ###############

        ctrl = xrc.XRCCTRL(self.frame,'EDIT_GLOBAL_OPTIONS')
        ctrl.Bind( wx.EVT_BUTTON, self.OnEditGlobalOptions)
        self.options_dlg = RES.LoadDialog(self.frame,"OPTIONS_DIALOG")

        ###############
        # ROS stuff

        self.topic_prefix_ctrl = xrc.XRCCTRL(self.frame,"ROS_TOPIC_PREFIX")
        self.topic_prefix_ctrl.SetValue( str(self.topic_prefix ))
        self.topic_prefix_validator = wxvt.Validator(self.topic_prefix_ctrl,
                                                     self.topic_prefix_ctrl.GetId(),
                                                     self.OnSetTopicPrefix,
                                                     topic_prefix_validator)
        self.OnSetTopicPrefix(None) # setup initial ROS publisher

        ###############


        def validate_roi_dimension(value):
            try:
                iv = int(value)
            except ValueError:
                return False
            if not 2 <= iv <= 100:
                return False
            if not (iv%2)==0:
                return False
            return True

        ctrl = xrc.XRCCTRL(self.options_dlg,'ROI_DISPLAY_WIDTH')
        wxvt.Validator(ctrl,ctrl.GetId(),self.OnSetROI,validate_roi_dimension)
        ctrl = xrc.XRCCTRL(self.options_dlg,'ROI_DISPLAY_HEIGHT')
        wxvt.Validator(ctrl,ctrl.GetId(),self.OnSetROI,validate_roi_dimension)

        ctrl = xrc.XRCCTRL(self.options_dlg,'ROI_SAVE_FMF_WIDTH')
        wxvt.Validator(ctrl,ctrl.GetId(),self.OnSetROI,validate_roi_dimension)
        ctrl = xrc.XRCCTRL(self.options_dlg,'ROI_SAVE_FMF_HEIGHT')
        wxvt.Validator(ctrl,ctrl.GetId(),self.OnSetROI,validate_roi_dimension)

        ctrl = xrc.XRCCTRL(self.options_dlg,'ROI_SEND_WIDTH')
        wxvt.Validator(ctrl,ctrl.GetId(),self.OnSetROI,validate_roi_dimension)
        ctrl = xrc.XRCCTRL(self.options_dlg,'ROI_SEND_HEIGHT')
        wxvt.Validator(ctrl,ctrl.GetId(),self.OnSetROI,validate_roi_dimension)

        self.OnSetROI(None)

#######################


        ID_Timer = wx.NewId()
        self.timer = wx.Timer(self.wx_parent, ID_Timer)
        wx.EVT_TIMER(self.wx_parent, ID_Timer, self.OnServiceIncomingData)
        self.update_interval=200 # 5 times per sec
        self.timer.Start(self.update_interval)

        ID_Timer = wx.NewId()
        self.timer_clear_message = wx.Timer(self.wx_parent, ID_Timer)
        wx.EVT_TIMER(self.wx_parent, ID_Timer, self.OnClearMessage)

        self.full_bg_image = {}
        self.xrcid2validator = {}
        self.max_num_points={}

    def get_frame(self):
        return self.frame

    def OnSetTopicPrefix(self, event):
        value = self.topic_prefix_ctrl.GetValue().encode('ascii')
        # our validator ensured this is in [a-zA-Z0-9_] and thus ASCII
        self.topic_prefix = value

        with self.publisher_lock:
            # unregister old publisher
            if self.publisher is not None:
                self.publisher.unregister()

            # register a new publisher
            if have_ROS:
                 self.publisher = rospy.Publisher('%s/flytrax_info'%self.topic_prefix,
                                                  FlytraxInfo,
                                                  tcp_nodelay=True,
                                                  )


    def OnEditGlobalOptions(self, event):
        self.options_dlg.Show()

    def OnSetROI(self,event):
        names = ['ROI_DISPLAY',
                 'ROI_SAVE_FMF',
                 'ROI_SEND']
        topush = {}
        for name in names:
            width_ctrl = xrc.XRCCTRL(self.options_dlg, name+'_WIDTH')
            height_ctrl = xrc.XRCCTRL(self.options_dlg, name+'_HEIGHT')
            attr = name.lower()+'_sz'
            w = int(width_ctrl.GetValue())
            h = int(height_ctrl.GetValue())
            topush[attr] = (w,h)

        self.roi_sz_lock.acquire()
        try:
            for attr,(w,h) in topush.iteritems():
                setattr(self,attr,FastImage.Size(w,h))
        finally:
            self.roi_sz_lock.release()

    def set_view_flip_LR( self, val ):
        self.live_canvas.set_flip_LR(val)
        if BGROI_IM:
            self.bgroi_canvas.set_flip_LR(val)

    def set_view_rotate_180(self,val):
        self.live_canvas.set_rotate_180(val)
        if BGROI_IM:
            self.bgroi_canvas.set_rotate_180(val)

    def camera_starting_notification(self,
                                     cam_id,
                                     pixel_format=None,
                                     max_width=None,
                                     max_height=None):
        """

        cam_id is simply used as a dict key

        """
        self.xrcid2validator[cam_id] = {}

        self.pixel_format[cam_id]=pixel_format
        # setup GUI stuff
        if len(self.cam_ids)==0:
            # adding first camera
            self.frame_nb.DeleteAllPages()

        #  make new per-camera wx panel
        per_cam_panel = RES.LoadPanel(self.frame_nb,"PER_CAM_PANEL")
        self.per_cam_panel[cam_id] = per_cam_panel
        per_cam_panel.SetAutoLayout(True)
        self.frame_nb.AddPage(per_cam_panel,cam_id)

        ctrl = xrc.XRCCTRL(per_cam_panel,"TAKE_BG_IMAGE")
        self.widget2cam_id[ctrl]=cam_id
        wx.EVT_BUTTON(ctrl,
                      ctrl.GetId(),
                      self.OnTakeBgImage)

        ctrl = xrc.XRCCTRL(per_cam_panel,"LOAD_BG_IMAGE")
        self.widget2cam_id[ctrl]=cam_id
        wx.EVT_BUTTON(ctrl,
                      ctrl.GetId(),
                      self.OnLoadBgImage)

        ctrl = xrc.XRCCTRL(per_cam_panel,"ONGOING_BG_UPDATES")
        self.widget2cam_id[ctrl]=cam_id
        wx.EVT_CHECKBOX(ctrl,ctrl.GetId(),
                        self.OnEnableOngoingBg)

        self.ongoing_bg_image_num_images[cam_id] = LockedValue(20)
        ctrl = xrc.XRCCTRL(per_cam_panel,"NUM_BACKGROUND_IMAGES")
        ctrl.SetValue( str(self.ongoing_bg_image_num_images[cam_id].get() ))
        self.widget2cam_id[ctrl]=cam_id
        validator = wxvt.setup_validated_integer_callback(
            ctrl,
            ctrl.GetId(),
            self.OnSetNumBackgroundImages)
        self.xrcid2validator[cam_id]["NUM_BACKGROUND_IMAGES"] = validator

        self.ongoing_bg_image_update_interval[cam_id] = LockedValue(50)
        ctrl = xrc.XRCCTRL(per_cam_panel,"BACKGROUND_IMAGE_UPDATE_INTERVAL")
        ctrl.SetValue( str(self.ongoing_bg_image_update_interval[cam_id].get()))
        self.widget2cam_id[ctrl]=cam_id
        validator = wxvt.setup_validated_integer_callback(
            ctrl,
            ctrl.GetId(),
            self.OnSetBackgroundUpdateInterval)
        self.xrcid2validator[cam_id]["BACKGROUND_IMAGE_UPDATE_INTERVAL"] = validator

        tracking_enabled_widget = xrc.XRCCTRL(per_cam_panel,"TRACKING_ENABLED")
        self.widget2cam_id[tracking_enabled_widget]=cam_id
        wx.EVT_CHECKBOX(tracking_enabled_widget,
                        tracking_enabled_widget.GetId(),
                        self.OnTrackingEnabled)

        use_roi2_widget = xrc.XRCCTRL(per_cam_panel,"USE_ROI2")
        self.widget2cam_id[use_roi2_widget]=cam_id
        wx.EVT_CHECKBOX(use_roi2_widget,
                        use_roi2_widget.GetId(),
                        self.OnUseROI2)
        self.use_roi2[cam_id] = threading.Event()
        if use_roi2_widget.IsChecked():
            self.use_roi2[cam_id].set()

        ctrl = xrc.XRCCTRL(per_cam_panel,"CLEAR_THRESHOLD")
        self.widget2cam_id[ctrl]=cam_id
        validator = wxvt.setup_validated_float_callback(
            ctrl,
            ctrl.GetId(),
            self.OnClearThreshold,
            ignore_initial_value=True)
        self.xrcid2validator[cam_id]["CLEAR_THRESHOLD"] = validator

        ctrl = xrc.XRCCTRL(per_cam_panel,"DIFF_THRESHOLD")
        self.widget2cam_id[ctrl]=cam_id
        validator = wxvt.setup_validated_float_callback(
            ctrl,
            ctrl.GetId(),
            self.OnDiffThreshold,
            ignore_initial_value=True)
        self.xrcid2validator[cam_id]["DIFF_THRESHOLD"] = validator

        ctrl = xrc.XRCCTRL(per_cam_panel,"HISTORY_BUFFER_LENGTH")
        self.widget2cam_id[ctrl]=cam_id
        validator = wxvt.setup_validated_integer_callback(
            ctrl,
            ctrl.GetId(),
            self.OnHistoryBuflen,
            ignore_initial_value=True)
        self.xrcid2validator[cam_id]["HISTORY_BUFFER_LENGTH"] = validator

#####################

        ctrl = xrc.XRCCTRL(per_cam_panel,"EDIT_MASK_BUTTON")
        self.widget2cam_id[ctrl]=cam_id
        ctrl.Bind( wx.EVT_BUTTON, self.OnEditMask )

        ##############
        self.edit_mask_dlg[cam_id] = RES.LoadDialog(per_cam_panel,"EDIT_MASK_DIALOG")

        view_mask_mode_widget = xrc.XRCCTRL(self.edit_mask_dlg[cam_id],"VIEW_MASK_CHECKBOX")
        self.widget2cam_id[view_mask_mode_widget]=cam_id
        wx.EVT_CHECKBOX(view_mask_mode_widget,
                        view_mask_mode_widget.GetId(),
                        self.OnViewMaskMode)

        self.new_mask_x_center[cam_id] = max_width//2
        self.new_mask_y_center[cam_id] = max_height//2
        self.new_mask_radius[cam_id] = max(max_width,max_height)

        mask_x_center_widget = xrc.XRCCTRL(self.edit_mask_dlg[cam_id], "MASK_X_CENTER")
        self.widget2cam_id[mask_x_center_widget]=cam_id
        wx.EVT_COMMAND_SCROLL(mask_x_center_widget,
                              mask_x_center_widget.GetId(),
                              self.OnScrollMaskXCenter)
        mask_x_center_widget.SetRange(0,max_width-1)
        mask_x_center_widget.SetValue(self.new_mask_x_center[cam_id])

        mask_y_center_widget = xrc.XRCCTRL(self.edit_mask_dlg[cam_id], "MASK_Y_CENTER")
        self.widget2cam_id[mask_y_center_widget]=cam_id
        wx.EVT_COMMAND_SCROLL(mask_y_center_widget,
                              mask_y_center_widget.GetId(),
                              self.OnScrollMaskYCenter)
        mask_y_center_widget.SetRange(0,max_height-1)
        mask_y_center_widget.SetValue(self.new_mask_y_center[cam_id])

        mask_radius_widget = xrc.XRCCTRL(self.edit_mask_dlg[cam_id], "MASK_RADIUS")
        self.widget2cam_id[mask_radius_widget]=cam_id
        wx.EVT_COMMAND_SCROLL(mask_radius_widget,
                              mask_radius_widget.GetId(),
                              self.OnScrollMaskRadius)
        mask_radius_widget.SetRange(0,max(max_width,max_height)-1)
        mask_radius_widget.SetValue(self.new_mask_radius[cam_id])
        ##############

        # setup non-GUI stuff
        self.cam_ids.append(cam_id)

        self.display_active[cam_id] = threading.Event()
        if len(self.cam_ids) > 1:
            raise NotImplementedError('if >1 camera supported, implement setting display_active on notebook page change')
        else:
            self.display_active[cam_id].set()

        self.view_mask_mode[cam_id] = threading.Event()
        self.newmask[cam_id] = SharedValue()

        self.wxmessage_queues[cam_id] = Queue.Queue()
        self.clear_and_take_bg_image[cam_id] = threading.Event()
        self.load_bg_image[cam_id] = Queue.Queue()
        self.enable_ongoing_bg_image[cam_id] = threading.Event()

        self.tracking_enabled[cam_id] = threading.Event()
        if tracking_enabled_widget.IsChecked():
            self.tracking_enabled[cam_id].set()
        else:
            self.tracking_enabled[cam_id].clear()

        self.ticks_since_last_update[cam_id] = 0
        lbrt = (0,0,max_width-1,max_height-1)
        roi2_radius=15
        self.max_num_points[cam_id]=SharedValue()
        self.max_num_points[cam_id].set(8)
        ra = realtime_image_analysis.RealtimeAnalyzer(lbrt,
                                                      max_width,
                                                      max_height,
                                                      self.max_num_points[cam_id].get_nowait(),
                                                      roi2_radius)
        self.realtime_analyzer[cam_id] = ra

        self.new_clear_threshold[cam_id] = threading.Event()
        self.new_diff_threshold[cam_id] = threading.Event()

        self.history_buflen_value[cam_id] = 100
        ctrl = xrc.XRCCTRL(per_cam_panel,"HISTORY_BUFFER_LENGTH")
        validator = self.xrcid2validator[cam_id]["HISTORY_BUFFER_LENGTH"]
        ctrl.SetValue( '%d'%self.history_buflen_value[cam_id])
        validator.set_state('valid')

        ctrl = xrc.XRCCTRL(per_cam_panel,"MAX_NUM_POINTS")
        self.widget2cam_id[ctrl]=cam_id
        validator = wxvt.setup_validated_integer_callback(
            ctrl,
            ctrl.GetId(),
            self.OnMaxNPoints,
            ignore_initial_value=True)
        self.xrcid2validator[cam_id]["MAX_NUM_POINTS"] = validator
        ctrl.SetValue(str(self.max_num_points[cam_id].get_nowait()))
        validator.set_state('valid')


        ctrl = xrc.XRCCTRL(per_cam_panel,"ROI2_RADIUS")
        self.widget2cam_id[ctrl]=cam_id
        validator = wxvt.setup_validated_integer_callback(
            ctrl,
            ctrl.GetId(),
            self.OnROI2Radius,
            ignore_initial_value=True)
        self.xrcid2validator[cam_id]["ROI2_RADIUS"] = validator
        ctrl.SetValue(str(roi2_radius))
        validator.set_state('valid')

        ra.clear_threshold = 0.8
        ra.diff_threshold = 30
        self.clear_threshold_value[cam_id] = ra.clear_threshold
        self.clear_threshold_value[cam_id] = ra.diff_threshold

        ctrl = xrc.XRCCTRL(per_cam_panel,"CLEAR_THRESHOLD")
        validator = self.xrcid2validator[cam_id]["CLEAR_THRESHOLD"]
        ctrl.SetValue( '%.2f'%ra.clear_threshold )
        validator.set_state('valid')

        ctrl = xrc.XRCCTRL(per_cam_panel,"DIFF_THRESHOLD")
        validator = self.xrcid2validator[cam_id]["DIFF_THRESHOLD"]
        ctrl.SetValue( '%d'%ra.diff_threshold )
        validator.set_state('valid')

        max_frame_size = FastImage.Size( max_width, max_height )
        self.max_frame_size[cam_id] = max_frame_size
        self.full_frame_live[cam_id] = FastImage.FastImage8u( max_frame_size )
        self.running_mean_im[cam_id] = FastImage.FastImage32f( max_frame_size)

        self.frame.Fit()

    def get_buffer_allocator(self,cam_id):
        return BufferAllocator()

    def get_plugin_name(self):
        return 'FlyTrax'

    def OnEditMask(self,event):
        widget = event.GetEventObject()
        cam_id = self.widget2cam_id[widget]
        self.edit_mask_dlg[cam_id].Show()

    def OnTakeBgImage(self,event):
        widget = event.GetEventObject()
        cam_id = self.widget2cam_id[widget]

        self.clear_and_take_bg_image[cam_id].set()
        self.display_message('capturing background image')

    def OnLoadBgImage(self,event):
        widget = event.GetEventObject()
        cam_id = self.widget2cam_id[widget]

        # open dialog
        dlg = wx.FileDialog( self.wx_parent, "open backsub output")
        doit=False
        try:
            if dlg.ShowModal() == wx.ID_OK:
                fname = dlg.GetFilename()
                dirname = dlg.GetDirectory()
                doit=True
        finally:
            dlg.Destroy()

        if doit:
            filename = os.path.join(dirname,fname)

            if filename.endswith('.mat'):
                load_dict = scipy.io.loadmat( filename, squeeze_me=True )
                newbg = load_dict['bg_img']
                if 0:
                    print 'newbg.shape',newbg.shape
                    print 'newbg.dtype',newbg.dtype
                    print 'newbg.min()',newbg.min()
                    print 'newbg.max()',newbg.max()
                newbg = numpy.clip(newbg,0,255)
                newbg = newbg.astype(numpy.uint8)
            else:
                raise ValueError("don't know how to open background image file")
            newbg_fi = FastImage.asfastimage(newbg)
            self.load_bg_image[cam_id].put(newbg_fi)
            self.display_message('background image loaded')

    def OnEnableOngoingBg(self,event):
        widget = event.GetEventObject()
        cam_id = self.widget2cam_id[widget]

        if widget.GetValue():
            self.enable_ongoing_bg_image[cam_id].set()
        else:
            self.enable_ongoing_bg_image[cam_id].clear()
        self.display_message('enabled ongoing background image updates')

    def OnSetNumBackgroundImages(self,event):
        widget = event.GetEventObject()
        cam_id = self.widget2cam_id[widget]
        val = int(widget.GetValue())
        self.ongoing_bg_image_num_images[cam_id].set(val)

    def OnSetBackgroundUpdateInterval(self,event):
        widget = event.GetEventObject()
        cam_id = self.widget2cam_id[widget]
        val = int(widget.GetValue())
        self.ongoing_bg_image_update_interval[cam_id].set(val)

    def OnTrackingEnabled(self,event):
        widget = event.GetEventObject()
        cam_id = self.widget2cam_id[widget]
        if widget.IsChecked():
            self.tracking_enabled[cam_id].set()
        else:
            self.tracking_enabled[cam_id].clear()

    def OnUseROI2(self,event):
        widget = event.GetEventObject()
        cam_id = self.widget2cam_id[widget]
        if widget.IsChecked():
            self.use_roi2[cam_id].set()
        else:
            self.use_roi2[cam_id].clear()

    def OnClearThreshold(self,event):
        widget = event.GetEventObject()
        cam_id = self.widget2cam_id[widget]
        newvalstr = widget.GetValue()
        try:
            newval = float(newvalstr)
        except ValueError:
            pass
        else:
            # only touch realtime_analysis in other thread
            self.clear_threshold_value[cam_id] = newval
            self.new_clear_threshold[cam_id].set()
            self.display_message('set clear threshold %s'%str(newval))
        event.Skip()

    def OnDiffThreshold(self,event):
        widget = event.GetEventObject()
        cam_id = self.widget2cam_id[widget]
        newvalstr = widget.GetValue()
        try:
            newval = int(newvalstr)
        except ValueError:
            pass
        else:
            # only touch realtime_analysis in other thread
            self.diff_threshold_value[cam_id] = newval
            self.new_diff_threshold[cam_id].set()
            self.display_message('set difference threshold %d'%newval)
        event.Skip()

    def OnHistoryBuflen(self,event):
        widget = event.GetEventObject()
        cam_id = self.widget2cam_id[widget]
        newvalstr = widget.GetValue()
        try:
            newval = int(newvalstr)
        except ValueError:
            pass
        else:
            self.history_buflen_value[cam_id] = newval
        event.Skip()

    def OnViewMaskMode(self,event):
        widget = event.GetEventObject()
        cam_id = self.widget2cam_id[widget]
        if widget.IsChecked():
            self.view_mask_mode[cam_id].set()
        else:
            self.view_mask_mode[cam_id].clear()

    def OnScrollMaskXCenter(self,event):
        widget = event.GetEventObject()
        cam_id = self.widget2cam_id[widget]
        self.new_mask_x_center[cam_id] = widget.GetValue()

    def OnScrollMaskYCenter(self,event):
        widget = event.GetEventObject()
        cam_id = self.widget2cam_id[widget]
        self.new_mask_y_center[cam_id] = widget.GetValue()

    def OnScrollMaskRadius(self,event):
        widget = event.GetEventObject()
        cam_id = self.widget2cam_id[widget]
        self.new_mask_radius[cam_id] = widget.GetValue()

    def _process_frame_extract_roi( self, points, roi_sz,
                                    fibuf, buf_offset, full_frame_live,
                                    max_frame_size):
        # called from self.process_frame()
        n_pts = len(points)

        if n_pts:
            pt = points[0] # only operate on first point
            (x,y,area,slope,eccentricity)=pt[:5]

            # find software ROI
            rx = int(round(x))
            x0=rx-roi_sz.w//2
            x1=x0+roi_sz.w
            if x0<0:
                x0=0
            elif x1>=max_frame_size.w:
                x0=max_frame_size.w-roi_sz.w
                x1=max_frame_size.w

            ry = int(round(y))
            y0=ry-roi_sz.h//2
            y1=y0+roi_sz.h
            if y0<0:
                y0=0
            elif y1>=max_frame_size.h:
                y0=max_frame_size.h-roi_sz.h
                y1=max_frame_size.h

        else: # no points found
            x0 = 0
            y0 = 0

        # extract smaller image for saving
        if fibuf.size == max_frame_size:
            software_roi = fibuf.roi( x0, y0, roi_sz )
        else:
            # make sure we can do software_roi size live view
            # 1. make full frame "live view"
            l,b = buf_offset
            roi_into_full_frame = full_frame_live.roi( l,b, fibuf.size )
            fibuf.get_8u_copy_put(roi_into_full_frame,fibuf.size)
            # 2. get software_roi view into it
            tmp = full_frame_live.roi( x0, y0, roi_sz )
            # 3. make copy of software_roi
            software_roi = tmp.get_8u_copy(tmp.size) # copy

        return software_roi, (x0,y0)

    def OnMaxNPoints(self,event):
        widget = event.GetEventObject()
        cam_id = self.widget2cam_id[widget]

        newvalstr = widget.GetValue()
        try:
            newval = int(newvalstr)
        except ValueError:
            pass
        else:
            self.max_num_points[cam_id].set( newval )
        event.Skip()

    def OnROI2Radius(self,event):
        widget = event.GetEventObject()
        cam_id = self.widget2cam_id[widget]

        newvalstr = widget.GetValue()
        try:
            newval = int(newvalstr)
        except ValueError:
            pass
        else:
            self.realtime_analyzer[cam_id].roi2_radius = newval
        event.Skip()

    def process_frame(self,cam_id,buf,buf_offset,timestamp,framenumber):
        if self.pixel_format[cam_id]=='YUV422':
            buf = imops.yuv422_to_mono8( numpy.asarray(buf) ) # convert
        elif not (self.pixel_format[cam_id].startswith('MONO8') or
                  self.pixel_format[cam_id].startswith('RAW8')):
            warnings.warn("flytrax plugin incompatible with data format")
            return [], []

        self.ticks_since_last_update[cam_id] += 1
        start = time.time()
        # this is called in realtime thread
        fibuf = FastImage.asfastimage(buf) # FastImage view of image data (hardware ROI)
        l,b = buf_offset
        lbrt = l, b, l+fibuf.size.w-1, b+fibuf.size.h-1

        view_mask_mode = self.view_mask_mode[cam_id]
        newmask = self.newmask[cam_id]

        clear_and_take_bg_image = self.clear_and_take_bg_image[cam_id]
        load_bg_image = self.load_bg_image[cam_id]
        enable_ongoing_bg_image = self.enable_ongoing_bg_image[cam_id]
        wxmessage_queue = self.wxmessage_queues[cam_id] # transfers and messages to non-realtime thread
        new_clear_threshold = self.new_clear_threshold[cam_id]
        new_diff_threshold = self.new_diff_threshold[cam_id]
        realtime_analyzer = self.realtime_analyzer[cam_id]
        realtime_analyzer.roi = lbrt # hardware ROI
        max_frame_size = self.max_frame_size[cam_id]
        full_frame_live = self.full_frame_live[cam_id]
        running_mean_im = self.running_mean_im[cam_id]
        display_active = self.display_active[cam_id]

        history_buflen_value = self.history_buflen_value[cam_id]
        use_roi2 = self.use_roi2[cam_id].isSet()

        use_cmp = False # use variance-based background subtraction/analysis
        draw_points = []
        draw_linesegs = []

        if newmask.is_new_value_waiting():
            (x,y,radius), newmask_im = newmask.get_nowait()

            self.realtime_mask_x_center[cam_id]=x
            self.realtime_mask_y_center[cam_id]=y
            self.realtime_mask_radius[cam_id]=radius

            newmask_fi = FastImage.asfastimage( newmask_im )
            assert newmask_fi.size == max_frame_size
            mask_im = realtime_analyzer.get_image_view('mask')
            newmask_fi.get_8u_copy_put(mask_im, max_frame_size)
            del mask_im # don't leak view into other thread

        if view_mask_mode.isSet():

            w,h = max_frame_size.w, max_frame_size.h
            x=self.realtime_mask_x_center.get(cam_id, w//2)
            y=self.realtime_mask_y_center.get(cam_id, h//2)
            radius=self.realtime_mask_radius.get(cam_id, max(w,h))

            N = 64
            theta = numpy.arange(N)*2*math.pi/N
            xdraw = x+numpy.cos(theta)*radius
            ydraw = y+numpy.sin(theta)*radius
            for i in range(N-1):
                draw_linesegs.append(
                    (xdraw[i],ydraw[i],xdraw[i+1],ydraw[i+1]))
            draw_linesegs.append(
                (xdraw[-1],ydraw[-1],xdraw[0],ydraw[0]))

        if clear_and_take_bg_image.isSet():
            # this is a view we write into
            # copy current image into background image
            running_mean8u_im = realtime_analyzer.get_image_view('mean')
            if running_mean8u_im.size == fibuf.size:
                srcfi = fibuf
                bg_copy = srcfi.get_8u_copy(max_frame_size)
            else:
                srcfi = FastImage.FastImage8u(max_frame_size)
                srcfi_roi = srcfi.roi(l,b,fibuf.size)
                fibuf.get_8u_copy_put(srcfi_roi, fibuf.size)
                bg_copy = srcfi # newly created, no need to copy

            srcfi.get_32f_copy_put( running_mean_im,   max_frame_size )
            srcfi.get_8u_copy_put(  running_mean8u_im, max_frame_size )

            # make copy available for saving data
            self.bg_update_lock.acquire()
            self.full_bg_image[cam_id] = bg_copy
            self.bg_update_lock.release()

            clear_and_take_bg_image.clear()
            del srcfi, bg_copy # don't pollute namespace

        if not load_bg_image.empty():
            try:
                while 1:
                    new_bg_image_fastimage = load_bg_image.get_nowait()
            except Queue.Empty:
                pass
            # this is a view we write into
            # copy current image into background image
            running_mean8u_im = realtime_analyzer.get_image_view('mean')
            if running_mean8u_im.size == new_bg_image_fastimage.size:
                new_bg_image_fastimage.get_32f_copy_put( running_mean_im,   max_frame_size )
                new_bg_image_fastimage.get_8u_copy_put(  running_mean8u_im, max_frame_size )

                # make copy available for saving data
                self.bg_update_lock.acquire()
                self.full_bg_image[cam_id] = new_bg_image_fastimage
                self.bg_update_lock.release()
            else:
                wxmessage_queue.put( ('new background image must be same size as image frame',
                                      'FlyTrax error',
                                      wx.OK | wx.ICON_ERROR) )

        if enable_ongoing_bg_image.isSet():

            update_interval = self.ongoing_bg_image_update_interval[cam_id].get()
            if self.ticks_since_last_update[cam_id]%update_interval == 0:
                alpha = 1.0/self.ongoing_bg_image_num_images[cam_id].get()
                if running_mean_im.size == fibuf.size:
                    srcfi = fibuf
                else:
                    # This is inelegant (it creates a full frame), but it works.
                    srcfi = FastImage.FastImage8u(max_frame_size)
                    srcfi_roi = srcfi.roi(l,b,fibuf.size)
                    fibuf.get_8u_copy_put(srcfi_roi, fibuf.size)

                running_mean8u_im = realtime_analyzer.get_image_view('mean')
                # maintain running average
                running_mean_im.toself_add_weighted( srcfi, max_frame_size, alpha )
                # maintain 8bit unsigned background image
                running_mean_im.get_8u_copy_put( running_mean8u_im, max_frame_size )

                # make copy available for saving data
                bg_copy = running_mean_im.get_8u_copy(running_mean_im.size)
                self.bg_update_lock.acquire()
                self.full_bg_image[cam_id] = bg_copy
                self.bg_update_lock.release()

        if new_clear_threshold.isSet():
            nv = self.clear_threshold_value[cam_id]
            realtime_analyzer.clear_threshold = nv
            #print 'set clear',nv
            new_clear_threshold.clear()

        if new_diff_threshold.isSet():
            nv = self.diff_threshold_value[cam_id]
            realtime_analyzer.diff_threshold = nv
            #print 'set diff',nv
            new_diff_threshold.clear()

        n_pts = 0
        if self.tracking_enabled[cam_id].isSet():
            max_num_points = self.max_num_points[cam_id].get_nowait()
            realtime_analyzer.max_num_points = max_num_points # AttributeError here means old realtime_image_analysis
            points = realtime_analyzer.do_work(fibuf,
                                               timestamp, framenumber, use_roi2,
                                               use_cmp=use_cmp)

            self.roi_sz_lock.acquire()
            try:
                roi_display_sz = self.roi_display_sz
                roi_save_fmf_sz = self.roi_save_fmf_sz
                ros_send_sz = self.ros_send_sz
            finally:
                self.roi_sz_lock.release()

            roi_display, (display_x0, display_y0) = self._process_frame_extract_roi(
                points, roi_display_sz,
                fibuf, buf_offset, full_frame_live,
                max_frame_size)
            roi_save_fmf, (fmf_save_x0, fmf_save_y0) = self._process_frame_extract_roi(
                points, roi_save_fmf_sz,
                fibuf, buf_offset, full_frame_live,
                max_frame_size)

            n_pts = len(points)

            if BGROI_IM:
                running_mean8u_im = realtime_analyzer.get_image_view('mean')
                tmp = running_mean8u_im.roi( display_x0, display_y0, self.roi_display_sz )
                bgroi = tmp.get_8u_copy(tmp.size) # copy

            # live display of image
            if display_active.isSet():
                self.image_update_lock.acquire()
                self.last_image = roi_display
                self.last_image_cam_id = cam_id
                self.last_image_format = 'MONO8' # forced in this routine
                self.last_points = points
                self.roi_display_lb = display_x0,display_y0
                self.new_image = True
                if BGROI_IM:
                    self.bgroi_image = bgroi
                self.image_update_lock.release()

        if n_pts and have_ROS:
            stamp = rospy.Time.from_sec(timestamp)

            msg = FlytraxInfo()
            msg.framenumber = framenumber
            msg.stamp = stamp
            msg.cam_id = cam_id

            detections = []
            for ptnum,this_point in enumerate(points):
                ros_send, (ros_send_x0, ros_send_y0) = self._process_frame_extract_roi(
                    [this_point], ros_send_sz,
                    fibuf, buf_offset, full_frame_live,
                    max_frame_size)

                detection = Detection()

                (x,y,area,slope,eccentricity)=this_point[:5]
                detection.x = x
                detection.y = y
                detection.slope = slope
                detection.area = area
                detection.eccentricity = eccentricity

                if 1:
                    # fill detection.image
                    detection.image = Image()
                    im = detection.image # shorthand
                    im.header.seq = framenumber
                    im.header.stamp = stamp
                    im.header.frame_id = '0'

                    detection.imbufx = ros_send_x0
                    detection.imbufy = ros_send_y0
                    npbuf = numpy.array(ros_send)
                    (height,width) = npbuf.shape

                    im.height = height
                    im.width = width
                    im.encoding = 'MONO8'
                    im.step = width
                    im.data = npbuf.tostring() # let numpy convert to string

                detections.append( detection )
            msg.detections = detections

            with self.publisher_lock:
                self.publisher.publish(msg)

        if n_pts:
            this_list = [ (pt[0], pt[1]) for pt in points ]
            self.last_detection_list.append(this_list)
        else:
            self.last_detection_list.append(None)
        if len(self.last_detection_list) > history_buflen_value:
            self.last_detection_list = self.last_detection_list[-history_buflen_value:]
        for this_list in self.last_detection_list:
            if this_list is not None:
                draw_points.extend(this_list)
        return draw_points, draw_linesegs

    def display_message(self,msg,duration_msec=2000):
        self.status_message.SetLabel(msg)
        self.timer_clear_message.Start(duration_msec,wx.TIMER_ONE_SHOT)

    def OnClearMessage(self,evt):
        self.status_message.SetLabel('')

    def OnServiceIncomingData(self, evt):
        self.update_screen()

        # show any messages
        msgs = []
        for cam_id in self.cam_ids:
            wxmessage_queue = self.wxmessage_queues[cam_id]
            try:
                while 1:
                    msg = wxmessage_queue.get(False) # don't block
                    msgs.append(msg)
            except Queue.Empty:
                pass
        for text,title,flags in msgs:
            dlg = wx.MessageDialog(self.wx_parent,text,title,flags)
            try:
                dlg.ShowModal()
            finally:
                dlg.Destroy()

        # calculate masks (only do occasionally, expensive)
        for cam_id in self.cam_ids:
            changed=False
            if self.new_mask_x_center[cam_id] is not None:
                changed=True
                self.mask_x_center[cam_id] = self.new_mask_x_center[cam_id]
                self.new_mask_x_center[cam_id] = None

            if self.new_mask_y_center[cam_id] is not None:
                changed=True
                self.mask_y_center[cam_id] = self.new_mask_y_center[cam_id]
                self.new_mask_y_center[cam_id] = None

            if self.new_mask_radius[cam_id] is not None:
                changed=True
                self.mask_radius[cam_id] = self.new_mask_radius[cam_id]
                self.new_mask_radius[cam_id] = None

            if changed:
                a = self.mask_x_center[cam_id]
                b = self.mask_y_center[cam_id]
                c = self.mask_radius[cam_id]
                x,y,radius=a,b,c
                #print 'recalculating mask: X %d, Y %d, r %d'%(a,b,c)

                width = self.max_frame_size[cam_id].w
                height = self.max_frame_size[cam_id].h

                X = numpy.arange(width,dtype=numpy.float32)
                Y = numpy.arange(height,dtype=numpy.float32)
                Y.shape = (Y.shape[0],1)
                X.shape = (1,X.shape[0])
                vals = (X-a)**2+(Y-b)**2 - c**2
                circim = numpy.zeros((height,width),dtype=numpy.uint8)
                circim[vals>0]=255
                self.newmask[cam_id].set(((x,y,radius),circim))

    def quit(self):
        pass

    def update_screen(self):
        """Draw on screen

        Called from wx thread by timer. Grabs data from realtime
        thread respecting locks.
        """
        self.image_update_lock.acquire()
        if self.new_image:
            have_new_image = True
            # Get data from other thread as quickly as possible and
            # release lock.
            cam_id = self.last_image_cam_id
            format = self.last_image_format
            im = self.last_image
            if BGROI_IM:
                bgroi_im = self.bgroi_image
            orig_points = self.last_points
            roi_display_left,roi_display_bottom = self.roi_display_lb
            self.new_image = False # reset for next pass
        else:
            have_new_image = False
        self.image_update_lock.release()

        if have_new_image:
            points = []
            linesegs = []

            width = im.size.w
            height = im.size.h

            # this scaling should be moved to wxvideo:
            if 1:
                xg = width
                xo = 0
            else:
                xg = -width
                xo = width-1
            yg = height
            yo = 0

            for orig_pt in orig_points:

                ox0,oy0,area,slope,eccentricity = orig_pt[:5]
                #print '% 8.1f % 8.1f (slope: % 8.1f)'%(ox0, oy0, slope)
                ox0 = ox0-roi_display_left   # put in display ROI coordinate system
                oy0 = oy0-roi_display_bottom # put in display ROI coordinate system


                # points ================================
                points.append((ox0,oy0))

                # linesegs ==============================
                if eccentricity <= self.minimum_eccentricity:
                    # don't draw green lines -- not much orientation info
                    continue

                slope=-slope
                oy0 = height-oy0

                # line segment for orientation
                xmin = 0
                ymin = 0
                xmax = width-1
                ymax = height-1

                # ax+by+c=0
                a=slope
                b=-1
                c=oy0-a*ox0

                x1=xmin
                y1=-(c+a*x1)/b
                if y1 < ymin:
                    y1 = ymin
                    x1 = -(c+b*y1)/a
                elif y1 > ymax:
                    y1 = ymax
                    x1 = -(c+b*y1)/a

                x2=xmax
                y2=-(c+a*x2)/b
                if y2 < ymin:
                    y2 = ymin
                    x2 = -(c+b*y2)/a
                elif y2 > ymax:
                    y2 = ymax
                    x2 = -(c+b*y2)/a

                x1 = x1/width*xg+xo
                x2 = x2/width*xg+xo

                y1 = (height-y1)/height*yg+yo
                y2 = (height-y2)/height*yg+yo

                linesegs.append( (int(x1),int(y1),int(x2),int(y2)) )

            self.live_canvas.update_image_and_drawings(
                'camera', im, format=format,
                points=points,
                linesegs=linesegs,
                )

            if 1:
                self.live_canvas.Refresh(eraseBackground=False)

            if BGROI_IM:
                self.bgroi_canvas.update_image_and_drawings(
                    'camera', bgroi_im, format=format,
                    )
                if 1:
                    self.bgroi_canvas.Refresh(eraseBackground=False)
