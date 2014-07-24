// {"request_idle_timeout_sec":10}
//
// vim:set sw=8 et:
//
// Scrolls to the bottom of the page. That's it at the moment.
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

var umbraState = {'idleSince':null};
var umbraAlreadyClicked = {};
var UMBRA_IFRAME_SOUNDCLOUD_EMBEDDED_SELECTOR = "iframe[src^='https://w.soundcloud.com/player']";
var UMBRA_THINGS_TO_CLICK_SOUNDCLOUD_EMBEDDED_SELECTOR = "button.playButton";
var umbraFinished = false;
var umbraIntervalFunc = function() {

	var umbraSoundCloudEmbeddedElements = getUmbraSoundCloudEmbeddedElements();
	
    var clickedSomething = false;
    var somethingLeftBelow = false;
    var somethingLeftAbove = false;
    var missedAbove = 0;
    
    for (var i = 0; i < umbraSoundCloudEmbeddedElements.length; i++) {
    
    		var targetId = umbraSoundCloudEmbeddedElements[i].id;
            var target = umbraSoundCloudEmbeddedElements[i].target;
            
            if (!(targetId in umbraAlreadyClicked)) {
                    var where = umbraAboveBelowOrOnScreen(target);
                    
                    if (where == 0) { // on screen
                            // var pos = target.getBoundingClientRect().top;
                            // window.scrollTo(0, target.getBoundingClientRect().top - 100);
                            console.log("clicking at " + target.getBoundingClientRect().top + " on " + target.outerHTML);
                            if (target.click != undefined) {
                                    target.click();
                            }
                            umbraAlreadyClicked[targetId] = true;
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
	
	if (umbraState.idleSince == null) {
                umbraState.idleSince = Date.now();
    }
}

//try to detect sound cloud "Play" buttons and return them as targets for clicking
var getUmbraSoundCloudEmbeddedElements = function() {
	
	var soundCloudEmbeddedElements = [];
	
	var id = 0;
	
	[].forEach.call(document.querySelectorAll(UMBRA_IFRAME_SOUNDCLOUD_EMBEDDED_SELECTOR), 
		function  fn(elem){ 
			if (elem.src.indexOf("auto_play=false") != -1) {
				    var button = elem.contentWindow.document.body.querySelectorAll(UMBRA_THINGS_TO_CLICK_SOUNDCLOUD_EMBEDDED_SELECTOR);
				   
				    //use the iframe's src attribute as the key to the sound cloud player button. assumption is that each iframe created by the sound cloud widget
				    //contains only a single unique audio file on a given page
					if (button && button.length > 0) {
						//get the Element from the NodeList
						soundCloudEmbeddedElements.push({"id" : elem.src, "target" : button.item(0)});
						id++;
					}
			    }
			}
	);
	
	return soundCloudEmbeddedElements;
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
