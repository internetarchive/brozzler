// {"url_regex":"^https?://(?:www\\.)?instagram\\.com/.*$", "request_idle_timeout_sec":10}
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
	var more = document.querySelectorAll("span.more-photos a.more-photos-enabled");
	if(more.length>0) {
	    more[0].click();
	    umbraState.idleSince=Date.now();
	}
	else if(document.querySelectorAll("span.more-photos a.more-photos-disabled").length>0) { //finally done scrolling/loading
	    clearInterval(intervalID);
	    umbraState.idleSince=null;
	    images = document.querySelectorAll("li.photo div.photo-wrapper a.bg[data-reactid]");
	    if(images && images !=='undefined' && images.length>0 ) {
		images[0].click();
		imageID++;
		imageCount=images.length;
	    }
	    intervalID = setInterval(clickPhotosInterval,200);
	}
   }
}

function clickPhotosInterval() {
    rightArrow = document.querySelectorAll("a.mmRightArrow");
    
    if(imageID>=imageCount) {
	clearInterval(intervalID);
	umbraState.done=true;
	umbraState.idleSince=(Date.now()-50000);//ready to exit
    }
    else {
	rightArrow[0].click();
	imageID++;
	umbraState.idleSince=Date.now();
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
    
