@echo off
set PROFILE=ecli
echo Profile is located in:
ipython locate profile %PROFILE%

rem ipython --profile=%PROFILE% --pylab 2> stderr
ipython --profile=%PROFILE% 2> stderr
