# coding=utf-8
import locale
import logging
import os
import platform
import traceback

import logger
import copy

from requests import HTTPError
from item_details import ItemDetailsMenu
from refresh_item import RefreshItem
from menu_helpers import add_incl_excl_options, dig_tree, set_refresh_menu_state, \
    default_thumb, debounce, ObjectContainer, SubFolderObjectContainer, route
from main import fatality, InclExclMenu
from advanced import DispatchRestart
from subzero.constants import ART, PREFIX, DEPENDENCY_MODULE_NAMES
from support.extract import season_extract_embedded
from support.scheduler import scheduler
from support.config import config
from support.helpers import timestamp, df, display_language
from support.ignore import get_decision_list
from support.items import get_all_items, get_items_info, get_item_kind_from_rating_key, get_item, get_item_title
from support.i18n import _

# init GUI
ObjectContainer.art = R(ART)
ObjectContainer.no_cache = True

# default thumb for DirectoryObjects
DirectoryObject.thumb = default_thumb
Plugin.AddViewGroup("full_details", viewMode="InfoList", mediaType="items", type="list", summary=2)


@route(PREFIX + '/section/firstLetter/key', deeper=bool)
def FirstLetterMetadataMenu(rating_key, key, title=None, base_title=None, display_items=False, previous_item_type=None,
                            previous_rating_key=None):
    """
    displays the contents of a section filtered by the first letter
    :param rating_key: actually is the section's key
    :param key: the firstLetter wanted
    :param title: the first letter, or #
    :param deeper:
    :return:
    """
    title = base_title + " > " + unicode(title)
    oc = SubFolderObjectContainer(title2=title, no_cache=True, no_history=True)

    items = get_all_items(key="first_character", value=[rating_key, key], base="library/sections", flat=False)
    kind, deeper = get_items_info(items)
    dig_tree(oc, items, MetadataMenu,
             pass_kwargs={"base_title": title, "display_items": deeper, "previous_item_type": kind,
                          "previous_rating_key": rating_key})
    return oc


@route(PREFIX + '/section/contents', display_items=bool)
def MetadataMenu(rating_key, title=None, base_title=None, display_items=False, previous_item_type=None,
                 previous_rating_key=None, message=None, header=None, randomize=None):
    """
    displays the contents of a section based on whether it has a deeper tree or not (movies->movie (item) list; series->series list)
    :param rating_key:
    :param title:
    :param base_title:
    :param display_items:
    :param previous_item_type:
    :param previous_rating_key:
    :return:
    """
    title = unicode(title)
    item_title = title
    title = base_title + " > " + title
    oc = SubFolderObjectContainer(title2=title, no_cache=True, no_history=True, header=header, message=message,
                                  view_group="full_details")

    current_kind = get_item_kind_from_rating_key(rating_key)

    if display_items:
        timeout = 30
        show = None

        # add back to series for season
        if current_kind == "season":
            timeout = 720

            show = get_item(previous_rating_key)
            oc.add(DirectoryObject(
                key=Callback(MetadataMenu, rating_key=show.rating_key, title=show.title, base_title=show.section.title,
                             previous_item_type="section", display_items=True, randomize=timestamp()),
                title=_(u"< Back to %s", show.title),
                thumb=show.thumb or default_thumb
            ))
        elif current_kind == "series":
            # it shouldn't take more than 6 minutes to scan all of a series' files and determine the force refresh
            timeout = 3600

        items = get_all_items(key="children", value=rating_key, base="library/metadata")
        kind, deeper = get_items_info(items)
        dig_tree(oc, items, MetadataMenu,
                 pass_kwargs={"base_title": title, "display_items": deeper, "previous_item_type": kind,
                              "previous_rating_key": rating_key})

        # we don't know exactly where we are here, only add ignore option to series
        if current_kind in ("series", "season"):
            item = get_item(rating_key)
            sub_title = get_item_title(item)
            add_incl_excl_options(oc, current_kind, title=sub_title, rating_key=rating_key, callback_menu=InclExclMenu)

        # mass-extract embedded
        if current_kind == "season" and config.plex_transcoder:
            for lang in config.lang_list:
                oc.add(DirectoryObject(
                    key=Callback(SeasonExtractEmbedded, rating_key=rating_key, language=lang,
                                 base_title=show.section.title, display_items=display_items, item_title=item_title,
                                 title=title,
                                 previous_item_type=previous_item_type, with_mods=True,
                                 previous_rating_key=previous_rating_key, randomize=timestamp()),
                    title=_(u"Extract missing %(language)s embedded subtitles", language=display_language(lang)),
                    summary=_("Extracts the not yet extracted embedded subtitles of all episodes for the current "
                              "season with all configured default modifications")
                ))
                oc.add(DirectoryObject(
                    key=Callback(SeasonExtractEmbedded, rating_key=rating_key, language=lang,
                                 base_title=show.section.title, display_items=display_items, item_title=item_title,
                                 title=title, force=True,
                                 previous_item_type=previous_item_type, with_mods=True,
                                 previous_rating_key=previous_rating_key, randomize=timestamp()),
                    title=_(u"Extract and activate %(language)s embedded subtitles", language=display_language(lang)),
                    summary=_("Extracts embedded subtitles of all episodes for the current season "
                              "with all configured default modifications")
                ))

        # add refresh
        oc.add(DirectoryObject(
            key=Callback(RefreshItem, rating_key=rating_key, item_title=title, refresh_kind=current_kind,
                         previous_rating_key=previous_rating_key, timeout=timeout * 1000, randomize=timestamp()),
            title=_(u"Refresh: %s", item_title),
            summary=_("Refreshes %(the_movie_series_season_episode)s, possibly searching for missing and picking up "
                      "new subtitles on disk", the_movie_series_season_episode=_(u"the %s" % current_kind))
        ))
        oc.add(DirectoryObject(
            key=Callback(RefreshItem, rating_key=rating_key, item_title=title, force=True,
                         refresh_kind=current_kind, previous_rating_key=previous_rating_key, timeout=timeout * 1000,
                         randomize=timestamp()),
            title=_(u"Auto-Find subtitles: %s", item_title),
            summary=_("Issues a forced refresh, ignoring known subtitles and searching for new ones")
        ))
    else:
        return ItemDetailsMenu(rating_key=rating_key, title=title, item_title=item_title)

    return oc


