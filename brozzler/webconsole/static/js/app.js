/*
 * brozzler-webconsole/static/js/app.js - brozzler console angularjs code
 *
 * Copyright (C) 2014-2016 Internet Archive
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

"use strict";

var brozzlerConsoleApp = angular.module("brozzlerConsoleApp", [
    "ngRoute",
    "brozzlerControllers",
]);

brozzlerConsoleApp.config(["$routeProvider", "$locationProvider",
    function($routeProvider, $locationProvider) {
        $routeProvider.
            when("/workers", {
                templateUrl: "/static/partials/workers.html",
                controller: "WorkersListController"
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
                templateUrl: "/static/partials/home.html",
                controller: "HomeController"
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
        var result = (bytes_f / Math.pow(1024, Math.floor(number))).toFixed(precision) +    " " + units[number];
        return result;
    }
});

var brozzlerControllers = angular.module("brozzlerControllers", []);

brozzlerControllers.controller("HomeController", ["$scope", "$http",
   function($scope, $http) {
        $http.get("/api/config").success(function(data) {
            $scope.config = data.config;
        });
        $http.get("/api/jobs").success(function(data) {
            $scope.jobs = data.jobs;
        });
        $http.get("/api/services").success(function(data) {
            $scope.services = data.services;
        });
        $http.get("/api/jobless-sites").success(function(data) {
            $scope.joblessSites = data.sites;
        });
   }]);

brozzlerControllers.controller("WorkersListController", ["$scope", "$http",
   function($scope, $http) {
        $http.get("/api/config").success(function(data) {
            $scope.config = data.config;
        });
       $http.get("/api/workers").success(function(data) {
           $scope.workers = data.workers;
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

    // look at Warcprox-Meta to find stats bucket
    for (var j = 0; j < site.warcprox_meta.stats.buckets.length; j++) {
        var bucket = site.warcprox_meta.stats.buckets[j];
        if (typeof(bucket) == "object") {
            bucket = bucket["bucket"];
        }
        if (bucket.indexOf("seed") >= 0) {
            // console.log("warcprox_meta.stats.buckets[" + j + "]=" + bucket);
            $http.get("/api/stats/" + bucket).success(statsSuccessCallback(site, bucket));
        }
    }
}

brozzlerControllers.controller("JobController", ["$scope", "$routeParams", "$http",
    function($scope, $routeParams, $http) {
        $scope.show_yaml = false;
        // console.log('JobController');
        $http.get("/api/config").success(function(data) {
            $scope.config = data.config;
        });
        $http.get("/api/jobs/" + $routeParams.id).success(function(data) {
            $scope.job = data;
            $scope.job.page_count = $scope.job.queued_count = 0;
            // console.log("job=", $scope.job);
            var bucket = $scope.job.conf.warcprox_meta.stats.buckets[0];
            if (typeof(bucket) == "object") {
                bucket = bucket["bucket"];
            }
            $http.get("/api/stats/" + bucket).success(function(data) {
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
        $http.get("/api/jobs/" + $routeParams.id + "/yaml").success(function(data) {
            $scope.job_yaml = data;
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

        $http.get("/api/config").success(function(data) {
            $scope.config = data.config;
        });
        $http.get("/api/site/" + $routeParams.id).success(function(data) {
            $scope.site = data;
            loadSiteStats($http, $scope.site);
            // console.log("site = ", $scope.site);
        });
        $http.get("/api/site/" + $routeParams.id + "/yaml").success(function(data) {
            $scope.site_yaml = data;
        });

        loadMorePages();
    }]);

