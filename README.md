# Thorio Lite Lead Finder

A small daily lead finder. It searches public posts through the official X and Threads APIs, identifies people or businesses asking for technology help, matches each post to one partner, drafts a personal message, and saves the lead in Airtable. It never sends messages.

## 1. Add your API keys to GitHub

Open this repository on GitHub. Go to **Settings → Secrets and variables → Actions → New repository secret**. Add each secret using the exact name below.

### X API

1. Visit [X Developer Platform](https://developer.x.com/).
2. Sign in and create a developer project and app.
3. Open your app's **Keys and tokens** page.
4. Copy the **Bearer Token**.
5. In GitHub, create a secret named `X_BEARER_TOKEN` and paste the token as its value.

The program uses X's official recent-search API, which covers the most recent seven days. X controls API access and pricing for your account.

### Threads API

1. Visit [Meta for Developers](https://developers.facebook.com/).
2. Create an app with the Threads API use case and configure Threads API access.
3. Request the `threads_basic` and `threads_keyword_search` permissions.
4. Complete Meta's app review for advanced access to `threads_keyword_search` if you want to search public posts from other people. Without that approval, Meta limits keyword search to posts owned by the authenticated account.
5. Generate a Threads access token.
6. In GitHub, create a secret named `THREADS_ACCESS_TOKEN` and paste the token as its value.

### Airtable

The existing Airtable connection uses these secrets:

- `AIRTABLE_BASE_ID`: your existing Airtable base ID.
- `AIRTABLE_API_KEY`: your Airtable personal access token. Give it record read and write access to the existing base.

The table name defaults to **Lead Radar**. If your table has a different name, add an Actions variable named `AIRTABLE_LEAD_TABLE` with the exact table name.

## 2. Run it by hand

1. Open the repository on GitHub.
2. Select the **Actions** tab.
3. Select **Daily Leads** on the left.
4. Press **Run workflow**, select the `lite` branch, and press the green **Run workflow** button.

It also runs automatically every day at 13:00 UTC. Each run saves no more than 40 new leads.

## 3. Edit your keywords

1. Open `keywords.yaml` in the repository.
2. Press the pencil icon to edit it.
3. Under each partner name, add or remove plain-English search phrases in the `keywords` list. Keep each phrase inside quotation marks.
4. Save the change directly to the `lite` branch.

For example, add `"need a mobile app developer"` to the partner whose service best fits that request.

## 4. Review leads

Open the **Lead Radar** table in Airtable. New rows have Status set to **New**. Review the post and the suggested draft, then send any message yourself. The program does not send DMs, replies, emails, or other messages.

The program checks the existing Airtable rows before creating a lead. It skips a post link or handle already present in the table.

## What the finder considers a lead

It keeps recent posts that show a real business need, such as hiring developers, looking for contractors, needing a development agency, or building an MVP. It skips job seekers, recruiters advertising their own services, obvious spam, and duplicate posts. Partner matching is keyword-based, so review the post and suggested partner before contacting anyone.

## Troubleshooting

Each platform is handled independently. If an API key is missing or that platform's search fails, the run prints a short explanation and continues with the other platform. Airtable errors are also printed in plain English.

Official API references: [X recent search](https://docs.x.com/x-api/posts/search/introduction) and [Threads keyword search](https://developers.facebook.com/docs/threads/keyword-search/).
