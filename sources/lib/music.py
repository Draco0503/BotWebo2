from random import shuffle
from time import time
from os import getenv
from asyncio import sleep, get_event_loop
from os import remove
import yt_dlp
from discord import ClientException
from spotify import HTTPClient
import discord
from yt_dlp.utils import ExtractorError, DownloadError

from sources.lib.myRequests import getJsonResponse

yt_key = getenv("YT_KEY") # takes the TOKEN from the YT_KEY on env.example
spotifyClientId = getenv("SPOTIFY_ID") # takes the TOKEN from the SPOTIFY_ID on env.example
spotifySecretId = getenv("SPOTIFY_SECRET") # takes the TOKEN from the SPOTIFY_SECRET on env.example

spotifyClient = HTTPClient(spotifyClientId, spotifySecretId)

MAX_SONGS = 30  # The limit of the API is 50
MAX_VIDEO_DURATION = 900 

COLOR_RED = discord.Color.red()
COLOR_GREEN = discord.Color.green()


class Video:

    """ Saves the main info of a video. """

    def __init__(self, video_id: str, title: str, duration: int = None):
        self.id = video_id
        self.title = title
        self.duration = duration
        self.startTime = None

    def perCentPlayed(self):

        """ Gets the percentage reached on real time of the video. """

        return (time() - self.startTime) / self.duration if self.duration != 0 else 0


