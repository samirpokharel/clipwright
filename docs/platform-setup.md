# Platform credentials: step-by-step

You create one developer app per platform. All your brands share it, and each brand connects its own accounts to it with `./post connect`. Everything goes into `secrets/apps.json` (git-ignored):

```json
{"google": {"client_id": "...", "client_secret": "..."},
 "tiktok": {"client_key": "...", "client_secret": "..."},
 "meta":   {"app_id": "...", "app_secret": "...", "graph_version": "v23.0", "config_id": "..."}}
```

The redirect URI is the same everywhere: `http://localhost:8765/callback`.

The developer sites rename menus often. The names below match the platforms' documentation as of November 2026. If a label differs, look for the closest match.

| | Meta (Facebook + Instagram) | Google (YouTube) | TikTok |
|---|---|---|---|
| Time to set up | about 1 hour | about 20 min | about 30 min plus a demo video |
| Posts publicly before review? | **Yes** (development mode, your own Pages) | No: private until the audit | No: private, and the account must be private |
| Review | not needed for your own accounts | YouTube API Services audit | Content Posting API audit |

---

## 1. Meta: Facebook Page + Instagram

### 1.0 Before you start
- **A Facebook Page** for the brand, and your personal Facebook account must have full control of it.
- **An Instagram professional account** (Business or Creator). Instagram app → Settings → *Account type and tools* → *Switch to professional account*.
- **Link Instagram to the Page:** Page → Settings → *Linked accounts* → Instagram → Connect. The API only publishes to Instagram accounts linked to a Page.

### 1.1 Create the app
1. Go to <https://developers.facebook.com/apps> → **Create app**.
2. **App name:** for example `Clipwright Publisher`. Meta refuses names containing "Facebook", "Instagram", "Meta" or "FB".
3. **Use cases:** choose **"Manage everything on your Page"**. It adds `business_management`, `pages_show_list` and `public_profile`, which can't be removed.
4. Add the Instagram use case **"Manage messaging & content on Instagram"**. When asked which setup, choose **"API setup with Facebook login"**, *not* "Instagram login". Clipwright uses Page tokens and resumable upload, which only work with Facebook Login for Business.
   - Do **not** add *"Authenticate and request data from users with Facebook Login"*. Meta says it is incompatible with the Page use case.
   - If the dashboard won't combine the Page and Instagram use cases, create the app with **Other → Business** type instead. Then add the products **Facebook Login for Business** and **Instagram**.
5. **Business portfolio:** you can skip this. If your Page already belongs to a business portfolio, connect that one.

### 1.2 Permissions to add
Open each use case → **Customize** → **Permissions**, and click **Add** on:

| Permission | Why |
|---|---|
| `pages_show_list` | List your Pages at connect time (added automatically) |
| `business_management` | Pages owned by a business portfolio (added automatically) |
| `pages_read_engagement` | Read the Page and its Page token; required for Reels and IG publishing |
| `pages_manage_posts` | Publish and schedule Facebook Reels |
| `instagram_basic` | Read the linked Instagram account id |
| `instagram_content_publish` | Publish Instagram Reels |
| `ads_management`, `ads_read` | **Only if** your Page is in a business portfolio where you have a Business Manager role. Meta's Instagram publishing docs require them in that case |

Leave out messaging, comments and insights permissions. You don't need them, and each one you add has to be justified if you ever go through App Review. (`read_insights` and `instagram_manage_insights` come later, for view stats.)

### 1.3 Login settings and the configuration
1. **Facebook Login for Business → Settings:**
   - *Client OAuth login*: on
   - *Web OAuth login*: on
   - *Valid OAuth Redirect URIs*: `http://localhost:8765/callback`. In development mode Meta allows `localhost` even with *Enforce HTTPS* on.
