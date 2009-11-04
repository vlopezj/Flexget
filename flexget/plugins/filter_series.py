import logging
from datetime import datetime, timedelta
from flexget.utils.titles import SeriesParser, ParseWarning
from flexget.manager import Base
from flexget.plugin import *
from sqlalchemy import Column, Integer, String, DateTime, Boolean, desc
from sqlalchemy.schema import ForeignKey
from sqlalchemy.orm import relation, join

log = logging.getLogger('series')

class Series(Base):
    
    __tablename__ = 'series'
    
    id = Column(Integer, primary_key=True)
    name = Column(String)
    episodes = relation('Episode', backref='series')

    def __repr__(self):
        return '<Series(name=%s)>' % (self.name)

class Episode(Base):
    
    __tablename__ = 'series_episodes'

    id = Column(Integer, primary_key=True)
    identifier = Column(String)
    first_seen = Column(DateTime, default=datetime.now())
    
    season = Column(Integer)
    number = Column(Integer)

    series_id = Column(Integer, ForeignKey('series.id'))
    releases = relation('Release', backref='episode')

    def __repr__(self):
        return '<Episode(identifier=%s)>' % (self.identifier)

class Release(Base):

    __tablename__ = 'episode_releases'

    id = Column(Integer, primary_key=True)
    episode_id = Column(Integer, ForeignKey('series_episodes.id'))
    quality = Column(String)
    downloaded = Column(Boolean, default=False)
    proper = Column(Boolean, default=False)
    title = Column(String)

    def __repr__(self):
        return '<Release(quality=%s,downloaded=%s,proper=%s,title=%s)>' % (self.quality, self.downloaded, self.proper, self.title)

class SeriesPlugin(object):
    
    """Database helpers"""

    def get_first_seen(self, session, parser):
        """Return datetime when this episode of series was first seen"""
        episode = session.query(Episode).select_from(join(Episode, Series)).\
            filter(Series.name == parser.name.lower()).filter(Episode.identifier == parser.identifier()).first()
        return episode.first_seen
        
    def get_latest_info(self, session, name):
        """Return latest known identifier in dict (season, episode) for series name"""
        episode = session.query(Episode).select_from(join(Episode, Series)).\
            filter(Episode.season != None).filter(Series.name == name.lower()).\
            order_by(desc(Episode.season)).order_by(desc(Episode.number)).first()
        if not episode:
            log.log(5, 'get_latest_info: no info available for %s' % name)
            return False
        log.log(5, 'get_latest_info, series: %s season: %s episode: %s' % \
            (name, episode.season, episode.number))
        return {'season':episode.season, 'episode':episode.number}
    
    def get_releases(self, session, name, identifier):
        """Return all releases for series by identifier."""
        episode = session.query(Episode).select_from(join(Episode, Series)).\
            filter(Series.name == name.lower()).\
            filter(Episode.identifier == identifier).first()
        if not episode:
            return []
        releases = []
        for release in session.query(Release).filter(Release.episode_id == episode.id).\
            order_by(desc(Release.quality)).all():
            releases.append(release)
        return releases
    
    def get_downloaded(self, session, name, identifier):
        """Return list of downloaded releases for this episode"""
        episode = session.query(Episode).select_from(join(Episode, Series)).\
            filter(Series.name == name.lower()).\
            filter(Episode.identifier == identifier).first()
        if not episode:
            log.debug('get_downloaded: episode or series does not exist')
            return []
        downloaded = []
        for release in session.query(Release).filter(Release.episode_id == episode.id).\
            filter(Release.downloaded == True).all():
            downloaded.append(release)
        if not downloaded:
            log.debug('get_downloaded: no %s downloads recorded for %s' % (identifier, name))
        return downloaded
    
    def store(self, session, parser):
        """Push series information into database. Returns added/existing release."""
        # if series does not exist in database, add new
        series = session.query(Series).filter(Series.name == parser.name.lower()).first()
        if not series:
            log.debug('adding series %s into db' % parser.name)
            series = Series()
            series.name = parser.name.lower()
            session.add(series)
            log.debug('-> added %s' % series)
        
        # if episode does not exist in series, add new
        episode = session.query(Episode).filter(Episode.series_id == series.id).\
            filter(Episode.identifier == parser.identifier()).first()
        if not episode:
            log.debug('adding episode %s into series %s' % (parser.identifier(), parser.name))
            episode = Episode()
            episode.identifier = parser.identifier()
            # if episodic format
            if parser.season and parser.episode:
                episode.season = parser.season
                episode.number = parser.episode
            series.episodes.append(episode) # pylint: disable-msg=E1103
            log.debug('-> added %s' % episode)

        # if release does not exists in episodes, add new
        release = session.query(Release).filter(Release.episode_id == episode.id).\
            filter(Release.quality == parser.quality).\
            filter(Release.proper == parser.proper_or_repack).first()
        if not release:
            log.debug('addding release %s into episode' % parser)
            release = Release()
            release.quality = parser.quality
            release.proper = parser.proper_or_repack
            release.title = parser.data
            episode.releases.append(release) # pylint: disable-msg=E1103
            log.debug('-> added %s' % release)
        return release


