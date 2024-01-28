"""
np.py
"""
import argparse
from collections import deque
import json
import os
import sys
import time
import pyaes
from operator import itemgetter
import multiprocessing as mp

from m3ufu import (
    M3uFu,
    AESDecrypt,
    TagParser,
    HEADER_TAGS,
    BASIC_TAGS,
    MULTI_TAGS,
    MEDIA_TAGS,
)
import threefive
from threefive import Cue
from new_reader import reader
from iframes import IFramer
from x9k3 import X9K3, SCTE35
from umzz import UMZZ, do
from splitstream import SplitStream

"""
Odd number versions are releases.
Even number versions are testing builds between releases.

Used to set version in setup.py
and as an easy way to check which
version you have installed.
"""

MAJOR = "0"
MINOR = "0"
MAINTAINENCE = "09"


ON = "\033[1m"
OFF = "\033[0m"

REV = "\033[7m"
NORM = "\033[27m"

ROLLOVER = 8589934591

media_list = deque()
segments = deque()


def version():
    """
    version prints the m3ufu version as a string
    """
    return f"{MAJOR}.{MINOR}.{MAINTAINENCE}"


def atoif(value):
    """
    atoif converts ascii to (int|float)
    """
    if isinstance(value, float):
        return value
    if "." in value:
        try:
            value = float(value)
        finally:
            return value
    else:
        try:
            value = int(value)
        finally:
            return value


