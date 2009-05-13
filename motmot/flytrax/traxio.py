import motmot.FlyMovieFormat.FlyMovieFormat as FlyMovieFormat
import numpy as np
from numpy import nan
import sys, struct
import unittest
import os, tempfile, shutil, warnings

header_fmt = 'iii'
chunk_fmt_v1 = 'dddddd'
chunk_fmt_v2 = 'ddddddd'

fields_v1 = ('posx','posy','slope','windowx','windowy','timestamp')
fields_v2 = ('posx','posy','slope','windowx','windowy','timestamp','area')

VALID_VERSIONS = (1,2)

class TraxDataWriter:
    def __init__(self, fname_prefix, bgimage, version=2, save_fmf=True):
        """
        version 1 does not save area
        version 2 does save area
        """

        data_fname = fname_prefix+'.trx'
        self.data_fd = open(data_fname,'wb')
        bgimage = np.asarray(bgimage)

        assert len(bgimage.shape)==2
        assert bgimage.dtype==np.dtype(np.uint8)

        assert version in VALID_VERSIONS
        self.version = version

        self.data_fd.write( struct.pack(header_fmt,
                                        self.version,
                                        bgimage.shape[0],
                                        bgimage.shape[1] ))
        self.data_fd.write( bgimage.tostring() )

        self.save_fmf = save_fmf
        if self.save_fmf:
            fmf_fname = fname_prefix + '.fmf'
            self.fmf = FlyMovieFormat.FlyMovieSaver( fmf_fname)

    def close(self):
        if self.save_fmf:
            self.fmf.close()
        self.data_fd.close()

    def write_data(self,roi_img=None,
                   posx=nan,posy=nan,
                   orientation=None,
                   windowx=nan,windowy=nan,
                   timestamp=nan,
                   area=nan,
                   slope=None):
        if self.save_fmf:
            self.fmf.add_frame(roi_img,timestamp)
        else:
            if roi_img is not None:
                raise ValueError('not saving .fmf, but roi_img was given')
        if slope is not None and orientation is not None:
            raise ValueError('both slope and orientation were given')
        if slope is None:
            slope=orientation
            warnings.warn('using old orientation parameter name',
                          DeprecationWarning)
        if self.version==1:
            buf = struct.pack(chunk_fmt_v1,posx,posy,slope,
                              windowx,windowy,timestamp)
        elif self.version==2:
            buf = struct.pack(chunk_fmt_v2,posx,posy,slope,
                              windowx,windowy,timestamp,area)
        self.data_fd.write( buf )

def readtrax(fname,return_structured_array=False):
    """sample Python reader"""
    fd = open(fname,'rb')
    asz = struct.calcsize(header_fmt)
    header = fd.read(asz)
    version,shape0,shape1 = struct.unpack(header_fmt,header)
    assert version in VALID_VERSIONS
    imsz = shape0*shape1
    imbuf = fd.read(imsz)
    im = np.fromstring(imbuf,np.uint8)
    im.shape = shape0,shape1
    buf = fd.read()
    bufptr = 0
    if version==1:
        chunk_fmt = chunk_fmt_v1
        fields = fields_v1
    elif version==2:
        chunk_fmt = chunk_fmt_v2
        fields = fields_v2
    chunksz = struct.calcsize(chunk_fmt)
    all_vals = []
    while bufptr<len(buf):
        chunkbuf = buf[bufptr:bufptr+chunksz]
        if len(chunkbuf) < chunksz:
            # incomplete data, skip this point
            break
        vals = struct.unpack( chunk_fmt, chunkbuf )
        all_vals.append(vals)
        bufptr+=chunksz
    results = all_vals
    if return_structured_array:
        results = np.array(all_vals)
        results = results.view( dtype = [(field,np.float) for field in fields ])
    return im, results

def test_version(version,incomplete=False):
    a=np.zeros((1200,1600),np.uint8)
    if version==1:
        r1=np.array((1,2,3,4,5,6),np.float64)
    elif version==2:
        # include area
        r1=np.array((1,2,3,4,5,6,7),np.float64)
    r2 = r1*3.2
    r1 = list(r1)
    r2 = list(r2)

    fake_image = np.zeros((10,10),np.uint8)
    ar1 = [fake_image]+r1
    ar2 = [fake_image]+r2

    dirname = tempfile.mkdtemp()
    try:
        fname = os.path.join(dirname,'test_v%d'%version)
        f1 = TraxDataWriter(fname,a,version=version)
        f1.write_data( *tuple(ar1) )
        f1.write_data( *tuple(ar2) )
        if incomplete:
            # simulate incomplete write operation
            f1.write_data( *tuple(ar2) )
            f1.data_fd.seek(0,2)
            where = f1.data_fd.tell()
            f1.data_fd.seek(where-2,0)
            f1.data_fd.truncate()
        f1.close()

        im,rows=readtrax(fname+'.trx')
    finally:
        shutil.rmtree(dirname)

    assert np.allclose(im,a)
    assert np.allclose(r1,rows[0])
    assert np.allclose(r2,rows[1])

def print_info(fname_prefix):
    data_fname = fname_prefix+'.trx'
    fmf_fname = fname_prefix+'.fmf'
    bg_im,all_vals = readtrax(data_fname)
    print 'bg_im.shape',bg_im.shape
    print 'len(all_vals)',len(all_vals)
    print 'all_vals[0]',all_vals[0]
    print 'all_vals[-1]',all_vals[-1]

    fmf = FlyMovieFormat.FlyMovie(fmf_fname,check_integrity=True)
    print 'fmf.get_n_frames()',fmf.get_n_frames()
    print 'fmf.get_width(), fmf.get_height()',fmf.get_width(), fmf.get_height()
    print 'fmf.get_frame(0)[1]',fmf.get_frame(0)[1]
    print 'fmf.get_frame(-1)[1]',fmf.get_frame(-1)[1]

def print_info_main():
    fname_prefix = sys.argv[1]
    print_info(fname_prefix)

class TestTraxIO(unittest.TestCase):
    def test_fmt1(self):
        test_version(1)
    def test_fmt2(self):
        test_version(2)

    def test_fmt1_incomplete(self):
        test_version(1,incomplete=True)
    def test_fmt2_incomplete(self):
        test_version(2,incomplete=True)

def get_test_suite():
    suite = unittest.TestLoader().loadTestsFromTestCase(TestTraxIO)
    return suite

if __name__=='__main__':
    for version in VALID_VERSIONS:
        test_version(version)
