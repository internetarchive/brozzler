/**
 * Mock GPU information with real values. Check using: https://bot.sannysoft.com/
 */
WebGLRenderingContext.prototype.getParameter = function(origFn) {
  const paramMap = {};
  paramMap[0x9245] = "Google Inc. (NVIDIA Corporation)";	// UNMASKED_VENDOR_WEBGL
  paramMap[0x9246] = "ANGLE (NVIDIA Corporation, Quadro P400/PCIe/SSE2, OpenGL 4.5.0)";  // UNMASKED_RENDERER_WEBGL
  paramMap[0x1F00] = "WebKit";      // VENDOR
  paramMap[0x1F01] = "WebKit WebGL"; // RENDERER
  paramMap[0x1F02] = "WebGL 1.0 (OpenGL ES 2.0 Chromium)"; // VERSION

  return function(parameter) {
    return paramMap[parameter] || origFn.call(this, parameter);
  };
}(WebGLRenderingContext.prototype.getParameter);

// This is `Linux x86_64` on Linux.
Object.defineProperty(navigator, 'platform', {
    get: () => 'Win32'
});

// Randomize navigator.deviceMemory and navigator.hardwareConcurrency to evade
// browser fingerprinting.
function getRandomInt(min, max) {
  min = Math.ceil(min);
  max = Math.floor(max);
  return Math.floor(Math.random() * (max - min) + min); //The maximum is exclusive and the minimum is inclusive
}

Object.defineProperty(navigator, 'deviceMemory', {
    get: () => getRandomInt(4, 32)
});
Object.defineProperty(navigator, 'hardwareConcurrency', {
    get: () => getRandomInt(4, 32)
});

// Brozzler runs chrome with --disable-notifications which disables `window.Notification`.
// This object is used for web bot detection and should be there.
if (!window.Notification) {
  window.Notification = {
    permission: 'denied'
  }
}

// TODO Add many more feature detection evations here. For example:
// Mock navigator.permissions.query. In headful on secure origins the
// permission should be "default", not "denied".
