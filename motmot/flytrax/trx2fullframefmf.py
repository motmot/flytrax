from __future__ import division, with_statement
import pkg_resources
import numpy as np
import motmot.FlyMovieFormat.FlyMovieFormat as fmf_mod
import motmot.flytrax.traxio as traxio
import os, sys, collections
from optparse import OptionParser

def trx2fmf(trx_filename,output_filename):
    base,ext = os.path.splitext(trx_filename)
    assert ext=='.trx','must give .trx filename'
    fmf_filename = base + '.fmf'
    fmf = fmf_mod.FlyMovie(fmf_filename)
    assert fmf.get_format()=='MONO8'
    w,h=fmf.get_width(),fmf.get_height()
    bg_image, orig_data = traxio.readtrax(trx_filename,
                                          return_structured_array=True)
    progress=True
    if progress:
        import progressbar
        widgets=['saving frames: ', progressbar.Percentage(), ' ',
                 progressbar.Bar(), ' ', progressbar.ETA()]
        pbar=progressbar.ProgressBar(widgets=widgets,maxval=len(orig_data)).start()

    cur_image = np.array(bg_image,copy=True)

    fmf_saver = fmf_mod.FlyMovieSaver(output_filename)
    for i,trx_row in enumerate(orig_data):
        if progress:
            pbar.update(i)
        orig_fmf_image,fmf_timestamp = fmf.get_next_frame()
        assert trx_row['timestamp']==fmf_timestamp
        windowx=trx_row['windowx'][0]
        windowy=trx_row['windowy'][0]
        cur_image[windowy:windowy+h,windowx:windowx+w] = orig_fmf_image
        fmf_saver.add_frame(cur_image,fmf_timestamp)
    fmf_saver.close()
    fmf.close()
    if progress:
        pbar.finish()

def main():
    usage = '%prog INPUT.trx OUTPUT.fmf [options]'
    parser = OptionParser(usage)
    (options, args) = parser.parse_args()

    if len(args)>2:
        print >> sys.stderr,  "too many arguments given"
        parser.print_help()
        sys.exit(1)

    if len(args)<2:
        print >> sys.stderr,  "too few arguments given"
        parser.print_help()
        sys.exit(1)

    trx_filename=args[0]
    output_filename=args[1]
    trx2fmf(trx_filename,output_filename)

if __name__=='__main__':
    main()
