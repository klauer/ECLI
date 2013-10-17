#!/bin/bash

PROFILE="${1:-ecli}"
CONFIG_FILE=`ipython locate profile $PROFILE`/ipython_config.py

echo "Profile is $PROFILE"
echo "Configuration file location: $CONFIG_FILE"

if [ -n "$EDITOR" ];
then
    $EDITOR $CONFIG_FILE
else
    editor $CONFIG_FILE
fi
