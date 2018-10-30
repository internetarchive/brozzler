// we have problems if the page has changed the definition of Set or Array
// http://www.polyvore.com/ does this for example
var __brzl_framesDone = new Set();
var __brzl_compileOutlinks = function(frame) {
    __brzl_framesDone.add(frame);
    var outlinks = [];
    try {
        if (frame && frame.document) {
            outlinks = Array.prototype.slice.call(
                frame.document.querySelectorAll('a[href], area[href]'));
            for (var i = 0; i < frame.frames.length; i++) {
                if (frame.frames[i] && !__brzl_framesDone.has(frame.frames[i])) {
                    outlinks = outlinks.concat(
                        __brzl_compileOutlinks(frame.frames[i]));
                }
            }
        }
    } catch (e) {
        console.log("exception looking at frame" + frame + ": " + e);
    }

    return outlinks;
}
__brzl_compileOutlinks(window).join('\n');
