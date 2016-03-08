FROM phusion/baseimage
MAINTAINER Noah Levitt <nlevitt@archive.org>

ENV LANG=C.UTF-8

RUN apt-get update && apt-get --auto-remove -y dist-upgrade
RUN apt-get -y install vnc4server
RUN apt-get -y install chromium-browser
RUN apt-get -y install xfonts-base fonts-arphic-bkai00mp fonts-arphic-bsmi00lp fonts-arphic-gbsn00lp fonts-arphic-gkai00mp fonts-arphic-ukai fonts-farsiweb fonts-nafees fonts-sil-abyssinica fonts-sil-ezra fonts-sil-padauk fonts-unfonts-extra fonts-unfonts-core ttf-indic-fonts fonts-thai-tlwg fonts-lklug-sinhala
RUN apt-get -y install python3-pip git vlc
RUN apt-get -y install libjpeg-turbo8-dev zlib1g-dev
RUN pip3 install websockify

RUN adduser --disabled-password --gecos="Charlie Brozzler" brozzler

RUN mkdir -vp /etc/service/vncserver
ADD vncserver.sh /etc/service/vncserver/run

RUN mkdir -vp /etc/service/vnc-websock
ADD vnc-websock.sh /etc/service/vnc-websock/run

EXPOSE 5901 8901
EXPOSE 8080

# RUN pip3 install -i http://crawl342.us.archive.org:9000/nlevitt/dev/+simple/ git+https://github.com/nlevitt/brozzler.git