_series = {}
def optik_series(option, opt, value, parser):
    """--series [NAME]"""
    _series['got'] = True
    if len(parser.rargs) != 0:
        _series['name'] = parser.rargs[0]

class SeriesReport(SeriesPlugin):
    
    """Produces --series report"""

    def on_process_start(self, feed):
        if _series:
            feed.manager.disable_feeds()

            if not 'name' in _series:
                self.display_summary()
            else:
                self.display_details()

    def display_details(self):
        """Display detailed series information"""
        from flexget.manager import Session
        session = Session()

        name = _series['name'].lower()
        series = session.query(Series).filter(Series.name == name.lower()).first()
        if not series:
            print 'Unknown series %s' % name
            return

        print ' %-30s%-20s' % ('Identifier', 'Status')
        print '-' * 79

        for episode in series.episodes:
            status = ''
            for release in episode.releases:
                if release.downloaded:
                    status += '*'
                status += release.quality
                if release.proper:
                    status += '-Proper'
                status += ' '
            print ' %-30s%-20s' % (episode.identifier, status)
            
        print '-' * 79
        print ' * = downloaded'
        session.close()

    def display_summary(self):
        """Display series summary"""
        print ' %-30s%-20s%-21s' % ('Name', 'Latest', 'Status')
        print '-' * 79

        from flexget.manager import Session
        session = Session()

        for series in session.query(Series).all():

            # get latest episode in episodic format
            episode = session.query(Episode).select_from(join(Episode, Series)).\
                      filter(Series.name == series.name.lower()).filter(Episode.season != None).\
                      order_by(desc(Episode.season)).order_by(desc(Episode.number)).first()

            # no luck, try uid format
            if not episode:
                episode = session.query(Episode).select_from(join(Episode, Series)).\
                          filter(Series.name == series.name.lower()).filter(Episode.season == None).\
                          order_by(desc(Episode.first_seen)).first()

            latest = ''
            status = ''

            if episode:
                if not episode.season or not episode.number:
                    latest = '%s (uid)' % episode.identifier
                else:
                    latest = 's%se%s' % (str(episode.season).zfill(2), str(episode.number).zfill(2))

                for release in self.get_releases(session, series.name, episode.identifier):
                    if release.downloaded:
                        status += '*'
                    status += release.quality
                    if release.proper:
                        status += '-Proper'
                    status += ' '
            else:
                latest = 'N/A'
                status = 'N/A'

            print ' %-30s%-20s%-21s' % (series.name, latest, status)

        print '-' * 79
        print ' * = downloaded'
        session.close()

