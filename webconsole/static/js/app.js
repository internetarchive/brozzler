"use strict";

var brozzlerConsoleApp = angular.module("brozzlerConsoleApp", [
  "ngRoute",
  "brozzlerControllers",
]);

brozzlerConsoleApp.config(["$routeProvider", "$locationProvider",
  function($routeProvider, $locationProvider) {
    $routeProvider.
      when("/jobs", {
        templateUrl: "/static/partials/jobs.html",
        controller: "JobsListController"
      }).
      when("/jobs/:id", {
        templateUrl: "/static/partials/job.html",
        controller: "JobController"
      }).
      when("/sites/:id", {
        templateUrl: "/static/partials/site.html",
        controller: "SiteController"
      }).
      when("/", {
        redirectTo: "/jobs"
      }).
      otherwise({
        template: '<div> <div class="page-header"> <h1>Not Found</h1> </div> <div class="row"> <div class="col-sm-12"> How the heck did you get here? </div> </div> </div> ',
      });

    $locationProvider.html5Mode({
      enabled: true,
      requireBase: false,
    });
  }]);

// copied from https://bitbucket.org/webarchive/ait5/src/master/archiveit/static/app/js/filters/ByteFormat.js
brozzlerConsoleApp.filter("byteformat", function() {
  return function(bytes, precision) {
    var bytes_f = parseFloat(bytes);
    if (bytes_f == 0 || isNaN(bytes_f) || !isFinite(bytes_f)) return "0";
    if (bytes_f < 1024) return bytes_f.toFixed(0) + " bytes";
    if (typeof precision === "undefined") precision = 1;
    var units = ["bytes", "kB", "MB", "GB", "TB", "PB"];
    var number = Math.floor(Math.log(bytes_f) / Math.log(1024));
    var result = (bytes_f / Math.pow(1024, Math.floor(number))).toFixed(precision) +  " " + units[number];
    return result;
  }
});

