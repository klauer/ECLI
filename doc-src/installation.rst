Installation
------------

------
Ubuntu
------

Required packages::

    % sudo apt-get install ipython python-h5py git python-pip

Optional package for Qt console (with inline plots)::

    % sudo apt-get install ipython-qtconsole

Install pyepics (the -E will allow your proxy settings to be used with pip, if necessary)::

    % sudo -E pip install pyepics

Download the ECLI source::

    % git clone https://github.com/klauer/ECLI.git ecli
    % cd ecli
    % pwd # <-- this line tells you the full path to your ECLI installation

To have scan support, install pyEpics' StepScan::

    % git clone https://github.com/pyepics/stepscan.git stepscan_install
    % mkdir stepscan
    % cp -R stepscan_install/lib stepscan
    % rm -rf stepscan_install

.. note:: StepScan requires sqlalchemy, although its functionality can be safely removed from StepScan (TODO need to add request to remove this dependency, or at least make it optional)

Create an ECLI profile and edit it::

    % ipython profile create ecli
    % sh edit_profile.sh ecli

Search for the 'extensions' in the profile and modify the `c.InteractiveShellApp.extensions` line to look like this::

    c.InteractiveShellApp.extensions = ['ecli_core', 'ecli_motor', 'ecli_stepscan', 'ecli_scanprinter', 'ecli_scanwriter_spec', 'ecli_scanwriter_hdf5', 'ecli_xmlrpc', 'ecli_scaler', 'ecli_opi', 'ecli_cas', 'ecli_pymca']
.. note:: Add or remove extensions based on your needs, but ecli_core has to be loaded before the others.

Optionally, to make it so functions can be called simply on the IPython command line (i.e., without parentheses and commas between arguments), set::

    c.TerminalInteractiveShell.autocall = 2

Add ECLI to the PYTHONPATH environment variable::

    % echo export PYTHONPATH=/full/path/to/ECLI:$$PYTHONPATH >> ~/.profile
    % source ~/.profile

Run ipython with the correct profile::

  % ipython --profile=ecli

or, using the Qt console::

  % ipython qtconsole --profile=ecli --pylab=inline

..................
PyMca installation
..................

.. note:: The paths in the examples are for Ubuntu with Python 2.7. You may have to modify these paths for your distribution/Python version.

Required packages::

    % sudo apt-get install python-h5py python-numpy python-qt4 python-qwt5-qt4 python-matplotlib

Although PyMca is available on the Ubuntu software repository, it may not be the latest version. Install PyMca from source::
    
    % sudo apt-get install subversion
    % svn checkout svn://svn.code.sf.net/p/pymca/code/ pymca-code
    % cd pymca-code
    % python setup.py build
    % sudo python setup.py install

Start ECLI and load pymca::
    
    In [1]: pymca()
    In [2]: pymca     # if you have autocall set to 2, this will work

-------
Windows
-------

TODO installation notes -- but it does work -- can also potentially distribute packaged, portable executable


