// vim:set sw=8 et:
//
// Scrolls to the bottom of the page. That's it at the moment.
//

var umbraState = {'idleSince':null};
var umbraFinished = false;
var umbraIntervalFunc = function() {
	var needToScroll = (window.scrollY + window.innerHeight < document.documentElement.scrollHeight);

        // console.log('intervalFunc umbraState.idleSince=' + umbraState.idleSince + ' needToScroll=' + needToScroll + ' window.scrollY=' + window.scrollY + ' window.innerHeight=' + window.innerHeight + ' document.documentElement.scrollHeight=' + document.documentElement.scrollHeight);
	if (needToScroll) {
		window.scrollBy(0, 200);
		umbraState.idleSince = null;
	} else if (umbraState.idleSince == null) {
                umbraState.idleSince = Date.now();
        }
}

// If we haven't had anything to do (scrolled, clicked, etc) in this amount of
// time, then we consider ourselves finished with the page.
var UMBRA_USER_ACTION_IDLE_TIMEOUT_SEC = 10;

// Called from outside of this script.
var umbraBehaviorFinished = function() {
        if (umbraState.idleSince != null) {
                var idleTimeMs = Date.now() - umbraState.idleSince;
                if (idleTimeMs / 1000 > UMBRA_USER_ACTION_IDLE_TIMEOUT_SEC) {
                        return true;
                }
        }
        return false;
}

var umbraIntervalId = setInterval(umbraIntervalFunc, 100);
