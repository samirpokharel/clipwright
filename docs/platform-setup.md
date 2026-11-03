# Platform setup: credentials, audits and every error we hit

This guide comes from a real setup of the `ojastra_mind` brand in November 2026. Every step is one that was done, and every error box below is one that actually appeared, with its cause and fix. Follow it in order:

| Order | What | Time | Why first |
|---|---|---|---|
| 0 | [Secrets folder and keys file](#0-the-secrets-folder) | 2 min | Every connect reads it |
| 1 | [A small website for your policies](#1-a-policy-website-github-pages) | 15 min | TikTok and Google refuse `github.com` links |
| 2 | [Meta: Facebook + Instagram](#2-meta-facebook-page--instagram) | ~1 hour | Posts publicly the same day, no review |
| 3 | [Google: YouTube](#3-google-youtube) | ~1 hour plus the audit form | Audit takes 1–3 weeks, so start it early |
| 4 | [TikTok](#4-tiktok) | ~1 hour plus a demo video | Audit takes weeks; needs the review page's TikTok controls |
| 5 | [Check everything works](#5-first-real-posts) | 15 min | First live post per platform, watched by hand |
| | [Error index](#error-index) | | Every error message → section |

**Golden rules learned the hard way**
1. **Use the same app name everywhere** (we use **Clipwright**). Reviewers compare the name on the consent screen, on the audit form and on your website. Our first try had "clipright" on Google and "clipright-content-management" on TikTok; fix it before any review.
2. **Policy links must be on a site you can prove you own.** `github.com/...` links are rejected as "not verified" by TikTok, and can't be an authorised domain on Google. Use the GitHub Pages site from step 1.
3. **Blur keys in screenshots.** A client secret shown in a screenshot or chat must be reset.
4. **Don't copy a full stop with a link.** `.../yt_api_form.` with a trailing "." gives "Sorry, this page can't be found".
5. **Unsaved forms fail silently.** If a developer page says "This form has unsaved changes", nothing you changed is live yet, and connecting fails with a confusing error.

---

## 0. The secrets folder

Everything private lives in `secrets/` in the project folder, `/home/smr/_me/clipwright/secrets/`. It is git-ignored and only your user can open it (`chmod 700`, files `600`).

```
secrets/
├── apps.json                 you fill this in: one developer app per platform, shared by all brands
├── <brand>/google.json       written by ./post connect <brand> google
├── <brand>/meta.json         written by ./post connect <brand> meta
├── <brand>/tiktok.json       written by ./post connect <brand> tiktok
└── youtube-cookies.txt       optional, for downloading sources past YouTube's bot check
```

`secrets/apps.json` (replace every `PASTE_...`; platforms you haven't set up can stay as placeholders):
```json
{
  "google": {"client_id": "PASTE_GOOGLE_CLIENT_ID", "client_secret": "PASTE_GOOGLE_CLIENT_SECRET"},
  "tiktok": {"client_key": "PASTE_TIKTOK_CLIENT_KEY", "client_secret": "PASTE_TIKTOK_CLIENT_SECRET"},
  "meta":   {"app_id": "PASTE_META_APP_ID", "app_secret": "PASTE_META_APP_SECRET",
             "graph_version": "v23.0", "config_id": "PASTE_META_CONFIGURATION_ID"}
}
```

**Redirect URIs** (what each developer app must have registered, exactly):

| Provider | Register | Notes |
|---|---|---|
| Google | nothing (Desktop clients allow any loopback) | Clipwright uses `http://localhost:8765/callback` |
| Meta | `http://localhost:8765/callback` | Allowed in development mode |
| TikTok | `http://127.0.0.1:8765/callback` | TikTok's form rejected `localhost` for us |

To use a different one, add `"redirect_uri": "..."` to that provider in `apps.json`. It must match what's registered character for character.

---

## 1. A policy website (GitHub Pages)

TikTok requires Terms and Privacy URLs **you have verified you own**, and Google's consent-screen Branding only accepts links on an **authorised domain**. A GitHub repo link (`github.com/you/repo/blob/main/PRIVACY.md`) fails both: you can't verify ownership of `github.com`. A free GitHub Pages site at `https://<you>.github.io/clipwright/` passes both.

Ours: <https://samirpokharel.github.io/clipwright/> with `/privacy/` and `/terms/`, built from `PRIVACY.md` and `TERMS.md` in the repo.

### 1.1 Build and publish it
The site is a separate `gh-pages` branch with three HTML pages (made from the Markdown policies with `pandoc`), a `style.css` and an empty `.nojekyll`. Run these **in your own terminal, one at a time**, from the site folder:
```bash
git add -A && git commit -qm "Clipwright site: home, privacy policy, terms"
git push git@github.com:<you>/clipwright.git gh-pages
gh api -X POST repos/<you>/clipwright/pages -f "source[branch]=gh-pages" -f "source[path]=/"
```
- The first build takes **1–2 minutes**. Until then every URL says *"Site not found · GitHub Pages"*. Wait; don't change anything.
- *"The gh-pages branch must exist before GitHub Pages can be built (HTTP 422)"* means the push didn't happen. In our case the commands were pasted with a leading `!`, which only works inside the Claude Code prompt. In a normal terminal, type them without `!`, and run the push before the `gh api` line.
- Later updates are just commit + push to `gh-pages`. GitHub republishes in about 40 seconds.

### 1.2 What the policies must say (reviewers check)
- **Privacy:** which scopes per platform and why; what is stored and where (locally, owner-only files); that nothing is sold or shared; **how to delete data**; **how to revoke access** (with the Google link `myaccount.google.com/connections`); a link to the Google Privacy Policy; a TikTok section (`user.info.basic`, `video.publish`); a contact email.
- **Terms:** the sentence *"By using Clipwright, you agree to be bound by the YouTube Terms of Service"* with a link. YouTube's developer policies require it.
- **Home page:** what the tool is, links to both policies, *"Uses YouTube API Services"*, and a contact email.
- **Only claim what the code does.** We removed a "deleted after 30 days" line because nothing enforces it. A policy that doesn't match the app is grounds for rejection.

### 1.3 Verification files
Platforms prove ownership by asking you to put a file on the site:
- **TikTok:** *URL prefix* → a file like `tiktokXXXXXXXX.txt` containing `tiktok-developers-site-verification=XXXXXXXX`. Copy it to the **root** of the `gh-pages` branch, push, wait about 40 s, check `https://<you>.github.io/clipwright/tiktokXXXXXXXX.txt` shows the line, **then** click Verify.
- **Google Search Console** (if Branding asks you to verify the domain): choose *URL prefix* `https://<you>.github.io/clipwright/`, download the HTML file, and add it the same way.

---

## 2. Meta: Facebook Page + Instagram

Status in our setup: connected and working on the first try (a Reel uploaded and scheduled).

### 2.0 Before you start
- **A Facebook Page** for the brand, and your personal Facebook account must have full control of it.
- **An Instagram professional account** (Business or Creator). Instagram app → Settings → *Account type and tools* → *Switch to professional account*.
- **Link Instagram to the Page:** Page → Settings → *Linked accounts* → Instagram → Connect. The API only publishes to Instagram accounts linked to a Page.

### 2.1 Create the app
1. <https://developers.facebook.com/apps> → **Create app**.
2. **App name:** `Clipwright`. Meta refuses names containing "Facebook", "Instagram", "Meta" or "FB".
3. **Use cases:** **"Manage everything on your Page"**. It adds `business_management`, `pages_show_list` and `public_profile`, which can't be removed.
4. Add **"Manage messaging & content on Instagram"** → choose **"API setup with Facebook login"**, *not* "Instagram login". Clipwright uses Page tokens and resumable upload, which need Facebook Login for Business.
   - Do **not** add *"Authenticate and request data from users with Facebook Login"*: it is incompatible with the Page use case.
   - If the dashboard won't combine them, create the app as **Other → Business** and add **Facebook Login for Business** and **Instagram**.
5. **Business portfolio:** optional. Connect it if your Page already belongs to one.

### 2.2 Permissions
Each use case → **Customize** → **Permissions** → **Add**:

| Permission | Why |
|---|---|
| `pages_show_list`, `business_management` | List your Pages (automatic) |
| `pages_read_engagement` | Page token; required for Reels and IG publishing |
| `pages_manage_posts` | Publish and schedule Facebook Reels |
| `instagram_basic` | Read the linked Instagram account id |
| `instagram_content_publish` | Publish Instagram Reels |
| `ads_management`, `ads_read` | **Only if** the Page is in a business portfolio where you have a Business Manager role |

Leave out messaging, comments and insights.

### 2.3 Login settings and configuration
1. **Facebook Login for Business → Settings:** Client OAuth login **on**, Web OAuth login **on**, Valid OAuth Redirect URIs `http://localhost:8765/callback`.
2. **Facebook Login for Business → Configurations → Create configuration:** token type **User access token**, expiration **Never** (or the longest offered), assets **Pages + Instagram accounts**, permissions from 2.2. Copy the **Configuration ID** into `apps.json` → `meta.config_id`.
3. **App settings → Basic:** copy **App ID** and **App Secret** into `apps.json` → `meta`.
4. **Stay in Development mode.** It can post to Pages you admin, with no App Review.

### 2.4 Connect
```bash
./post connect ojastra_mind meta
```
Tick the brand's Page **and** its Instagram account on the consent screen. It prints the Page id and IG id; put them in `brands/<brand>/accounts.json`:
```json
"facebook":  {"page_id": "1234567890123456"},
"instagram": {"ig_user_id": "17841400000000000"}
```
Limits: Facebook Reels 3–90 s (the validator checks); Instagram 50–100 API posts per 24 h; complete *Page Publishing Authorization* first if your Page asks for it.

---

## 3. Google: YouTube

Status in our setup: connected (channel "Ojastra"), first upload scheduled successfully, audit submitted.

### 3.1 Project, API and client
1. <https://console.cloud.google.com> → **New project** (name it `clipwright`).
2. **APIs & Services → Library → "YouTube Data API v3" → Enable.**
3. **Google Auth Platform** (formerly "OAuth consent screen") → **Get started**: app name **Clipwright**, support email, **Audience: External**, contact email.
4. **Data access → Add scopes:** `.../auth/youtube.upload` and `.../auth/youtube.readonly`. Not the broad `.../auth/youtube`.
5. **Clients → Create client → Desktop app.** Copy the client ID and secret into `apps.json` → `google`.

### 3.2 Test users (or you get "Access blocked")
> ❌ **"Access blocked: clipright has not completed the Google verification process … can only be accessed by developer-approved testers. Error 403: access_denied"**

**Cause:** the app is in *Testing* and your Google account isn't a test user.
**Fix:** Google Auth Platform → **Audience → Test users → + Add users** → the Google account that manages the channel → Save. Then press Ctrl+C on the old connect if it's still waiting, and run it again.

### 3.3 Branding (do this before the audit)
Google Auth Platform → **Branding**:
- **App name: Clipwright.** It must match the audit form. Ours said "clipright".
- **App logo:** optional. You can use `~/Pictures/clipwright-audit/clipwright-app-icon.png`.
- **Home page:** `https://<you>.github.io/clipwright/`
- **Privacy policy:** `https://<you>.github.io/clipwright/privacy/`
- **Terms of service:** `https://<you>.github.io/clipwright/terms/`
- **Authorized domains:** `<you>.github.io`. Verify it in Search Console if asked ([1.3](#13-verification-files)).

Without these, the consent screen shows *"Learn why you're not seeing links to clipright's Privacy Policy or Terms of Service"*, and the reviewer sees that.

### 3.4 Connect
```bash
./post connect ojastra_mind google
```
You'll see "Google hasn't verified this app": click **Continue** (or Advanced → Go to Clipwright) and allow both permissions. It prints `ojastra_mind: connected YouTube channel Ojastra`.

### 3.5 Publish the app (or the login dies after 7 days)
While the app is in **Testing**, Google revokes the refresh token **after 7 days** and every upload then fails. After the first upload works: **Audience → Publish app → In production**. This is not the audit. The "unverified app" warning stays until the audit passes, and that's fine for your own accounts.

### 3.6 What uploads look like before the audit
Our first upload (`./post publish-due`) printed `scheduled #1 ojastra_mind/youtube … https://youtube.com/shorts/…`, and YouTube Studio showed **"Schedule as public, Nov 4, 9:00 AM, video is private before publishing"**. Uploads from unaudited projects created after July 2020 can be locked **private** at publish time, and a locked video can't be unlocked later (only re-uploaded). Check one scheduled video after its time to see whether your project is affected.

Quota: `videos.insert` has its **own bucket of 100 uploads per day** (1 unit each), separate from the 10,000 units for everything else. Clipwright counts uploads and stops before the limit.

### 3.7 The audit form: the answers that went in
Form: **<https://support.google.com/youtube/contact/yt_api_form>** (nothing after `form`). If it says "page can't be found", check for a trailing "." and that you're signed into the Cloud project's account (`?authuser=1`).

| Section / field | Answer |
|---|---|
| 1. Request type | **Complete a compliance audit to request for additional quota** (also lifts the private lock) |
| 2. Organization | Your name or the channel brand; website = your channel URL; Nepal |
| 2. Describe your work | *"I am an individual content creator… The API client, Clipwright, is an internal tool that only I use, on my own computer… not sold, licensed or offered to anyone else, and does not access any other user's YouTube data."* |
| 2. Target audience | ✅ Individual Content Creators ✅ Internal Users (nothing else) |
| 3. How does it monetize | ✅ **Free service only**. ❌ Don't tick "Advertising displayed on pages…": that's about ads in *your tool*, not YouTube's ads on your videos |
| 3. Sell ads in the YouTube player? | **Not applicable**. Answering "Yes" says you sell ads inside YouTube's player without approval, which is a likely denial |
| 3. Google representative | No |
| 4. API client name / contains "YouTube" | Clipwright / **No** |
| 4. Primary access URL | `https://<you>.github.io/clipwright/` (or the repo) |
| 4. Privacy policy / Terms | the GitHub Pages URLs |
| 4. Publicly accessible? | **No** |
| 5. How many project numbers | **1** (the dropdown defaulted to 10 for us; change it) |
| 5. Project number | Cloud Console → Dashboard → *Project number* (digits, not the ID) |
| 5. Use case category | ✅ **Video Uploading & Account Management** only. "Tools for Creators" means growth, comments and earnings; "Internal Company Tool" adds required dashboard screenshots |
| 5. Users sign in with Google? | Yes |
| 5. Expected volume | Fewer than 1,000 requests per day |
| 5. Endpoints | ✅ `youtube.videos.insert` ✅ `youtube.channels.list` |
| 5. Total quota | **No change / Default** |
| 5. videos.insert per-day quota | **100**, with the justification: own channels only, about 3–10 uploads a day, no increase needed, audit is to lift the private-only restriction |

**Evidence uploads** (rules: JPEG/PNG or PDF, **one file per box, under 10 MB**, at least **1280×720**, readable, address bar visible):

| Box | File (in `~/Pictures/clipwright-audit/`) |
|---|---|
| Privacy Policy screenshots | the privacy page showing scopes, deletion and revocation, Google Privacy Policy link |
| Homepage screenshot | the home page with the "Uses YouTube API Services" line and policy links |
| Terms of Service documentation | the terms page with the YouTube ToS sentence |
| Conditional evidence (OAuth + upload) | `clipwright-oauth-and-upload-flow.png`: six captioned panels (consent with scopes → connected channel → review/approve → `publish-due` upload → Studio scheduled → revoke "Delete all") combined into **one** image, because the box takes one file |
| Architecture diagram | `clipwright-architecture-diagram.png` |
| User flow diagram | `clipwright-user-flow-diagram.png` |
| Other supporting materials | `clipwright-supporting-materials.pdf`: links and the **complete upload code** (`youtube.py`, `auth.py`, `http.py`, `base.py`). The form says static screenshots aren't enough for upload tools: give a complete working script **or** a screencast |

Gotchas: our first combined image was 1064 px wide (below the 1280 minimum) and had to be rebuilt. For the revocation screenshot, open the "Delete all" dialog but **don't click Confirm**, or you must reconnect. Use a clip you own or have permission for anywhere a reviewer will look.

After submitting ("Thank you for submitting the YouTube API Services Form"), watch the Cloud project owner's email for follow-up questions. When approved, set `"audited": true` under `youtube` in each brand's `accounts.json`.

---

## 4. TikTok

Status in our setup: Sandbox configured and Login Kit reaching the consent step. The audit is waiting on the review page's TikTok posting controls (see 4.6).

### 4.1 Basic information (Production app)
| Field | What worked |
|---|---|
| App icon | 1024×1024 PNG, up to 5 MB: `~/Pictures/clipwright-audit/clipwright-app-icon.png` |
| App name | **Clipwright** (not "clipright-content-management") |
| Category | Productivity |
| Description (≤120) | `Personal tool to schedule and post my own short videos to my TikTok account after I review and approve each one.`. Ours accidentally kept a "(120 max)" note; it's shown to users, so check it |
| Terms of Service URL | `https://<you>.github.io/clipwright/terms/` |
| Privacy Policy URL | `https://<you>.github.io/clipwright/privacy/` |
| Platforms | ✅ **Desktop** only |
| Web/Desktop URL | `https://<you>.github.io/clipwright/` |

> ❌ **"This URL is not verified. Verify URL properties"** under each URL
**Cause:** TikTok needs proof you own the site. **Fix:** Verify URL properties → **URL prefix** (not Domain, which needs DNS you can't set on `github.io`) → `https://<you>.github.io/clipwright/` → download the signature file → put it on the site ([1.3](#13-verification-files)) → **Verify**. All three URLs share the prefix, so one verification covers them.

> ❌ **"Enter a valid URL beginning with…"** → the field is cut off or has a stray space. Retype it.

### 4.2 Sandbox (test before the audit)
The top switch → **Sandbox → Create Sandbox** (copy settings from Production). The Sandbox has **its own products, scopes, redirect and keys**, so set them inside it.

1. **Login Kit → the `Desktop*` tab** (not Web):
   - Redirect URI: **`http://127.0.0.1:8765/callback`**
   - Leave the **Web** tab off. Don't click "Configure for Web".

   > ❌ **"Redirect Uri host should be {localhost}:{port} or {127.0.0.1}:{port}"** (red box at the top)
   **Cause:** the form rejected the redirect entry, so **none** of the Sandbox changes saved. **Fix:** retype `http://127.0.0.1:8765/callback` by hand in the Desktop tab, clear any half-filled entry on other tabs, then **Apply changes**. The "This form has unsaved changes" bar must disappear.
2. **Content Posting API:** turn **Direct Post on**. Skip *Verify domains*: that's only for `pull_by_url`, and Clipwright uploads the file (`push_by_file`).
3. **Scopes:** `user.info.basic`, `video.publish`. `video.upload` shows "Included in Content Posting API" and can't be removed; that's fine, because Clipwright only requests the first two.
4. **Apply changes.**
5. **Target Users → Add account** → log in with the TikTok account you'll post to → accept.
6. **Credentials:** copy the **Sandbox** client key (starts with `sb`) and secret into `apps.json` → `tiktok`. They differ from Production; swap to Production keys after approval.
7. **Set the TikTok account to Private** (Settings and privacy → Privacy → Private account). Unaudited apps can only post to private accounts, and every post is `SELF_ONLY`.

### 4.3 Connect
```bash
./post connect ojastra_mind tiktok
```
> ❌ TikTok page **"Something went wrong… correct the following: client_key"**
**Cause:** the Sandbox changes were never saved (the redirect error above), so TikTok didn't recognise the key for Login Kit. It can also be a key from a different Sandbox, or Production vs Sandbox mixed up. **Fix:** clear the redirect error, Apply changes, wait 2–5 minutes, retry.

> ❌ **"…correct the following: redirect_uri"**, URL ends in `error=invalid_request&error_type=redirect_uri`
**Cause:** the redirect Clipwright sent doesn't match the registered one exactly (we registered `127.0.0.1`, and the code sent `localhost`). **Fix:** the code now sends `http://127.0.0.1:8765/callback` for TikTok. If you registered `localhost`, add `"redirect_uri": "http://localhost:8765/callback"` to `tiktok` in `apps.json`.

The error page's URL always ends in `error_type=…`, which names the field TikTok objects to. Paste that URL when asking for help.

### 4.4 App review: the explanation text (≤1000)
> Clipwright is a desktop tool I (the account owner) use to post my own short videos to my own TikTok account.
>
> Login Kit (user.info.basic): I run "connect", Login Kit for Desktop opens in the browser, I authorize, and TikTok redirects to localhost. user.info.basic shows which account is connected (display name and avatar) on the posting screen.
>
> Content Posting API, Direct Post (video.publish): on the local review page I watch each video and edit its caption. The app calls creator_info and shows my TikTok name, a privacy level I must choose (no default) from the returned options, comment/duet/stitch toggles (disabled if the account turned them off), the commercial content disclosure, and TikTok's Music Usage Confirmation. Nothing posts until I click Approve; at the scheduled time it calls video/init (FILE_UPLOAD), uploads the file and polls status/fetch until the post completes.
>
> No other users' data is accessed or stored.

### 4.5 Demo video (mp4/mov, up to 5 files, 50 MB each)
Record in the **Sandbox**, showing: the app opening (the review page), `./post connect` → TikTok login and consent with both scopes → the posting controls with your choices → Approve → `./post publish-due` → the post on the (private) profile. Every product and scope you selected must appear on screen.

### 4.6 Don't submit until the posting controls exist
TikTok checks the posting screen for: creator nickname and avatar, a privacy dropdown **with no default**, comment/duet/stitch toggles, a commercial-content disclosure, and the music-usage consent line. Clipwright's review page doesn't have these yet; adding them is the next code change. A demo that doesn't match the explanation gets rejected, and each rejection costs weeks. When approved: switch `apps.json` to the Production keys, set `"audited": true` under `tiktok` in `accounts.json`, and make the account public again.

---

## 5. First real posts
```bash
./post review                   # approve one clip; tick only the platform you're testing
./post publish-due --dry-run    # shows what would upload
./post publish-due              # uploads; prints status and link per platform
./post queue                    # status, link or last error for everything
```
Our first live run printed:
```
scheduled   #1 ojastra_mind/youtube  kKvK2foOTJM @ 2026-11-04T03:15:00Z https://youtube.com/shorts/…
scheduled   #3 ojastra_mind/facebook kKvK2foOTJM @ 2026-11-04T03:55:00Z https://www.facebook.com/reel/…
```
- **YouTube and Facebook** are handed over up to 48 hours early and publish themselves at the slot. **Instagram and TikTok** upload at the slot time, only while `publish-due` runs (install the timers: `scripts/install-timers.sh`).
- **Approving ticks every platform by default.** Untick the ones you don't want. Facebook goes **public** at its slot. To stop one: `./post cancel <id>` for pending rows; Meta Business Suite → Scheduled for a Facebook Reel already handed over; YouTube Studio for a YouTube video.
- The connect flow waits 5 minutes for the browser. If it times out, run it again.

---

## Error index

| Message | Platform | Section |
|---|---|---|
| "Sorry, this page can't be found" (audit form) | Google | [3.7](#37-the-audit-form-the-answers-that-went-in): trailing "." or wrong account |
| "Access blocked: … has not completed the Google verification process. Error 403: access_denied" | Google | [3.2](#32-test-users-or-you-get-access-blocked) |
| "Learn why you're not seeing links to …'s Privacy Policy or Terms" | Google | [3.3](#33-branding-do-this-before-the-audit) |
| Uploads stop working after about a week | Google | [3.5](#35-publish-the-app-or-the-login-dies-after-7-days) |
| "This URL is not verified. Verify URL properties" | TikTok | [4.1](#41-basic-information-production-app) |
| "Redirect Uri host should be {localhost}:{port} or {127.0.0.1}:{port}" | TikTok | [4.2](#42-sandbox-test-before-the-audit) |
| "Something went wrong … client_key" | TikTok | [4.3](#43-connect) |
| "Something went wrong … redirect_uri" / `error_type=redirect_uri` | TikTok | [4.3](#43-connect) |
| "Site not found · GitHub Pages" | GitHub | [1.1](#11-build-and-publish-it): wait 1–2 min |
| "The gh-pages branch must exist before GitHub Pages can be built (HTTP 422)" | GitHub | [1.1](#11-build-and-publish-it) |
| "<brand> is not connected to <provider>: run ./post connect …" | Clipwright | run that connect |
| "Sign in to confirm you're not a bot" (fetching sources) | YouTube | README → YouTube bot check (cookies) |

## Sources
- Meta: [Pages use case](https://developers.facebook.com/documentation/development/create-an-app/pages-use-case), [Facebook Login for Business](https://developers.facebook.com/docs/facebook-login/facebook-login-for-business), [Instagram content publishing](https://developers.facebook.com/docs/instagram-platform/content-publishing)
- Google: [YouTube Data API quota costs](https://developers.google.com/youtube/v3/determine_quota_cost), [audit form](https://support.google.com/youtube/contact/yt_api_form)
- TikTok: [Login Kit for Desktop](https://developers.tiktok.com/doc/login-kit-desktop), [Content Posting API](https://developers.tiktok.com/doc/content-posting-api-get-started)