_series_forget = {}
def optik_series_forget(option, opt, value, parser):
    """
    Callback for Optik
    --series-forget NAME [ID]
    """
    if len(parser.rargs) == 0:
        return # how to handle invalid?
    if len(parser.rargs) > 0:
        _series_forget['name'] = parser.rargs[0]
    if len(parser.rargs) > 1:
        _series_forget['episode'] = parser.rargs[1]

class SeriesForget(object):
    
    """Provides --series-forget"""

    def on_process_start(self, feed):
        if _series_forget:
            feed.manager.disable_feeds()

            name = _series_forget.get('name')

            from flexget.manager import Session
            session = Session()

            if _series_forget.get('episode'):
                # remove by id
                identifier = _series_forget.get('episode').upper()
                if identifier and name:
                    series = session.query(Series).filter(Series.name == name.lower()).first()
                    if series:
                        episode = session.query(Episode).filter(Episode.identifier == identifier).first()
                        if episode:
                            print 'Removed %s %s' % (name.capitalize(), identifier)
                            session.delete(episode)
                        else:
                            print 'Didn\'t find %s episode identified by %s' % (name.capitalize(), identifier)
                    else:
                        print 'Unknown series %s' % name
            else:
                # remove whole series
                series = session.query(Series).\
                         filter(Series.name == name.lower()).first()
                if series:
                    print 'Removed %s' % name
                    session.delete(series)
                else:
                    print 'Unknown series %s' % name
            
            session.commit()