class GuildInstance:

    """ Every server has one, has the information of the actions on that server. """

    def __init__(self, guild_id: int):
        self.guild_id = guild_id
        self.textChannel = None
        self.voiceClient = None
        self.playlist = []
        self.searchResults = []
        self.loop: int = 0
        self.currentSong: Video or None = None
        self.data = {"playlist_id": "", "nextPageToken": ""}

    def emptyPlaylist(self):

        """ Resets the playlist. """

        self.playlist = []

        self.data["playlist_id"] = ""
        self.data["nextPageToken"] = ""

    async def shuffleList(self):

        """ Shuffles the playlist. """

        shuffle(self.playlist)
        await self.textChannel.send(embed=discord.Embed(title="Playlist shuffled.", color=COLOR_GREEN))

    async def exit(self) -> None:

        """ Disconnects from the server, when the conditions are met. """

        self.loop = 0
        self.emptyPlaylist()
        self.currentSong = None

        # Disconnect by force
        if self.voiceClient.is_connected:
            await self.voiceClient.disconnect(force=True)

        try:
            remove("serverAudio/" + str(self.guild_id) + ".mp3")
        except FileNotFoundError:
            pass

    async def addVideoToPlaylist(self, url: str) -> None:

        """ Adds a new video's title to the playlist. """
        # Gets the info of the Video as a JSON
        r = await getJsonResponse(
            f"https://www.googleapis.com/youtube/v3/videos?key={yt_key}&part=snippet, contentDetails&id={url}")

        # The video does exists
        if r is not None:

            if len(self.playlist) < MAX_SONGS:
                self.playlist.append(Video(r["items"][0]["id"], r["items"][0]["snippet"]["title"]))
                await self.textChannel.send(embed = discord.Embed(title=f'Added "{r["items"][0]["snippet"]["title"]}" to the playlist', color=COLOR_GREEN))

            else:
                await self.textChannel.send(embed=discord.Embed(title='The playlist is full already.', colour=COLOR_RED))

        else:
            await self.textChannel.send(embed=discord.Embed(title='Wrong url.', colour=COLOR_RED))

    async def addToPlaylistFromSearchList(self, ind: int) -> None:

        """ Add if exists the song you are looking for. """

        try:
            # search for the song
            self.playlist.append(self.searchResults[ind])
            await self.textChannel.send(embed=discord.Embed(title="Song added to the playlist", colour=COLOR_GREEN))

        except IndexError:
            await self.textChannel.send("Index out of range.")

    async def getYoutubePlaylist(self, playlist_id: str) -> None:

        """ Gets at most 30 song from the playlist send. """

        # saves the playlist id in case there remain more than 30 songs
        self.data["playlist_id"] = playlist_id

        # gets the list as JSON
        results = await getJsonResponse(
            f"https://www.googleapis.com/youtube/v3/playlistItems?pageToken={self.data['nextPageToken']}&key={yt_key}&part=snippet,contentDetails&maxResults=30&playlistId={self.data['playlist_id']}")
        # creates a new list of Video class
        video_list = [Video(vid["snippet"]["resourceId"]["videoId"], vid["snippet"]["title"]) for vid in
                      results["items"] if vid["snippet"]["title"] != 'Deleted video' and vid["snippet"]["title"] != 'Private video']

        cont = 0
        for video in video_list:
            self.playlist.append(video)
            cont += 1
            if len(self.playlist) >= 30:
                break
        # saves the playlist nextPageToken in case there remain more than 30 songs
        try:
            self.data["nextPageToken"] = results["nextPageToken"]
        except KeyError:
            self.data["nextPageToken"] = ""

        await self.textChannel.send(embed=discord.Embed(title=f"{cont} song(s) where added to the playlist.", colour=COLOR_GREEN))

    async def findYoutubeEquivalent(self):
        
        """ Finds a YT equivalent video for the text send """

        # gets the list as JSON
        results = await getJsonResponse(
            f"https://www.googleapis.com/youtube/v3/search?key={yt_key}&part=snippet&type=video&q={self.currentSong.title}")

        # Attempts to get the 1st video
        try:
            self.currentSong.id = results["items"][0]["id"]["videoId"]

        except IndexError:
            await self.textChannel.send(embed=discord.Embed(title=f'Could not find a youtube video for song {self.currentSong.title}', colour=COLOR_RED))

    async def youtubeSearch(self, string: str) -> None:

        """ Search for the video (only text) that you want """

        results = await getJsonResponse(
            f"https://www.googleapis.com/youtube/v3/search?key={yt_key}&part=snippet&type=video&q={string}")

        # error on the JSON
        if results is None:
            await self.textChannel.send(embed=discord.Embed(title="An error has occurred.", colour=COLOR_RED))
        # search but no results
        elif len(results["items"]) == 0:
            await self.textChannel.send(embed=discord.Embed(title="No results.", colour=COLOR_GREEN))

        else:
            self.searchResults.clear()

            for num, vid in enumerate(results["items"]):

                embed = discord.Embed(title=str(num + 1) + ") " + vid["snippet"]["title"], colour=COLOR_GREEN)
                embed.set_image(url=vid["snippet"]["thumbnails"]["default"]["url"])
                await self.textChannel.send(embed=embed)

                self.searchResults.append(Video(vid["id"]["videoId"], vid["snippet"]["title"]))

    async def getYoutubeVidDuration(self) -> None:

        """ Gets the video length """

        r = await getJsonResponse(
            f"https://www.googleapis.com/youtube/v3/videos?key={yt_key}&part=contentDetails&id={self.currentSong.id}")
        # convert the time into seconds
        self.currentSong.duration = convertTime(r["items"][0]["contentDetails"]["duration"]) if r is not None else 0

    async def getSpotifyAlbum(self, albumID: str) -> None:

        """ Gets and creates a Video class list of a spotify url list """

        album = await spotifyClient.album(albumID)
        lista = album["tracks"]["items"]

        cont = 0
        for song in lista:

            self.playlist.append(Video(None, song["name"] + " " + song["artists"][0]["name"]))
            cont += 1
            if len(self.playlist) >= 30:
                break

        await self.textChannel.send(embed=discord.Embed(title=f"{cont} song(s) where added to the playlist.", colour=COLOR_GREEN))

    async def getSpotifyPlaylist(self, playlist_id: str) -> None:

        """ Sends a message of the playlist saved """

        playlist = await spotifyClient.get_playlist(playlist_id)

        lista = playlist["tracks"]["items"]

        cont = 0
        for song in lista:

            self.playlist.append(Video(None, song["track"]["name"] + " " + song["track"]["artists"][0]["name"]))
            cont += 1
            if len(self.playlist) >= 30:
                break

        await self.textChannel.send(embed=discord.Embed(title=f"{cont} song(s) where added to the playlist.", colour=COLOR_GREEN))

    async def player(self, voice_channel: discord.VoiceChannel) -> None:

        """ Is who takes care of the programme checks regarding the music.   """

        try:
            self.voiceClient = await voice_channel.connect()

        except discord.ClientException:
            return

        leave_reason = None
        while self.voiceClient.is_connected():

            if len(self.voiceClient.channel.members) == 1:
                leave_reason = "Channel is empty."
                await self.exit()

            elif not self.voiceClient.is_playing():

                if len(self.playlist) > 0 or self.loop == 1:
                    try:
                        await self.playSong()
                    except ClientException:
                        leave_reason = "Some error occurred."
                        print("HOLA")
                        await self.exit()

                elif self.data["nextPageToken"] != "":
                    await self.getYoutubePlaylist(self.data["playlist_id"])
                else:
                    leave_reason = "Playlist is empty."
                    await self.exit()

            await sleep(3)

        if leave_reason is None:
            leave_reason = "I was kicked :("
            await self.exit()
        await self.textChannel.send(embed=discord.Embed(title=f"Leaving the channel: {leave_reason}", colour=discord.Color.green()))


    async def playSong(self) -> None:

        """ Plays the song """

        global MAX_VIDEO_DURATION

        # Changes current song info if loop != single
        if self.loop != 1:

            # Adds ended song to the end of the playlist if loop == all
            if self.loop == 2:
                self.playlist.append(self.currentSong)

            if len(self.playlist) > 0:
                self.currentSong = self.playlist[0]
                self.playlist.pop(0)

            else:
                self.currentSong = None
                return


        # If the song has no id (Most likely becasue it comes from a spotify playlist)
        # here a yt video will be found for that song
        if self.currentSong.id is None:
            await self.findYoutubeEquivalent()

        await self.getYoutubeVidDuration()

        # Skips videos that are too long.
        if self.currentSong.duration > MAX_VIDEO_DURATION:
            await self.textChannel.send(f"Skipped {self.currentSong.title} because it was too long.")
            return

        path = f"serverAudio/{self.guild_id}.mp3"
        # Downloads the song if loop is not on single.
        if self.loop != 1:

            try:
                remove(path)
            except FileNotFoundError:
                pass

            loop = get_event_loop()
            await loop.run_in_executor(None, downloadSong, self.currentSong.id, path)

        try:
            self.voiceClient.play(discord.FFmpegPCMAudio(path))
            self.currentSong.startTime = time()
        except FileNotFoundError:
            self.textChannel.send(embed=discord.Embed(title="Could not download video", colour=COLOR_RED))

    async def skip(self, ind: int = None) -> None:

        """ Command to skip the current song. """

        if self.loop == 1:
            self.loop = 0

        if ind is not None:

            try:
                ind = int(ind)

                for x in range(ind):
                    self.playlist.pop(0)

            except IndexError:
                await self.textChannel.send(
                    embed=discord.Embed(title="Index out of range", color=COLOR_RED))

        self.voiceClient.stop()
        await self.textChannel.send(embed=discord.Embed(title="Song skipped", color=COLOR_RED))

    async def remove(self, ind: int) -> None:

        """ Removes a song from the playlist """

        try:
            title = self.playlist[ind].title
            self.playlist.pop(ind)
            embed = embed = discord.Embed(title=f'Song "{title}" has been removed from the playlist.', colour=COLOR_GREEN)
            await self.textChannel.send(embed=embed)

        except IndexError:
            await self.textChannel.send(
                embed=discord.Embed(title="Index out of range", color=COLOR_RED))


