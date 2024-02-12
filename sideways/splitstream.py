import sys
from iframes import IFramer
from functools import partial
from new_reader import reader


class SplitStream(IFramer):
    def __init__(self, shush=True):
        self.shush = shush

    @staticmethod
    def mk_uri(head, tail):
        """
        mk_uri is used to create local filepaths
        """
        sep = "/"
        if len(head.split("\\")) > len(head.split("/")):
            sep = "\\"
        if not head.endswith(sep):
            head = head + sep
        return f"{head}{tail}"

    def split_at(self, segment, pts, output_dir):
        splice_point = None
        seg = segment.rsplit("/")[-1]
        a_name = f"a-{seg.split('?')[0]}"
        b_name = f"b-{seg.split('?')[0]}"
        a_media = self.mk_uri(output_dir, a_name)
        b_media = self.mk_uri(output_dir, b_name)
        with open(a_media, "wb") as a:
            with open(b_media, "wb") as b:
                outfile = a
                with reader(segment) as video:
                    for pkt in iter(partial(video.read, 188), b""):
                        if not splice_point:
                            iframe_pts = self.parse(pkt)
                            if iframe_pts:
                                if iframe_pts >= pts:
                                    splice_point = iframe_pts
                                    outfile = b
                        outfile.write(pkt)
        return splice_point, a_media, b_media
