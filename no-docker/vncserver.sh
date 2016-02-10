#!/bin/bash
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec Xvnc4 :1 -auth /tmp/Xauthority.$USER -geometry 1600x1000 -depth 24 -rfbwait 0 -nolisten tcp -rfbport 5901 -SecurityTypes None -pn -fp /usr/share/fonts/X11/misc/ -co /etc/X11/rgb AcceptCutText=0 AcceptPointerEvents=0 AcceptKeyEvents=0 >> $script_dir/Xvnc4-`hostname -s`:1.out 2>&1