class Segment:
    """
    The Segment class represents a segment
    and associated data
    """

    def __init__(self, lines, media_uri, start, base_uri, first):
        self.lines = lines
        self.media = media_uri
        self.pts = 0
        self.start = start
        self.end = None
        self.duration = 0
        self.cue = False
        self.cue_data = None
        self.tags = {}
        self.tmp = None
        self.base_uri = base_uri
        self.relative_uri = media_uri.replace(base_uri, "")
        self.last_iv = None
        self.last_key_uri = None
        self.first = first

    def __repr__(self):
        return str(self.__dict__)

    @staticmethod
    def _dot_dot(media_uri):
        """
        dot dot resolves '..' in  urls
        """
        ssu = media_uri.split("/")
        ss, u = ssu[:-1], ssu[-1:]
        while ".." in ss:
            i = ss.index("..")
            del ss[i]
            del ss[i - 1]
        media_uri = "/".join(ss + u)
        return media_uri

    def kv_clean(self):
        """
        _kv_clean removes items from a dict if the value is None
        """
        data = {
            "media": self.media,
            "start": self.start,
            "end": self.end,
            " duration": self.duration,
            "tags": self.tags,
            "first": self.first,
        }

        def b2l(val):
            if isinstance(val, (list)):
                val = [b2l(v) for v in val]
            if isinstance(val, (dict)):
                val = {k: b2l(v) for k, v in val.items()}
            return val

        return {k: b2l(v) for k, v in data.items() if v}

    def _get_pts_start(self):
        iframer = IFramer(shush=True)
        pts_start = iframer.first(self.media)
        #   print(pts_start)
        if pts_start:
            self.pts = round(pts_start, 6)

        self.start = self.pts

    def media_file(self):
        """
        media_file returns self.media
        or self.tmp if self.media is AES Encrypted
        """
        media_file = self.media
        if self.tmp:
            media_file = self.tmp
        return media_file

    def cue2sidecar(self, sidecar):
        if self.cue:
            with open(sidecar, "a") as out:
                out.write(f"{self.start},{self.cue}\n")

    def _extinf(self):
        if "#EXTINF" in self.tags:
            if isinstance(self.tags["#EXTINF"], str):
                self.tags["#EXTINF"] = self.tags["#EXTINF"].rsplit(",", 1)[0]
            self.duration = round(float(self.tags["#EXTINF"]), 6)

    def _scte35(self):
        if "#EXT-X-SCTE35" in self.tags:
            if "CUE" in self.tags["#EXT-X-SCTE35"]:
                self.cue = self.tags["#EXT-X-SCTE35"]["CUE"]
                if "CUE-OUT" in self.tags["#EXT-X-SCTE35"]:
                    if self.tags["#EXT-X-SCTE35"]["CUE-OUT"] == "YES":
                        self._do_cue()
                if "#EXT-X-CUE-OUT" in self.tags:
                    self._do_cue()
        if "#EXT-X-DATERANGE" in self.tags:
            if "SCTE35-OUT" in self.tags["#EXT-X-DATERANGE"]:
                self.cue = self.tags["#EXT-X-DATERANGE"]["SCTE35-OUT"]
                self._do_cue()
                return
        if "#EXT-OATCLS-SCTE35" in self.tags:
            self.cue = self.tags["#EXT-OATCLS-SCTE35"]
            if isinstance(self.cue, dict):
                self.cue = self.cue.popitem()[0]
            self._do_cue()
            return
        if "#EXT-X-CUE-OUT-CONT" in self.tags:
            try:
                self.cue = self.tags["#EXT-X-CUE-OUT-CONT"]["SCTE35"]
                self._do_cue()
            except:
                pass

    def _do_cue(self):
        """
        _do_cue parses a SCTE-35 encoded string
        via the threefive.Cue class
        """
        if self.cue:
            try:
                tf = threefive.Cue(self.cue)
                tf.decode()
                self.cue_data = tf.get()
            except:
                pass

    def _chk_aes(self):
        if "#EXT-X-KEY" in self.tags:
            if "URI" in self.tags["#EXT-X-KEY"]:
                key_uri = self.tags["#EXT-X-KEY"]["URI"]
                if not key_uri.startswith("http"):
                    key_uri = self.base_uri + key_uri
                if "IV" in self.tags["#EXT-X-KEY"]:
                    iv = self.tags["#EXT-X-KEY"]["IV"]
                    decryptr = AESDecrypt(self.media, key_uri, iv)
                    self.tmp = decryptr.decrypt()
                    self.last_iv = iv
                    self.last_key_uri = key_uri
        else:
            if self.last_iv is not None:
                decryptr = AESDecrypt(self.media, self.last_key_uri, self.last_iv)
                self.tmp = decryptr.decrypt()

    def decode(self):
        self.tags = TagParser(self.lines).tags
        self._chk_aes()
        self._extinf()
        self._scte35()
        if self.first:
            self._get_pts_start()
            if self.pts:
                self.start = self.pts
        if self.start:
            self.start = round(self.start, 6)
            self.end = round(self.start + self.duration, 6)
        else:
            self.start = 0
        # del self.lines
        return self.start

    def get_lines(self):
        return self.lines

    def add_tag(self, quay, val):
        """
        add_tag appends key and value for a hls tag
        """
        self.tags[quay] = val

    def as_stanza(self):
        """
        as_stanza returns segment data formated for m3u8.

        """
        stanza = []
        presort = list(self.tags.keys())
        presort.sort()
        for x in presort:
            kay = x
            vee = self.tags[x]
            if isinstance(vee, dict):
                tmp = []
                for k, v in vee.items():
                    tmp.append(f"{k}={v}")
                vee = ",".join(tmp)
            stanza.append(f"{kay}:{vee}")
        stanza = [x.replace(":None", "").replace(":{}", "") for x in stanza]
        stanza.append(self.media)
        return stanza


