// we have problems if the page has changed the definition of Set or Array
// http://www.polyvore.com/ does this for example
var __brzl_framesDone = new Set();
var __brzl_compileAssets = function(frame) {
    __brzl_framesDone.add(frame);
    if (frame && frame.document) {
        var elem = frame.document.querySelectorAll('[srcset]');
        var srcset_list = new Array();
        var base = frame.document.baseURI.substring(0,
            frame.document.baseURI.lastIndexOf("/"));

        for (var i = 0; i < elem.length; i++) {
            var srcs = elem[i].srcset.match(/(?:[^\s]+\/[^\s]+)/g);

            for (var i = 0; i < srcs.length; i++) {
                if ( /https?:/.test(srcs[i]) ) {
                    srcset_list = srcset_list.concat(srcs[i]);
                } else {
                    srcset_list = srcset_list.concat(base + srcs[i]);
                }
            }
        }

        var assets = Array.prototype.slice.call(srcset_list);

        for (var i = 0; i < frame.frames.length; i++) {
            if (frame.frames[i] && !__brzl_framesDone.has(frame.frames[i])) {
                assets = assets.concat(
                            __brzl_compileAssets(frame.frames[i]));
            }
        }
    }

    return assets;
}
__brzl_compileAssets(window).join('\n');
