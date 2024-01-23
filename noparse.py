"""
noparse.py
"""
import argparse
from collections import deque
import json
import gc
import os
import sys
import time
import pyaes
from operator import itemgetter
from m3ufu import AESDecrypt,TagParser, HEADER_TAGS, BASIC_TAGS , MULTI_TAGS , MEDIA_TAGS
import threefive
from threefive import Cue
from new_reader import reader
from iframes import IFramer
from x9k3 import X9K3, SCTE35
import cProfile

"""
Odd number versions are releases.
Even number versions are testing builds between releases.

Used to set version in setup.py
and as an easy way to check which
version you have installed.
"""

MAJOR = "0"
MINOR = "0"
MAINTAINENCE = "03"



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
        self.pts = None
        self.start = start
        self.end = None
        self.duration = 0
        self.cue = False
        self.cue_data = None
        self.tags = {}
        self.tmp = None
        self.base_uri = base_uri
        self.relative_uri = media_uri.replace(base_uri,'')
        self.last_iv = None
        self.last_key_uri = None
        self.debug = False
        self.first =first

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
        data ={"media":self.media, "start":self.start,"end":self.end," duration":self.duration, "tags":self.tags,"first":self.first}

        def b2l(val):
            if isinstance(val, (list)):
                val = [b2l(v) for v in val]
            if isinstance(val, (dict)):
                val = {k: b2l(v) for k, v in val.items()}
            return val

        return {k: b2l(v) for k, v in data.items() if v}

    def _get_pts_start(self):
        iframer =IFramer(shush=True)
        pts_start = iframer.first(self.media)
        print(pts_start)
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
                if self.debug:
                    tf.show()
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
            self.start = round(self.start,6)
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
            kay =x
            vee = self.tags[x]
            if isinstance(vee,dict):
                tmp =[]
                for k,v in vee.items():
                    tmp.append(f'{k}={v}')
                vee =','.join(tmp)
            stanza.append(f'{kay}:{vee}' )
        stanza =[x.replace(':None','').replace(':{}','') for x in stanza]
        stanza.append(self.media)
        return stanza


