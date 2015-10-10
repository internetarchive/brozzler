"use strict";

var brozzlerControllers = angular.module("brozzlerControllers", []);

brozzlerControllers.controller("JobsListController", ["$scope", "$http",
   function($scope, $http) {
       $http.get("/api/jobs").success(function(data) {
           $scope.jobs = data.jobs;
       });
   }]);

function statsSuccessCallback(site, bucket) {
    return function(data) {
        // console.log("site = ", site);
        // console.log("/api/stats/" + bucket + " = ", data);
        site.stats = data;
    }
}

function pageCountSuccessCallback(site, job) {
    return function(data) {
        // console.log("site = ", site);
        // console.log("/api/sites/" + site.id + "/page_count = ", data);
        site.page_count = data.count;
	if (job) {
		job.page_count += data.count;
	}
    }
}

function queuedCountSuccessCallback(site, job) {
    return function(data) {
        // console.log("site = ", site);
        // console.log("/api/sites/" + site.id + "/queued_count = ", data);
        site.queued_count = data.count;
	if (job) {
		job.queued_count += data.count;
	}
    }
}

function loadSiteStats($http, site, job) {
    $http.get("/api/sites/" + site.id + "/page_count").success(pageCountSuccessCallback(site, job));
    $http.get("/api/sites/" + site.id + "/queued_count").success(queuedCountSuccessCallback(site, job));

    // parse Warcprox-Meta to find stats bucket
    var warcprox_meta = angular.fromJson(site.extra_headers["Warcprox-Meta"]);
    for (var j = 0; j < warcprox_meta.stats.buckets.length; j++) {
        if (warcprox_meta.stats.buckets[j].indexOf("seed") >= 0) {
            var bucket = warcprox_meta.stats.buckets[j];
            // console.log("warcprox_meta.stats.buckets[" + j + "]=" + bucket);
            $http.get("/api/stats/" + bucket).success(statsSuccessCallback(site, bucket));
        }
    }
}

brozzlerControllers.controller("JobController", ["$scope", "$routeParams", "$http",
    function($scope, $routeParams, $http) {
        $http.get("/api/jobs/" + $routeParams.id).success(function(data) {
            $scope.job = data;
            $scope.job.page_count = $scope.job.queued_count = 0;
            console.log("job=", $scope.job);
            $http.get("/api/stats/" + $scope.job.conf.warcprox_meta.stats.buckets[0]).success(function(data) {
                $scope.job.stats = data;
                // console.log("job stats=", $scope.job.stats);
            });

            $http.get("/api/jobs/" + $routeParams.id + "/sites").success(function(data) {
                $scope.sites = data.sites;
                // console.log("sites=", $scope.sites);
                for (var i = 0; i < $scope.sites.length; i++) {
                    loadSiteStats($http, $scope.sites[i], $scope.job); 
                }
            });
        });

    }]);

brozzlerControllers.controller("SiteController", ["$scope", "$routeParams", "$http",
    function($scope, $routeParams, $http) {
        $http.get("/api/site/" + $routeParams.id).success(function(data) {
            $scope.site = data;
            loadSiteStats($http, $scope.site);
            // console.log("site = ", $scope.site);
        });

        $http.get("/api/site/" + $routeParams.id + "/pages?start=0&end=99").success(function(data) {
            $scope.pages = data.pages;
            console.log("pages = ", $scope.pages);
        });

    }]);

/*
   $http.get("/api/site/" + $routeParams.id).then(function(response) {
   console.log("/api/site/" + $routeParams.id + " returned", response);
   $scope.site = response.data;
   return $http.get("/api/site/" + $routeParams.id + "/pages");
   }).then(function(response) {
   console.log("/api/site/" + $routeParams.id + "/pages returned", response);
   $scope.site.pages = response.data.pages;
   });
   */
