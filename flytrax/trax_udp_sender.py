from __future__ import with_statement
import pkg_resources

import socket

import wx
from wx import xrc

RESFILE = pkg_resources.resource_filename(__name__,"trax_udp_sender.xrc") # trigger extraction
RES = xrc.EmptyXmlResource()
RES.LoadFromString(open(RESFILE).read())

class UDPSender(object):
    def __init__(self,frame):
        self.frame = frame

        self.edit_udp_receivers_dlg = RES.LoadDialog(self.frame,"UDP_RECEIVER_DIALOG")
        
#####################
        
        ctrl = xrc.XRCCTRL(self.edit_udp_receivers_dlg,"UDP_ADD")
        ctrl.Bind(wx.EVT_BUTTON, self.OnUDPAdd )

        ctrl = xrc.XRCCTRL(self.edit_udp_receivers_dlg,"UDP_EDIT")
        wx.EVT_BUTTON(ctrl,ctrl.GetId(),self.OnUDPEdit)

        ctrl = xrc.XRCCTRL(self.edit_udp_receivers_dlg,"UDP_REMOVE")
        wx.EVT_BUTTON(ctrl,ctrl.GetId(),self.OnUDPRemove)

#######################
    def OnEditUDPReceivers(self,event):
        self.edit_udp_receivers_dlg.ShowModal()

    def remote_hosts_changed(self):
        listctrl = xrc.XRCCTRL(self.edit_udp_receivers_dlg,"UDP_RECEIVER_LIST")
        n = listctrl.GetCount()
        
        with self.remote_host_lock:
            self.remote_host_changed.set()
            if n > 0:
                self.remote_host = []
                for idx in range(n):
                    self.remote_host.append( listctrl.GetClientData(idx) )
            else:
                self.remote_host = None

        ctrl = xrc.XRCCTRL(self.frame,'SEND_TO_IP_ENABLED')
        ctrl.SetLabel('send data to %d receiver(s)'%n)
        
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
