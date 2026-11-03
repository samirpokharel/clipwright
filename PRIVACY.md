# Clipwright Privacy Policy

*Last updated: 4 November 2026*

Clipwright is a personal publishing tool. Its operator (the "operator") runs it on their own computer to upload short videos to the operator's own YouTube channels and other social media accounts. It is not offered to the public, and nobody else uses it.

## What data Clipwright accesses
Clipwright uses the YouTube API Services. When the operator connects a YouTube channel, Clipwright requests these Google OAuth scopes:

- `https://www.googleapis.com/auth/youtube.upload`: to upload videos the operator has approved to the operator's own channel.
- `https://www.googleapis.com/auth/youtube.readonly`: only to read the connected channel's ID and name, so the operator can see which channel is connected.

Clipwright calls `videos.insert` and `channels.list` (for the authenticated user's own channel). It does **not** access, collect or analyse any other YouTube user's data, comments, subscribers or analytics.

## What data Clipwright stores
Everything is stored locally, on the operator's own computer:

- **OAuth tokens** (access and refresh tokens) for the operator's own accounts, in a file only the operator's user account can read. They are never sent anywhere except to Google's OAuth servers, to refresh access.
- **Upload records**: the ID, URL and status of each video Clipwright uploaded, so that it never uploads the same video twice.
- **The channel ID and name** of each connected channel.

Clipwright has no servers. It does not send, sell, share or transfer any YouTube API data to anyone, and it uses none of it for advertising.

## How long data is kept
Tokens are kept until the operator disconnects the account or revokes access. Upload records are kept as a local history, and the operator can delete them at any time by deleting the local database file.

## Deleting your data
- **Revoke access:** remove Clipwright at [Google Account → Security → Third-party apps with account access](https://myaccount.google.com/connections). Its tokens stop working immediately.
- **Delete local data:** delete the token file (`secrets/<brand>/google.json`) and the upload records (`queue.db`). Clipwright keeps no other copy, and there is no server-side copy to delete.
- **Stored API data** (the channel ID and name, and the IDs of its own uploads) belongs only to the operator's own connected channels, and is deleted with the files above.

## How to revoke access
Access can be revoked at any time at [Google Account → Security → Third-party apps with account access](https://myaccount.google.com/connections), or by deleting the local token file. After revoking, Clipwright can no longer access the account.

## Google's privacy policy
Clipwright uses YouTube API Services. By using it, the operator is bound by the [YouTube Terms of Service](https://www.youtube.com/t/terms). Google's handling of data is described in the [Google Privacy Policy](https://policies.google.com/privacy).

## Other platforms
Clipwright can also publish to TikTok, Facebook and Instagram accounts that belong to the operator, through those platforms' official APIs. The same rules apply: tokens are stored locally, only the operator's own accounts are used, and no data is shared or sold.

## Contact
Questions about this policy: thevoidsmr@gmail.com
