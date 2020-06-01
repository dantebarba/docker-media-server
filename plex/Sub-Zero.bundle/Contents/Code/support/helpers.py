# coding=utf-8
import os
import traceback
import types
import unicodedata
import datetime
import urllib
import time
import re
import platform
import subprocess
import sys
from collections import OrderedDict

from babelfish.exceptions import LanguageError

import chardet

from bs4 import UnicodeDammit
from subzero.language import Language, language_from_stream
from subzero.analytics import track_event

mswindows = (sys.platform == "win32")
if mswindows:
    from subprocess import list2cmdline
    quote_args = list2cmdline
else:
    # POSIX
    from pipes import quote

    def quote_args(seq):
        return ' '.join(quote(arg) for arg in seq)

# Unicode control characters can appear in ID3v2 tags but are not legal in XML.
RE_UNICODE_CONTROL = u'([\u0000-\u0008\u000b-\u000c\u000e-\u001f\ufffe-\uffff])' + \
                     u'|' + \
                     u'([%s-%s][^%s-%s])|([^%s-%s][%s-%s])|([%s-%s]$)|(^[%s-%s])' % \
                     (
                         unichr(0xd800), unichr(0xdbff), unichr(0xdc00), unichr(0xdfff),
                         unichr(0xd800), unichr(0xdbff), unichr(0xdc00), unichr(0xdfff),
                         unichr(0xd800), unichr(0xdbff), unichr(0xdc00), unichr(0xdfff)
                     )


def cast_bool(value):
    return str(value).strip() in ("true", "True")


def cast_int(value, default=None):
    try:
        return int(value)
    except ValueError:
        return default


# A platform independent way to split paths which might come in with different separators.
def split_path(str):
    if str.find('\\') != -1:
        return str.split('\\')
    else:
        return str.split('/')


def unicodize(s):
    filename = s
    try:
        filename = unicodedata.normalize('NFC', unicode(s.decode('utf-8')))
    except:
        Log('Failed to unicodize: ' + repr(filename))
    try:
        filename = re.sub(RE_UNICODE_CONTROL, '', filename)
    except:
        Log('Couldn\'t strip control characters: ' + repr(filename))
    return filename


def force_unicode(s):
    if not isinstance(s, types.UnicodeType):
        try:
            s = s.decode("utf-8")
        except UnicodeDecodeError:
            t = chardet.detect(s)
            try:
                s = s.decode(t["encoding"])
            except UnicodeDecodeError:
                s = UnicodeDammit(s).unicode_markup
    return s


def clean_filename(filename):
    # this will remove any whitespace and punctuation chars and replace them with spaces, strip and return as lowercase
    return string.translate(filename.encode('utf-8'), string.maketrans(string.punctuation + string.whitespace,
                                                                       ' ' * len(
                                                                           string.punctuation + string.whitespace))).strip().lower()


def is_recent(t):
    now = datetime.datetime.now()
    when = datetime.datetime.fromtimestamp(t)
    value, key = Prefs["scheduler.item_is_recent_age"].split()
    if now - datetime.timedelta(**{key: int(value)}) < when:
        return True
    return False


# thanks, Plex-Trakt-Scrobbler
def str_pad(s, length, align='left', pad_char=' ', trim=False):
    if not s:
        return s

    if not isinstance(s, (str, unicode)):
        s = str(s)

    if len(s) == length:
        return s
    elif len(s) > length and not trim:
        return s

    if align == 'left':
        if len(s) > length:
            return s[:length]
        else:
            return s + (pad_char * (length - len(s)))
    elif align == 'right':
        if len(s) > length:
            return s[len(s) - length:]
        else:
            return (pad_char * (length - len(s))) + s
    else:
        raise ValueError("Unknown align type, expected either 'left' or 'right'")


def pad_title(value, width=49):
    """Pad a title to 30 characters to force the 'details' view."""
    return str_pad(value, width, pad_char=' ')


def get_plex_item_display_title(item, kind, parent=None, parent_title=None, section_title=None,
                                add_section_title=False):
    """
    :param item: plex item
    :param kind: show or movie
    :param parent: season or None
    :param parent_title: parentTitle or None
    :return:
    """
    return get_video_display_title(kind, item.title,
                                   section_title=(
                                       section_title or (parent.section.title if parent and getattr(parent, "section")
                                                         else None)),
                                   parent_title=(parent_title or (parent.show.title if parent else None)),
                                   season=parent.index if parent else None,
                                   episode=item.index if kind == "show" else None,
                                   add_section_title=add_section_title)


