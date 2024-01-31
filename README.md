
# Sideways
_np was already taken on pypi_ 
HLS SCTE-35 Injection via sidecar file

# <s>There has got to be a better way.</s> 
# This is the better way.

## Update: it's working.



<br>

Inject SCTE-35 from a sidecar file, on the fly, 
into live ABR  HLS streams,
<br>
over a network, make it easy, 
and keep CPU usage to a minimum.

<br>



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
* Sidecar files can now accept 0 as the PTS insert time for Splice Immediate.

* Specify 0 as the insert time, the cue will be insert at the start of the next segment. 
```lua
printf '0,/DAhAAAAAAAAAP/wEAUAAAAJf78A/gASZvAACQAAAACokv3z\n' > sidecar.txt
```
* A CUE-OUT can be terminated early using a sidecar file.

In the middle of a CUE-OUT send a splice insert with the out_of_network_indicator flag not set and the splice immediate flag set. Do the steps above , and then do this
<br>
```lua
printf '0,/DAcAAAAAAAAAP/wCwUAAAABfx8AAAEAAAAA3r8DiQ==\n' > sidecar.txt
```
* It will cause the CUE-OUT to end at the next segment start.
```
#EXT-X-CUE-OUT 13.4
./seg5.ts:	start:112.966667	end:114.966667	duration:2.233334
#EXT-X-CUE-OUT-CONT 2.233334/13.4
./seg6.ts:	start:114.966667	end:116.966667	duration:2.1
#EXT-X-CUE-OUT-CONT 4.333334/13.4
./seg7.ts:	start:116.966667	end:118.966667	duration:2.0
#EXT-X-CUE-OUT-CONT 6.333334/13.4
./seg8.ts:	start:117.0	        end:119.0	duration:0.033333
#EXT-X-CUE-IN None
./seg9.ts:	start:119.3	        end:121.3	duration:2.3
```