guilds = {}


def getGuildInstance(guild_id: int, create_if_missing: bool = True) -> GuildInstance or None:

    """ Saves the ID of a guild on a dictionary so all can work properly. """

    # calls to the dictionary of guilds
    global guilds
    # check if the ID its in the dictionary
    # the ID exists in the dict
    if guild_id in guilds:
        return guilds.get(guild_id)
    # saves it if its not
    elif create_if_missing:
        guild = GuildInstance(guild_id)
        guilds[guild_id] = guild
        return guild
    # nothing to save
    else:
        return None


def downloadSong(videoId: str, path: str) -> None:

    """ Downloads the video set by parameter. """

    url = "https://www.youtube.com/watch?v={0}".format(videoId)
    # gets the video with the best quality
    ydl_opts = {'format': 'bestaudio/best', 'quiet': False, 'noplaylist': True, "outtmpl": path}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])  # Download into the current working directory
    except ExtractorError:
        pass
    except DownloadError:
        pass


def convertTime(string: str) -> int:

    """ Convert a time format like '00H00M00S' to seconds. """

    n = ""
    H = 0
    M = 0
    S = 0

    for x in string:

        if x.isnumeric():
            n += x

        elif x == "H":
            H = int(n)
            n = ""

        elif x == "M":
            M = int(n)
            n = ""

        elif x == "S":
            S = int(n)
            n = ""

    return H * 3600 + M * 60 + S
