//^https?://(?:www\.)?facebook.com/.*$

var isOnScreen = function(e) {
        var eTop = e.getBoundingClientRect().top;
        return eTop > window.scrollY && eTop < window.scrollY + window.innerHeight;
};
 
var THINGS_TO_CLICK_SELECTOR = 'a.UFIPagerLink > span, a.UFIPagerLink, a[href^="/browse/likes"], span.UFIReplySocialSentenceLinkText, a.photo';
var alreadyClicked = {};
var intervalId;
 
var intervalFunc = function() {
        var closeButton = document.querySelector('a[title="Close"]');
        if (closeButton) { 
                console.log("clicking close button " + closeButton);
                closeButton.click();
                return;
        }
        var closeTheaterButton = document.querySelector('a.closeTheater');
        if (closeTheaterButton && closeTheaterButton.offsetWidth > 0) { 
                console.log("clicking close button " + closeTheaterButton);
                closeTheaterButton.click();
                return;
        }
         
        var thingsToClick = document.querySelectorAll(THINGS_TO_CLICK_SELECTOR);
        var clickedSomething = false;
        var somethingLeftToClick = false;
 
        for (var i = 0; i < thingsToClick.length; i++) {
                var target = thingsToClick[i]; 
                if (!(target in alreadyClicked)) {
                        if (isOnScreen(target)) {
                                // var pos = target.getBoundingClientRect().top;
                                // window.scrollTo(0, target.getBoundingClientRect().top - 100);
                                console.log("clicking at " + target.getBoundingClientRect().top + " on " + target);
                                target.click();
                                target.style.border = '1px solid #0a0';
                                alreadyClicked[target] = true;
                                clickedSomething = true;
                                break;
                        } else {
                                somethingLeftToClick = true;
                        }
                }
        }
 
        if (!clickedSomething) {
                if (somethingLeftToClick) {
                        console.log("scrolling because everything on this screen has been clicked but there's more below document.body.clientHeight=" + document.body.clientHeight);
                        window.scrollBy(0, 100);
                } else if (window.scrollY + window.innerHeight + 10 < document.body.clientHeight) {
                        console.log("scrolling because we're not to the bottom yet document.body.clientHeight=" + document.body.clientHeight);
                        window.scrollBy(0, 100);
                } 
        }
}
 
var intervalId = setInterval(intervalFunc, 200);
