"""
sideways.py
"""

import argparse
from collections import deque
import datetime
import os
import sys
import time
from operator import itemgetter
import multiprocessing as mp

from m3ufu import (
    M3uFu,
    AESDecrypt,
    TagParser,
    HEADER_TAGS,
)
import threefive
from threefive import Cue
from new_reader import reader
from iframes import IFramer
from umzz import UMZZ
from .splitstream import SplitStream

"""
Odd number versions are releases.
Even number versions are testing builds between releases.

Used to set version in setup.py
and as an easy way to check which
version you have installed.
"""

MAJOR = "0"
MINOR = "0"
MAINTAINENCE = "23"


ON = "\033[1m"
OFF = "\033[0m"

REV = "\033[7m"
NORM = "\033[27m"

ROLLOVER = 8589934591


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


class AacParser:
    applehead = b"com.apple.streaming.transportStreamTimestamp"

    @staticmethod
    def is_header(header):
        """
        is_header tests aac and ac3 files for ID3 headers.
        """
        if header[:3] == b"ID3":
            return True
        return False

    @staticmethod
    def id3_len(header):
        """
        id3_len parses the length value from ID3 headers
        """
        id3len = int.from_bytes(header[6:], byteorder="big")
        return id3len

    @staticmethod
    def syncsafe5(somebytes):
        """
        syncsafe5 parses PTS from ID3 tags.
        """
        lsb = len(somebytes) - 1
        syncd = 0
        for idx, b in enumerate(somebytes):
            syncd += b << ((lsb - idx) << 3)
        return round(syncd / 90000.0, 6)

    def parse(self, media):
        """
        aac_pts parses the ID3 header tags in aac and ac3 audio files
        """
        aac = reader(media)
        header = aac.read(10)
        if self.is_header(header):
            id3len = self.id3_len(header)
            data = aac.read(id3len)
            pts = 0
            if self.applehead in data:
                try:
                    pts = float(data.split(self.applehead)[1].split(b"\x00", 2)[1])
                except:
                    pts = self.syncsafe5(data.split(self.applehead)[1][:9])
                finally:
                    self.first_segment = False
                    return round((pts % ROLLOVER), 6)


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

    def _extinf(self):
        if "#EXTINF" in self.tags:
            if isinstance(self.tags["#EXTINF"], str):
                self.tags["#EXTINF"] = self.tags["#EXTINF"].rsplit(",", 1)[0]
            self.duration = round(float(self.tags["#EXTINF"]), 6)

    def _get_pts_start(self):
        pts_start = None
        if ".aac" in self.media:
            ap = AacParser()
            pts_start = ap.parse(self.media)
        else:
            iframer = IFramer(shush=True)
            pts_start = iframer.first(self.media)
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
        self._get_pts_start()
        if self.start:
            self.start = round(self.start, 6)
            self.end = round(self.start + self.duration, 6)
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