2. **Facebook Login for Business → Configurations → Create configuration:**
   - Name: `clipwright-publish`
   - Login variation: General
   - **Token type: User access token**
   - Expiration: *Never* if offered, otherwise the longest available. Clipwright trades it for Page tokens, and those don't expire.
   - **Assets:** Pages and Instagram accounts. Tick each brand's Page and IG account, or "all current and future".
   - **Permissions:** the ones from 1.2.
   - Create it, then copy the **Configuration ID** into `apps.json` → `meta.config_id`.

   With a `config_id` set, Clipwright sends it instead of a permission list, which is how Login for Business works. If you skip the configuration, Clipwright sends the permission list from 1.2. In that case, add `"extra_scopes": ["ads_management", "ads_read"]` if you need those two.

### 1.4 Copy the keys
- **App settings → Basic:** copy *App ID* and *App Secret* (click Show) into `apps.json` → `meta`.
- **Leave the app in Development mode.** In development, it can publish to Pages and IG accounts belonging to people with a role on the app. You are the admin. To add another person's brand, add them under **App roles → Roles** as a tester.
- *Live* mode and App Review are only needed to post for people with no role on the app.

### 1.5 Connect each brand
```bash
./post connect ojastra_mind meta
```
On the consent screen, tick the brand's Page and its Instagram account. It prints, for example, `Pages Ojastra Mind (1234567890, IG 17841400000000000)`. Put those ids in `brands/ojastra_mind/accounts.json`:
```json
"facebook":  {"page_id": "1234567890"},
"instagram": {"ig_user_id": "17841400000000000"}
```
Limits:
- Facebook Reels must be 3–90 seconds. The validator checks this.
- Instagram allows 50–100 API posts per 24 hours. Meta's docs give both numbers.
- If your Page requires *Page Publishing Authorization*, complete it in the Page settings first, or every post fails.

---

## 2. Google: YouTube

### 2.1 Project and API
1. Go to <https://console.cloud.google.com> → project picker → **New project**, named for example `clipwright`.
2. **APIs & Services → Library →** search **"YouTube Data API v3"** → **Enable**.

### 2.2 OAuth consent screen (Google Auth Platform)
1. **APIs & Services → OAuth consent screen** (now called *Google Auth Platform*) → **Get started**.
2. *App name* `Clipwright`, your support email, **Audience: External**, contact email → Create.
3. **Data access → Add or remove scopes**, then tick:

   | Scope | Why |
   |---|---|
   | `https://www.googleapis.com/auth/youtube.upload` | Upload videos |
   | `https://www.googleapis.com/auth/youtube.readonly` | Read the channel name at connect time, to show which channel you connected |

   Don't add the broad `.../auth/youtube` scope. Upload alone is all Clipwright uses, and a smaller scope makes the audit easier.
4. **Audience → Test users:** add the Google account that manages each brand's channel.
5. **Publishing status:** while the app is in *Testing*, Google expires refresh tokens after 7 days, so you would have to reconnect every week. Once your first upload works, click **Publish app** (→ *In production*). The consent screen then says "Google hasn't verified this app". Click *Advanced* → *Go to Clipwright*. That warning is fine for your own accounts.

### 2.3 Client credentials
1. **Clients → Create client → Application type: Desktop app**, name `clipwright-desktop`.
2. Copy the **Client ID** and **Client secret** into `apps.json` → `google`. Desktop clients accept loopback redirects (`http://localhost:<port>`) without registering them.

### 2.4 Connect each brand
```bash
./post connect ojastra_mind google
```
If one Google account manages several channels, Google asks which channel to use. It prints `connected YouTube channel <name>`. To connect another brand, run it again with that brand's name and pick its channel.

### 2.5 The audit (start it now, it takes weeks)
Every upload from an unaudited project is locked to **private**. Locked videos can't be unlocked later: they have to be re-uploaded.
- Use the form **YouTube API Services – Audit and Quota Extension Form**: <https://support.google.com/youtube/contact/yt_api_form>.
- Describe it as it is: an internal tool, not offered to the public, that uploads short videos to channels you own on a schedule you approve; it stores no YouTube data beyond the ids of its own uploads. Give the project number and your channel URLs.
- Quota: `videos.insert` has its own default bucket of **100 uploads per day**. You only need to ask for more if you post over 100 a day across all brands.
- After approval, set `"audited": true` under `youtube` in each brand's `accounts.json`.

