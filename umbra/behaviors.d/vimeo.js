// vim:set sw=8 et:

var umbraState = {'idleSince':null};
var umbraVideoElements = document.getElementsByTagName('video');
for (var i = 0; i < umbraVideoElements.length; i++) {
	umbraVideoElements[i].play();
}
umbraState.idleSince = Date.now();

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

