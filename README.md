# bluesky-moderation-tools

**This tool is still in development. This tool requires understanding of how to use a terminal.**

A CLI application for effectively managing moderation lists.

## Features
- Add all users that liked a post to a moderation list,
- Queue accounts to be added to your moderation list,
- Automatically skip users added to a particular moderation list,
- Rate limits itself so that you can continue to use Bluesky,
- Stores list adds with the source.

## Installation
Recommendation: use `uv`. Should work with pip or poetry, but untested.
```
uv sync
```

### Usage
```
uv run moderation_tools.py --help
```

- This tools works as a two-step process.
- First, run the process with `add_likes_to_be_processed <POST_URL>`. This will populate the database. You can do this for as many posts as you want.
- Then, run `process_list <LIST_URL>` to add the likes in the database to the list.
