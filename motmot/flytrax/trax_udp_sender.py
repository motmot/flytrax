import pkg_resources

import socket, threading

import wx
from wx import xrc

RESFILE = pkg_resources.resource_filename(__name__,"trax_udp_sender.xrc") # trigger extraction
RES = xrc.EmptyXmlResource()
RES.LoadFromString(open(RESFILE).read())

class UDPSender(object):
    """A base class for keeping track of a list of UDP receiver hostnames

Use this class in the following way to get a list of hostnames to send data to:

hosts = udp_sender_instance.get_downstream_hosts()
for host in hosts:
    sockobj.sendto( 'hello', host)

    """

    def __init__(self,frame):
        self.frame = frame
        self._remote_host_lock = threading.Lock()
        self._remote_host_changed = threading.Event()

        self._remote_host_caller = []
        self._remote_host_gui = []

        self.edit_udp_receivers_dlg = RES.LoadDialog(self.frame,"UDP_RECEIVER_DIALOG")

#####################

        ctrl = xrc.XRCCTRL(self.edit_udp_receivers_dlg,"UDP_ADD")
        ctrl.Bind(wx.EVT_BUTTON, self.OnUDPAdd )

        ctrl = xrc.XRCCTRL(self.edit_udp_receivers_dlg,"UDP_EDIT")
        wx.EVT_BUTTON(ctrl,ctrl.GetId(),self.OnUDPEdit)

        ctrl = xrc.XRCCTRL(self.edit_udp_receivers_dlg,"UDP_REMOVE")
        wx.EVT_BUTTON(ctrl,ctrl.GetId(),self.OnUDPRemove)

#######################
    def get_downstream_hosts(self):
        if self._remote_host_changed.isSet():
            self._remote_host_lock.acquire()
            try:
                # copy items out of list shared across threads
                self._remote_host_caller = self._remote_host_gui
                self._remote_host_changed.clear()
            finally:
                self._remote_host_lock.release()
        return self._remote_host_caller

    def OnEditUDPReceivers(self,event):
        self.edit_udp_receivers_dlg.ShowModal()

    def remote_hosts_changed(self):
        listctrl = xrc.XRCCTRL(self.edit_udp_receivers_dlg,"UDP_RECEIVER_LIST")
        n = listctrl.GetCount()

        self._remote_host_lock.acquire()
        try:
            self._remote_host_changed.set()
            self._remote_host_gui = []
            for idx in range(n):
                self._remote_host_gui.append( listctrl.GetClientData(idx) )
        finally:
            self._remote_host_lock.release()

    def OnEnableSendToIP(self,event):
        widget = event.GetEventObject()
        if widget.IsChecked():
            self.send_over_ip.set()
        else:
            self.send_over_ip.clear()

    def OnUDPAdd(self,event):
        listctrl = xrc.XRCCTRL(self.edit_udp_receivers_dlg,"UDP_RECEIVER_LIST")
        dlg = wx.TextEntryDialog(self.wx_parent,
                                 'Please add the hostname',
                                 )
        try:
            if dlg.ShowModal() == wx.ID_OK:
                hostname = dlg.GetValue()
                try:
                    ip = socket.gethostbyname(hostname)
                except socket.gaierror, x:
                    dlg2 = wx.MessageDialog(dlg,
                                            'error getting IP address: '+str(x),
                                            'FlyTrax: socket error',
                                            wx.OK | wx.ICON_ERROR)
                    dlg2.ShowModal()
                    dlg2.Destroy()
                else:
                    remote_host = (ip, 28931)
                    if hostname != '':
                        toshow = hostname
                    else:
                        toshow = str(ip)
                    idx = listctrl.Append( toshow )
                    listctrl.SetClientData(idx,remote_host)
                    self.remote_hosts_changed()
        finally:
            dlg.Destroy()

    def OnUDPEdit(self,event):
        widget = event.GetEventObject()

    def OnUDPRemove(self,event):
        listctrl = xrc.XRCCTRL(self.edit_udp_receivers_dlg,"UDP_RECEIVER_LIST")
        idx = listctrl.GetSelection()
        if idx==wx.NOT_FOUND:
            return
        remote_host = listctrl.GetClientData(idx)
        listctrl.Delete(idx)
        self.remote_hosts_changed()
