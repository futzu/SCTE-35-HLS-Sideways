
# np
no parse  HLS SCTE-35 Injection via sidecar file

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
#EXTINF:6.0
https://example.com/0/seg541.ts    <-- expands existing segment URI, but doesn't parse the segments


# start: 3255.733333 cue: 3256.0
#EXTINF:0.266667
./0/a-seg542.ts       <--- When there is a SCTE-35 Cue, it splits the segment at the splice point
                                                                    the split segments are stored on your server.

# start: 3256.0 cue: 3256.0        < -- the second split segment is the where the CUE-OUT starts
#EXT-X-CUE-OUT:13.0
#EXT-X-DISCONTINUITY
#EXTINF:5.466666
./0/b-seg542.ts
# start: 3261.466666 cue: 3269.0
#EXT-X-CUE-OUT-CONT:5.466666/13.0
#EXTINF:6.0
https://example.com/0/seg543.ts     <--- during  the ad break, the segments are not parsed 
# start: 3267.466666 cue: 3269.0
#EXT-X-CUE-OUT-CONT:11.466666/13.0
#EXTINF:1.533334
./0/a-seg544.ts                   <-- split on the CUE-IN splice point      

  
# start: 3269.0 cue: 3269.0      <--- CUE IN on the second split segment     
#EXT-X-CUE-IN
#EXT-X-DISCONTINUITY
#EXTINF:4.199999
./0/b-seg544.ts


# start: 3273.199999 cue: None
#EXTINF:6.0
https://example.com/0/seg545.ts   <--- back to not parsing segments
# start: 3279.199999 cue: None
#EXTINF:6.0
https://example.com/0/seg546.ts
```
```smalltalk
Each directory looks like this

 ls 0/
  a-seg542.ts    b-seg542.ts 
  a-seg544.ts   b-seg544.ts  
  index.m3u8 sidecar.txt
```
