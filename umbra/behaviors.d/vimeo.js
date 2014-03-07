//^https?://(?:www\.)?vimeo.com/.*$

var videoElements = document.getElementsByTagName('video');
for (var i = 0; i < videoElements.length; i++) {
	videoElements[i].play();
}

