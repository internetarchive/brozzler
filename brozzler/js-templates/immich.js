/*
 * brozzler/js-templates/immich.js - scroll an Immich photo grid to the end,
 * and report each photo's page as an outlink
 *
 * Immich (a self-hosted photo server, on any domain) scrolls its photo grid
 * inside its own element, not the window, so the default behavior's
 * window.scrollBy() does nothing there and only the first screen of
 * thumbnails is captured. The grid is virtualized: it fetches a month and its
 * thumbnails only when they scroll into view. Photos aren't links either (a
 * click opens <page>/photos/<id> from script).
 *
 * Included by umbraBehavior.js.j2 when its "immich" parameter is set (see
 * behaviors.yaml). Pages are recognized as Immich by their content, so it
 * works on any domain.
 *
 * Copyright (C) 2026 Internet Archive
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

class ImmichGrid {

    constructor(behavior) {
        this.behavior = behavior;
        this.isImmich = undefined;
        this.gridFound = false;
        this.lastScroll = 0;
        this.lastHeight = 0;
        this.assetIds = new Set();
    }

    // Scroll the grid a screen at a time, slowly enough for each month to
    // load, and collect each photo page as an outlink as its thumbnail
    // scrolls past. Returns false if this isn't an Immich page with a grid to
    // scroll, so the default behavior scrolls the window instead.
    scroll() {
        if (this.isImmich === undefined) {
            var noscript = document.querySelector("noscript");
            this.isImmich = !!(noscript && noscript.textContent.indexOf("To use Immich") > -1);
        }
        if (!this.isImmich) {
            return false;
        }
        var now = Date.now();
        if (now - this.lastScroll < 1500) {
            return this.gridFound;
        }
        this.lastScroll = now;

        // the scrollable element with the most to scroll
        var grid = null;
        var gridRoom = 0;
        var all = document.querySelectorAll("*");
        for (var i = 0; i < all.length; i++) {
            var room = all[i].scrollHeight - all[i].clientHeight;
            if (room > gridRoom) {
                var overflowY = getComputedStyle(all[i]).overflowY;
                if (overflowY == "auto" || overflowY == "scroll") {
                    grid = all[i];
                    gridRoom = room;
                }
            }
        }
        this.gridFound = !!grid;
        if (!grid) {
            return false;
        }

        var pageUrl = location.origin + location.pathname.replace(/\/photos\/.*$/, "").replace(/\/$/, "");
        var assets = document.querySelectorAll("[data-asset-id]");
        for (var i = 0; i < assets.length; i++) {
            var id = assets[i].getAttribute("data-asset-id");
            if (!this.assetIds.has(id)) {
                this.assetIds.add(id);
                this.behavior.outlinks.push(pageUrl + "/photos/" + id + location.search);
            }
        }

        if (Math.ceil(grid.scrollTop + grid.clientHeight) < grid.scrollHeight) {
            grid.scrollBy(0, Math.max(200, Math.floor(grid.clientHeight * 0.8)));
            this.behavior.idleSince = null;
        } else if (grid.scrollHeight != this.lastHeight) {
            // at the bottom, but the grid grew since last time: more may load
            this.behavior.idleSince = null;
        }
        this.lastHeight = grid.scrollHeight;
        return true;
    }
}

