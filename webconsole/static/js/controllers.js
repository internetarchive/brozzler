"use strict";

var brozzlerControllers = angular.module("brozzlerControllers", []);

brozzlerControllers.controller("JobsListController", ["$scope", "$http",
  function($scope, $http) {
    $http.get("api/jobs").success(function(data) {
      console.log(data);
      $scope.jobs = data.jobs;
    });
  }]);

brozzlerControllers.controller("JobController", ["$scope", "$routeParams", "$http",
  function($scope, $routeParams, $http) {
    $scope.phoneId = $routeParams.phoneId;
    $http.get("api/jobs/" + $routeParams.id).success(function(data) {
      console.log(data);
      $scope.job = data;
    });
  }]);