@route(PREFIX + '/season/extract_embedded/{rating_key}/{language}')
def SeasonExtractEmbedded(**kwargs):
    rating_key = kwargs.get("rating_key")
    requested_language = kwargs.pop("language")
    with_mods = kwargs.pop("with_mods")
    item_title = kwargs.pop("item_title")
    title = kwargs.pop("title")
    force = kwargs.pop("force", False)

    Thread.Create(season_extract_embedded, **{"rating_key": rating_key, "requested_language": requested_language,
                                              "with_mods": with_mods, "force": force})

    kwargs["header"] = _("Success")
    kwargs["message"] = _(u"Extracting of embedded subtitles for %s triggered", title)

    kwargs.pop("randomize")
    return MetadataMenu(randomize=timestamp(), title=item_title, **kwargs)


@route(PREFIX + '/ignore_list')
def IgnoreListMenu():
    ref_list = get_decision_list()
    include = ref_list.store == "include"
    list_title = _("Include list" if include else "Ignore list")
    oc = SubFolderObjectContainer(title2=list_title, replace_parent=True)
    for key in ref_list.key_order:
        values = ref_list[key]
        for value in values:
            add_incl_excl_options(oc, key, title=ref_list.get_title(key, value), rating_key=value,
                                  callback_menu=InclExclMenu)
    return oc


@route(PREFIX + '/history')
def HistoryMenu():
    from support.history import get_history
    history = get_history()
    oc = SubFolderObjectContainer(title2=_("History"), replace_parent=True)

    for item in history.items[:100]:
        possible_language = item.language
        language_display = item.lang_name if not possible_language else display_language(possible_language)

        oc.add(DirectoryObject(
            key=Callback(ItemDetailsMenu, title=item.title, item_title=item.item_title,
                         rating_key=item.rating_key),
            title=u"%s (%s)" % (item.item_title, _(item.mode_verbose)),
            summary=_(u"%s in %s (%s, score: %s), %s", language_display, item.section_title,
                                                       _(item.provider_name), item.score, df(item.time)),
            thumb=item.thumb or default_thumb
        ))

    history.destroy()

    return oc


@route(PREFIX + '/missing/refresh')
@debounce
def RefreshMissing(randomize=None):
    scheduler.dispatch_task("SearchAllRecentlyAddedMissing")
    header = "Refresh of recently added items with missing subtitles triggered"
    return fatality(header=header, replace_parent=True)


def replace_item(obj, key, replace_value):
    for k, v in obj.items():
        if isinstance(v, dict):
            obj[k] = replace_item(v, key, replace_value)
    if key in obj:
        obj[key] = replace_value
    return obj


def check_connections():
    # debug drone
    Log.Debug("Checking connections ...")
    log_buffer = []
    try:
        from subliminal_patch.refiners.drone import SonarrClient, RadarrClient
        log_buffer.append(["----- Connections -----"])
        for key, cls in [("sonarr", SonarrClient), ("radarr", RadarrClient)]:
            if key in config.refiner_settings:
                cname = key.capitalize()
                try:
                    status = cls(**config.refiner_settings[key]).status(timeout=5)
                except HTTPError, e:
                    if e.response.status_code == 401:
                        log_buffer.append(("%s: NOT WORKING - BAD API KEY", cname))
                    else:
                        log_buffer.append(("%s: NOT WORKING - %s", cname, traceback.format_exc()))
                except:
                    log_buffer.append(("%s: NOT WORKING - %s", cname, traceback.format_exc()))
                else:
                    if status and status["version"]:
                        log_buffer.append(("%s: OK - %s", cname, status["version"]))
                    else:
                        log_buffer.append(("%s: NOT WORKING - %s", cname))
    except:
        log_buffer.append(("Something went really wrong when evaluating Sonarr/Radarr: %s", traceback.format_exc()))
    finally:
        Core.log.setLevel(logging.DEBUG)
        for entry in log_buffer:
            Log.Debug(*entry)

        Core.log.setLevel(logging.getLevelName(Prefs["log_level"]))


