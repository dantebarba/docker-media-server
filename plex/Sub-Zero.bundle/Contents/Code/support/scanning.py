# coding=utf-8
import traceback
import helpers
from babelfish.exceptions import LanguageError

from support.lib import Plex, get_intent
from support.plex_media import get_stream_fps, is_stream_forced, update_stream_info
from support.storage import get_subtitle_storage
from support.config import config, TEXT_SUBTITLE_EXTS
from support.subtitlehelpers import get_subtitles_from_metadata
from subzero.video import parse_video, set_existing_languages
from subzero.language import language_from_stream, Language


def prepare_video(pms_video_info, ignore_all=False, hints=None, rating_key=None, providers=None, skip_hashing=False):
    """
    returnes a subliminal/guessit-refined parsed video
    :param pms_video_info:
    :param ignore_all:
    :param hints:
    :param rating_key:
    :return:
    """
    embedded_subtitles = not ignore_all and Prefs['subtitles.scan.embedded']
    external_subtitles = not ignore_all and Prefs['subtitles.scan.external']

    plex_part = pms_video_info["plex_part"]

    if ignore_all:
        Log.Debug("Force refresh intended.")

    Log.Debug("Detecting streams: %s, account_for_external_subtitles=%s, account_for_embedded_subtitles=%s" % (
        plex_part.file, external_subtitles, embedded_subtitles))

    known_embedded = []
    parts = []
    for media in list(Plex["library"].metadata(rating_key))[0].media:
        parts += media.parts

    plexpy_part = None
    for part in parts:
        if int(part.id) == int(plex_part.id):
            plexpy_part = part

    # embedded subtitles
    # fixme: skip the whole scanning process if known_embedded == wanted languages?
    audio_languages = []
    if plexpy_part:
        update_stream_info(plexpy_part)
        for stream in plexpy_part.streams:
            if stream.stream_type == 2:
                lang = None
                try:
                    lang = language_from_stream(stream.language_code)
                except LanguageError:
                    Log.Info("Couldn't detect embedded audio stream language: %s", stream.language_code)

                # treat unknown language as lang1?
                if not lang and config.treat_und_as_first:
                    lang = Language.rebuild(list(config.lang_list)[0])
                    Log.Info("Assuming language %s for audio stream: %s", lang, getattr(stream, "index", None))

                audio_languages.append(lang)

            # subtitle stream
            elif stream.stream_type == 3 and embedded_subtitles:
                is_forced = is_stream_forced(stream)

                if ((config.forced_only or config.forced_also) and is_forced) or not is_forced:
                    # embedded subtitle
                    # fixme: tap into external subtitles here instead of scanning for ourselves later?
                    if stream.codec and getattr(stream, "index", None):
                        if config.exotic_ext or stream.codec.lower() in config.text_based_formats:
                            lang = None
                            try:
                                lang = language_from_stream(stream.language_code)
                            except LanguageError:
                                Log.Info("Couldn't detect embedded subtitle stream language: %s", stream.language_code)

                            # treat unknown language as lang1?
                            if not lang and config.treat_und_as_first:
                                lang = Language.rebuild(list(config.lang_list)[0])
                                Log.Info("Assuming language %s for subtitle stream: %s", lang,
                                         getattr(stream, "index", None))

                            if lang:
                                if is_forced:
                                    lang.forced = True
                                known_embedded.append(lang)
    else:
        Log.Warn("Part %s missing of %s, not able to scan internal streams", plex_part.id, rating_key)

    # metadata subtitles
    known_metadata_subs = set()
    meta_subs = get_subtitles_from_metadata(plex_part)
    for language, subList in meta_subs.iteritems():
        try:
            lang = Language.fromietf(Locale.Language.Match(language))
        except LanguageError:
            if config.treat_und_as_first:
                lang = Language.rebuild(list(config.lang_list)[0])
            else:
                continue

        if subList:
            for key in subList:
                if key.startswith("subzero_md_forced"):
                    lang = Language.rebuild(lang, forced=True)

                known_metadata_subs.add(lang)
                Log.Debug("Found metadata subtitle %r:%s for %s", lang, key, plex_part.file)

    Log.Debug("Known metadata subtitles: %r", known_metadata_subs)
    Log.Debug("Known embedded subtitles: %r", known_embedded)

    subtitle_storage = get_subtitle_storage()
    stored_subs = subtitle_storage.load(rating_key)
    subtitle_storage.destroy()

    try:
        # get basic video info scan (filename)
        video = parse_video(plex_part.file, hints, skip_hashing=config.low_impact_mode or skip_hashing,
                            providers=providers)

        # set stream languages
        if audio_languages:
            video.audio_languages = audio_languages
            Log.Info("Found audio streams: %s" % ", ".join([str(l) for l in audio_languages]))

        if not ignore_all:
            set_existing_languages(video, pms_video_info, external_subtitles=external_subtitles,
                                   embedded_subtitles=embedded_subtitles, known_embedded=known_embedded,
                                   stored_subs=stored_subs, languages=config.lang_list,
                                   only_one=config.only_one, known_metadata_subs=known_metadata_subs,
                                   match_strictness=config.ext_match_strictness)

        # add video fps info
        video.fps = plex_part.fps
        return video

    except ValueError:
        Log.Warn("File could not be guessed: %s: %s", plex_part.file, traceback.format_exc())


def scan_videos(videos, ignore_all=False, providers=None, skip_hashing=False):
    """
    receives a list of videos containing dictionaries returned by media_to_videos
    :param videos:
    :param kind: series or movies
    :return: dictionary of subliminal.video.scan_video, key=subliminal scanned video, value=plex file part
    """
    ret = {}
    for video in videos:
        intent = get_intent()
        force_refresh = intent.get("force", video["id"], video["series_id"], video["season_id"])
        Log.Debug("Determining force-refresh (video: %s, series: %s, season: %s), result: %s"
                  % (video["id"], video["series_id"], video["season_id"], force_refresh))

        hints = helpers.get_item_hints(video)
        video["plex_part"].fps = get_stream_fps(video["plex_part"].streams)
        p = providers or config.get_providers(media_type="series" if video["type"] == "episode" else "movies")
        scanned_video = prepare_video(video, ignore_all=force_refresh or ignore_all, hints=hints,
                                      rating_key=video["id"], providers=p,
                                      skip_hashing=skip_hashing)

        if not scanned_video:
            continue

        scanned_video.id = video["id"]
        part_metadata = video.copy()
        del part_metadata["plex_part"]
        scanned_video.plexapi_metadata = part_metadata
        scanned_video.ignore_all = force_refresh
        ret[scanned_video] = video["plex_part"]
    return ret
