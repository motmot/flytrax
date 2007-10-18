from setuptools import setup

setup(name='flytrax',
      description='plugin for fview to perform 2D image tracking (part of the motmot camera packages)',
      version='0.5.2',
      license='BSD',
      author='Andrew Straw',
      author_email='strawman@astraw.com',
      url='http://code.astraw.com/projects/motmot',
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
                                 'trax_udp_sender.xrc',
                                 'read_trx.m', # include matlab reader...
                                 ]},
      )
