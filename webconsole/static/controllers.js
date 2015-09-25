"use strict";

var brozzlerConsoleApp = angular.module("brozzlerConsoleApp", []);

brozzlerConsoleApp.controller("JobsAppController", ["$scope", "$http", function($scope, $http) {
    $http.get("api/jobs").success(function(data) {
        console.log(data);
        $scope.jobs = data.jobs;
    });
}]);

