#!/bin/sh

# https://github.com/phusion/baseimage-docker#adding-additional-daemons
# /usr/bin/vncserver backgrounds the Xvnc4 process, so we run Xvnc4 directly

exec setuser brozzler Xvnc4 :1 -desktop brozzler@`hostname`:1 -auth /tmp/Xauthority.brozzler -geometry 1600x1000 -depth 24 -rfbwait 0 -nolisten tcp -rfbport 5901 -pn -fp /usr/X11R6/lib/X11/fonts/Type1/,/usr/X11R6/lib/X11/fonts/Speedo/,/usr/X11R6/lib/X11/fonts/misc/,/usr/X11R6/lib/X11/fonts/75dpi/,/usr/X11R6/lib/X11/fonts/100dpi/,/usr/share/fonts/X11/misc/,/usr/share/fonts/X11/Type1/,/usr/share/fonts/X11/75dpi/,/usr/share/fonts/X11/100dpi/ -co /etc/X11/rgb >> /tmp/`hostname`:1.log 2>&1
