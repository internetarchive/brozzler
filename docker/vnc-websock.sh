#!/bin/sh
exec setuser brozzler websockify 0.0.0.0:8901 localhost:5901
