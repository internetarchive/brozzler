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

// TODO Add many more feature detection evations here. For example:
// Mock navigator.permissions.query. In headful on secure origins the
// permission should be "default", not "denied".
