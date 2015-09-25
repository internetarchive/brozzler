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
      });
      // .
      // otherwise({
      //   redirectTo: "/jobs"
      // });

    $locationProvider.html5Mode({
      enabled: true,
      requireBase: false,
    });
  }]);
