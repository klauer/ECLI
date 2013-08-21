#!/bin/bash
#
# ipython on the command line:
#   ipython --profile=ecli
# ipython with the Qt console:
#   ipython qtconsole --profile=ecli --pylab=inline

PROFILE="${1:-ecli}"
PROFILE_PATH=$(ipython locate profile $PROFILE)

echo "Profile is located in: $PROFILE_PATH"

if [ -f "$PROFILE_PATH/ecli_config.py" ]
then
    # If a configuration file exists in the profile directory, load it
    echo "Loading ECLI configuration from profile directory"
    ipython --profile=$PROFILE -c "%load_config $PROFILE_PATH/ecli_config.py" -i
elif [ -f ecli_config.py ]
then
    # If a configuration file exists in the current directory, load it
    echo "Loading ECLI configuration from the current directory"
    ipython --profile=$PROFILE -c "%load_config ecli_config.py" -i
else
    ipython --profile=$PROFILE
fi
