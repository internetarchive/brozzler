// vim:set sw=8 et:

setInterval(function() { window.scrollBy(0,50); }, 100);

setTimeout(function() { 
        a = document.evaluate("//a[contains(@class, 'sn-ico-slideshow')]", document, null, XPathResult.UNORDERED_NODE_ITERATOR_TYPE, null ); 
        f = a.iterateNext(); 
        f.click();
}, 5000);

setTimeout(function() { 
        a = document.evaluate("//a[contains(@data-track, 'photo-click')]", document, null, XPathResult.UNORDERED_NODE_ITERATOR_TYPE, null ); 
        setInterval(function() { 
                f = a.iterateNext(); 
                f.click();
        }, 5000);
}, 5000);