class NP:
    """
    Ultra Mega Zoom Zoom no parse edition.
    """

    def __init__(self, args):
        self.base_uri = ""
        self.sidecar = deque()
        self.sidecar_file = "sidecar.txt"
        self.next_expected = 0
        self.hls_time = 0.0
        self.desegment = False
        self.master = None
        self.reload = True
        self.m3u8 = None
        self.manifest = None
        self.start = None
        self.outfile = "index.m3u8"
        self.output = None
        self.chunk = []
        self.headers = {}
        self.window_size = 100
        self.first = True
        self.scte35 = SCTE35()
        self.last_sidelines = None
        self.args = args

    def _args_version(self):
        if self.args.version:
            print(version())
            sys.exit()

    def _args_input(self):
        if self.args.input:
            self.m3u8 = self.args.input

    def _args_output(self):
        self.output = self.args.output_dir

    def _args_sidecar(self):
        self.sidecar_file = self.args.sidecar

    def _apply_args(self):
        """
        _apply_args  uses command line args
        to set m3ufu instance vars
        """
        self._args_version()
        self._args_input()
        self._args_output()
        self._args_sidecar()

    @staticmethod
    def _clean_line(line):
        if isinstance(line, bytes):
            line = line.decode(errors="ignore")
            line = line.replace("\n", "").replace("\r", "")
        return line

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

    def _set_times(self, segment):
        if not self.start:
            self.start = segment.start
        if not self.start:
            self.start = 0.0
        self.start += segment.duration
        self.next_expected = self.start  # + self.hls_time
        self.next_expected += round(segment.duration, 6)
        self.hls_time += segment.duration

    def _add_segment_tags(self, segment):
        self._add_cue_tag(segment)
        segment.add_tag("# start", f" {segment.start} cue: {self.scte35.cue_time}")
        if segment.tmp:
            os.unlink(segment.tmp)
            del segment.tmp

    def _pop(self, media):
        popped = None
        if media not in media_list:
            media_list.append(media)
            while len(media_list) > self.window_size:
                popped = media_list.popleft()
                del popped
            while len(segments) > self.window_size:
                popped = segments.popleft()
                del popped

    def _add_split_segment(self, chunk, media, start):
        sp_seg = Segment(chunk, media, start, self.args.output_dir, self.first)
        sp_seg.decode()
        self._add_segment_tags(sp_seg)
        self._add_segment(sp_seg)
        media_list.append(media)
        self.chunk = []
        self.scte35.mk_cue_state()

    def _add_media(self, media):
        segment = Segment(
            self.chunk, media, self.start, self.base_uri, first=self.first
        )
        segment.decode()
        self._chk_sidecar_cues(segment)
        self.scte35.chk_cue_state() # leave this here.

        if self.scte35.cue_time:
            if (segment.start) < self.scte35.cue_time < (segment.end):
                print(segment.start, "CUE", self.scte35.cue_time)
                print("SPLIT")
                self.chunk = []
                stream = SplitStream()
                splice_point, a_media, b_media = stream.split_at(
                    segment.media, self.scte35.cue_time, self.args.output_dir
                )
                a_chunk = [f"#EXTINF:{round(self.scte35.cue_time - segment.start,6)}"]
                a_start = segment.start
                self._add_split_segment(a_chunk, a_media, a_start)
                if splice_point:
                    print(self.scte35.cue_time, "spliced @", splice_point)
                    b_chunk = [f"#EXTINF:{round(segment.end - splice_point,6)}"]
                    b_start = splice_point
                    self._add_split_segment(b_chunk, b_media, b_start)
                return
        self._add_segment_tags(segment)
        self._add_segment(segment)
        self._pop(segment)

    def _add_segment(self, segment):
        segments.append(segment)
        self._set_times(segment)
        self.first = False
        if self.scte35.break_timer is not None:
            self.scte35.break_timer += segment.duration
        self._pop(segment)

    def _do_media(self, line):
        media = line
        if self.base_uri not in line:
            if "http" not in line:
                media = self.base_uri + media
        if media not in media_list:
            self._add_media(media)
        self.chunk = []

    def _parse_header(self, line):
        splitline = line.split(":", 1)
        if splitline[0] in HEADER_TAGS:
            val = None
            tag = splitline[0]
            if len(splitline) > 1:
                val = splitline[1]
                try:
                    val = atoif(val)
                except:
                    val = None
            self.headers[tag] = val
            return True
        return False

    def _endlist_chk(self, line):
        """
        _endlist_chk checks for
        #EXT-X-ENDLIST tags
        """
        if "ENDLIST" in line:
            self.reload = False

    def _disco_chk(self, line):
        """
        _disco_chk sets self.first when it sees a segment
        with a discontinuity tag.

        setting self.first causes np to
        parse a segment for pts.
        """
        if "#EXT-X-DISCONTINUITY" in line:
            self.first = True

    def _parse_line(self, line):
        if not line:
            return False
        line = self._clean_line(line)
        self._endlist_chk(line)
        if not self._parse_header(line):
            self._disco_chk(line)
            self.chunk.append(line)
            if line[0] != "#":
                if len(line):
                    self._do_media(line)
        return True

    def _get_window_size(self, m3u8_lines):
        self.window_size = len([line for line in m3u8_lines if b"#EXTINF:" in line])

    def decode(self):
        self._apply_args()
        if self.m3u8:
            based = self.m3u8.rsplit("/", 1)
            if len(based) > 1:
                self.base_uri = f"{based[0]}/"
        while self.reload:
            self.read_m3u8()
            self.write_m3u8()

    def read_m3u8(self):
        with reader(self.m3u8) as self.manifest:
            m3u8_lines = self.manifest.readlines()
            if self.first:
                self._get_window_size(m3u8_lines)
            for line in m3u8_lines:
                if not self._parse_line(line):
                    break

    def write_m3u8(self):
        out = self.mk_uri(self.output, self.outfile)
        with open(out, "w", encoding="utf8") as npm3u8:
            for k, v in self.headers.items():
                if v is None:
                    npm3u8.write(f"{k}\n")
                else:
                    npm3u8.write(f"{k}:{v}\n")
            for segment in segments:
                stanza = segment.as_stanza()
                _ = [npm3u8.write(j + "\n") for j in stanza]
        segment = segments[-1]
        seg = segment.relative_uri.rsplit("/", 1)[-1]
        print(
            f" proc: {self.args.output_dir[-1]}  media: {seg}\tstart: {segment.start}\tduration: {segment.duration}"
        )
        throttle = segments[-1].duration * 0.90
        time.sleep(throttle)

    def load_sidecar(self):
        """
        load_sidecar reads (pts, cue) pairs from
        the sidecar file and loads them into X9K3.sidecar
        """
        if self.sidecar_file:
            if not self.start:
                return
            with reader(self.sidecar_file) as sidefile:
                sidelines = sidefile.readlines()
                if sidelines == self.last_sidelines:
                    return
                for line in sidelines:
                    line = line.decode().strip().split("#", 1)[0]
                    if line:
                        print(f"{ON}loading  {line}{OFF}")
                        time.sleep(0.1)
                        if float(line.split(",", 1)[0]) == 0.0:
                            line = f'{self.start},{line.split(",",1)[1]}'
                        self.add2sidecar(line)
                sidefile.close()
                self.last_sidelines = sidelines
        #   self.clobber_file(self.args.sidecar_file)

    def add2sidecar(self, line):
        """
        add2sidecar add insert_pts,cue to the deque
        """
        insert_pts, cue = line.split(",", 1)
        insert_pts = float(insert_pts)
        if [insert_pts, cue] not in self.sidecar:
            self.sidecar.append([insert_pts, cue])
            self.sidecar = deque(sorted(self.sidecar, key=itemgetter(0)))

    def _chk_sidecar_cues(self, segment):
        """
        _chk_sidecar_cues checks the insert pts time
        for the next sidecar cue and inserts the cue if needed.
        """
        self.load_sidecar()
        if self.sidecar:
            for s in list(self.sidecar):
                splice_pts = float(s[0])
                splice_cue = s[1]
                if splice_pts:
                    if (segment.start) < splice_pts < segment.end:
                        print("SPLICE TIME", splice_pts)
                        self.sidecar.remove(s)
                        self.scte35.cue = Cue(splice_cue)
                        self.scte35.cue.decode()
                        # self.scte35.cue_time = splice_pts
                        print(f"{self.scte35.cue.command.name}")
                        self._chk_cue_time()

    def _disco_seq_plus_one(self):
        if "#EXT-X-DISCONTINUITY" in segments[0].tags:
            self.discontinuity_sequence += 1

    def _add_discontinuity(self, segment):
        """
        _add_discontinuity adds a discontinuity tag.
        """
        segment.add_tag("#EXT-X-DISCONTINUITY", None)

    def _add_cue_tag(self, segment):
        """
        _add_cue_tag adds SCTE-35 tags,
        auto CUE-INs, and discontinuity tags.
        """
        if self.scte35.break_timer is not None:
            if self.scte35.break_timer >= self.scte35.break_duration:
                self.scte35.break_timer = None
                self.scte35.cue_state = "IN"
        tag = self.scte35.mk_cue_tag()
        if tag:
            print(tag)
            if self.scte35.cue_state in ["OUT", "IN"]:
                self._add_discontinuity(segment)
            kay = tag
            vee = None
            if ":" in tag:
                kay, vee = tag.split(":", 1)
            segment.add_tag(kay, vee)

    def _chk_cue_time(self):
        if self.scte35.cue:
            self.scte35.cue_time = self._adjusted_pts(self.scte35.cue)

    def _adjusted_pts(self, cue):
        adj_pts = 0
        if "pts_time" in cue.command.get():
            pts = cue.command.pts_time
        else:
            pts = self.start
        if pts:
            pts_adjust = cue.info_section.pts_adjustment
            adj_pts = (pts + pts_adjust) % self.as_90k(ROLLOVER)
        return round(adj_pts, 6)

    @staticmethod
    def as_90k(int_time):
        """
        ticks to 90k timestamps
        """
        return round((int_time / 90000.0), 6)

    @staticmethod
    def as_ticks(float_time):
        """
        90k timestamps to ticks
        """
        return int(round(float_time * 90000))


