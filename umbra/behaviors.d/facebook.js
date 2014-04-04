//^https?://(?:www\.)?facebook.com/.*$
// vim:set sw=8 et:

var aboveBelowOrOnScreen = function(e) {
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
var THINGS_TO_CLICK_SELECTOR = 'a[href^="/browse/likes"], *[rel="theater"]';
var alreadyClicked = {};
var intervalId;

var intervalFunc = function() {
        var closeButton = document.querySelector('a[title="Close"]');
        if (closeButton) { 
                console.log("clicking close button " + closeButton.outerHTML);
                closeButton.click();
                return;
        }
        var closeTheaterButton = document.querySelector('a.closeTheater');
        if (closeTheaterButton && closeTheaterButton.offsetWidth > 0) { 
                console.log("clicking close button " + closeTheaterButton.outerHTML);
                closeTheaterButton.click();
                return;
        }

        var thingsToClick = document.querySelectorAll(THINGS_TO_CLICK_SELECTOR);
        var clickedSomething = false;
        var somethingLeftBelow = false;
        var missedAbove = 0;

        for (var i = 0; i < thingsToClick.length; i++) {
                var target = thingsToClick[i]; 
                if (!(target in alreadyClicked)) {
                        var where = aboveBelowOrOnScreen(target);
                        if (where == 0) { // on screen
                                // var pos = target.getBoundingClientRect().top;
                                // window.scrollTo(0, target.getBoundingClientRect().top - 100);
                                console.log("clicking at " + target.getBoundingClientRect().top + " on " + target.outerHTML);
                                if(target.click != undefined) {
                                        target.click();
                                }
                                target.style.border = '1px solid #0a0';
                                alreadyClicked[target] = true;
                                clickedSomething = true;
                                break;
                        } else if (where > 0) { 
                                somethingLeftBelow = true;
                        } else {
                                missedAbove++;
                        }
                }
        }

        if (missedAbove > 0) {
                console.log("somehow missed " + missedAbove + " click targets above");
        }

        if (!clickedSomething) {
                if (somethingLeftBelow) {
                        console.log("scrolling because everything on this screen has been clicked but there's more below document.body.clientHeight=" + document.body.clientHeight);
                        window.scrollBy(0, 200);
                } else if (window.scrollY + window.innerHeight + 10 < document.body.clientHeight) {
                        console.log("scrolling because we're not to the bottom yet document.body.clientHeight=" + document.body.clientHeight);
                        window.scrollBy(0, 200);
                } 
        }
}

var intervalId = setInterval(intervalFunc, 200);
