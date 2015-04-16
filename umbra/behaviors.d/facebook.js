// vim:set sw=8 et:

var umbraAboveBelowOrOnScreen = function(e) {
        var eTop = e.getBoundingClientRect().top;
        if (eTop < window.scrollY) {
                return -1; // above
        } else if (eTop > window.scrollY + window.innerHeight) {
                // if (e.clientWidth != 0) {
                //         console.warn("e.clientWidth=" + e.clientWidth + " though it appears to be below the screen? e.getBoundingClientRect().top=" + eTop + " window.scrollY=" + window.scrollY + " window.innerHeight=" + window.innerHeight + " e=" + e);
                // }
                return 1;  // below
        } else {
                // if (e.clientWidth != 0) {
                //         console.warn("e.clientWidth=" + e.clientWidth + " though it appears to be on screen? e.getBoundingClientRect().top=" + eTop + " window.scrollY=" + window.scrollY + " window.innerHeight=" + window.innerHeight + " e=" + e);
                // }
                return 0;  // on screen
        }
}

// comments - 'a.UFIPagerLink > span, a.UFIPagerLink, span.UFIReplySocialSentenceLinkText'
var UMBRA_THINGS_TO_CLICK_SELECTOR = 'a[href^="/browse/likes"], *[rel="theater"]';
//div[class="phm pluginLikeboxStream"] = facebook widget embedded in 3rd party pages
var UMBRA_THINGS_TO_SCROLL_SELECTOR = 'div[class="phm pluginLikeboxStream"]';
var NUMBER_FAILED_SCROLL_ATTEMPTS_ON_THING_TO_SCROLL_BEFORE_STOP_SCROLLING = 5;
var umbraAlreadyClicked = {};
var umbraAlreadyScrolledThing = {};
var umbraScrolledThingFailedScrollAttempts = {};
var umbraState = {'idleSince':null,'expectingSomething':null,'bottomReachedScrollY':0};

var umbraIntervalFunc = function() {
	
		var thingsToScroll = document.querySelectorAll(UMBRA_THINGS_TO_SCROLL_SELECTOR);
		var everythingScrolled = true;
		
		for (var i = 0; i < thingsToScroll.length; i++) {
			var target = thingsToScroll[i];
			
			if (!(target in umbraAlreadyScrolledThing)) {
				
				everythingScrolled = false;
				
				console.log("scrolling to " + target.scrollHeight + " on element with nodeName " + target.nodeName + " with id of " + target.id);
				var lastScrollTop = target.scrollTop;
				target.scrollTop = target.scrollHeight;
				
				umbraState.idleSince = null;
				
				if (target.scrollTop >= target.scrollHeight) {
					umbraAlreadyScrolledThing[target] = true;
				} 
				else if (target.scrollTop == lastScrollTop) {
					if (umbraScrolledThingFailedScrollAttempts[target]) {
						umbraScrolledThingFailedScrollAttempts[target]++;
					}
					else {
						umbraScrolledThingFailedScrollAttempts[target] = 1;
					}
					
					if (umbraScrolledThingFailedScrollAttempts[target] >= NUMBER_FAILED_SCROLL_ATTEMPTS_ON_THING_TO_SCROLL_BEFORE_STOP_SCROLLING) {
						umbraAlreadyScrolledThing[target] = true;
					}
				}
				else {
					//reset failed count on a successful scroll
					umbraScrolledThingFailedScrollAttempts[target] = 0;
				}
			}
			else {
				console.log("done scrolling for element with nodeName " + target.nodeName + " with id of " + target.id)
			} 
			
			umbraState.expectingSomething = null;
		}
		
		if (thingsToScroll && thingsToScroll.length > 0 && everythingScrolled) {
			if (umbraState.idleSince == null) {
				umbraState.idleSince = Date.now();
			}
            
			return;
		}
	
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
        
        if (window.scrollY > umbraState.bottomReachedScrollY) {
                umbraState.bottomReachedScrollY = window.scrollY;
        }

        if (!clickedSomething) {
                if (somethingLeftBelow) {
                        // console.log("scrolling down because everything on this screen has been clicked but there's more below document.body.clientHeight=" + document.body.clientHeight);
                        window.scrollBy(0, 300);
                        umbraState.idleSince = null;
                } else if (umbraState.bottomReachedScrollY + window.innerHeight < document.documentElement.scrollHeight) {
                        // console.log("scrolling down because we haven't reached the bottom yet document.body.clientHeight=" + document.body.clientHeight);
                        window.scrollBy(0, 300);
                        umbraState.idleSince = null;
                } else if (somethingLeftAbove) {
                        // console.log("scrolling UP because we've already been to the bottom, everything on or below this screen has been clicked, but we missed something above");
                        window.scrollBy(0, -600);
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
