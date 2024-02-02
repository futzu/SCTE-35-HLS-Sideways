
### Sideways

HLS SCTE-35 Injection via sidecar file

### <s>There has got to be a better way.</s> This is the better way.


Inject SCTE-35 from a sidecar file,<br> on the fly, <br>
into live ABR  HLS streams, 
<br>
over a network, make it easy, <br>
and keep CPU usage to a minimum.<br>


#### Version 0.0.17 is out! _( wear a helmet, it might be a little buggy)_


* read the master.m3u8 and copy it locally.
    * change the rendition URIs to the new local index.m3u8 files.
* load SCTE-35 from a sidecar file for all renditions, just like umzz.
* spawn a process for each rendition and do the following:
  *  throttle for live output, just like x9k3.
  * read the index.m3u8 all HLS options defined by the index.m3u8.
  *  and write a new one according to these rules.
  * if this the first segment or a segment with a DISCO tag, parse out PTS from the segment.
      * otherwise just add the duration the the first PTS. 
  * for every other segment, don't read the raw segment, no parse.
    * copy over the index.m3u8 data for the segment,
    * change the segment path to the full URI, seg1.ts becomes https://example.com/seg1.ts

### When there are SCTE-35 cues
* if the ad break starts in the middle of a segment:
  * parse the segment, and split it into two pieces to match the SCTE-35 splice point.
  * replace the original segment with the 2 local split segments in the new index.m3u8.
  *  add CONT cue tags to the manifests as needed, but don't parse any other segment until you have a CUE-IN event.


```lua
#EXTM3U
#EXT-X-VERSION:4
#EXT-X-TARGETDURATION:7    <--- headers and settings are copied over.
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
./0/a-seg544.ts             <-- split on the CUE-IN splice point       
#EXT-X-CUE-IN            
#EXT-X-DISCONTINUITY
#EXTINF:4.199999
./0/b-seg544.ts    <--- CUE IN on the second split segment 
#EXTINF:6.0
https://example.com/0/seg545.ts   <--- back to not parsing segments

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
python3 -mpip install sidewwwys
```
## Cli tool 

```lua
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
  -t HLS_TAG, --hls_tag HLS_TAG
                        x_scte35, x_cue, x_daterange, or x_splicepoint
                        default: x_cue
  -v, --version         Show version
```

* -i Input is a master.m3u8, local or over a network via http(s)
* -s the sidecar file with  PTS,Cue pairs. [Sidecar File details](#sidecar)
* -o Output is a directory on your system, the default is the current directory.
   * The new master.m3u8 is written to the output directory. 
   * Each rendition has a numerical subdirectory, starting a 0.
      * rendition sub-directories have an index.m3u8
      *  When segments are split for SCTE-35 splice points, the split segments are stored in the rendition subdiectory.

* -t HLS_TAG has been lightly tested. The default x_cue works well, I havent really tested the others.

# Running:
* the sidecar file contains two lines, a CUE-OUT and a CUE-IN, the  ad break is for 17 seconds.
```smalltalk
3274.0,/DAlAAAAAAAAAP/wFAUAAAABf+/+EZAnoP4AF1iQAAEAAAAAE5sHRg==
3291.0,/DAgAAAAAAAAAP/wDwUAAAABf0/+EaeAMAABAAAAAJlXlzg=
```
* the command

```lua
a@fu:~/testme$ sideways -i /home/a/foam4/master.m3u8 -s ../sidecar.txt
```

* the output
```smalltalk
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
```smalltalk
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


### Sidecar
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


