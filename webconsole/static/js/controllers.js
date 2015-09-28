"use strict";

var brozzlerControllers = angular.module("brozzlerControllers", []);

brozzlerControllers.controller("JobsListController", ["$scope", "$http",
  function($scope, $http) {
    $http.get("/api/jobs").success(function(data) {
      $scope.jobs = data.jobs;
    });
  }]);

brozzlerControllers.controller("JobController", ["$scope", "$routeParams", "$http",
  function($scope, $routeParams, $http) {
    $scope.phoneId = $routeParams.phoneId;
    $http.get("/api/jobs/" + $routeParams.id).success(function(data) {
      $scope.job = data;
      console.log("job=", $scope.job);
    });

    $http.get("/api/jobs/" + $routeParams.id + "/sites").success(function(data) {
      $scope.sites = data.sites;
      console.log("sites=", $scope.sites);
      for (var i = 0; i < $scope.sites.length; i++) {
        var site = $scope.sites[i]; // parse Warcprox-Meta to find stats bucket
        var warcprox_meta = angular.fromJson(site.extra_headers["Warcprox-Meta"]);
        for (var j = 0; j < warcprox_meta.stats.buckets.length; j++) {
          if (warcprox_meta.stats.buckets[j].indexOf("seed") >= 0) {
            console.log("warcprox_meta.stats.buckets[" + j + "]=" + warcprox_meta.stats.buckets[j]);
            var bucket = warcprox_meta.stats.buckets[j];
            $http.get("/api/stats/" + warcprox_meta.stats.buckets[j]).success(function(data) {
              console.log("/api/stats/" + bucket + "=", data);
              site.stats = data;
            });
          }
        }
      }
    });
  }]);

brozzlerControllers.controller("SiteController", ["$scope", "$routeParams", "$http",
  function($scope, $routeParams, $http) {
    $http.get("/api/site/" + $routeParams.id).success(function(data) {
      $scope.site = data;
    });
  }]);

/*
$http.get(...)
    .then(function(response){ 
      // successHandler
      // do some stuff
      return $http.get('/somethingelse') // get more data
    })
    .then(anotherSuccessHandler)
    .catch(errorHandler)
*/
