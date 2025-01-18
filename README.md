# bluesky-moderation-tools
A CLI application for effectively managing moderation lists.

## Planned
- Ability to queue additions, with an offline cache (SQLite works for this),
- Cache of already added users for a particular list - this should reduce rate limit overheads with duplicates,
- Ability to generate an initial cache from the list as it is.
- Support post likes, and user follows,
- Have a limit lower than the rate limit (to allow actual use of Bluesky in the meantime),
- Allow exclusions to be manually specified,
- Maintain a list of sources (i.e. allow you to remember what informed your blocks)
