// we have problems if the page has changed the definition of Set or Array
// http://www.polyvore.com/ does this for example
var __brzl_framesDone = new Set();
var __brzl_popup_re = /window.open\(\s*(['"])(.*?)\1/;
var __brzl_compileOutlinks = function(frame) {
    __brzl_framesDone.add(frame);
    var outlinks = [];
    try {
        if (frame && frame.document) {
            outlinks = Array.prototype.slice.call(
                frame.document.querySelectorAll('a[href], area[href]'));
            popups = Array.prototype.slice.call(
                frame.document.querySelectorAll('a[onclick], a[ondblclick]'));
            if (popups && popups.length > 0) {
                for (var p=0; p < popups.length; p++) {
                    if (popups[p].onclick){
                        m = __brzl_popup_re[Symbol.match](popups[p].onclick.toString());
                    } else {
                        m = __brzl_popup_re[Symbol.match](popups[p].ondblclick.toString());
                    }
                    if (m) {
                        outlinks.push(m[2]);
                    }
                }
            }
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
