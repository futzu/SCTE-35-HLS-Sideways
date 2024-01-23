import sys
from iframes import IFramer
from functools import partial
from new_reader import reader


class SplitStream(IFramer):
    def __init__(self, shush=False):
        self.shush = shush
        
    def split_at(self,segment, pts):
        splice_point= None
        seg =segment.rsplit('/')[-1]
        a_name=f'a-{seg}'
        b_name=f'b-{seg}'
        with open(a_name,'wb') as a:
            with open(b_name,'wb') as b:
                outfile = a
                with reader(segment) as video:
                    for pkt in iter(partial(video.read, 188), b""):
                        iframe_pts=self.parse(pkt)
                        if iframe_pts:
                            if iframe_pts >= pts:
                                if not splice_point:
                                    splice_point= iframe_pts
                                outfile = b
                        outfile.write(pkt)
        return splice_point, a_name, b_name



segment = sys.argv[1]
pts = float(sys.argv[2])
if segment and pts:
    stream=SplitStream()
    print(stream.split_at(segment,pts))




            
