# vim: set sw=4 et:

import logging
import brozzler
import yaml
import json

def merge(a, b):
    if isinstance(a, dict) and isinstance(b, dict):
        merged = dict(a)
        b_tmp = dict(b)
        for k in a:
            merged[k] = merge(a[k], b_tmp.pop(k, None))
        merged.update(b_tmp)
        return merged
    elif isinstance(a, list) and isinstance(b, list):
        return a + b
    else:
        return a

def new_job_file(frontier, job_conf_file):
    logging.info("loading %s", args.job_conf_file)
    with open(args.job_conf_file) as f:
        job_conf = yaml.load(f)
        new_job(frontier, job_conf)

def new_job(frontier, job_conf):
    # logging.info("job_conf=%s", job_conf)
    seeds = job_conf.pop("seeds")
    # logging.info("=== global settings ===\n%s", yaml.dump(job_conf))
    
    sites = []
    for seed_conf in seeds:
        if "id" in seed_conf:
            seed_conf.pop("id")
        merged_conf = merge(seed_conf, job_conf)
        # XXX check for unknown settings, invalid url, etc
        # logging.info("merge(%s, %s) = %s", seed_conf, global_conf, merged_conf)
        # logging.info("=== seed_conf ===\n%s", yaml.dump(seed_conf))
        # logging.info("=== merged_conf ===\n%s", yaml.dump(merged_conf))
    
        extra_headers = None
        if "warcprox_meta" in merged_conf:
            warcprox_meta = json.dumps(merged_conf["warcprox_meta"], separators=(',', ':'))
            extra_headers = {"Warcprox-Meta":warcprox_meta}
    
        site = brozzler.Site(seed=merged_conf["url"],
                scope=merged_conf.get("scope"),
                time_limit=merged_conf.get("time_limit"),
                proxy=merged_conf.get("proxy"),
                ignore_robots=merged_conf.get("ignore_robots"),
                enable_warcprox_features=merged_conf.get("enable_warcprox_features"),
                extra_headers=extra_headers)
        sites.append(site)
    
    # frontier = brozzler.RethinkDbFrontier(args.db.split(","))
    for site in sites:
        new_site(frontier, site)

def new_site(frontier, site):
    logging.info("new site {}".format(site))
    frontier.new_site(site)
    try:
        if brozzler.is_permitted_by_robots(site, site.seed):
            page = brozzler.Page(site.seed, site_id=site.id, hops_from_seed=0, priority=1000)
            frontier.new_page(page)
        else:
            logging.warn("seed url {} is blocked by robots.txt".format(site.seed))
    except brozzler.ReachedLimit as e:
        site.note_limit_reached(e)
        frontier.update_site(site)


