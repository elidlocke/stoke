# Gmail sending: Google Cloud setup and verification

Stoke sends notes from each writer's own Gmail. It asks for the `gmail.send` scope only, plus `openid email` to learn which address was connected. `gmail.send` is a **sensitive** scope (not restricted). That means:
- Google has to verify the app before it can be used by anyone outside its list of test users.
- No CASA security assessment is needed.

Until verification is approved, up to 100 Google accounts you add as test users can connect.

Part A gets sending working for you today. Part B is the verification submission, which takes a while, so start it now.

## Part A: send yourself a test (local)

1. **Create a project.** In the [Google Cloud console](https://console.cloud.google.com/), create a project named `Stoke`.
2. **Enable the Gmail API.** Go to APIs & Services → Library → Gmail API → Enable.
3. **Set up the consent screen.** Go to Google Auth Platform → Get started.
   - App name: `Stoke`.
   - User support email: your address.
   - Audience: **External**.
   - Contact email: your address.
4. **Add the scopes.** Go to Google Auth Platform → Data Access → Add or remove scopes, and add:
   - `https://www.googleapis.com/auth/gmail.send` (it's listed under "Your sensitive scopes")
   - `openid`
   - `https://www.googleapis.com/auth/userinfo.email`
5. **Add test users.** Go to Google Auth Platform → Audience → Test users → Add users. Add the Gmail address you'll connect, and later each beta writer (up to 100). Leave the publishing status on **Testing** for now.
6. **Create the OAuth client.** Go to Google Auth Platform → Clients → Create client, and choose **Web application**.
   - Authorized JavaScript origins:
     - `http://localhost:5173`
     - `https://stoke-y4sf.onrender.com`
   - Authorized redirect URIs: `http://localhost:5173/api/gmail/callback` and `https://stoke-y4sf.onrender.com/api/gmail/callback`. Each is `CORS_ORIGIN` followed by `/api/gmail/callback`, and must match exactly.
   - Copy the client ID and the client secret. Google only shows the secret once, so download the JSON too.
7. **Configure Stoke.** Add both values to the repo-root `.env`:
   ```
   GOOGLE_CLIENT_ID=…apps.googleusercontent.com
   GOOGLE_CLIENT_SECRET=…
   ```
   For production, add the same two variables in Render (stoke → Environment). `render.yaml` lists them.
8. **Restart Stoke.** Run `./dev.sh`. It applies migration `0006_gmail_connections`.
9. **Connect your Gmail.** In Settings → Gmail, click **Connect Gmail**.
   - Google warns that it hasn't verified the app. Click Continue: that's expected for test users.
   - Allow "Send email on your behalf". If you untick it, Stoke refuses the connection.
   - You land back in Settings, showing the address as Connected.
10. **Send yourself a test.** Open any action → Note → **Send me a test**.
    - The draft as it stands (saved or not) is filled in for the first person in the audience, or for an example reader when the audience is empty.
    - It's sent from your Gmail to the same address, with the subject starting `[Test]` and a line at the top saying whose copy it is.
    - In the Preview, **Email me this copy** sends the copy of whichever reader is showing.
11. **Send from the queue (optional).** Turn the action on and approve the note. Each queue card then has **Send from Gmail**, which asks you to confirm and then sends to the reader for real. In Contacted, it shows as "Sent from Gmail".

**While the app is in Testing, Google expires refresh tokens after 7 days.** After that, Settings shows "Needs reconnecting" and sending asks you to reconnect. This stops once the app's publishing status is In production.

## Part B: verification (start now)

Google reviews the consent screen, your domain, a homepage, a privacy policy and a demo video. Expect a few weeks of back-and-forth with Google's Trust & Safety team by email, and reply to them promptly.

1. **Get a domain you own.** You must verify every authorized domain in [Google Search Console](https://search.google.com/search-console), using the same Google account that owns the Cloud project. A custom domain (e.g. `getstoke.com`) is the reliable route; an `onrender.com` subdomain is likely to be questioned. When you add one:
   - Point it at the Render service.
   - Update `ALLOWED_HOSTS` and `CORS_ORIGIN` in `render.yaml`.
   - Add `https://<domain>` and `https://<domain>/api/gmail/callback` to the OAuth client.
2. **Publish a public homepage on that domain.** Google needs a page anyone can read without signing in. It should say what Stoke is, why it asks for Gmail access, and link to the privacy policy. Stoke's root URL currently shows only the sign-in screen, which isn't enough.
3. **Publish a privacy policy on the same domain**, linked from the homepage. It must cover:
   - **What Google data Stoke gets:** the Gmail address, and permission to send email as the writer. Stoke can't read, search or delete their email.
   - **How it's used:** only to send notes the writer has approved, to the readers they chose, and test notes to themselves.
   - **How it's stored:** the refresh token is encrypted at rest. Note text is encrypted. Stoke keeps no copy of the writer's mailbox.
   - **Sharing:** none. The data isn't used for ads or for training AI models.
   - **Deleting it:** Settings → Gmail → Disconnect revokes Stoke's access at Google and deletes the token. Writers can also revoke access at myaccount.google.com/permissions.
   - **The Limited Use statement, word for word:** "Stoke's use and transfer of information received from Google APIs to any other app will adhere to [Google API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy), including the Limited Use requirements."
4. **Fill in Branding** (Google Auth Platform → Branding):
   - app name, support email and developer contact;
   - homepage, privacy policy and terms of service URLs;
   - authorized domains.

   A logo is optional. Adding one triggers a separate brand review, so you may want to leave it off at first.
5. **Write the scope justification** (Data Access → `gmail.send`). For example:
   > Stoke helps newsletter writers send short personal notes (a thank-you, a welcome back) to their own paying subscribers. The writer writes and approves each note template in Stoke. Stoke then sends the notes from the writer's own Gmail account, so they come from the writer, appear in their Sent folder, and replies go straight to them. Stoke only sends: it never reads, lists or modifies the writer's mail, so gmail.send is the narrowest scope that works. gmail.compose would be broader, and Stoke doesn't need drafts.
6. **Record a demo video** in English and upload it to YouTube as unlisted. Show, in one take:
   1. the Stoke homepage and its privacy policy link;
   2. signing in, then Settings → Gmail → **Connect Gmail**;
   3. Google's consent screen, with the browser's address bar visible so the `client_id` in the URL can be read, and the requested permissions on screen;
   4. allowing access, and landing back in Settings, connected;
   5. an action's Note → **Send me a test**, then that email arriving in Gmail and sitting in Sent;
   6. a queue card → **Send from Gmail** → confirm, with the note showing in Sent;
   7. **Disconnect** in Settings.
7. **Submit.** Set Audience → Publishing status to **In production**, then Verification Center → Submit for verification.
   - Until approval, you keep the 100-user cap and the "unverified app" warning.
   - In production, refresh tokens stop expiring after 7 days.

## Limits to know

- Gmail itself caps sending at about 500 recipients a day on personal accounts, and about 2,000 on Google Workspace. Stoke's planned daily cap (step 6) defaults to 50.
- Each writer can connect one Gmail account. Connecting another one replaces it.