---

## 3. TikTok

### 3.1 Developer account and app
1. Go to <https://developers.tiktok.com> → log in → **Manage apps → Connect an app** (or *Create app*). Register as an individual or an organization.
2. App details:
   - Icon, name `Clipwright`, category (Productivity / Social), and a short description.
   - **Terms of Service URL** and **Privacy Policy URL:** both are required for review. A simple page on GitHub Pages or Notion that states what the app does is enough.
   - **Platforms: Desktop.**

### 3.2 Products and scopes
1. **Add products → Login Kit.** Under Login Kit → *Desktop*, add the **Redirect URI** `http://localhost:8765/callback`. TikTok only allows `localhost` or `127.0.0.1`, and requires a port.
2. **Add products → Content Posting API**, then turn on **Direct Post**.
3. **Scopes:**

   | Scope | Why |
   |---|---|
   | `user.info.basic` | Identify the connected account (comes with Login Kit) |
   | `video.publish` | Direct Post to the profile |

   Don't add `video.upload`: that sends videos to the TikTok inbox as drafts, which Clipwright doesn't do. (`video.list` comes later, for stats.)
4. Copy the **Client key** and **Client secret** into `apps.json` → `tiktok`.

### 3.3 Test before the audit
- **Sandbox:** create one in the app page, add your TikTok account as a *target user*, and use the sandbox's client key and secret first.
- **While unaudited:**
  - Every post is **SELF_ONLY** (only you can see it). Clipwright forces this.
  - At most 5 accounts can post in 24 hours.
  - **The TikTok account itself must be set to Private** (TikTok → Settings → Privacy → Private account), or the API refuses with `unaudited_client_can_only_post_to_private_accounts`.
- Connect each brand:
  ```bash
  ./post connect ojastra_mind tiktok
  ```

### 3.4 Submit for the audit
TikTok reviews a **demo video** of the whole flow and checks the posting screen against its Direct Post guidelines. The posting screen must:
- show the creator's TikTok name;
- let the user pick the privacy level from the options TikTok returns, with **no pre-selected default**;
- offer allow-comment, duet and stitch toggles;
- offer a commercial-content disclosure ("your brand / branded content");
- show the consent text ("By posting, you agree to TikTok's Music Usage Confirmation").

**Clipwright's review page doesn't have these controls yet.** They need adding before you record the demo, which is a small job on the review page. When TikTok approves the app, set `"audited": true` under `tiktok` in each brand's `accounts.json`, and switch your account back to public.

---

## 4. Check it works
```bash
./post review                   # approve one clip, tick one platform
./post publish-due --dry-run    # shows the row that would upload
./post publish-due              # uploads; prints the link
./post queue                    # status, link or last error
```
Do this once per platform before turning on `scripts/install-timers.sh`. If something fails, `./post queue` shows the platform's error message. Most first-run failures are a missing permission (Meta), an account that isn't private (unaudited TikTok), or a test user that wasn't added (Google).

## Sources
- Meta: [Pages use case](https://developers.facebook.com/documentation/development/create-an-app/pages-use-case), [Facebook Login for Business](https://developers.facebook.com/docs/facebook-login/facebook-login-for-business), [Instagram content publishing](https://developers.facebook.com/docs/instagram-platform/content-publishing)
- Google: [YouTube Data API quota costs](https://developers.google.com/youtube/v3/determine_quota_cost), [audit form](https://support.google.com/youtube/contact/yt_api_form)
- TikTok: [Login Kit for Desktop](https://developers.tiktok.com/doc/login-kit-desktop), [Content Posting API](https://developers.tiktok.com/doc/content-posting-api-get-started)
