// vim:set sw=8 et:

// STATES = ['NASCENT', 'NEED_SCROLL', 'WAITING', 'FINISHED']

// var transition = prepareTransition(state);
// if (transition.callback) {
// 	newState.callback(state, newState);
// }
// state = newState;

// if (state.status === 'NASCENT') {
// } else if (state.status == 'NEED_SCROLL') {
// } else if (state.status == 'FINISHED') {

var UMBRA_FINISH_AFTER_IDLE_TIME = 10 * 1000; // ms
var umbraState = {'idleSince':null};
var umbraFinished = false;
var umbraIntervalFunc = function() {
	// var needToScroll = (window.scrollY + window.innerHeight + 10 < document.body.clientHeight);
	// var needToScroll = (document.documentElement.scrollTop + document.documentElement.clientHeight < document.documentElement.scrollHeight);
	var needToScroll = (window.scrollY + window.innerHeight < document.documentElement.scrollHeight);

        // console.log('intervalFunc umbraState.idleSince=' + umbraState.idleSince + ' needToScroll=' + needToScroll + ' window.scrollY=' + window.scrollY + ' window.innerHeight=' + window.innerHeight + ' document.documentElement.scrollHeight=' + document.documentElement.scrollHeight);
	if (needToScroll) {
		window.scrollBy(0, 200);
		umbraState.idleSince = null;
	} else if (umbraState.idleSince == null) {
                umbraState.idleSince = Date.now();
        }
}

var umbraBehaviorFinished = function() {
        if (umbraState.idleSince != null) {
                var idleTime = Date.now() - umbraState.idleSince;
                if (idleTime > UMBRA_FINISH_AFTER_IDLE_TIME) {
                        return true;
                }
        }
        return false;
}

var umbraIntervalId = setInterval(umbraIntervalFunc, 100);
