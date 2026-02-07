# Frappe Social Media Scheduler

A comprehensive social media scheduling and analytics module for Frappe/ERPNext. Schedule posts across 5 platforms, manage OAuth integrations, and track analytics with persistent storage in Frappe.

## Features

- **Multi-Platform Support**: X/Twitter, LinkedIn, Instagram, Facebook, YouTube
- **Scheduled Publishing**: Schedule posts for future publishing with automatic execution
- **OAuth Management**: Secure OAuth integration with automatic token refresh
- **Analytics Tracking**: Account-level and post-level analytics with historical data
- **Media Support**: Images, videos, carousels (platform-specific)
- **Retry Logic**: Exponential backoff for failed posts
- **Rate Limiting**: Platform-specific rate limit tracking

## Supported Platforms

| Platform | API Version | Auth Method | Special Requirements |
|----------|-------------|-------------|---------------------|
| X/Twitter | v2 + v1.1 | OAuth 2.0 + PKCE, OAuth 1.0a for media | Free tier: 17 posts/day; Basic ($200/mo): 100/day |
| LinkedIn | 202501 (monthly versioned) | OAuth 2.0 | Header: `LinkedIn-Version: 202501` |
| Instagram | Meta Graph API v21.0 | Facebook OAuth | Business/Creator account required; JPEG only |
| Facebook | Meta Graph API v21.0 | OAuth 2.0 | Page required; `business_management` permission |
| YouTube | Data API v3 | Google OAuth 2.0 | 10,000 quota units/day; upload costs 1,600 |

## Installation

### Prerequisites

- Frappe v15+
- Python 3.10+
- ERPNext (optional)

### Install via Bench

```bash
# Get the app
bench get-app https://github.com/prethive303/frappe_social.git

# Install on your site
bench --site your-site.local install-app frappe_social

# Run migrations
bench --site your-site.local migrate

# Install Python dependencies
cd apps/frappe_social
pip install -r requirements.txt
```

### Manual Installation

```bash
cd frappe-bench/apps
git clone https://github.com/prethive303/frappe_social.git
cd frappe_social
pip install -r requirements.txt
cd ../..
bench --site your-site.local install-app frappe_social
```

## Configuration

### 1. Configure API Credentials

Navigate to **Social Settings** and enter API credentials for each platform:

