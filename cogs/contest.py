import asyncio
import math
from datetime import datetime, timezone
from operator import attrgetter, itemgetter

import discord
from discord.ext import commands
from discord.utils import get
from numpy import indices
from sqlalchemy import orm
from utils.api import ObjectNotFound, _query_api
from utils.constants import ADMIN_ROLES, SITE_URL, TZ
from utils.db import Contest as Contest_DB
from utils.db import Handle as Handle_DB
from utils.db import Json
from utils.db import Judge as Judge_DB
from utils.db import Language as Language_DB
from utils.db import Organization as Organization_DB
from utils.db import Participation as Participation_DB
from utils.db import Problem as Problem_DB
from utils.db import Submission as Submission_DB
from utils.db import User as User_DB
from utils.db import session
from utils.jomd_common import scroll_message
from utils.query import Query
from utils.rating_calculator import rate_contest

# Post new contests
# Rating change predictions for all users in a server


class Contest(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(aliases=['contest'], usage='[contest key] [+server, +all, +predict, dmoj_handles]')
    async def ranklist(self, ctx, key, *args):
        '''List rating predictions of a contest'''
        q = session.query(Contest_DB).filter(Contest_DB.key == key)
        # Clear cache
        if q.count():
            q.delete()
            session.commit()
        query = Query()
        try:
            contest = await query.get_contest(key)
        except ObjectNotFound:
            await ctx.send('Contest not found')
            return

        if contest.hidden_scoreboard and contest.end_time > datetime.utcnow() and\
                ctx.channel.id not in [677272424693104680, 625108494256701481]:
            return await ctx.send('Contest ongoing')
        q = session.query(Handle_DB).filter(Handle_DB.guild_id == ctx.guild.id)
        handles = q.all()

        usernames = []
        showAll = False
        predict = False
        showServerDefault = True
        for arg in args:
            arg = arg.lower()
            if arg == '+server':
                usernames += list(map(attrgetter('handle'), handles))
            elif arg == '+all':
                showAll = True
            elif arg == '+predict':
                predict = True
            else:
                showServerDefault = False
                usernames.append((await query.get_user(arg)).username)
        if showServerDefault:
            usernames += list(map(attrgetter('handle'), handles))

        # The only way to calculate rating changes is by getting the volitility of all the users
        # that means 100+ seperate api calls
        # How does evan do it?
        # TODO: Use the custom api on evan's site
        rankings = {}
        import requests
        r = requests.get(f'https://evanzhang.ca/rating/contest/{key}/api')
        if r:
            rankings = r.json()['users']
        if predict or len(rankings) == 0:
            print('predicted', key)
            rankings = await rate_contest(contest)
            contest.is_rated = True

        # Don't really need this, just sanity check
        # users = await asyncio.gather(*[query.get_user(username)
        #                              for username in users])
        # usernames = [user.username for user in users]
        # Filter for those who participated in contest
        user_rankings = list(map(itemgetter('user'), contest.rankings))
        if showAll:
            usernames = list(set(user_rankings))
        else:
            usernames = list(set(usernames) & set(user_rankings))

        # The length is 0 is contest is still ongoing
        problems = len(contest.problems)

        data = []

        for rank_num, ranking in enumerate(contest.rankings):
            # TODO: ok ish, but placements match the rankings
            for username in usernames:
                if ranking['user'] == username:
                    # If contest is not rated, this crashes
                    if contest.is_rated:
                        if username in rankings:
                            evan_ranking = rankings[username]
                            rank_dict = {
                                'rank': int(evan_ranking['rank']),
                                'username': username + ':',
                                'old_rating': evan_ranking['old_rating'],
                                'new_rating': evan_ranking['new_rating'],
                                'performance': round(evan_ranking['performance'])
                                if evan_ranking['performance'] else evan_ranking['performance']
                            }
                            if evan_ranking['rating_change'] and evan_ranking['rating_change'] > 0:
                                rank_dict['rating_change'] = '+' + str(evan_ranking['rating_change'])
                            else:
                                rank_dict['rating_change'] = evan_ranking['rating_change']
                        else:
                            # User joined contest but was not rated
                            # TODO: Placement does not match ranking
                            rank_dict = {
                                'rank': len(rankings) + 1,
                                'username': username + ':',
                                'old_rating': 'N/A',
                                'new_rating': 'N/A',
                                'rating_change': 'N/A',
                                'performance': 'N/A',
                            }
                    else:
                        rank_dict = {
                            'rank': rank_num + 1,
                            'username': username + ':',
                        }
                    # This is a quick fix :>
                    problems = len(ranking['solutions'])
                    for i in range(1, problems + 1):
                        solution = ranking['solutions'][i - 1]
                        if solution:
                            rank_dict[str(i)] = int(solution['points'])
                        else:
                            rank_dict[str(i)] = '-'
                    data.append(rank_dict)
        max_len = {}
        max_len['rank'] = len('#')
        max_len['username'] = len('Handle')
        for i in range(1, problems + 1):
            max_len[str(i)] = len(str(i))
        max_len['rating_change'] = max_len['old_rating'] = max_len['new_rating'] = max_len['performance'] = 3

        for rank in data:
            for k, v in rank.items():
                max_len[k] = max(len(str(v)), max_len.get(k, 0))

        format_output = '{:>' + str(max_len['rank']) + '} '
        format_output += '{:' + str(max_len['username'] + 1) + '}  '
        for i in range(1, problems + 1):
            format_output += '{:' + str(max_len[str(i)]) + '} '

        to_format = [
            '#',
            'Handle',
            *[str(i) for i in range(1, problems + 1)],
        ]

        hyphen_format = [
            '—' * max_len['rank'],
            '—' * max_len['username'],
            *['—' * max_len[str(i)] for i in range(1, problems + 1)],
        ]
        if contest.is_rated:
            format_output += ' '
            format_output += '{:>' + str(max_len['rating_change']) + '}  '
            format_output += '{:' + str(max_len['old_rating']) + '} '
            format_output += '{:' + str(max_len['new_rating']) + '} '
            format_output += '{:' + str(max_len['performance']) + '} '
            to_format += [
                '∆',
                'Old',
                'New',
                'Perf',
            ]

            hyphen_format += [
                '—' * max_len['rating_change'],
                '—' * max_len['old_rating'],
                '—' * max_len['new_rating'],
                '—' * max_len['performance'],
            ]
        outputBegin = format_output.format(*to_format)
        outputBegin += '\n'
        hyphens = format_output.format(*hyphen_format)
        outputBegin += hyphens
        outputBegin += '\n'
        outputEnd = hyphens + '\n'

        content = []
        output = outputBegin
        for rank in data:
            if contest.is_rated:
                output += format_output.format(
                    rank['rank'],
                    rank['username'],
                    *[rank[str(i)] for i in range(1, problems + 1)],
                    str(rank['rating_change']),
                    str(rank['old_rating']),
                    str(rank['new_rating']),
                    str(rank['performance']),
                )
            else:
                output += format_output.format(
                    rank['rank'],
                    rank['username'],
                    *[rank[str(i)] for i in range(1, problems + 1)],
                )
            output += '\n'
            if(len(output) + len(outputEnd) * 2 > 1980):
                output += outputEnd
                content.append('```yaml\n' + output + '```')
                output = outputBegin
        output += outputEnd
        content.append('```yaml\n' + output + '```')
        await ctx.send('Results for ' + contest.name + ' (<' + SITE_URL + 'contest/' + key + '>): ')
        message = await ctx.send(content[0])
        await scroll_message(ctx, self.bot, message, content)

    @commands.command(aliases=['pc'], usage='[contest key] [+all]')
    async def postcontest(self, ctx, key, option=''):
        '''Updates post-contest role'''

        def has_admin_perms(ctx):
            return any(get(ctx.guild.roles, name=role) in ctx.author.roles for role in ADMIN_ROLES)

        update_all = option == '+all' and has_admin_perms(ctx)

        query = Query()

        if update_all:
            usernames = session.query(Handle_DB).filter(Handle_DB.guild_id == ctx.guild.id).all()
        else:
            username = query.get_handle(ctx.author.id, ctx.guild.id)

            if username is None:
                return await ctx.send('Your account is not linked!')

        q = session.query(Contest_DB).filter(Contest_DB.key == key)
        # Clear cache
        if q.count():
            q.delete()
            session.commit()
        try:
            contest = await query.get_contest(key)
        except ObjectNotFound:
            await ctx.send('Contest not found')
            return

        if contest.is_organization_private:
            return await ctx.send('Contest not found')

        role = get(ctx.guild.roles, name='postcontest ' + key)
        if not role:
            return await ctx.send(f'No `postcontest {key}` role found.')

        if update_all:
            participants = set()
            for ranking in contest.rankings:
                endTime = datetime.strptime(ranking['end_time'], '%Y-%m-%dT%H:%M:%S%z')
                if endTime < datetime.now(timezone.utc).astimezone():
                    participants.add(ranking['user'])

            for user in usernames:
                if user.handle in participants:
                    try:
                        await ctx.guild.get_member(user.id).add_roles(role)
                    except discord.Forbidden:
                        return await ctx.send('No permission to assign the role')
                    except AttributeError:
                        pass
            return await ctx.send('Updated post contest for ' + key)

        for ranking in contest.rankings:
            if ranking['user'].lower() != username.lower():
                continue

            endTime = datetime.strptime(ranking['end_time'], '%Y-%m-%dT%H:%M:%S%z')
            if endTime > datetime.now(timezone.utc).astimezone():
                return await ctx.send('Your window is not done')
            else:
                try:
                    await ctx.author.add_roles(role)
                except discord.Forbidden:
                    return await ctx.send('No permission to assign the role')
                return await ctx.send('You\'ve been added to post contest')
        return await ctx.send('You haven\'t joined the contest yet')

    @commands.command(aliases=['cdif'], usage='[contest key]')
    async def contestDifficulty(self, ctx, key):
        '''Calculate contest problem difficulty'''
        def calculateDifficutly(ratings, solved):
            (bestProb, ans) = (-1e9, 0)

            def calcProb(dif):
                prob = 0
                for (r, s) in zip(ratings, solved):
                    p = 1 / (1 + 10**((dif - r) / 400))
                    prob += math.log(p) if s else math.log(1 - p)
                if prob > bestProb:
                    return (prob, dif)
                return (bestProb, ans)
            jump = 50  # sqrt :blobcreep:
            for dif in range(-1000, 5001, jump):
                (bestProb, ans) = calcProb(dif)
            for dif in range(ans - jump, ans + jump):
                (bestProb, ans) = calcProb(dif)
            ans = min(max(ans, -1000), 5000)
            return ans
        print(key)
        try:
            contest = await _query_api(SITE_URL + 'api/v2/contest/' + key, 'json')
            contest = contest['data']['object']
        except ObjectNotFound:
            await ctx.send('Contest not found')
            return
        pCount = len(contest['problems'])
        pMax = [p['points'] for p in contest['problems']]
        solved = [[] for i in range(pCount)]
        ratings = []
        for ranking in contest['rankings']:
            if not ranking['old_rating'] or ranking['is_disqualified']:
                continue
            ratings.append(ranking['old_rating'])
            for (i, p) in enumerate(ranking['solutions']):
                solved[i].append(p['points'] == pMax[i] if p else False)
        output = ''
        for i in range(pCount):
            output += f'Problem {i+1}: {calculateDifficutly(ratings,solved[i])}\n'
        await ctx.send(output)



def setup(bot):
    bot.add_cog(Contest(bot))
