#!/bin/sh
DISPLAY=:1 exec setuser brozzler cvlc screen:// :screen-fps=3 :screen-caching=100 ':sout=#transcode{vcodec=theo,vb=800,scale=0.5,acodec=none}:http{mux=ogg,dst=:8080/screen}' :sout-keep >> /tmp/vlc-screencast.out 2>&1