class UMZZnp(UMZZ):
    def __init__(self, m3u8_list):
        super().__init__(m3u8_list)

    def add_rendition(self, m3u8, dir_name, rendition_sidecar=None):
        """
        add_rendition starts a process for each rendition and
        creates a pipe for each rendition to receive SCTE-35.
        """
        p = mp.Process(
            target=npmp_run,
            args=(m3u8, dir_name, rendition_sidecar),
        )
        p.start()
        print(f"Rendition Process Started {dir_name}")
        self.procs.append(p)


def mk_npmp(manifest, dir_name, rendition_sidecar):
    """
    mk_x9mp generates an X9MP instance and
    sets default values
    """
    np = NP(argue())
    np.args.output_dir = dir_name
    np.args.input = manifest.media
    np.args.sidecar = rendition_sidecar
    return np


def npmp_run(manifest, dir_name, rendition_sidecar=None):
    """
    mp_run is the process started for each rendition.
    """
    args = argue()
    np = mk_npmp(manifest, dir_name, rendition_sidecar)
    np.decode()
    return False


def do(args):
    """
    do runs np programmatically.

    """
    fu = M3uFu(shush=True)
    if not args.input:
        print("input source required (Set args.input)")
        sys.exit()
    fu.m3u8 = args.input
    if not os.path.isdir(args.output_dir):
        os.mkdir(args.output_dir)
    fu.decode()
    um = UMZZnp(fu.segments)
    um.go()


def argue():
    """
    argue parses command line args
    """
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-i",
        "--input",
        default=None,
        help=""" Input source, like "/home/a/vid.ts"
                                or "udp://@235.35.3.5:3535"
                                or "https://futzu.com/xaa.ts"
                                """,
    )

    parser.add_argument(
        "-s",
        "--sidecar_file",
        default=None,
        help=f"Sidecar file of SCTE-35 (pts,cue) pairs   [default:{ON}None{OFF}]",
    )

    parser.add_argument(
        "-o",
        "--output_dir",
        default=".",
        help=" output directory ",
    )

    parser.add_argument(
        "-v",
        "--version",
        action="store_const",
        default=False,
        const=True,
        help="Show version",
    )

    return parser.parse_args()


def cli():
    """
    cli provides one function call
    for running shari with command line args
    Two lines of code gives you a full umzz command line tool.

     from umzz import cli
     cli()

    """
    args = argue()
    _ = {print(k, "=", v) for k, v in vars(args).items()}
    do(args)


if __name__ == "__main__":
    mp.set_start_method("spawn")
    cli()
