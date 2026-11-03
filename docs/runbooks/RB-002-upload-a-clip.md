# RB-002 Upload one clip

**Trigger:** a packaged clip whose source has permission recorded as granted (or the source is CC BY), and the clip is marked OK in the Clips tab.
**Outcome:** the clip is live on YouTube Shorts, Instagram Reels, Facebook Reels and TikTok with the packaged text, and the tracker records where it was posted.

Never upload a clip from a standard-licence source without the creator's written permission. The three overnight sources (Cogito, The Diary Of A CEO, Rich Roll) are standard licence; the requests are in out/permissions/.

## Steps

1. Open `out/<job>/upload/<NN_slug>/`. It holds `video.mp4`, `cover.jpg`, `post.txt` and `post.json`. Read `post.txt` once: the title, the description with the source credit and the domain disclaimer, the hashtags, and the short caption for TikTok and Reels.
2. YouTube: Studio, Create, Upload `video.mp4`. Title from `post.txt`. Description: the full description block including the source line. Set "Altered or synthetic content" to no. Audience: not made for kids. Visibility: Public. The clip is 1080 by 1920 and at most 90 s, so it lands as a Short. Add `cover.jpg` as the thumbnail if the account can set one.
3. Instagram: Reel, pick `video.mp4`, cover from `cover.jpg`. Caption: the short caption from `post.txt` plus the source line from the description. Before sharing, turn on "Share to Facebook" so the Reel also lands on the linked Page. Share.
4. Facebook: if the Reel did not cross-post (the toggle was off or the Page is not linked), open the Page, Reel, pick `video.mp4`, same caption and cover. Publish.
5. TikTok: Upload `video.mp4`, caption: the short caption plus the source line. Cover from `cover.jpg`. Post.
6. Record each post URL in the tracker so the Clips tab shows it: in the Clips tab, mark the clip OK if not already, and note the four URLs in the clip's note field. If the UI gains a posted field, use that instead.
7. Check each post once after an hour: plays, no copyright claim, captions readable. A claim means stop, take the clip down, and reread the permission. Facebook's Rights Manager and YouTube's Content ID both act on the source channel's claim, so a claim on one usually follows on the other.

## Notes

- YouTube reduces Shorts distribution for channels that mostly repost others' clips without meaningful changes (policy from October 2026, see README). Every clip here carries a commentary card, a title and captions; keep that, and keep the share of original or commentary posts up.
- One clip per channel per day is enough at the start. Post at the same local time each day.
