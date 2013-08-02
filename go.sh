#!/bin/bash
#
# ipython on the command line:
#   ipython --profile=ecli
# ipython with the Qt console:
#   ipython qtconsole --profile=ecli --pylab=inline

PROFILE="${1:-ecli}"
echo Profile is located in: `ipython locate profile $PROFILE`

ipython --profile=$PROFILE 
#2> stderr
