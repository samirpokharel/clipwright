# RB-001 Create the three channels

**Trigger:** the handles are decided (docs/DECISIONS.md, 3 November 2026) and clips are packaged.
**Outcome:** one YouTube channel, one Instagram account, one TikTok account and one Facebook Page per domain, with the same handle on all four, bios filled, avatar and banner set, and the result written to docs/DECISIONS.md.

Do the four platforms for one domain, then the next domain. Instagram and Facebook availability is not verified; if a handle is taken on either, stop and pick the fallback for all four platforms of that domain before creating anything else.

## The fields

| Domain | Handle | Display name | Fallback handle |
|---|---|---|---|
| mythology | `shlokaclips` | Shloka Clips | `shlokacuts` (free on YouTube and TikTok on 3 November 2026) |
| tech | `gradientcuts` | Gradient Cuts | `kernelcuts` (free on YouTube and TikTok on 3 November 2026) |
| health | `vagusclips` | Vagus Clips | `nervecuts` (free on YouTube and TikTok on 3 November 2026) |

Bios. YouTube takes up to 1000 characters, Instagram 150, Facebook 101 (the Page intro), TikTok 80. Paste as written. The Facebook intro is the Instagram bio shortened; the About section of the Page takes the YouTube bio.

**Shloka Clips**
- YouTube: Short clips from talks and explainers on Hindu scripture and epics. Every clip names its source text and notes where versions differ. Clips are posted with the creator's permission and credit the original video.
- Instagram: Short, sourced clips on Hindu scripture and epics. Every clip names its text. Posted with permission.
- Facebook: Sourced clips on Hindu scripture and epics. Every clip names its text. Posted with permission.
- TikTok: Sourced clips on Hindu scripture and epics. Every clip names its text.

**Gradient Cuts**
- YouTube: Short clips from AI, software and startup interviews, cut to the claim. Every number and date is checked against the transcript, and the speaker is named on screen. Clips are posted with the creator's permission and credit the original episode.
- Instagram: AI and startup interviews, cut to the claim. Numbers checked, speaker named. Posted with permission.
- Facebook: AI and startup interviews, cut to the claim. Speaker named. Posted with permission.
- TikTok: AI and startup interviews, cut to the claim. Speaker named, numbers checked.

**Vagus Clips**
- YouTube: Short clips from health and neuroscience podcasts. Each clip keeps the question with the answer and names the speaker and their credential on screen. General information, not medical advice. Clips are posted with the creator's permission and credit the original episode.
- Instagram: Health and neuroscience podcast clips. Speaker and credential named. General information, not medical advice.
- Facebook: Health and neuroscience clips, speaker and credential named. Not medical advice.
- TikTok: Health podcast clips, speaker named. Not medical advice.

## Steps

1. One Google account owns all three YouTube channels. Each extra channel is a Brand Account under that Google account, so no new email is needed. Use a recovery phone you control. Record the owning account in docs/DECISIONS.md.
2. YouTube, once per domain: open youtube.com signed in, click the avatar, then Switch account, then View all channels, then Create a channel. Enter the display name, the handle and the avatar from out/brand/<handle>/, then Create. Then in studio.youtube.com, Customization: paste the YouTube bio and upload the banner from out/brand/<handle>/. Under Settings, set the country and the default upload visibility to Private. Before creating the next one, switch back to the main account: a Brand Account cannot hold a second channel.
   TikTok has no equivalent: each account needs its own email or phone, and a Gmail alias such as you+shlokaclips@gmail.com works for sign-up. Facebook has Pages (step 3) and Instagram has added accounts (step 4), both under the profile you already have.
3. Facebook: from your own profile, Pages, Create new Page. Name: the display name. Category: Media/News Company or Entertainment website. Paste the Facebook intro, then in About paste the YouTube bio and the YouTube link. Set the username to the handle under Settings, Page setup. If Facebook reports it as taken, use the fallback for all four platforms of that domain and write that down. Upload the avatar and the banner from out/brand/<handle>/ (Facebook crops the cover to 820 by 312 on desktop; the banner's safe area still reads). Do not create a second personal profile: Meta allows one per person.
4. Instagram: in the app, Settings, Add account, Create new account. Choose the handle. If Instagram reports it as taken, use the fallback for all four platforms of that domain and write that down. Give it the channel's Gmail alias when asked. Switch to a Professional account (Creator), paste the Instagram bio, add the YouTube channel link, upload the avatar. In Accounts Center, link this account to the Facebook Page of the same domain so a Reel can go to both.
5. TikTok: sign up with the same Gmail alias, not with Continue with Google (one Google login maps to one TikTok account). Set the username to the handle and the display name, paste the TikTok bio, upload the avatar. Add the YouTube link.
6. On each platform enable two-factor authentication. Store the credentials in the password manager, never in the repo.
7. Write one entry in docs/DECISIONS.md: date, the handles as registered on each platform, the owning Google account and Meta profile, and any fallback used. Commit it.
8. Do not upload anything yet. RB-002 starts only when the creator's permission is recorded.