class SCTE35:
    """
    A SCTE35 instance is used to hold
    SCTE35 cue data by X9K5.
    """

    def __init__(self):
        self.cue = None
        self.cue_state = None
        self.cue_time = None
        self.tag_method = self.x_cue
        self.break_timer = None
        self.break_duration = None
        self.event_id = 1
        self.seg_type = None

    def mk_cue_tag(self):
        """
        mk_cue_tag routes hls tag creation
        """
        tag = False
        if self.cue:
            tag = self.tag_method()
        return tag

    def chk_cue_state(self):
        """
        chk_cue_state changes self.cue_state
        """
        if self.cue_state == "OUT":
            self.cue_state = "CONT"
        if self.cue_state == "IN":
            self.cue_time = None
            self.cue = None
            self.cue_state = None
            self.break_timer = None

    def mk_cue_state(self):
        """
        mk_cue_state checks if the cue
        is a CUE-OUT or a CUE-IN and
        sets cue_state.
        """

        if self.cue_state == None:
            if self.is_cue_out(self.cue):
                self.cue_state = "OUT"
                self.break_timer = 0.0

        elif self.cue_state == "OUT":
            self.cue_state = "CONT"

        elif self.cue_state in ["OUT", "CONT"]:
            if self.cue_time and self.break_duration:
                self.cue_time += self.break_duration
            if self.is_cue_in(self.cue):
                self.cue_state = "IN"

        elif self.cue_state == "IN":
            self.cue_time = None
            self.cue = None
            self.cue_state = None
            self.break_timer = None

    def x_cue(self):
        """
        #EXT-X-CUE-( OUT | IN | CONT )
        """
        if self.cue_state == "OUT":
            return f"#EXT-X-CUE-OUT:{self.break_duration}"
        if self.cue_state == "IN":
            return "#EXT-X-CUE-IN"
        if self.cue_state == "CONT":
            return f"#EXT-X-CUE-OUT-CONT:{self.break_timer:.6f}/{self.break_duration}"
        return False

    def x_splicepoint(self):
        """
        #EXT-X-SPLICEPOINT-SCTE35
        """
        base = f"#EXT-X-SPLICEPOINT-SCTE35:{self.cue.encode()}"
        if self.cue_state == "OUT":
            return f"{base}"
        if self.cue_state == "IN":
            return f"{base}"
        return False

    def x_scte35(self):
        """
        #EXT-X-SCTE35
        """
        base = f'#EXT-X-SCTE35:CUE="{self.cue.encode()}"'
        if self.cue_state == "OUT":
            return f"{base},CUE-OUT=YES "
        if self.cue_state == "IN":
            return f"{base},CUE-IN=YES "
        if self.cue_state == "CONT":
            return f"{base},CUE-OUT=CONT"
        return False

    def x_daterange(self):
        """
        #EXT-X-DATERANGE
        """
        fbase = f'#EXT-X-DATERANGE:ID="{self.event_id}"'
        iso8601 = f"{datetime.datetime.utcnow().isoformat()}Z"
        fdur = ""
        if self.break_duration:
            fdur = f",PLANNED-DURATION={self.break_duration}"

        if self.cue_state == "OUT":
            fstart = f',START-DATE="{iso8601}"'
            tag = f"{fbase}{fstart}{fdur},SCTE35-OUT={self.cue.encode_as_hex()}"
            return tag

        if self.cue_state == "IN":
            fstop = f',END-DATE="{iso8601}"'
            tag = f"{fbase}{fstop},SCTE35-IN={self.cue.encode_as_hex()}"
            self.event_id += 1
            return tag
        return False

    def _splice_insert_cue_out(self, cue):
        cmd = cue.command
        if cmd.out_of_network_indicator:
            if cmd.break_duration:
                self.break_duration = cmd.break_duration
            self.cue_state = "OUT"
            return True
        return False

    def _time_signal_cue_out(self, cue):
        seg_starts = [0x22, 0x30, 0x32, 0x34, 0x36, 0x44, 0x46]
        for dsptr in cue.descriptors:
            if dsptr.tag != 2:
                return False
            if dsptr.segmentation_type_id in seg_starts:
                self.seg_type = dsptr.segmentation_type_id + 1
                if dsptr.segmentation_duration:
                    self.break_duration = dsptr.segmentation_duration
                    self.cue_state = "OUT"
                    return True
        return False

    def is_cue_out(self, cue):
        """
        is_cue_out checks a Cue instance
        Returns True for a cue_out event.
        """
        if cue is None:
            return False
        if self.cue_state not in ["IN", None]:
            return False
        cmd = cue.command
        if cmd.command_type == 5:
            return self._splice_insert_cue_out(cue)
        if cmd.command_type == 6:
            return self._time_signal_cue_out(cue)

        return False

    def is_cue_in(self, cue):
        """
        is_cue_in checks a Cue instance
        Returns True for a cue_in event.
        """
        if cue is None:
            return False
        if self.cue_state not in ["OUT", "CONT"]:
            return False
        cmd = cue.command
        if cmd.command_type == 5:
            if not cmd.out_of_network_indicator:
                return True
        if cmd.command_type == 6:
            for dsptr in cue.descriptors:
                if dsptr.tag == 2:
                    if dsptr.segmentation_type_id == self.seg_type:
                        self.seg_type = None
                        self.cue_state = "IN"
                        return True
        return False


