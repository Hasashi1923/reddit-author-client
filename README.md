# reddit_author_client

A small Reddit Data API client for one author account. It posts occasional original, sourced history posts, reads subreddit rules before posting, and replies to comments on its own posts. Every post and reply needs the author to type "yes" before it is submitted.

It never votes, sends private messages, scrapes or stores other users' data, or posts the same text in more than one subreddit. It refuses a second post within 24 hours.

Scopes: `identity submit read edit`. OAuth web-app flow; credentials live in `~/.config/reddit_author_client/` and are never committed.

License: MIT
