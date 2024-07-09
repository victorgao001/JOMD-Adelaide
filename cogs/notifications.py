# based off https://github.com/kevinjycui/Practice-Bot/blob/master/cogs/contests.py
import json
import os
import random as rand
from datetime import datetime, timedelta
from time import sleep, time

import bs4 as bs
import discord
import pytz
import requests
from discord.ext import commands, tasks
from utils.constants import ADMIN_ROLES


class Contest(object):
    def __init__(self, data):
        self.data = data

    def asdict(self):
        return self.data

    def __eq__(self, other):
        if self.data['oj'] == 'topcoder' and other.data['oj'] == 'topcoder':
            return self.data['title'] == other.data['title']
        return self.data['description'] == other.data['description']

    def __gt__(self, other):
        if self.data['oj'] == 'topcoder' and other.data['oj'] == 'topcoder':
            return self.data['title'] > other.data['title']
        return self.data['description'] > other.data['description']

    def __str__(self):
        if self.data['oj'] == 'topcoder':
            return self.data['title']
        return self.data['description']

    def __hash__(self):
        return hash(str(self))


class NoContestsAvailableException(Exception):

    def __init__(self, oj=None):
        self.oj = oj

    def __str__(self):
        if self.oj is None:
            return 'Sorry, there are not upcoming contests currently available.'
        return 'Sorry, there are not upcoming contests from %s currently available.'\
            % self.onlineJudges.formal_names[self.oj]