class Sideways:
    """
    Sideways injects SCTE-35 into HLS.
    """

    def __init__(self, args):
        self.base_uri = ""
        self.sidecar = deque()
        self.sidecar_file = "sidecar.txt"
        self.discontinuity_sequence = 0
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
        self.segments = deque()
        self.media_list = deque()

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

    def _args_hls_tag(self):
        tag_map = {
            "x_scte35": self.scte35.x_scte35,
            "x_cue": self.scte35.x_cue,
            "x_daterange": self.scte35.x_daterange,
            "x_splicepoint": self.scte35.x_splicepoint,
        }
        if self.args.hls_tag not in tag_map:
            raise ValueError(f"hls tag  must be in {tag_map.keys()}")
        self.scte35.tag_method = tag_map[self.args.hls_tag]

    def _apply_args(self):
        """
        _apply_args  uses command line args
        to set m3ufu instance vars
        """
        self._args_version()
        self._args_input()
        self._args_output()
        self._args_sidecar()
        self._args_hls_tag()

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

    def _add_segment_tags(self, segment):
        self._add_cue_tag(segment)
        segment.add_tag("# start", f" {segment.start} ")
        if segment.tmp:
            os.unlink(segment.tmp)
            del segment.tmp

    def _pop(self, media):
        popped = None
        if media not in self.media_list:
            self.media_list.append(media)
            while len(self.media_list) == self.window_size:
                popped = self.media_list.popleft()
                del popped
            while len(self.segments) == self.window_size:
                popped = self.segments.popleft()
                del popped

    def _add_split_segment(self, chunk, media, start):
        sp_seg = Segment(chunk, media, start, self.args.output_dir, self.first)
        sp_seg.decode()
        sp_seg.media = sp_seg.media.rsplit("/", 1)[-1]
        self._add_segment_tags(sp_seg)
        self._add_segment(sp_seg)
        self.media_list.append(sp_seg.media)
        self.chunk = []

    def _add_media(self, media):
        segment = Segment(
            self.chunk, media, self.start, self.base_uri, first=self.first
        )
        segment.decode()
        self._chk_sidecar_cues(segment)
        if self.scte35.cue_time:
            if (segment.start) < self.scte35.cue_time < (segment.end):
                print(segment.start, "CUE", self.scte35.cue_time)
                self.chunk = []
                stream = SplitStream()
                splice_point, a_media, b_media = stream.split_at(
                    segment.media, self.scte35.cue_time, self.args.output_dir
                )
                print("Splice Point @", splice_point, "Splitting Segment")
                if splice_point:
                    a_chunk = [
                        f"#EXTINF:{round(self.scte35.cue_time - segment.start,6)}"
                    ]
                    a_start = segment.start
                    self._add_split_segment(a_chunk, a_media, a_start)
                    # self.write_m3u8()
                    print(self.scte35.cue_time, "spliced @", splice_point)
                    b_chunk = [f"#EXTINF:{round(segment.end - self.scte35.cue_time,6)}"]
                    self.scte35.mk_cue_state()
                    b_start = self.scte35.cue_time
                    self._add_split_segment(b_chunk, b_media, b_start)
                    self.scte35.cue_time = None
                    return
        self.scte35.mk_cue_state()
        self._add_segment_tags(segment)
        self._add_segment(segment)

    def _add_segment(self, segment):
        self.segments.append(segment)
        self._set_times(segment)
        self.first = False
        p = f" {ON}{self.pnum()}{OFF} "
        m = f"media: {segment.relative_uri.rsplit('/')[-1]}\t"
        s = f"start: {segment.start}\t"
        d = f"duration: {segment.duration}"
        print(f"{p}{m}{s}{d}")
        if self.scte35.break_timer is not None:
            self.scte35.break_timer += segment.duration
        self._pop(segment.media)

    def _do_media(self, line):
        media = line
        if self.base_uri not in line:
            if "http" not in line:
                media = self.base_uri + media
        if media not in self.media_list:
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

    def _parse_line(self, line):
        if not line:
            return False
        line = self._clean_line(line)
        self._endlist_chk(line)
        if not self._parse_header(line):
            self.chunk.append(line)
            if line[0] != "#":
                if len(line):
                    self._do_media(line)
        return True

    def _get_window_size(self, m3u8_lines):
        exf = b"#EXTINF:"
        ws = [line for line in m3u8_lines if exf in line]
        self.window_size = len(ws)

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
            for segment in self.segments:
                stanza = segment.as_stanza()
                _ = [npm3u8.write(j + "\n") for j in stanza]
        throttle = self.segments[-1].duration * 0.97
        time.sleep(throttle)

    @staticmethod
    def clobber_file(the_file):
        """
        clobber_file  blanks the_file
        """
        with open(the_file, "w", encoding="utf8") as clobbered:
            clobbered.close()

    def pnum(self):
        """
        pnum returns the internal process number
        for the rendition process
        """
        return f"{ON}proc: {self.args.output_dir[-1]}"

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
                        print(f"{self.pnum()} -> loading  {line}{OFF}")
                        if float(line.split(",", 1)[0]) == 0.0:
                            line = f'{self.start},{line.split(",",1)[1]}'
                        self.add2sidecar(line)
                sidefile.close()
                self.last_sidelines = sidelines
            self.clobber_file(self.sidecar_file)

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
                    # half =segment.duration/2
                    # if (segment.start -half) <= splice_pts <= (segment.start + half):
                    if segment.start <= splice_pts <= segment.end:
                        print(
                            f"{ON}{self.pnum()}-> SPLICE TIME: {splice_pts} ACTUAL:{segment.start}{OFF}"
                        )
                        print(
                            f"{self.pnum()} {REV}SPLICE DIFF: {round(segment.start -splice_pts,6)}{NORM}"
                        )
                        self.sidecar.remove(s)
                        self.scte35.cue = Cue(splice_cue)
                        self.scte35.cue.decode()
                        print(
                            f"{ON}{self.pnum()}  -> {self.scte35.cue.command.name}{OFF}"
                        )
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
        print(f"{ON}Rendition Process Started {dir_name}{OFF}")
        self.procs.append(p)


