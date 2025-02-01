import datetime
from dataclasses import dataclass, field
from typing import Optional

import atproto_client.models.app.bsky.graph.listitem
import sqlite_utils
from atproto import Client, IdResolver, models, SessionEvent
from jsonargparse import auto_cli
from pyrate_limiter import Duration, Limiter, Rate, SQLiteBucket
from rich.progress import track


@dataclass
class DID_RKey:
    """Stores a DID/record key combination."""

    did: str
    rkey: str


@dataclass
class BlueskyConstants:
    """Some useful constants."""

    post = "app.bsky.feed.post"
    list = "app.bsky.graph.list"

@dataclass
class DatabaseNames:
    """ Locations of various databases """
    auth = 'auth.sqlite'
    moderation = 'moderation.sqlite'
    rates = 'ratelimit.sqlite'


@dataclass
class BlueskyAPI:
    """Class for interacting with the Bluesky API."""

    handle: str
    session_string: str | None
    app_password: str

    _client: Client = field(default_factory=Client)
    _resolver: IdResolver = field(default_factory=IdResolver)

    def __post_init__(self):
        if self.session_string:
            try:
                self._client.login(session_string=self.session_string)
            except Exception:
                self._client = Client()
                self._client.login(self.handle, self.app_password)
        else:
            self._client.login(self.handle, self.app_password)

    def _url_to_did_rkey(self, url: str) -> Optional[DID_RKey]:
        """
        Converts a Bluesky URL to a DID_RKey combination.
        """
        # Extract the handle and post rkey from the URL
        url_parts = url.split("/")
        handle = url_parts[4]  # Username in the URL
        rkey = url_parts[6]  # Post Record Key in the URL

        # Resolve the DID for the username
        did = self._resolver.handle.resolve(handle)
        if not did:
            print(f'Could not resolve DID for handle "{handle}".')
            return None

        # Fetch the post record
        return DID_RKey(did, rkey)

    def _did_rkey_to_atproto_uri(self, did_rkey: DID_RKey, record_type: str) -> str:
        """Convert DID_RKey records to a ATProto uri."""
        return f"at://{did_rkey.did}/{record_type}/{did_rkey.rkey}"

    def fetch_posts(self, url: str) -> Optional[models.AppBskyFeedPost.Record]:
        """
        Fetch a post using its Bluesky URL.
        """
        try:
            resolve = self._url_to_did_rkey(url)
            return self._client.get_post(resolve.rkey, resolve.did).value
        except (ValueError, KeyError) as e:
            print(f"Error fetching post for URL {url}: {e}")
            return None

    def fetch_likes(self, url: str, all: bool = True) -> list:
        """
        Get the likes from a post, using its Bluesky url.
        """
        did_rkey = self._did_rkey_to_atproto_uri(
            self._url_to_did_rkey(url), BlueskyConstants.post
        )
        page = self._client.get_likes(did_rkey)

        likes = page.likes

        while page.cursor and all:
            page = self._client.get_likes(did_rkey, cursor=page.cursor)
            if page.likes:
                likes += page.likes

        return likes

    def add_item_to_list(
        self, repo_uri: str, subject_did: str
    ) -> models.AppBskyGraphListitem.CreateRecordResponse:
        """
        Adds an item to the moderation list.
        """
        record = atproto_client.models.app.bsky.graph.listitem.Record(
            created_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            subject=subject_did,
            list=repo_uri,
        )

        return self._client.app.bsky.graph.listitem.create(
            repo=self._client.me.did, record=record
        )


@dataclass
class Moderation:
    _moderationDb: sqlite_utils.Database = field(init=False)
    _authDb: sqlite_utils.Database = field(init=False)
    _api: BlueskyAPI = field(init=False)

    handle: str
    app_password: str

    # The limits from https://docs.bsky.app/docs/advanced-guides/rate-limits, with a decent amount of
    # headroom for regular usage.
    _limits = [Rate(1200, Duration.HOUR), Rate(9000, Duration.DAY)]
    # Create SQLite bucket for storage
    _sqliteBucket = SQLiteBucket.init_from_file(
        rates=_limits, db_path=DatabaseNames.rates
    )
    _limiter = Limiter(_sqliteBucket, max_delay=Duration.HOUR, raise_when_fail=False)

    def __post_init__(self):
        self._moderationDb = sqlite_utils.Database(DatabaseNames.moderation)
        self._authDb = sqlite_utils.Database(DatabaseNames.auth)

        # If we can use a session_string from a previous session, do that - there are rate limits here.
        session_string = None
        try:
            session_string = self._authDb["session"].get(self.handle)["session_string"]
        except sqlite_utils.db.NotFoundError:
            pass

        self._api = BlueskyAPI(self.handle, session_string, self.app_password)

        # Handle the session string, and save it in the future.
        self._authDb["session"].insert(
            {
                "handle": self.handle,
                "session_string": self._api._client.export_session_string(),
            },
            pk="handle",
            ignore=True,
        )

        def session_change(event, session):
            # Only update the session string when it's a refresh event
            if event == SessionEvent.REFRESH:
                self._authDb["session"].upsert(
                    {"handle": self.handle, "session_string": self._api._client.export_session_string()},
                    pk="handle",
                )

        self._api._client.on_session_change(session_change)

    def add_likes_to_be_processed(self, post_url: str) -> None:
        """
        Adds all of the likes from a particular post to the database.
        """
        likes = self._api.fetch_likes(post_url)
        db_to_add = self._moderationDb["to_be_added"]
        for like in likes:
            try:
                db_to_add.insert(
                    {
                        "subject": like.actor.did,
                        "handle": like.actor.handle,
                        "source": post_url,
                        "action": "like",
                    },
                    pk="subject",
                )
            except Exception:
                pass

    def process_list(self, list_url: str):
        """
        Adds all of the list additions from the database to the specified list.
        """
        print(
            "This process will pause quite frequently to ensure that we do not reach rate limits. Do not be alarmed, it is still processing."
        )
        list_uri = self._api._did_rkey_to_atproto_uri(
            self._api._url_to_did_rkey(list_url), BlueskyConstants.list
        )

        for row in track(
            self._moderationDb["to_be_added"].rows,
            total=self._moderationDb["to_be_added"].count,
            show_speed=False,
        ):
            try:
                self._moderationDb["added"].get(row["subject"])
            except sqlite_utils.db.NotFoundError:
                self._limiter.try_acquire("Add to moderation list")
                self._api.add_item_to_list(list_uri, row["subject"])

                self._moderationDb["added"].insert(
                    {
                        "subject": row["subject"],
                        "handle": row["handle"],
                        "source": row["source"],
                        "action": row["action"],
                        "list_url": list_url,  # Technically speaking, we don't support adding the same DID to multiple block lists. Need a compound PK for that.
                    },
                    pk="subject",
                    alter=True,
                )

                self._moderationDb["to_be_added"].delete(row["subject"])
            else:
                print(
                    f"{row['subject']} (handle: {row['handle']}) already added to list, ignoring."
                )
                self._moderationDb["to_be_added"].delete(row["subject"])


if __name__ == "__main__":
    auto_cli(Moderation)
