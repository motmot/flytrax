from setuptools import setup

from motmot_utils import get_svnversion_persistent
version_str = '0.4.dev%(svnversion)s'
version = get_svnversion_persistent('flytrax/version.py',version_str)

setup(name='flytrax',
      version=version,
      license='BSD',
      entry_points = {
    'cam_iface.fview_plugins':'flytrax = flytrax:Tracker',
    'console_scripts': [
    'flytrax_print_info = flytrax.traxio:print_info_main',
    ],
    'gui_scripts': [
    'flytrax_replay = flytrax.trax_replay:main',
    ]
    },

      packages = ['flytrax'],
      install_requires = ['cam_iface',
                          'wxvideo>=0.3.dev286',
                          'imops>=0.3.dev288',
                          'FastImage>=0.4.dev1',
                          'realtime_image_analysis>=0.4.dev1',
                          'FlyMovieFormat',
                          'wxvalidatedtext',
                          'wxwrap'],
      zip_safe=True,
      package_data = {'flytrax':['flytrax.xrc',
                                 'trax_replay.xrc',
                                 'read_trx.m', # include matlab reader...
                                 ]},
      )
