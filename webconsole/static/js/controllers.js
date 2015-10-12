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
            // console.log("job=", $scope.job);
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

brozzlerControllers.controller("SiteController", ["$scope", "$routeParams", "$http", "$window",
    function($scope, $routeParams, $http, $window) {
        var start = 0;
        $scope.loading = false;
        $scope.pages = [];
        $window.addEventListener("scroll", function() {
            // console.log("window.scrollTop=" + window.scrollTop + " window.offsetHeight=" + window.offsetHeight + " window.scrollHeight=" + window.scrollHeight);
            if ($window.innerHeight + $window.scrollY + 50 >= window.document.documentElement.scrollHeight) {
                loadMorePages();
            }
        });

        var loadMorePages = function() {
            if ($scope.loading)
                return;
            $scope.loading = true;

            // console.log("load more! start=" + start);
            $http.get("/api/site/" + $routeParams.id + "/pages?start=" + start + "&end=" + (start+90)).then(function(response) {
                $scope.pages = $scope.pages.concat(response.data.pages);
                // console.log("pages = ", $scope.pages);
                start += response.data.pages.length;
                $scope.loading = false;
            }, function(reason) {
                $scope.loading = false;
            });

        };

        $http.get("/api/site/" + $routeParams.id).success(function(data) {
            $scope.site = data;
            loadSiteStats($http, $scope.site);
            // console.log("site = ", $scope.site);
        });

        loadMorePages();
    }]);

