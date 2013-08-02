#!/bin/bash

PROFILE="${1:-ecli}"
echo "Profile is $PROFILE"

editor `ipython locate profile $PROFILE`/ipython_config.py

