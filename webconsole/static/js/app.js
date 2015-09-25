"use strict";

var brozzlerConsoleApp = angular.module("brozzlerConsoleApp", [
  "ngRoute",
  "brozzlerControllers",
]);

brozzlerConsoleApp.config(["$routeProvider",
  function($routeProvider) {
    $routeProvider.
      when("/jobs", {
        templateUrl: "partials/jobs.html",
        controller: "JobsListController"
      }).
      when("/jobs/:id", {
        templateUrl: "partials/job.html",
        controller: "JobController"
      }).
      otherwise({
        redirectTo: "/jobs"
      });
  }]);
