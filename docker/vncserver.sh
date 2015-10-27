#!/bin/bash

# https://github.com/phusion/baseimage-docker#adding-additional-daemons
# /usr/bin/vncserver backgrounds the Xvnc4 process, so we run Xvnc4 directly

# password_file=/tmp/vnc-passwd
# /bin/echo -ne '\x95\x3f\x23\x7a\x76\x2a\x05\x89' > $password_file
# exec setuser brozzler Xvnc4 :1 -desktop brozzler@`hostname`:1 -auth /tmp/Xauthority.brozzler -geometry 1600x1000 -depth 24 -rfbwait 0 -nolisten tcp -rfbport 5901 -rfbauth $password_file -pn -fp /usr/share/fonts/X11/misc/ -co /etc/X11/rgb >> /tmp/`hostname`:1.log 2>&1

exec setuser brozzler Xvnc4 :1 -desktop brozzler@`hostname`:1 -auth /tmp/Xauthority.brozzler -geometry 1600x1000 -depth 24 -rfbwait 0 -nolisten tcp -rfbport 5901 -SecurityTypes None -pn -fp /usr/share/fonts/X11/misc/ -co /etc/X11/rgb AcceptCutText=0 AcceptPointerEvents=0 AcceptKeyEvents=0 >> /tmp/`hostname`:1.log 2>&1