def series_num(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        pass


def get_video_display_title(kind, title, section_title=None, parent_title=None, season=None, episode=None,
                            add_section_title=False):
    section_add = ""
    if add_section_title:
        section_add = ("%s: " % section_title) if section_title else ""

    if kind in ("season", "show") and parent_title:
        if series_num(season) is not None and series_num(episode) is not None:
            return '%s%s S%02dE%02d%s' % (section_add, parent_title, season or 0, episode or 0,
                                          (", %s" % title if title else ""))
        elif series_num(season) is not None:
            return '%s%s S%02d%s' % (section_add, parent_title, season or 0,
                                     (", %s" % title if title else ""))

        return '%s%s%s' % (section_add, parent_title, (", %s" % title if title else ""))
    return "%s%s" % (section_add, title)


def get_title_for_video_metadata(metadata, add_section_title=True, add_episode_title=False):
    """

    :param metadata:
    :param add_section_title:
    :param add_episode_title: add the episode's title if its an episode else always add title
    :return:
    """
    # compute item title
    add_title = (add_episode_title and metadata["series_id"]) or not metadata["series_id"]
    return get_video_display_title(
        "show" if metadata["series_id"] else "movie",
        metadata["title"] if add_title else "",
        parent_title=metadata.get("series", None),
        season=metadata.get("season", None),
        episode=metadata.get("episode", None),
        section_title=metadata.get("section", None),
        add_section_title=add_section_title
    )


def get_identifier():
    identifier = None
    try:
        identifier = Platform.MachineIdentifier
    except:
        pass

    if not identifier:
        identifier = String.UUID()

    return Hash.SHA1(identifier + "SUBZEROOOOOOOOOO")


def encode_message(base, s):
    return "%s?message=%s" % (base, urllib.quote_plus(s))


def decode_message(s):
    return urllib.unquote_plus(s)


def timestamp():
    return int(time.time()*1000)


def df(d):
    return d.strftime("%Y-%m-%d %H:%M:%S") if d else "legacy data"


def query_plex(url, args):
    """
    simple http query to the plex API without parsing anything too complicated
    :param url:
    :param args:
    :return:
    """
    use_args = args.copy()

    computed_args = "&".join(["%s=%s" % (key, String.Quote(value)) for key, value in use_args.iteritems()])

    return HTTP.Request(url + ("?%s" % computed_args) if computed_args else "", immediate=True)


def check_write_permissions(path):
    if platform.system() == "Windows":
        # physical access check
        check_path = os.path.join(os.path.realpath(path), ".sz_perm_chk")
        try:
            if os.path.exists(check_path):
                os.rmdir(check_path)
            os.mkdir(check_path)
            os.rmdir(check_path)
            return True
        except OSError:
            pass

    else:
        # os.access check
        return os.access(path, os.W_OK | os.X_OK)
    return False


def get_item_hints(data):
    """
    :param data: video item dict of media_to_videos 
    :return: 
    """
    hints = {"title": data["original_title"] or data["title"], "type": "movie"}
    if data["type"] == "episode":
        hints.update(
            {
                "type": "episode",
                "episode_title": data["title"],
                "title": data["original_title"] or data["series"],
            }
        )
    if hints["title"]:
        hints["title"] = hints["title"].replace(":", "")
    return hints


def notify_executable(exe_info, videos, subtitles, storage):
    variables = (
        "subtitle_language", "subtitle_path", "subtitle_filename", "provider", "score", "storage", "series_id",
        "series", "title", "section", "filename", "path", "folder", "season_id", "type", "id", "season"
    )
    to_clean = ("PYTHONPATH", "PYTHONHOME")
    exe, arguments = exe_info
    for video, video_subtitles in subtitles.items():
        for subtitle in video_subtitles:
            lang = str(subtitle.language)
            data = video.plexapi_metadata.copy()
            data.update({
                "subtitle_language": lang,
                "provider": subtitle.provider_name,
                "score": subtitle.score,
                "storage": storage,
                "subtitle_path": subtitle.storage_path,
                "subtitle_filename": os.path.basename(subtitle.storage_path)
            })

            # fill missing data with None
            prepared_data = dict((v, data.get(v)) for v in variables)

            prepared_arguments = [arg % prepared_data for arg in arguments]

            Log.Debug(u"Calling %s with arguments: %s" % (exe, prepared_arguments))
            if not mswindows:
                env_path = {"PATH": os.pathsep.join(
                                        [
                                            "/usr/local/bin",
                                            "/usr/bin",
                                            os.environ.get("PATH", "")
                                        ]
                                    )
                            }
                env = dict(os.environ, **env_path)
                env.pop("LD_LIBRARY_PATH", None)
            else:
                env = dict(os.environ)

            # clean out any Plex-PYTHONPATH that may bleed through the spawned process
            for v in to_clean:
                if v in env and "plex" in env[v].lower():
                    del env[v]

            try:
                proc = subprocess.Popen(quote_args([exe] + prepared_arguments), stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, shell=True, env=env, cwd=os.path.dirname(exe))
                output, errors = proc.communicate()

                if proc.returncode == 1:
                    Log.Error(u"Calling %s with args %s failed: output:\n%s, error:\n%s", exe, prepared_arguments,
                             output, errors)
                    return

                output = output.decode()

            except:
                Log.Error(u"Calling %s failed: %s", exe, traceback.format_exc())
            else:
                Log.Debug(u"Process output: %s", output)


def track_usage(category=None, action=None, label=None, value=None):
    if not cast_bool(Prefs["track_usage"]):
        return

    if "last_tracked" not in Dict:
        Dict["last_tracked"] = OrderedDict()
        Dict.Save()

    event_key = (category, action, label, value)
    now = datetime.datetime.now()
    if event_key in Dict["last_tracked"] and (Dict["last_tracked"][event_key] + datetime.timedelta(minutes=30)) < now:
        return

    Dict["last_tracked"][event_key] = now

    # maintenance
    for key, value in Dict["last_tracked"].copy().iteritems():
        # kill day old values
        if value < now - datetime.timedelta(days=1):
            try:
                del Dict["last_tracked"][key]
            except:
                pass

    try:
        Thread.Create(dispatch_track_usage, category, action, label, value,
                      identifier=Dict["anon_id"], first_use=Dict["first_use"],
                      add=Network.PublicAddress)
    except:
        Log.Debug("Something went wrong when reporting anonymous user statistics: %s", traceback.format_exc())


def dispatch_track_usage(*args, **kwargs):
    identifier = kwargs.pop("identifier")
    first_use = kwargs.pop("first_use")
    add = kwargs.pop("add")
    try:
        track_event(identifier=identifier, first_use=first_use, add=add, *[str(a) for a in args])
    except:
        Log.Debug("Something went wrong when reporting anonymous user statistics: %s", traceback.format_exc())


def get_language_from_stream(lang_code):
    if lang_code:
        lang = Locale.Language.Match(lang_code)
        if lang and lang != "xx":
            # Log.Debug("Found language: %r", lang)
            return Language.fromietf(lang)
        elif lang:
            try:
                return language_from_stream(lang_code)
            except LanguageError:
                pass


def audio_streams_match_languages(video, languages):
    without_forced = filter(lambda x: not x.forced, languages)
    if video.audio_languages and without_forced:
        if Prefs["subtitles.when"] == "Always":
            return set()

        elif Prefs["subtitles.when"] == "When main audio stream is not Subtitle Language (1)":
            if video.audio_languages[0] == without_forced[0]:
                return set(without_forced)

        elif Prefs["subtitles.when"] == "When any audio stream is not Subtitle Language (1)":
            if without_forced[0] in video.audio_languages:
                return set(without_forced)

        elif Prefs["subtitles.when"] == "When main audio stream is not any configured language":
            if video.audio_languages[0] in without_forced:
                return set(without_forced)

        elif Prefs["subtitles.when"] == "When any audio stream is not any configured language":
            matching = set(video.audio_languages).intersection(set(without_forced))
            if matching:
                return set(without_forced)

        # if Prefs["subtitles.when_forced"] in [
        #     "Always",
        #     "Only for Subtitle Language (1)",
        #     "Only for Subtitle Language (2)",
        #     "Only for Subtitle Language (3)"
        # ]:

    return set()


def get_language(lang_short):
    return Language.fromietf(lang_short)


def display_language(l):
    if not l:
        return "Unknown"
    return _(str(l.basename).lower()) + ((u" (%s)" % _("forced")) if l.forced else "")


class PartUnknownException(Exception):
    pass
