// {"url_regex":"^https?://(?:www\\.)?instagram\\.com/.*$", "request_idle_timeout_sec":10}
//
// vim:set sw=8 et:
//

var umbraInstagramBehavior = {
        IDLE_TIMEOUT_SEC: 10,
        idleSince: null,
        state: "loading-thumbs",
        imageCount: null,
        bigImagesLoaded: 0,
        latestBigImage: null,

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
                        } else if (Date.now() - this.idleSince > 3000) {
                                console.log("finished loading-thumbs, it appears we have reached the bottom");
                                this.state = "clicking-first-thumb";
                                this.idleSince = null;
                                return;
                        } else { 
                                // console.log("still might be waiting for something to load...");
                                return;
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
                        var imageFrame = document.querySelectorAll("div.Modal div.Item div.iMedia div.Image");
                        if (imageFrame.length > 0) {
                                var bigImage = new Image();
                                bigImage.src = imageFrame[0].getAttribute("src");
                                // console.log("bigImage.naturalWidth=" + bigImage.naturalWidth + " bigImage.src=" + bigImage.src);
                                if (bigImage.src !== this.latestBigImage && bigImage.naturalWidth !== 0) {
                                        console.log("next big image appears loaded, will click right arrow next time");
                                        this.state = "click-next-big-image";
                                        this.latestBigImage = bigImage.src;
                                        this.bigImagesLoaded++;
                                        this.idleSince = null;
                                        return;
                                } 
                        } 
                        if (this.bigImagesLoaded >= this.imageCount) {
                                console.log("looks like we're done, we've loaded all " + this.bigImagesLoaded + " of " + this.imageCount + " big images");
                                this.state = "finished";
                                this.idleSince = Date.now();
                        }
                        return;
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
                                return true;
                        }
                }
                return false;
        },
};

// Called from outside of this script.
var umbraBehaviorFinished = function() { return umbraInstagramBehavior.isFinished() };

umbraInstagramBehavior.start();