class FilterSeries(SeriesPlugin):

    """
        Intelligent filter for tv-series.
        
        http://flexget.com/wiki/FilterSeries
    """
    
    def __init__(self):
        self.parser2entry = {}
    
    def validator(self):
        from flexget import validator

        def build_options(advanced):
            advanced.accept('text', key='path')
            bundle = advanced.accept('dict', key='set')
            bundle.accept_any_key('any')
            # regexes can be given in as a single string ..
            advanced.accept('regexp', key='name_regexp')
            advanced.accept('regexp', key='ep_regexp')
            advanced.accept('regexp', key='id_regexp')
            # .. or as list containing strings
            advanced.accept('list', key='name_regexp').accept('regexp')
            advanced.accept('list', key='ep_regexp').accept('regexp')
            advanced.accept('list', key='id_regexp').accept('regexp')
            # quality
            advanced.accept('text', key='quality')                    # TODO: allow only SeriesParser.qualities
            advanced.accept('list', key='qualities').accept('text')   # TODO: ^^
            advanced.accept('text', key='min_quality')                # TODO: ^^
            advanced.accept('text', key='max_quality')                # TODO: ^^
            advanced.accept('regexp_match', key='timeframe').accept('\d+ (minutes|hours|days|weeks)')
            # watched
            watched = advanced.accept('dict', key='watched')
            watched.accept('number', key='season')
            watched.accept('number', key='episode')

        def build_list(series):
            """Build series list to series."""
            series.accept('text')
            bundle = series.accept('dict')
            # prevent invalid indentation level
            bundle.reject_keys(['set', 'path', 'timeframe', 'name_regexp', 'ep_regexp', 'id_regexp', 'watched'])
            advanced = bundle.accept_any_key('dict')
            build_options(advanced)
        
        root = validator.factory()
        
        # simple format:
        #   - series
        #   - another series
        
        simple = root.accept('list')
        build_list(simple)
        
        # advanced format:
        #   settings:
        #     group: {...}
        #   group:
        #     {...}

        advanced = root.accept('dict')
        settings = advanced.accept('dict', key='settings')
        settings.reject_keys(get_plugin_keywords())
        settings_group = settings.accept_any_key('dict')
        build_options(settings_group)

        group = advanced.accept_any_key('list')        
        build_list(group)

        return root

    # TODO: re-implement (as new (sub)-plugin InputBacklog)
    """
    def on_feed_input(self, feed):
        .
        .
        .
    """

    def generate_config(self, feed):
        """Generate configuration dictionary from configuration. Converts simple format into advanced.
        This way we don't need to handle two different configuration formats in the logic.
        Applies group settings with advanced form."""

        feed_config = feed.config.get('series', [])
        
        # generate unified configuration in complex form, requires complex code as well :)
        config = {}
        if isinstance(feed_config, list):
            # convert simpliest configuration internally grouped format
            config['settings'] = {}
            config['simple'] = []
            for series in feed_config:
                # convert into dict-form if necessary
                series_settings = {}
                if isinstance(series, dict):
                    series, series_settings = series.items()[0]
                    if series_settings is None:
                        raise Exception('Series %s has unexpected \':\'' % series)
                config['simple'].append({series: series_settings})
        else:
            # already in grouped format, just get settings from there
            import copy
            config = copy.deepcopy(feed_config)
            if not 'settings' in config:
                config['settings'] = {}
            
        # TODO: what if same series is configured in multiple groups?!
        
        # generate quality settings from group name and empty settings if not present (required) 
        for group_name, _ in config.iteritems():
            if group_name == 'settings':
                continue
            if not group_name in config['settings']:
                # at least empty settings 
                config['settings'][group_name] = {}
                # if known quality, convenience create settings with that quality
                if group_name in SeriesParser.qualities:
                    config['settings'][group_name]['quality'] = group_name
                    
        # generate groups from settings groups
        for group_name, group_settings in config['settings'].iteritems():
            # convert group series into complex types
            complex_series = []
            for series in config.get(group_name, []):
                # convert into dict-form if necessary
                series_settings = {}
                if isinstance(series, dict):
                    series, series_settings = series.items()[0]
                    if series_settings is None:
                        raise Exception('Series %s has unexpected \':\'' % series)
                # if series have given path instead of dict, convert it into a dict    
                if isinstance(series_settings, basestring):
                    series_settings = {'path': series_settings}
                # merge group settings into this series settings
                from flexget.utils.tools import merge_dict_from_to 
                merge_dict_from_to(group_settings, series_settings)
                complex_series.append({series: series_settings})
            # add generated complex series into config
            config[group_name] = complex_series
            
        return config
    
    def on_feed_filter(self, feed):
        """Filter series"""

        # TEMP: hack, test if running old database with sqlalchemy table reflection ..
        from flexget.utils.sqlalchemy_utils import table_exists
        if table_exists('episode_qualities', feed):
            log.critical('Running old database! Please see bleeding edge news!')
            feed.manager.disable_feeds()
            feed.abort()
        
        # TEMP: bugfix, convert all series to lowercase
        for series in feed.session.query(Series).all():
            series.name = series.name.lower()
        
        config = self.generate_config(feed)
        for group_name, group_series in config.iteritems():
            # TODO: do we even need settings block in the config at this point, should generate remove it?
            if group_name == 'settings':
                continue
            for series_item in group_series:
                series_name, series_config = series_item.items()[0]
                log.log(5, 'series_name: %s series_config: %s' % (series_name, series_config))
                series = self.parse_series(feed, series_name, series_config)
                self.process_series(feed, series, series_name, series_config)

    def parse_series(self, feed, series_name, config):
        """Search for :series_name: and return dict containing all episodes from it in a dict."""

        def get_as_array(config, key):
            """Return configuration key as array, even if given as a single string"""
            v = config.get(key, [])
            if isinstance(v, basestring):
                return [v]
            return v

        # helper function, iterate entry fields in certain order
        def field_order(a, b):
            order = ['title', 'description']
            def index(c):
                try:
                    return order.index(c[0])
                except ValueError:
                    return 1
            return cmp(index(a), index(b))
            
        # key: series (episode) identifier ie. S01E02
        # value: seriesparser
        series = {}
        for entry in feed.entries:

            # determine if series is known to be in season, episode format
            # note: inside the loop for better handling multiple new eps
            # ie. after first season, episode release we stick with expect_ep
            expect_ep = False
            latest = self.get_latest_info(feed.session, series_name)
            if latest:
                if latest.get('season') and latest.get('episode'):
                    log.log(5, 'enabling expect_ep for %s' % series_name)
                    expect_ep = True

            for field, data in sorted(entry.items(), cmp=field_order):
                # skip invalid fields
                if not isinstance(data, basestring) or not data: 
                    continue
                parser = SeriesParser()
                parser.name = series_name
                parser.data = data
                parser.expect_ep = expect_ep
                parser.ep_regexps = get_as_array(config, 'ep_regexp') + parser.ep_regexps
                parser.id_regexps = get_as_array(config, 'id_regexp') + parser.id_regexps
                # do not use builtin list for id when ep configigured and vice versa
                if 'ep_regexp' in config and not 'id_regexp' in config:
                    parser.id_regexps = []
                if 'id_regexp' in config and not 'ep_regexp' in config:
                    parser.ep_regexps = []
                parser.name_regexps.extend(get_as_array(config, 'name_regexp'))
                try:
                    parser.parse()
                except ParseWarning, pw:
                    from flexget.utils.log import log_once
                    log_once(pw.value, logger=log)
                    
                if parser.valid:
                    self.parser2entry[parser] = entry
                    entry['series_parser'] = parser
                    break
            else:
                continue
            
            # add series, season and episode to entry
            entry['series_name'] = series_name
            entry['series_season'] = parser.season
            entry['series_episode'] = parser.episode
            entry['series_id'] = parser.id
            
            # set custom download path
            if 'path' in config:
                log.debug('setting %s custom path to %s' % (entry['title'], config.get('path')))
                entry['path'] = config.get('path')
            
            # accept info from set: and place into the entry
            if 'set' in config:
                set = get_plugin_by_name('set')
                set.instance.modify(entry, config.get('set'))
                
            # add this episode into list of available episodes
            eps = series.setdefault(parser.identifier(), [])
            eps.append(parser)
            
            # store this episode into database and save reference for later use
            release = self.store(feed.session, parser)
            entry['series_release'] = release

        return series

    def process_series(self, feed, series, series_name, config):
        """Accept or Reject episode from available releases, or postpone choosing."""
        for identifier, eps in series.iteritems():
            if not eps: continue

            # sort episodes in order of quality
            eps.sort()
            
            # get list of downloaded releases
            downloaded_releases = self.get_downloaded(feed.session, eps[0].name, eps[0].identifier())
            log.debug('downloaded: %s' % [e.title for e in downloaded_releases])
            log.debug('processing episodes: %s' % [e.data for e in eps])

            """            
            from IPython.Shell import IPShellEmbed
            ipshell = IPShellEmbed()
            ipshell()
            """

            #
            # proper handling
            #
            def proper_downloaded():
                for release in downloaded_releases:
                    if release.proper:
                        return True

            the_proper = None
            for ep in eps:
                if ep.proper_or_repack:
                    if not proper_downloaded():
                        log.debug('found the_proper %s' % ep)
                        the_proper = ep
                        break
            
            if the_proper:
                removed = []

                # nuke non-propers and other propers
                for ep in eps[:]:
                    if ep is the_proper:
                        log.debug('killing %s would be suicide' % ep)
                        continue
                    log.debug('rejecting extra proper %s' % ep)
                    entry = self.parser2entry[ep]
                    feed.reject(entry, 'nuked')
                    removed.append(ep)

                # remove them from eps
                for ep in removed:
                    log.debug('removed: %s' % ep)
                    eps.remove(ep)
                    
                log.debug('post-eps: %s' % [e.data for e in eps])
                log.debug('after nuked, eps: %s' % [e.data for e in eps])
            

            #
            # reject downloaded (except if the proper)
            #
            if downloaded_releases and eps:
                log.debug('%s is downloaded' % eps[0].identifier())
                for ep in eps[:]:
                    if ep is not the_proper:
                        entry = self.parser2entry[ep]
                        feed.reject(entry, 'already downloaded')
                        # must test if ep in eps because downloaded_releases may contain this episode 
                        # multiple times and trying to remove it twice will cause crash
                        if ep in eps:
                            log.debug('removing from eps: %s' % ep.data)
                            eps.remove(ep)

            # no episodes left, continue to next series
            if not eps:
                log.debug('no eps left')
                continue 

            best = eps[0]
            log.debug('continuing w. episodes: %s' % [e.data for e in eps])
            log.debug('best episode is: %s' % best.data)

            # reject episodes that have been marked as watched in configig file
            if 'watched' in config:
                log.debug('::watched')
                from sys import maxint
                wconfig = config.get('watched')
                season = wconfig.get('season', -1)
                episode = wconfig.get('episode', maxint)
                if best.season < season or (best.season == season and best.episode <= episode):
                    log.debug('%s episode %s is already watched, rejecting all occurrences' % (series_name, identifier))
                    for ep in eps:
                        entry = self.parser2entry[ep]
                        feed.reject(entry, 'watched')
                    continue
                    
            # Episode advancement. Used only with season based series
            if best.season and best.episode:
                log.debug('::episode advancement')
                latest = self.get_latest_info(feed.session, best.name)
                if latest:
                    # allow few episodes "backwards" in case of missed eps
                    grace = len(series) + 2
                    if best.season < latest['season'] or (best.season == latest['season'] and best.episode < latest['episode'] - grace):
                        log.debug('%s episode %s does not meet episode advancement, rejecting all occurrences' % (series_name, identifier))
                        for ep in eps:
                            entry = self.parser2entry[ep]
                            feed.reject(entry, 'episode advancement')
                        continue

            # multiple qualities, accept all wanted qualities
            def is_quality_downloaded(quality):
                for release in downloaded_releases:
                    if release.quality == quality:
                        return True

            if 'qualities' in config:
                log.debug('::processing qualities')
                qualities = [quality.lower() for quality in config['qualities']]
                for ep in eps:
                    #log.debug('qualities, quality: %s' % ep.quality)
                    if not ep.quality.lower() in qualities:
                        continue # unwanted quality
                    if not is_quality_downloaded(ep.quality):
                        log.debug('found wanted quality %s' % ep.data)
                        self.accept_series(feed, ep, 'wanted qualities')
                continue

            # timeframe present
            if 'timeframe' in config:
                log.debug('::processing timeframe')
                if 'max_quality' in config:
                    log.warning('Timeframe does not support max_quality (yet)')
                if 'min_quality' in config:
                    log.warning('Timeframe does not support min_quality (yet)')
                if 'qualities' in config:
                    log.warning('Timeframe does not support qualities (yet)')

                # parse options
                amount, unit = config['timeframe'].split(' ')
                log.debug('amount: %s unit: %s' % (repr(amount), repr(unit)))
                params = {unit:int(amount)}
                try:
                    timeframe = timedelta(**params)
                except TypeError:
                    raise PluginWarning('Invalid time format', log)
                quality = config.get('quality', '720p')
                if not quality in SeriesParser.qualities:
                    log.error('Parameter quality has unknown value: %s' % quality)
                stop = feed.manager.options.stop_waiting == series_name

                # scan for quality, starting from worst quality (reverse) (old logic, see note below)
                eps.reverse()

                def cmp_quality(q1, q2):
                    return cmp(SeriesParser.qualities.index(q1), SeriesParser.qualities.index(q2))

                # scan for episode that meets defined quality
                found_quality = False
                for ep in eps:
                    # Note: switch == operator to >= if wish to enable old behaviour
                    if cmp_quality(quality, ep.quality) == 0: # 1=greater, 0=equal, -1=does not meet
                        entry = self.parser2entry[ep]
                        log.debug('Timeframe accepting. %s meets quality %s' % (entry['title'], quality))
                        self.accept_series(feed, ep, 'quality met, timeframe unnecessary')
                        found_quality = True
                        break
                if found_quality:
                    continue
                        
                # expire timeframe, accept anything
                diff = datetime.now() - self.get_first_seen(feed.session, best)
                if (diff.seconds < 60) and not feed.manager.unit_test:
                    entry = self.parser2entry[best]
                    log.info('Timeframe waiting %s for %s hours, currently best is %s' % (series_name, timeframe.seconds/60**2, entry['title']))
                
                first_seen = self.get_first_seen(feed.session, best)
                log.debug('timeframe: %s' % timeframe)
                log.debug('first_seen: %s' % first_seen)
                log.debug('first_seen + timeframe: %s' % str(first_seen + timeframe))
                
                if first_seen + timeframe <= datetime.now() or stop:
                    entry = self.parser2entry[best]
                    if stop:
                        log.info('Stopped timeframe, accepting %s' % (entry['title']))
                    else:
                        log.info('Timeframe expired, accepting %s' % (entry['title']))
                    self.accept_series(feed, best, 'expired/stopped')
                    for ep in eps:
                        if ep == best:
                            continue
                        entry = self.parser2entry[ep]
                        feed.reject(entry, 'wrong quality')
                    continue
                else:
                    log.debug('timeframe waiting %s episode %s, rejecting all occurrences' % (series_name, identifier))
                    for ep in eps:
                        entry = self.parser2entry[ep]
                        feed.reject(entry, 'timeframe is waiting')
                    continue

            # quality, min_quality, max_quality and NO timeframe
            if ('timeframe' not in config and 'qualities' not in config) and \
               ('quality' in config or 'min_quality' in config or 'max_quality' in config):
                log.debug('::quality/min_quality/max_quality without timeframe')
                accepted_qualities = []
                if 'quality' in config:
                    accepted_qualities.append(config['quality'])
                else:
                    qualities = SeriesParser.qualities
                    min = config.get('min_quality', qualities[-1])
                    max = config.get('max_quality', qualities[0])
                    min_index = qualities.index(min) + 1
                    max_index = qualities.index(max)
                    log.debug('min: %s (%s) max: %s (%s)' % (min, min_index, max, max_index))
                    for quality in qualities[max_index:min_index]:
                        accepted_qualities.append(quality)
                    log.debug('accepted qualities are %s' % accepted_qualities)
                # see if any of the eps match accepted qualities
                for ep in eps:
                    log.log(5, 'testing %s (quality: %s) for qualities' % (ep.data, ep.quality))
                    if ep.quality in accepted_qualities:
                        self.accept_series(feed, ep, 'meets quality')
                        break
                continue

            # no special configuration, just choose the best
            log.debug('::plain')
            self.accept_series(feed, best, 'choose best')

    def accept_series(self, feed, parser, reason):
        """Helper method for accepting series"""
        entry = self.parser2entry[parser]
        if (entry['title'] != parser.data):
            log.debug('BUG? accepted title is different from parser.data')
        feed.accept(entry, reason)

    def on_feed_exit(self, feed):
        """Learn succeeded episodes"""
        for entry in feed.accepted:
            if 'series_release' in entry:
                log.debug('marking %s as downloaded' % (entry['series_release']))
                entry['series_release'].downloaded = True

#
# Register plugins
#

register_plugin(FilterSeries, 'series')
register_plugin(SeriesReport, 'series_report', builtin=True)
register_plugin(SeriesForget, 'series_forget', builtin=True)


register_parser_option('--series', action='callback', callback=optik_series,
                       help='Display series summary.')

register_parser_option('--series-forget', action='callback', callback=optik_series_forget,
                       help='Remove complete series or single episode from database. <Series> [episode]')

register_parser_option('--stop-waiting', action='store', dest='stop_waiting', default=False, 
                       metavar='NAME', help='Stop timeframe for a given series.')

