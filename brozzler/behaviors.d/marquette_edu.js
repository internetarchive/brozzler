/*
 * brozzler/behaviors.d/flickr.js - behavior for marquette.edu, clicks to
 * play/crawl embedded videos
 *
 * Copyright (C) 2014-2016 Internet Archive
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

var umbraState = {'idleSince':null};
var umbraIntervalID = setInterval(umbraScrollInterval,50);
var umbraAlreadyClicked = {};
function umbraScrollInterval() {

   //if not at the bottom
   if(window.scrollY + window.innerHeight < document.documentElement.scrollHeight) {
       umbraScroll();
       umbraState.idleSince=null;
   }
   else {
	var videoBoxes = document.querySelectorAll("div#vid_box a");
	var clickedVideo = false;

	for(i=0;i<videoBoxes.length;i++) {
	    if(!(videoBoxes[i] in umbraAlreadyClicked)){
		videoBoxes[i].click();
		umbraState.idleSince=null;
		umbraAlreadyClicked[videoBoxes[i]]=true;
		clickedVideo=true;
	    }
	}

	if(!clickedVideo && umbraState.idleSince==null) {
	    umbraState.idleSince=Date.now();
	}
   }

}

function umbraScroll() {
    window.scrollBy(0,50);
}


// If we haven't had anything to do (scrolled, clicked, etc) in this amount of
// time, then we consider ourselves finished with the page.

var UMBRA_USER_ACTION_IDLE_TIMEOUT_SEC = 10;

// Called from outside of this script.
var umbraBehaviorFinished = function() {
    if (umbraState.idleSince != null) {
	var idleTimeMs = Date.now() - umbraState.idleSince;
	if (idleTimeMs / 1000 > UMBRA_USER_ACTION_IDLE_TIMEOUT_SEC) {
            clearInterval(umbraIntervalID);
	    return true;
	}
    }
    return false;
}