class ContestAnnouncements(commands.Cog):
    fetch_time = 0

    dmoj_contests = []

    contest_objects = []

    channel_subs = [726933922847653948]

    status = 0

    def __init__(self, bot):
        self.bot = bot
        self.refresh_contests.start()
        self.check1.start()
        self.contest_cache = []

    def get_random_contests(self, number):
        upcoming_contests = list(filter(self.is_recent, self.contest_cache))
        if len(upcoming_contests) == 0:
            raise NoContestsAvailableException()
        rand.shuffle(upcoming_contests)
        result = []
        for i in range(min(number, len(upcoming_contests))):
            result.append(upcoming_contests[i])
        return self.embed_multiple_contests(result)

    def reset_contest(self, oj):
        if oj == 'dmoj':
            self.dmoj_contests = []

    def set_time(self):
        self.fetch_time = time()

    def parse_dmoj_contests(self):
        contest_req = requests.get('https://dmoj.ca/api/v2/contests').json()
        contests = contest_req['data']['objects']
        for details in contests:
            name = details['key']
            if datetime.strptime(details['start_time'].replace(':', ''), '%Y-%m-%dT%H%M%S%z').timestamp() > time():
                spec = requests.get('https://dmoj.ca/api/v2/contest/' + name).json()['data']['object']
                url = 'https://dmoj.ca/contest/' + name
                contest_data = {
                    'title': ':trophy: %s' % details['name'],
                    'description': url,
                    'oj': 'dmoj',
                    'Start Time': datetime.strptime(details['start_time'].replace(':', ''),
                                                    '%Y-%m-%dT%H%M%S%z').strftime('%Y-%m-%d %H:%M:%S%z'),
                    'End Time': datetime.strptime(details['end_time'].replace(':', ''),
                                                  '%Y-%m-%dT%H%M%S%z').strftime('%Y-%m-%d %H:%M:%S%z')
                }
                if spec['time_limit'] is not None:
                    contest_data['Window'] = '%d:%d:%d' % (
                        spec['time_limit'] // (60 * 60), spec['time_limit'] % (60 * 60) // 60, spec['time_limit'] % 60)
                if len(spec['tags']) > 0:
                    contest_data['Tags'] = ', '.join(spec['tags'])
                contest_data['Rated'] = 'Yes' if spec['is_rated'] else 'No'
                contest_data['Format'] = spec['format']['name']
                self.dmoj_contests.append(Contest(contest_data))

    def embed_contest(self, contest):
        embed = discord.Embed(title=contest.asdict()['title'], description=contest.asdict()['description'])
        embed.set_thumbnail(
            url='https://raw.githubusercontent.com/kevinjycui/Practice-Bot/master/assets/dmoj-thumbnail.png')
        embed.colour = discord.Colour(int('fcdc00', 16))
        for key in list(contest.asdict().keys()):
            if key not in ('title', 'description', 'oj'):
                embed.add_field(name=key, value=contest.asdict()[key], inline=False)
        return embed

    def embed_multiple_contests(self, contests, oj=None, new=False):
        if len(contests) == 0:
            return None
        if len(contests) == 1:
            return self.embed_contest(contests[0])
        if oj is not None:
            embed = discord.Embed(title='%d %s%s Contests' % (
                len(contests), ' New' if new else '', self.onlineJudges.formal_names[oj]))
            embed.set_thumbnail(url=self.onlineJudges.thumbnails[oj])
            embed.colour = self.onlineJudges.colours[oj]
        else:
            embed = discord.Embed(title='%d%s Contests' % (len(contests), ' New' if new else ''))
        for contest in sorted(contests):
            embed.add_field(name=contest.asdict()['title'], value=contest.asdict()
                            ['description'], inline=(len(contests) > 6))
        return embed

    def generate_stream(self):
        self.contest_objects = list(set(self.dmoj_contests))

    @commands.command()
    @commands.has_any_role(*ADMIN_ROLES)
    async def sub(self, ctx, channel: discord.TextChannel = None):
        if not channel:
            channel = ctx.channel
        if channel.id not in self.channel_subs:
            self.channel_subs.append(channel.id)
            await ctx.send(f'subbed {channel.name}')
        else:
            await ctx.send(f'already subbed {channel.name}')

    @commands.command()
    @commands.has_any_role(*ADMIN_ROLES)
    async def unsub(self, ctx, channel: discord.TextChannel = None):
        if not channel:
            channel = ctx.channel
        if channel.id in self.channel_subs:
            self.channel_subs.remove(channel.id)
            await ctx.send(f'unsubbed {channel.name}')
        else:
            await ctx.send(f'already unsubbed {channel.name}')

    @commands.command()
    async def subs(self, ctx):
        await ctx.send(list(map(lambda id: '#' + self.bot.get_channel(id).name, self.channel_subs)))

    @commands.command()
    @commands.bot_has_permissions(embed_links=True)
    async def contests(self, ctx, numstr='1', channel: discord.TextChannel = None):
        try:
            if numstr.isdigit():
                number = int(numstr)
            else:
                number = len(self.contest_cache)
            contestList = self.get_random_contests(number)
            if channel:
                await channel.send(embed=contestList)
            else:
                await ctx.send(ctx.message.author.display_name + ', \
                    Here are some upcoming contest(s). Last fetched, %d minutes ago'
                               % ((time() - self.fetch_time) // 60), embed=contestList)
        except NoContestsAvailableException as e:
            if channel:
                await channel.send(str(e))
            else:
                await ctx.send(ctx.message.author.display_name + ', ' + str(e))

    def is_upcoming(self, contest):
        if '+' in contest.asdict()['Start Time']:
            return datetime.strptime(contest.asdict()['Start Time'], '%Y-%m-%d %H:%M:%S%z') > datetime.now(pytz.UTC)
        return datetime.strptime(contest.asdict()['Start Time'], '%Y-%m-%d %H:%M:%S') > datetime.now()

    def is_recent(self, contest):
        if '+' in contest.asdict()['Start Time']:
            return datetime.strptime(contest.asdict()['Start Time'], '%Y-%m-%d %H:%M:%S%z')\
                > datetime.now(pytz.UTC) - timedelta(days=9)
        return datetime.strptime(contest.asdict()['Start Time'], '%Y-%m-%d %H:%M:%S') \
            > datetime.now() - timedelta(days=9)

    @tasks.loop(minutes=5)
    async def check1(self):
        try:
            requests.get('https://codeforces.com/api/recentActions?maxCount=1').json()
            if self.status != 0:
                channel = self.bot.get_channel(782382023507443712)
                await channel.send(datetime.now().strftime('%Y-%m-%d %H:%M:%S') +
                                   ' Codeforces should be up. Thank you MikeMirzayanov for the great platform Codeforces!')
                self.status = 0
        except Exception:
            if self.status != 1:
                channel = self.bot.get_channel(782382023507443712)
                await channel.send(datetime.now().strftime('%Y-%m-%d %H:%M:%S') + ' Codeforces is down :wheelchair:')
                self.status = 1

    @check1.before_loop
    async def check_cf(self):
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=7)
    async def refresh_contests(self):
        self.reset_contest('dmoj')
        self.parse_dmoj_contests()

        self.set_time()
        self.generate_stream()

        new_contests = list(set(self.contest_objects).difference(set(self.contest_cache)))

        if len(new_contests):
            for channel_id in self.channel_subs:
                channel = self.bot.get_channel(channel_id)
                await channel.send(embed=self.embed_multiple_contests(new_contests, new=True))

        self.contest_cache = list(filter(self.is_recent, list(
            set(self.contest_objects).union(set(self.contest_cache)))))

    @refresh_contests.before_loop
    async def check_contests_before(self):
        await self.bot.wait_until_ready()


def setup(bot):
    bot.add_cog(ContestAnnouncements(bot))
