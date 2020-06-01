# coding=utf-8
import os

from subzero.language import Language

import subliminal_patch as subliminal

from support.config import config
from support.helpers import audio_streams_match_languages
from subliminal_patch import compute_score
from support.plex_media import get_blacklist_from_part_map
from subzero.video import refine_video
from support.storage import get_pack_data, store_pack_data


def get_missing_languages(video, part):
    languages_list = config.get_lang_list(ordered=True)
    languages = set(languages_list)
    valid_langs_in_media = set()

    if Prefs["subtitles.when"] != "Always":
        valid_langs_in_media = audio_streams_match_languages(video, languages_list)
        languages = languages.difference(valid_langs_in_media)
        if languages:
            Log.Debug("Languages missing after taking the audio streams into account: %s" % languages)

    if valid_langs_in_media and not languages:
        Log.Debug("Skipping subtitle search for %s, audio streams are in correct language(s)",
                  video)
        return set()

    # should we treat IETF as alpha3? (ditch the country part)
    alpha3_map = {}
    if config.ietf_as_alpha3:
        for language in languages:
            if language and language.country:
                alpha3_map[language.alpha3] = language.country
                language.country = None

    have_languages = video.subtitle_languages.copy()
    if config.ietf_as_alpha3:
        for language in have_languages:
            if language and language.country:
                alpha3_map[language.alpha3] = language.country
                language.country = None

    missing_languages = (languages - have_languages)

    if config.any_language_is_enough != "Always search for all configured languages":
        not_in_forced = "foreign" in config.any_language_is_enough
        if "External or embedded subtitle" in config.any_language_is_enough:
            langs = video.subtitle_languages if not not_in_forced else \
                filter(lambda l: not l.forced, video.subtitle_languages)
            if langs:
                Log.Debug("We have at least one subtitle for any configured language.")
                return set()

        elif "External subtitle" in config.any_language_is_enough:
            langs = video.external_subtitle_languages if not not_in_forced else \
                filter(lambda l: not l.forced, video.external_subtitle_languages)
            if langs:
                Log.Debug("We have at least one external subtitle for any configured language.")
                return set()

    # all languages are found if we either really have subs for all languages or we only want to have exactly one language
    # and we've only found one (the case for a selected language, Prefs['subtitles.only_one'] (one found sub matches any language))
    found_one_which_is_enough = len(video.subtitle_languages) >= 1 and Prefs['subtitles.only_one']
    if not missing_languages or found_one_which_is_enough:
        if found_one_which_is_enough:
            Log.Debug('Only one language was requested, and we\'ve got a subtitle for %s', video)
        else:
            Log.Debug('All languages %r exist for %s', languages, video)
        return set()

    # re-add country codes to the missing languages, in case we've removed them above
    if config.ietf_as_alpha3:
        for language in languages:
            language.country = alpha3_map.get(language.alpha3, None)

    return missing_languages


def pre_download_hook(subtitle):
    if subtitle.is_pack:
        # try retrieving the subtitle from a cached pack archive
        pack_data = get_pack_data(subtitle)
        if pack_data:
            subtitle.pack_data = pack_data


def post_download_hook(subtitle):
    # if a new pack was downloaded, store it in the cache; providers' download method is responsible for
    # setting subtitle.pack_data to None in case the cached pack data we provided was successfully used
    if subtitle.is_pack and subtitle.pack_data:
        # store pack data in cache
        store_pack_data(subtitle, subtitle.pack_data)

    # may be redundant
    subtitle.pack_data = None


def language_hook(provider):
    return config.get_lang_list(provider=provider)


def download_best_subtitles(video_part_map, min_score=0, throttle_time=None, providers=None):
    hearing_impaired = Prefs['subtitles.search.hearingImpaired']
    languages = set([Language.rebuild(l) for l in config.lang_list])
    if not languages:
        return

    use_videos = []
    missing_languages = set()
    for video, part in video_part_map.iteritems():
        if not video.ignore_all:
            p_missing_languages = get_missing_languages(video, part)
        else:
            p_missing_languages = languages

        if p_missing_languages:
            Log.Info(u"%s has missing languages: %s", os.path.basename(video.name), p_missing_languages)
            refine_video(video, refiner_settings=config.refiner_settings)
            use_videos.append(video)
            missing_languages.update(p_missing_languages)

    # prepare blacklist
    blacklist = get_blacklist_from_part_map(video_part_map, languages)

    if use_videos and missing_languages:
        Log.Debug("Download best subtitles using settings: min_score: %s, hearing_impaired: %s, languages: %s" %
                  (min_score, hearing_impaired, missing_languages))

        return subliminal.download_best_subtitles(set(use_videos), missing_languages, min_score, hearing_impaired,
                                                  providers=providers or config.providers,
                                                  provider_configs=config.provider_settings,
                                                  pool_class=config.provider_pool,
                                                  compute_score=compute_score, throttle_time=throttle_time,
                                                  blacklist=blacklist, throttle_callback=config.provider_throttle,
                                                  pre_download_hook=pre_download_hook,
                                                  post_download_hook=post_download_hook,
                                                  language_hook=language_hook)
    Log.Debug("All languages for all requested videos exist. Doing nothing.")