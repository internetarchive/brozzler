/*
 * brozzler/behaviors.d/huffpostslides.js - from article, start slideshow and 
 * click through end
 *
 * Copyright (C) 2014-2017 Internet Archive
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

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

var umbraIntervalFunc = function() {
	var clickedSomething = false;
	var somethingLeftBelow = false;
	var somethingLeftAbove = false;

	if (!('slides' in umbraAlreadyClicked)) {
		var target = document.querySelector('.slideshow');
		var where = umbraAboveBelowOrOnScreen(target);
		if (where === 0) {
			var mouseOverEvent = document.createEvent('Events');
			mouseOverEvent.initEvent("mouseover", true, false);
			target.dispatchEvent(mouseOverEvent);
			target.click();
			clickedSomething = true;
			umbraState.idleSince = null;
			umbraAlreadyClicked['slides'] = true;
		} else if (where > 0) {
			somethingLeftBelow = true;
		} else if (where < 0) {
			somethingLeftAbove = true;
		}
	} else if (!(location.href in umbraAlreadyClicked)){
		var target = document.querySelector('.slideshow-overlay__container__left__nav__next');
		target.id = location.href
		var where = umbraAboveBelowOrOnScreen(target);
		if (where === 0) {
			var mouseOverEvent = document.createEvent('Events');
			mouseOverEvent.initEvent("mouseover", true, false);
			target.dispatchEvent(mouseOverEvent);
			target.click();
			clickedSomething = true;
			umbraState.idleSince = null;
			console.log('clicked ' + target.id);
			umbraAlreadyClicked[target.id] = true;
		} else if (where > 0) {
			somethingLeftBelow = true;
		} else if (where < 0) {
			somethingLeftAbove = true;
		}
	}

	if (!clickedSomething) {
		if (somethingLeftAbove) {
			// console.log("scrolling UP because everything on this screen has been clicked but we missed something above");
			window.scrollBy(0, -500);
			umbraState.idleSince = null;
		} else if (somethingLeftBelow) {
			// console.log("scrolling because everything on this screen has been clicked but there's more below document.body.clientHeight="
			// 				+ document.body.clientHeight);
			window.scrollBy(0, 200);
			umbraState.idleSince = null;
		} else if (window.scrollY + window.innerHeight < document.documentElement.scrollHeight) {
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

// If we haven't had anything to do (scrolled, clicked, etc) in this amount of
// time, then we consider ourselves finished with the page.
var UMBRA_USER_ACTION_IDLE_TIMEOUT_SEC = 5;

// Called from outside of this script.
var umbraBehaviorFinished = function() {
  if (umbraState.idleSince != null) {
    var idleTimeMs = Date.now() - umbraState.idleSince;
    if (idleTimeMs / 1000 > UMBRA_USER_ACTION_IDLE_TIMEOUT_SEC) {
      clearInterval(umbraIntervalId);
      return true;
    }
  }
  return false;
}

var umbraIntervalId = setInterval(umbraIntervalFunc, 2000);
