// {"url_regex":"^https?://(?:www\\.)?instagram\\.com/.*$", "request_idle_timeout_sec":10}
//
// vim:set sw=8 et:
//
var UMBRA_USER_ACTION_IDLE_TIMEOUT_SEC = 10;

var umbraState = {'idleSince':null,'expectingSomething':null,'done':false};

var umbraIntervalID = setInterval(umbraScrollInterval,50);
var umbraImages;
var umbraImageID=0;
var umbraImageCount=0;

function umbraScrollInterval() {

    //if not at the bottom, keep scrolling
    if(window.scrollY + window.innerHeight < document.documentElement.scrollHeight) {
	window.scrollBy(0,50);
	umbraState.expectingSomething=null;
	umbraState.idleSince=null;
    }
    else {
	var more = document.querySelectorAll("span.more-photos a.more-photos-enabled");
	if(more.length>0 && umbraState.expectingSomething==null) {
	    more[0].click();
	    umbraState.expectingSomething="load more";
	    umbraState.idleSince=Date.now();
	}
	else if(document.querySelectorAll("span.more-photos a.more-photos-disabled").length>0 || umbraTimeoutExpired() ) { //done scrolling/loading
	    clearInterval(umbraIntervalID);
	    umbraImages = document.querySelectorAll("li.photo div.photo-wrapper a.bg[data-reactid]");
	    
	    //click first image
	    if(umbraImages && umbraImages !=='undefined' && umbraImages.length>0 ) {
		umbraImages[0].click();
		umbraImageID++;
		umbraImageCount=umbraImages.length;
	    }
	    intervalID = setInterval(umbraClickPhotosInterval,200);
	}
    }
}

function umbraClickPhotosInterval() {
    rightArrow = document.querySelectorAll("a.mmRightArrow");
    
    if(umbraImageID>=umbraImageCount) {
	clearInterval(umbraIntervalID);
	umbraState.done=true
    }
    else {
	rightArrow[0].click();
	umbraImageID++;
    }
}

function umbraTimeoutExpired () {
    if (umbraState.idleSince != null) {
	var idleTimeMs = Date.now() - umbraState.idleSince;
	return (idleTimeMs/1000 > UMBRA_USER_ACTION_IDLE_TIMEOUT_SEC);
    }
    return false;
}

// Called from outside of this script.
var umbraBehaviorFinished = function() {
    return umbraState.done;
}
    
