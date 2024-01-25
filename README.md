# np
no parse  HLS SCTE-35 Injection via sidecar file

# There has got to be a better way.

### Here are the facts as I see them.


* For some time now, I have been trying to figure out 
an effective way to inject SCTE-35 into HLS. 

* x9k3, is pretty cool, but scaling it to adaptive bitrate 
has been challenging. 

* sidercar SCTE-35, It was my idea, and I stand by it. 

* I noticed x9k3 now has a lot of options, and I really 
hate that.

* I like how umzz works, spawning a process for each rendition.

* I hate that umzz sucks over network if you don't have fat pipes.

that distills down to:
<br>

Inject SCTE-35 from a sidecar file, ,
<br>
into live ABR  HLS streams,
<br>
in real time,
<br>
over a network,
<br>
make it easy,
<br>
and keep CPU usage to a minimum.

<br>

 I can do that.

### the game plan.


* read the master.m3u8 and copy it locally.
    * change the rendition URIs to the new local index.m3u8 files.
* load SCTE-35 from a sidecar file for all renditioons, just like umzz.
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


### Current np state:

### I've got most of it done, here's what's working.
Everything is working,  except splitting segments for SCTE-35, I haven't merged it in yet.

__Currently__, I am  doing 'enhanced' rounding of SCTE-35 Cue splice points to the nearest segment.
* with a __6 second__ segments __np__ is averaging about __+/-1.5 seconds__ off,
* with __2 second__ segments, __np__ is less than __+/- 1 second__ off.


<br>

![image](https://github.com/futzu/np/assets/52701496/b4c2359c-8bff-4801-9533-90cd4bd7a065)
<br>
#### Multiprocessing siddcasr SCTE-35 is working. 
* np uses 1 sidecar and pushes the SCTE-35 to each rendition process.
* SCTE-35 can be written to the sidecar file while __np__ is running.
* notice how all renditions are in sync.
<br>


![image](https://github.com/futzu/np/assets/52701496/797bcc57-4ee3-4876-8d63-79e834b3092f)



<br>



