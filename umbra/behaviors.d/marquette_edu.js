// {"url_regex":"^https?://(?:www\\.)?marquette\\.edu/.*$", "request_idle_timeout_sec":10}
//
// vim:set sw=8 et:
//

var umbraState = {'idleSince':null,'done':null};


var intervalID = setInterval(scrollInterval,50);
var images;
var imageID=0;
var imageCount=0;
function scrollInterval() {
   scroll();

   //if not at the bottom
   if(window.scrollY + window.innerHeight < document.documentElement.scrollHeight) {
       umbraState.idleSince=Date.now();
   }
   else {
       clearInterval(intervalID);
       umbraState.idleSince=null;
	var videoBox = document.querySelectorAll("div#vid_box a");
	if(videoBox.length>0) {
	    for(i=0;i<videoBox.length;i++) {
		videoBox[i].click();
		umbraState.idleSince=Date.now();
	    }
	}
   }
}

function scroll() {
    window.scrollBy(0,50);
}


// If we haven't had anything to do (scrolled, clicked, etc) in this amount of
// time, then we consider ourselves finished with the page.

var UMBRA_USER_ACTION_IDLE_TIMEOUT_SEC = 10;

// Called from outside of this script.
var umbraBehaviorFinished = function() {
    if(umbraState.done!=null && umbraState.done==true) {
	return true;
    }
    if (umbraState.idleSince != null) {
	var idleTimeMs = Date.now() - umbraState.idleSince;
	if (idleTimeMs / 1000 > UMBRA_USER_ACTION_IDLE_TIMEOUT_SEC) {
	    return true;
	}
    }
    return false;
}
    
