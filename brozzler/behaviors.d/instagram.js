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
        state: "loading-thumbs",
        imageCount: null,
        bigImagesLoaded: 0,
        currentBigImage: null,
        previousBigImage: null,

        intervalFunc: function() {
                if (this.state === "loading-thumbs") {
                        if (window.scrollY + window.innerHeight < document.documentElement.scrollHeight) {
                                window.scrollBy(0, 200);
                                this.idleSince = null;
                                return;
                        }

                        var moreButtons = document.querySelectorAll(".PhotoGridMoreButton:not(.pgmbDisabled)");
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
                        } else {
                                var doneButtons = document.querySelectorAll(".PhotoGridMoreButton.pgmbDisabled");
                                if (Date.now() - this.idleSince > 9000 || (doneButtons.length > 0 && doneButtons[0].innerText === "All items loaded") ) {
                                        console.log("finished loading-thumbs, it appears we have reached the bottom");
                                        this.state = "clicking-first-thumb";
                                        this.idleSince = null;
                                        return;
                                } else {
                                        // console.log("still might be waiting for something to load...");
                                        return;
                                }
                        }
                }

                if (this.state === "clicking-first-thumb") {
                        var images = document.querySelectorAll("a.pgmiImageLink");
                        if (images && images !== "undefined") {
                                this.imageCount = images.length;
                                if (images.length > 0) {
                                        console.log("clicking first thumbnail");
                                        images[0].click();
                                        this.idleSince = null;
                                        this.state = "waiting-big-image";
                                        return;
                                }
                        }

                        console.log("no big images to load?");
                        this.idleSince = Date.now();
                        return;
                }

                if (this.state === "waiting-big-image") {
                        if(this.currentBigImage == null) {
                                var imageFrame = document.querySelectorAll("div.Modal div.Item div.iMedia div.Image");
                                if (imageFrame.length > 0 && imageFrame[0].getAttribute("src") !== this.previousBigImage ) {
                                        this.currentBigImage = new Image();
                                        this.currentBigImage.src = imageFrame[0].getAttribute("src");
                                        //console.log("this.currentBigImage.naturalWidth=" + this.currentBigImage.naturalWidth + " this.currentBigImage.src=" + this.currentBigImage.src);
                                        return;
                                } else if(this.idleSince == null ) {
                                        console.log("waiting for image frame to load");
                                        this.idleSince = Date.now();
                                        return;
                                }
                        } else if (this.currentBigImage.src !== this.previousBigImage && this.currentBigImage.naturalWidth !== 0) {
                                console.log("next big image appears loaded, will click right arrow next time");
                                this.state = "click-next-big-image";
                                this.previousBigImage = this.currentBigImage.src;
                                this.currentBigImage = null;
                                this.bigImagesLoaded++;
                                this.idleSince = null;

                                if (this.bigImagesLoaded >= this.imageCount) {
                                        console.log("looks like we're done, we've loaded all " + this.bigImagesLoaded + " of " + this.imageCount + " big images");
                                        this.state = "finished";
                                        this.idleSince = Date.now();
                                }
                                return;
                        } else if(this.idleSince == null) {
                                console.log("Waiting for big image to load");
                                this.idleSince = Date.now();
                                return;
                        }

                }

                if (this.state === "click-next-big-image") {
                        var rightArrow = document.querySelectorAll("a.mmRightArrow");
                        if (rightArrow.length > 0) {
                                // console.log("clicking right arrow");
                                rightArrow[0].click();
                                this.state = "waiting-big-image";
                                this.idleSince = null;
                                return;
                        } else {
                                console.warn("no right arrow to click?? weird");
                                this.idleSince = Date.now();
                                return;
                        }
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
