import argparse
from dataclasses import dataclass, field
import datetime
from typing import Optional

from atproto import Client, IdResolver, models
import atproto_client
import atproto_client.models.app
import atproto_client.models.app.bsky
import atproto_client.models.app.bsky.graph
import atproto_client.models.app.bsky.graph.listitem


@dataclass
class DID_RKey:
    """Stores a DID/record key combination."""

    did: str
    rkey: str


@dataclass
class constants:
    """Some useful constants."""

    post = "app.bsky.feed.post"
    list = "app.bsky.graph.list"


@dataclass
class BlueskyAPI:
    """Class for interacting with the Bluesky API."""

    handle: str
    app_password: str

    _client: Client = field(default_factory=Client)
    _resolver: IdResolver = field(default_factory=IdResolver)

    def __post_init__(self):
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
        did_rkey = self._did_rkey_to_atproto_uri(self._url_to_did_rkey(url), constants.post)
        page = self._client.get_likes(did_rkey)
        
        likes = page.likes

        while page.cursor and all:
            page = self._client.get_likes(did_rkey, cursor=page.cursor)
            likes.append(page.likes)

        return likes
    
    def add_item_to_list(self, repo_uri: str, record_did: str) -> models.AppBskyGraphListitem.CreateRecordResponse:
        record = atproto_client.models.app.bsky.graph.listitem.Record(
            created_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            subject=record_did,
            list=repo_uri
        )

        return self._client.app.bsky.graph.listitem.create(
            repo=self._client.me.did,
            record=record       
        )

if __name__ == "__main__":
    # Temporary development CLI interface.
    parser = argparse.ArgumentParser()
    parser.add_argument("handle")
    parser.add_argument("app_password")
    parser.add_argument("post_url")
    parser.add_argument("list_url")
    args = parser.parse_args()

    api = BlueskyAPI(args.handle, args.app_password)

    list_uri = api._did_rkey_to_atproto_uri(api._url_to_did_rkey(args.list_url), "app.bsky.graph.list")
    test = api.fetch_likes(args.post_url, all=False)[1]
    test_did = test.actor.did
    api.add_item_to_list(list_uri, test_did)
