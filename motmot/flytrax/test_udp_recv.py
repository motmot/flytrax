#!/usr/bin/env python
# $Id: calibrate_viewport.py 561 2005-06-30 23:22:01Z astraw $
from __future__ import division

import Numeric as nx
import math, socket, struct, select

hostname = ''
sockobj = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sockobj.setblocking(0)

port = 28931

sockobj.bind(( hostname, port))

def check_network():

    # return if data not ready
    while 1:
        in_ready, trash1, trash2 = select.select( [sockobj], [], [], 0.0 )
        if not len(in_ready):
            continue
##            #print '    no data'
##            break

        newdata, addr = sockobj.recvfrom(4096)
        if len(newdata):
            print repr(newdata)
            
check_network()