@route(PREFIX + '/ValidatePrefs', enforce_route=True)
def ValidatePrefs():
    Core.log.setLevel(logging.DEBUG)

    if Prefs["log_console"]:
        Core.log.addHandler(logger.console_handler)
        Log.Debug("Logging to console from now on")
    else:
        Core.log.removeHandler(logger.console_handler)
        Log.Debug("Stop logging to console")

    # cache the channel state
    update_dict = False
    restart = False

    # reset pin
    Dict["pin_correct_time"] = None

    config.initialize()
    if "channel_enabled" not in Dict:
        update_dict = True

    elif Dict["channel_enabled"] != config.enable_channel:
        Log.Debug("Interface features %s, restarting plugin", "enabled" if config.enable_channel else "disabled")
        update_dict = True
        restart = True

    if "plugin_pin_mode2" not in Dict:
        update_dict = True

    elif Dict["plugin_pin_mode2"] != Prefs["plugin_pin_mode2"]:
        update_dict = True
        restart = True

    if update_dict:
        Dict["channel_enabled"] = config.enable_channel
        Dict["plugin_pin_mode2"] = Prefs["plugin_pin_mode2"]
        Dict.Save()

    if restart:
        scheduler.stop()
        DispatchRestart()
        return

    scheduler.setup_tasks()
    scheduler.clear_task_data("MissingSubtitles")
    set_refresh_menu_state(None)

    Log.Debug("Validate Prefs called.")

    # SZ config debug
    Log.Debug("--- SZ Config-Debug ---")
    for attr in [
            "version", "app_support_path", "data_path", "data_items_path", "enable_agent",
            "enable_channel", "permissions_ok", "missing_permissions", "fs_encoding",
            "subtitle_destination_folder", "include", "include_exclude_paths", "include_exclude_sz_files",
            "new_style_cache", "dbm_supported", "lang_list", "providers", "normal_subs", "forced_only", "forced_also",
            "plex_transcoder", "refiner_settings", "unrar", "adv_cfg_path", "use_custom_dns",
            "has_anticaptcha", "anticaptcha_cls", "mediainfo_bin"]:

        value = getattr(config, attr)
        if isinstance(value, dict):
            d = replace_item(copy.deepcopy(value), "api_key", "xxxxxxxxxxxxxxxxxxxxxxxxx")
            Log.Debug("config.%s: %s", attr, d)
            continue

        if attr in ("api_key",):
            value = "xxxxxxxxxxxxxxxxxxxxxxxxx"

        Log.Debug("config.%s: %s", attr, value)

    for attr in ["plugin_log_path", "server_log_path"]:
        value = getattr(config, attr)

        if value:
            access = os.access(value, os.R_OK)
            if Core.runtime.os == "Windows":
                try:
                    f = open(value, "r")
                    f.read(1)
                    f.close()
                except:
                    access = False

        Log.Debug("config.%s: %s (accessible: %s)", attr, value, access)

    for attr in [
            "subtitles.save.filesystem", ]:
        Log.Debug("Pref.%s: %s", attr, Prefs[attr])

    if "sonarr" in config.refiner_settings or "radarr" in config.refiner_settings:
        Thread.Create(check_connections)

    # fixme: check existance of and os access of logs
    Log.Debug("----- Environment -----")
    Log.Debug("Platform: %s", Core.runtime.platform)
    Log.Debug("OS: %s", Core.runtime.os)
    Log.Debug("Python: %s", platform.python_version())
    for key, value in os.environ.iteritems():
        if key.startswith("PLEX") or key.startswith("SZ_"):
            if "TOKEN" in key:
                outval = "xxxxxxxxxxxxxxxxxxx"

            else:
                outval = value
            Log.Debug("%s: %s", key, outval)
    Log.Debug("Locale: %s", locale.getdefaultlocale())
    Log.Debug("-----------------------")

    Log.Debug("Setting log-level to %s", Prefs["log_level"])
    logger.register_logging_handler(DEPENDENCY_MODULE_NAMES, level=Prefs["log_level"])
    Core.log.setLevel(logging.getLevelName(Prefs["log_level"]))
    os.environ['U1pfT01EQl9LRVk'] = '789CF30DAC2C8B0AF433F5C9AD34290A712DF30D7135F12D0FB3E502006FDE081E'

    return
