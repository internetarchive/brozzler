// {"url_regex":"^https?://(?:www\\.)?facebook\\.com/.*$", "request_idle_timeout_sec":30}
//
// vim:set sw=8 et:
//

var umbraAboveBelowOrOnScreen = function(e) {
        var eTop = e.getBoundingClientRect().top;
        if (eTop < window.scrollY) {
                return -1; // above
        } else if (eTop > window.scrollY + window.innerHeight) {
                return 1;  // below
        } else {
                return 0;  // on screen
        }
}

// comments - 'a.UFIPagerLink > span, a.UFIPagerLink, span.UFIReplySocialSentenceLinkText'
var UMBRA_THINGS_TO_CLICK_SELECTOR = 'a[href^="/browse/likes"], *[rel="theater"]';
var umbraAlreadyClicked = {};
var umbraState = {'idleSince':null,'expectingSomething':null};

var umbraIntervalFunc = function() {
        var closeButtons = document.querySelectorAll('a[title="Close"], a.closeTheater');
        for (var i = 0; i < closeButtons.length; i++) {
                // XXX closeTheater buttons stick around in the dom after closing, clientWidth>0 is one way to check if they're visible
                if (closeButtons[i].clientWidth > 0) {  
                        if (umbraState.expectingSomething == 'closeButton') { 
                                console.log("found expected close button, clicking on it " + closeButtons[i].outerHTML);
                                umbraState.expectingSomething = null;
                        } else {
                                console.warn("found UNexpected close button, umbraState.expectingSomething=" + umbraState.expectingSomething + " ... clicking on it " + closeButtons[i].outerHTML);
                        }
                        closeButtons[i].click();
                        return;
                }
        }
        if (umbraState.expectingSomething == 'closeButton') {
                console.log("waiting for close button, haven't seen it yet");
                return;
        }

        var thingsToClick = document.querySelectorAll(UMBRA_THINGS_TO_CLICK_SELECTOR);
        var clickedSomething = false;
        var somethingLeftBelow = false;
        var somethingLeftAbove = false;
        var missedAbove = 0;

        for (var i = 0; i < thingsToClick.length; i++) {
                var target = thingsToClick[i]; 
                if (!(target in umbraAlreadyClicked)) {
                        var where = umbraAboveBelowOrOnScreen(target);
                        if (where == 0) { // on screen
                                // var pos = target.getBoundingClientRect().top;
                                // window.scrollTo(0, target.getBoundingClientRect().top - 100);
                                console.log("clicking at " + target.getBoundingClientRect().top + " on " + target.outerHTML);
                                if (target.click != undefined) {
                                        umbraState.expectingSomething = 'closeButton';
                                        target.click();
                                }
                                target.style.border = '1px solid #0a0';
                                umbraAlreadyClicked[target] = true;
                                clickedSomething = true;
                                umbraState.idleSince = null;
                                break;
                        } else if (where > 0) { 
                                somethingLeftBelow = true;
                        } else if (where < 0) {
                                somethingLeftAbove = true;
                        }
                }
        }

        if (!clickedSomething) {
                if (somethingLeftAbove) {
                        console.log("scrolling UP because everything on this screen has been clicked but we missed something above");
                        window.scrollBy(0, -500);
                        umbraState.idleSince = null;
                } else if (somethingLeftBelow) {
                        console.log("scrolling because everything on this screen has been clicked but there's more below document.body.clientHeight=" + document.body.clientHeight);
                        window.scrollBy(0, 200);
                        umbraState.idleSince = null;
                } else if (window.scrollY + window.innerHeight < document.documentElement.scrollHeight) {
                        console.log("scrolling because we're not to the bottom yet document.body.clientHeight=" + document.body.clientHeight);
                        window.scrollBy(0, 200);
                        umbraState.idleSince = null;
                } else if (umbraState.idleSince == null) {
                        umbraState.idleSince = Date.now();
                }
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


var umbraIntervalId = setInterval(umbraIntervalFunc, 200);
