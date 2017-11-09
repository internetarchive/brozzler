Steps taken to create DASH.

```
$ brew reinstall -v ffmpeg --with-libvpx
$ ffmpeg -i small.webm -c:v vp9 -f webm -dash 1 -an -vf scale=280:160 -b:v 100k -dash 1 small-video_280x160_100k.webm
$ ffmpeg -i small.webm -c:v vp9 -f webm -dash 1 -an -vf scale=140:80 -b:v 25k -dash 1 small-video_140x80_25k.webm
$ ffmpeg -i small.webm -acodec copy -vn -dash 1 small-audio.webm
$ ffmpeg -f webm_dash_manifest -i small-video_280x160_100k.webm -f webm_dash_manifest -i small-video_140x80_25k.webm -f webm_dash_manifest -i small-audio.webm -c copy -map 0 -map 1 -map 2 -f webm_dash_manifest -adaptation_sets "id=0,streams=0,1 id=1,streams=2" small.mpd
```

Don't know if the output is really correct, but youtube-dl downloads the
small.mpd, small-audio.web and small-video_280x160_100k.webm. Browser doesn't
download anything though, not even small.mpd.