def mk_npmp(manifest, dir_name, rendition_sidecar):
    """
    mk_npmp generates an Sideways instance and
    sets default values
    """
    sway = Sideways(argue())
    sway.args.output_dir = dir_name
    sway.args.input = manifest.media
    sway.args.sidecar = rendition_sidecar
    return sway


def npmp_run(manifest, dir_name, rendition_sidecar=None):
    """
    mp_run is the process started for each rendition.
    """
    sway = mk_npmp(manifest, dir_name, rendition_sidecar)
    sway.decode()
    return False


def do(args):
    """
    do runs sideways programmatically.

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
        help=f"Input source, is a master.m3u8(local or http(s) with MPEGTS segments  default: {ON}None{OFF}",
    )
    parser.add_argument(
        "-s",
        "--sidecar_file",
        default=None,
        help=f"SCTE-35 Sidecar file default: {ON}None{OFF}",
    )
    parser.add_argument(
        "-o",
        "--output_dir",
        default=".",
        help=f" output directory default:{ON}None{OFF}",
    )
    parser.add_argument(
        "-T",
        "--hls_tag",
        default="x_cue",
        help=f"x_scte35, x_cue, x_daterange, or x_splicepoint  default: {ON}x_cue{OFF}",
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
    if args.version:
        print(version())
        sys.exit()
    _ = {print(k, "=", v) for k, v in vars(args).items()}
    do(args)


if __name__ == "__main__":
    mp.set_start_method("spawn")
    cli()
