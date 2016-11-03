/*
 * brozzler/behaviors.d/flickr.js - behavior for instagram
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


var umbraInstagramBehavior = {
        IDLE_TIMEOUT_SEC: 20,
        idleSince: null,

        intervalFunc: function() {
                if (window.scrollY + window.innerHeight < document.documentElement.scrollHeight) {
                        window.scrollBy(0, 200);
                        this.idleSince = null;
                        return;
                }

                var moreButtons = document.querySelectorAll("a._oidfu");
                if (moreButtons.length > 0) {
                        console.log("clicking load more button");
                        moreButtons[0].click();
                        this.idleSince = null;
                        return;
                }

                if (this.idleSince == null) {
                        console.log("nothing to do at the moment, might be waiting for something to load, setting this.idleSince=Date.now()");
                        this.idleSince = Date.now();
                        return;
                }
        },

        start: function() {
                var that = this;
                this.intervalId = setInterval(function(){ that.intervalFunc() }, 50);
        },

        isFinished: function() {
                if (this.idleSince != null) {
                        var idleTimeMs = Date.now() - this.idleSince;
                        if (idleTimeMs / 1000 > this.IDLE_TIMEOUT_SEC) {
                                clearInterval(this.intervalId);
                                return true;
                        }
                }
                return false;
        },
};

// Called from outside of this script.
var umbraBehaviorFinished = function() { return umbraInstagramBehavior.isFinished() };

umbraInstagramBehavior.start();