class NP:
    """
   Ultra Mega Zoom Zoom no parse edition.
    """

    def __init__(self):
        self.base_uri = ""
        self.sidecar =deque()
        self.sidecar_file ='sidecar.txt'
        self.next_expected = 0
        self.hls_time = 0.0
        self.desegment = False
        self.master = None
        self.reload = True
        self.m3u8 = None
        self.manifest = None
        self.start = None
        self.outfile = "np.m3u8"
        self.chunk = []
        self.headers = {}
        self.debug = False
        self.window_size = 10000
        self.first = True
        self.scte35 = SCTE35()
        self.last_sidelines= None

    def _parse_args(self):
        """
        _parse_args parse command line args
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
            "-o",
            "--outfile",
            default="np.m3u8",
            help=" output m3u8 file ",
        )

        parser.add_argument(
            "-v",
            "--version",
            action="store_const",
            default=False,
            const=True,
            help="Show version",
        )

        parser.add_argument(
            "-d",
            "--debug",
            action="store_const",
            default=False,
            const=True,
            help="Enable debug output.",
        )

        args = parser.parse_args()
        self._apply_args(args)

    @staticmethod
    def _args_version(args):
        if args.version:
            print(version())
            sys.exit()

    def _args_desegment(self, args):
        self.outfile = args.outfile

    def _args_input(self, args):
        if args.input:
            self.m3u8 = args.input

    def _args_debug(self, args):
        self.debug = args.debug

    def _args_output(self, args):
        if args.output:
            self.outfile = args.output

    def _apply_args(self, args):
        """
        _apply_args  uses command line args
        to set m3ufu instance vars
        """
        self._args_version(args)
        self._args_input(args)
        self._args_desegment(args)
        self._args_debug(args)

    @staticmethod
    def _clean_line(line):
        if isinstance(line, bytes):
            line = line.decode(errors="ignore")
            line = line.replace("\n", "").replace("\r", "")
        return line

    def _is_master(self, line):
        playlist = False
        for this in ["STREAM-INF", "EXT-X-MEDIA","#EXT-X-I-FRAME-STREAM-INF"]:
            if this in line:
                self.master = True
                self.reload = False
                if "URI" in line:
                    playlist = line.split('URI="')[1].split('"')[0]
        return playlist

    def _set_times(self, segment):
        if not self.start:
            self.start = segment.start
        if not self.start:
            self.start = 0.0
        self.start += segment.duration
        self.next_expected = self.start + self.hls_time
        self.next_expected += round(segment.duration, 6)
        self.hls_time += segment.duration

    def _add_media(self, media):
        popped =None
        if media not in media_list:
            media_list.append(media)
            while len(media_list) > self.window_size:
                #popped, media_list = media_list[0],self.media_list[1:]
                popped =media_list.popleft()
                print(f"POP MEDIA {popped}")
                del popped
            while len(segments) > self.window_size :
                #popped, segments = self.segments[0],self.segments[1:]
                popped =segments.popleft()
                print(f"POP SEGMENT {popped}")
                del popped
            self.scte35.chk_cue_state()
            self.scte35.mk_cue_state()
            segment = Segment(self.chunk, media, self.start, self.base_uri, first=self.first)
            segment.decode()
            self._chk_sidecar_cues(segment)
          #  if self.scte35.cue_time:
            self._add_cue_tag(segment)
            segment.add_tag('# start', f' {segment.start}  cue time: {self.scte35.cue_time}')
            if segment.tmp:
                os.unlink(segment.tmp)
                del segment.tmp
            print(json.dumps(segment.kv_clean(), indent=3))
            segments.append(segment)
            self._set_times(segment)
            self.first=False
            if self.scte35.break_timer is not None:
                self.scte35.break_timer += segment.duration


    def _do_media(self, line):
        media = line
        if self.master is None:
            print(f"SELF.MASTER is {self.master}")
            playlist = self._is_master(line)
            self.master=True
            if playlist:
                media = playlist
        if self.base_uri not in line:
            if "http" not in line:
                media = self.base_uri + media
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

    def _parse_line(self, line):
        if not line:
            return False
        line = self._clean_line(line)
        if "ENDLIST" in line:
            self.reload = False
        if not self._parse_header(line):
            if "DISCONTINUITY" in line:
                self.first=True
           # self._is_master(line)
            self.chunk.append(line)
            if line[0] !="#":
                if len(line):
                    self._do_media(line)
                    #gc.collect()
                    #for i in gc.get_objects():
                     #   print(i)
        return True

    def _get_window_size(self, m3u8_lines):
        self.window_size = len([line for line in m3u8_lines if b"#EXTINF:" in line])
        print(self.window_size, "WINDOW")

    def decode(self):
        gc.enable()
        if self.desegment and os.path.exists(self.outfile):
            os.unlink(self.outfile)
        if self.m3u8:
            based = self.m3u8.rsplit("/", 1)
            if len(based) > 1:
                self.base_uri = f"{based[0]}/"
        while self.reload:
            with reader(self.m3u8) as self.manifest:
                m3u8_lines = self.manifest.readlines()
                if self.first:
                    self._get_window_size(m3u8_lines)
                for line in m3u8_lines:
                    if not self._parse_line(line):
                        break
                with open(self.outfile,"w",encoding="utf8") as npm3u8:
                    print(self.headers)
                    for k,v in self.headers.items():
                        if v is None:
                            npm3u8.write(f'{k}\n')
                        else:
                            npm3u8.write(f'{k}:{v}\n')
                    for segment in segments:
                        stanza = segment.as_stanza()
                        _=[npm3u8.write(j+'\n') for j in stanza]
                if self.reload == True:
                    if "#EXT-X-TARGETDURATION" in self.headers:
                        time.sleep(self.headers["#EXT-X-TARGETDURATION"] -2 )


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
                        time.sleep(.1)
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
        print(line)
        insert_pts, cue = line.split(",", 1)
        print(insert_pts)
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
        print(self.sidecar)
        if self.sidecar:
            for s in list(self.sidecar):
                splice_pts = float(s[0])
                splice_cue = s[1]
                if segment.start:
                  half = segment.duration/2
                if splice_pts:
                    if (segment.start - half) <= splice_pts <= (segment.start +half):
                        print("HIT",s)
                        self.sidecar.remove(s)
                        self.scte35.cue = Cue(splice_cue)
                        self.scte35.cue.decode()
                        print(f'{self.scte35.cue.command.get()}')
                        self._chk_cue_time()

    def _discontinuity_seq_plus_one(self):
        if segments:
            if "#EXT-X-DISCONTINUITY" in segments[0].tags:
                if len(segments) >= self.window.size:
                    self.discontinuity_sequence += 1
            if "#EXT-X-DISCONTINUITY" in segments[-1].tags:
                self.first = True

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
        print(tag)
        if tag:
            if self.scte35.cue_state in ["OUT", "IN"]:
                self._add_discontinuity(segment)
            kay = tag
            vee = None
            if ":" in tag:
                kay, vee = tag.split(":", 1)
            segment.add_tag(kay, vee)
            print(f"{segment.media}   {kay} {vee}")
            print(segment.tags)



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


def cli():
    fu = NP()
    fu._parse_args()
    fu.decode()


if __name__ == "__main__":
    cli()
