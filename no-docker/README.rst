Chromium seemed to be dying more often when running in a docker container.

To start the services brozzler-worker depends on:
/home/nlevitt/workspace/brozzler/no-docker/vncserver.sh & /home/nlevitt/workspace/brozzler/no-docker/vnc-websock.sh &

Prerequisites:
apt-get -y install vnc4server chromium-browser xfonts-base fonts-arphic-bkai00mp fonts-arphic-bsmi00lp fonts-arphic-gbsn00lp fonts-arphic-gkai00mp fonts-arphic-ukai fonts-farsiweb fonts-nafees fonts-sil-abyssinica fonts-sil-ezra fonts-sil-padauk fonts-unfonts-extra fonts-unfonts-core ttf-indic-fonts fonts-thai-tlwg fonts-lklug-sinhala python3-pip git libjpeg-turbo8-dev zlib1g-dev 
