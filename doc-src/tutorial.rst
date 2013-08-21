Tutorial
========

Core
----

Examples::

    %caget?
    %save_config

    # Edit 
    %load_config

    caget m1

    %find_field m1 user -v
    %find_field m1 user -a

    gui_config

Motor
-----

Examples::

    %load_ext ecli_motor
    %config ECLIMotor
    %config ECLIMotor.motor_list=['IOC:m1']
    m1.move(5)

    wm m1
    wa

    umvr m1 1
    umv m1 10

    edm m1

Scaler
------

Examples::

    %load_ext ecli_scaler
    ct

CAS
---

Examples::

    %load_ext ecli_cas
    %create_pv test float -l 0 -h 5

    caget ECLI:test
    caput ECLI:test 1.0

Step Scans
----------

Examples::

    %load_ext ecli_stepscan

    %config ECLIScanWriterSPEC.filename = 'spec_format.spec'
    %config ECLIScanWriterHDF5.filename = 'hdf5_format.hdf5'

    for i in range(2): 
        ascan(m1, 0.0, 1.0 + i, 5, 1)

    %mesh m1 1.0 2.0 3 m2 1.5 2.5 3 1

XMLRPC
------

Examples::

    (xmlrpc server...)


PyMca
-----

Examples::

    %load_ext ecli_pymca

    pymca