#### Twitter/X
- Create an app at [developer.twitter.com](https://developer.twitter.com)
- Enable OAuth 2.0 with PKCE
- Enable OAuth 1.0a for media uploads
- Required scopes: `tweet.read`, `tweet.write`, `users.read`, `offline.access`

#### LinkedIn
- Create an app at [linkedin.com/developers](https://www.linkedin.com/developers)
- Required products: "Share on LinkedIn", "Sign In with LinkedIn"
- Required scopes: `w_member_social`, `r_organization_admin`

#### Meta (Facebook/Instagram)
- Create an app at [developers.facebook.com](https://developers.facebook.com)
- Required permissions: `instagram_basic`, `instagram_content_publish`, `pages_manage_posts`, `business_management`

#### YouTube
- Create credentials at [console.cloud.google.com](https://console.cloud.google.com)
- Enable YouTube Data API v3
- Required scopes: `youtube.upload`, `youtube`, `yt-analytics.readonly`

### 2. Connect Social Accounts

1. Go to **Social Integration** list
2. Create new integration for each platform
3. Click "Connect Account" to initiate OAuth flow
4. Complete authorization in popup window

## Usage

### Creating Posts

```python
# Via API
import frappe

post = frappe.get_doc({
    "doctype": "Social Post",
    "content": "Hello from Frappe Social! 🚀",
    "platforms": [
        {"platform": "Twitter", "integration": "Twitter-myaccount"},
        {"platform": "LinkedIn", "integration": "LinkedIn-myprofile"}
    ],
    "scheduled_time": "2024-12-10 10:00:00"
})
post.insert()
post.submit()
```

### API Endpoints

```python
# Schedule a post
frappe.call({
    "method": "frappe_social.frappe_social.api.posts.create_post",
    "args": {
        "content": "My scheduled post",
        "platforms": ["Twitter", "LinkedIn"],
        "scheduled_time": "2024-12-10 10:00:00"
    }
})

# Get analytics
frappe.call({
    "method": "frappe_social.frappe_social.api.analytics.get_account_analytics",
    "args": {
        "integration": "Twitter-myaccount",
        "days": 30
    }
})
```

## DocTypes

| DocType | Purpose |
|---------|----------|
| Social Settings | API credentials, tier settings, quota tracking |
| Social Integration | OAuth tokens, profile info per platform account |
| Social Post | Content, media, scheduling, state machine |
| Social Post Platform | Per-platform post tracking (child table) |
| Social Analytics | Daily account-level metrics |
| Social Analytics Metric | Detailed metrics with change tracking (child) |
| Social Post Analytics | Per-post performance metrics |

## Scheduled Jobs

| Task | Schedule | Purpose |
|------|----------|----------|
| `publish_scheduled_posts` | Every minute | Publish due posts |
| `refresh_expiring_tokens` | Hourly | Refresh tokens expiring within 5 days |
| `fetch_daily_analytics` | Daily 6 AM | Fetch account analytics |
| `fetch_post_analytics` | Every 6 hours | Fetch post analytics (last 7 days) |
| `reset_rate_limit_counters` | Daily midnight | Reset daily counters |

## Platform-Specific Notes

### Twitter/X
- **Dual OAuth Required**: OAuth 2.0 for API, OAuth 1.0a for media upload
- **Tier Limits**: Free (17/day), Basic $200/mo (100/day), Pro $5K/mo (500/day)
- **Media**: Images 5MB, Videos 512MB/140s

### Instagram
- **JPEG Only**: PNG images are automatically converted
- **Two-Step Publishing**: Create container → Publish
- **Hard Limit**: 25 posts/24h (cannot be increased)
- **Stories**: NOT supported via API

### LinkedIn
- **Monthly API Versioning**: Update `LinkedIn-Version` header monthly (e.g., 202501 → 202502)
- **Analytics**: Organization pages only (personal post analytics not available)

### YouTube
- **Quota System**: 10,000 units/day, video upload costs 1,600 (~6 uploads/day)
- **Thumbnails**: Require phone verification, 1280×720, max 2MB
- **Shorts**: Use regular upload with 9:16 aspect ratio + ≤60s + #Shorts tag

## Development

### Project Structure

```
frappe_social/
├── frappe_social/
│   ├── frappe_social/
│   │   ├── doctype/           # DocTypes
│   │   ├── providers/         # Platform API providers
│   │   ├── services/          # Business logic
│   │   ├── api/               # REST API endpoints
│   │   └── tasks.py           # Scheduled jobs
│   ├── public/                # Static assets
│   ├── hooks.py               # Frappe hooks
│   └── install.py             # Installation hooks
├── requirements.txt           # Python dependencies
└── setup.py                   # Package setup
```

### Running Tests

```bash
bench --site your-site.local run-tests --app frappe_social
```

### Dependencies

```
tweepy>=4.14.0          # Twitter
google-api-python-client>=2.100.0  # YouTube
google-auth>=2.23.0
google-auth-oauthlib>=1.1.0
requests>=2.31.0        # LinkedIn, Meta
requests-oauthlib>=1.3.1
Pillow>=10.0.0          # PNG→JPEG for Instagram
python-magic>=0.4.27    # MIME detection
```

## License

MIT License - see [LICENSE](LICENSE) file.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## Support

- GitHub Issues: [Report bugs or request features](https://github.com/prithive303/frappe_social/issues)

## Changelog

### v1.0.0 (December 2024)
- Initial release
- Support for 5 platforms (Twitter, LinkedIn, Instagram, Facebook, YouTube)
- OAuth management with automatic token refresh
- Scheduled posting with retry logic
- Analytics tracking and storage
