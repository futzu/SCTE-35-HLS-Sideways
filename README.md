## <s>There has got to be a better way.</s> 
## This is the better way.

# Sideways is SCTE-35 Injection for live ABR HLS 
## Latest Version is `0`.`0`.`23` _released 02/13/2024_
* Input is a master.m3u8 file,local or over http(s), as input.
* SCTE-35 data is from a [sidecar file](#sidecar-files).
* The master. m3u8 and rendition index.m3u8 files are rewritten locally on your server with SCTE-35 Added to them.
* Segments with a CUE-OUT or CUE-IN tag in them, they are split at the SCTE-35 splicepoint.
* It's fast, light on the network, and uses very little CPU time. 
---
```js
#EXTM3U
#EXT-X-VERSION:4      <--- headers and settings are copied over.
#EXT-X-TARGETDURATION:7   
#EXTINF:6.0
https://example.com/0/seg541.ts    <-- expands existing segment URI, but doesn't parse the segments
#EXTINF:0.266667
./0/a-seg542.ts       <--- When there is a SCTE-35 Cue, it splits the segment at the splice point.
#EXT-X-CUE-OUT:13.0     
#EXT-X-DISCONTINUITY
#EXTINF:5.466666
./0/b-seg542.ts      < -- the second split segment is the where the CUE-OUT starts
#EXT-X-CUE-OUT-CONT:5.466666/13.0
#EXTINF:6.0
https://example.com/0/seg543.ts     <--- during  the ad break, the segments are not parsed, URIs are expanded.
#EXT-X-CUE-OUT-CONT:11.466666/13.0
#EXTINF:1.533334
./0/a-seg544.ts            
#EXT-X-CUE-IN            
#EXT-X-DISCONTINUITY
#EXTINF:4.199999
./0/b-seg544.ts   
#EXTINF:6.0
https://example.com/0/seg545.ts   

```
* The new master.m3u8 is written to your server
* Each rendition has an index.m3u8 and just the split segments in sub directories on your server.
* Each sub-directory looks like this
```smalltalk

 ls 0/
  a-seg542.ts    b-seg542.ts 
  a-seg544.ts   b-seg544.ts  
  index.m3u8 sidecar.txt
```
# How to Use
## Install
```js
python3 -mpip install sideways
```
## Cli tool 

```js
a@fu:~$ sideways -h
usage: sideways [-h] [-i INPUT] [-s SIDECAR_FILE] [-o OUTPUT_DIR] [-t HLS_TAG]
                [-v]

options:
  -h, --help            show this help message and exit
  -i INPUT, --input INPUT
                        Input source, is a master.m3u8(local or http(s) with
                        MPEGTS segments default: None
  -s SIDECAR_FILE, --sidecar_file SIDECAR_FILE
                        SCTE-35 Sidecar file default: None
  -o OUTPUT_DIR, --output_dir OUTPUT_DIR
                        output directory default:None
  -T HLS_TAG, --hls_tag HLS_TAG
                        x_scte35, x_cue, x_daterange, or x_splicepoint
                        default: x_cue
  -v, --version         Show version
```

* `-i` Input is a master.m3u8, local or over a network via http(s)
* `-s` the sidecar file with  PTS,Cue pairs. [Sidecar File details](#sidecar-files)
* `-o` Output is a directory on your system, the default is the current directory.
   * The new master.m3u8 is written to the output directory. 
   * Each rendition has a numerical subdirectory, starting a 0.
      * rendition sub-directories have an index.m3u8
      *  When segments are split for SCTE-35 splice points, the split segments are stored in the rendition subdiectory.

* `-T` HLS_TAG has been lightly tested. The default x_cue works well, x_daterange works too. I havent really tested the others.

# Running:
* the [sidecar file](#sidecar-files) contains two lines, a CUE-OUT and a CUE-IN, the  ad break is for 17 seconds.
```smalltalk
3274.0,/DAlAAAAAAAAAP/wFAUAAAABf+/+EZAnoP4AF1iQAAEAAAAAE5sHRg==
3291.0,/DAgAAAAAAAAAP/wDwUAAAABf0/+EaeAMAABAAAAAJlXlzg=
```
* the command

```js
a@fu:~/testme$ sideways -i /home/a/foam4/master.m3u8 -s ../sidecar.txt
```

* the output
```js
a@fu:~/testme$ ls -R
.:
0  1  master.m3u8

./0:
a-seg544.ts  a-seg547.ts  b-seg544.ts  b-seg547.ts  index.m3u8  sidecar.txt

./1:
a-seg544.ts  a-seg547.ts  b-seg544.ts  b-seg547.ts  index.m3u8  sidecar.txt
```
* 0 and 1 are renditon sub-directories.
* When a segment is split for SCTE-35 the name is prepended with a- and b-
* sideways  writes a copy of the sidecar to each rendition directory
* you can play the master.m3u8.
* the SCTE-35 Cues come out like this:
```js
# start: 3268.266667 
#EXTINF:5.733333
./0/a-seg544.ts     <-- seg544.ts is split into a-seg544.ts and b-seg544.ts.
# start: 3274.0 
#EXT-X-CUE-OUT:17.0
#EXT-X-DISCONTINUITY
#EXTINF:0.266667
./0/b-seg544.ts <-- The splice point is always at the start of b- segment.
# start: 3274.266667 
#EXT-X-CUE-OUT-CONT:0.266667/17.0
#EXTINF:6.0
/home/a/foam4/0/seg545.ts  
# start: 3280.266667 
#EXT-X-CUE-OUT-CONT:6.266667/17.0
#EXTINF:6.0
/home/a/foam4/0/seg546.ts
# start: 3286.266667 
#EXT-X-CUE-OUT-CONT:12.266667/17.0
#EXTINF:4.733333
./0/a-seg547.ts
# start: 3291.0 
#EXT-X-CUE-IN
#EXT-X-DISCONTINUITY
#EXTINF:1.266667
./0/b-seg547.ts
# start: 3292.266667 
```   


### Sidecar files
* load scte35 cues from a Sidecar file

* Sidecar Cues will be handled the same as SCTE35 cues from a video stream.
* line format for text file insert_pts, cue

* pts is the insert time for the cue, cue can be base64,hex, int, or bytes
```lua
a@debian:~/sidweways$ cat sidecar.txt

38103.868589, /DAxAAAAAAAAAP/wFAUAAABdf+/+zHRtOn4Ae6DOAAAAAAAMAQpDVUVJsZ8xMjEqLYemJQ== 
38199.918911, /DAsAAAAAAAAAP/wDwUAAABef0/+zPACTQAAAAAADAEKQ1VFSbGfMTIxIxGolm0= 
```
* you can do dynamic cue injection with a Sidecar file
```lua
touch sidecar.txt

sideways -i master.m3u8 -s sidecar.txt -o bob
```
*  Open another terminal and printf cues into sidecar.txt
```lua
printf '38103.868589, /DAxAAAAAAAAAP/wFAUAAABdf+/+zHRtOn4Ae6DOAAAAAAAMAQpDVUVJsZ8xMjEqLYemJQ==\n' > sidecar.txt
```

* A CUE-OUT can be terminated early using a sidecar file.


